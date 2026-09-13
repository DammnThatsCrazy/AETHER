"""Data Exchange Plane — artifact retention decision logic (M7).

Pure, DB-free decision logic that answers, from ONE ``data_artifacts`` row plus
the storage-plane policy vocabulary, whether an artifact is expire-eligible now
and whether its deletion is a ``hard_delete`` vs a ``tombstone`` — or is blocked
entirely by ``preserve`` policy or an active legal hold.

Policy source is the repo-wide ``config/storage_policies.yaml`` registry ONLY,
read through the canonical seam ``shared.storage.manager.policy_for``
(fail-closed for unknown resource types).  The ``data_artifacts`` row is a
metadata pointer into the shared ObjectStore (payload bytes never live in
Postgres), so *deleting the object bytes* and *tombstoning the row to a
terminal Data Exchange status* are the two halves of one lifecycle decision.

Design rules (mirroring ``shared/storage/ttl.py`` and ``lifecycle.py``):

- Retention is OFF unless an artifact carries an ``expires_at`` in the past, or
  the caller opts in to the policy retention-class default window
  (``apply_policy_default_ttl=True``).  Nothing here silently ages out a row
  with no expiry signal.
- ``legal`` retention_class resources are never swept; ``delete_behavior:
  preserve`` resources are never swept.
- Byte-ownership is explicit, never inferred.  ``available``/``committed``/
  ``partially_committed`` are **durable-byte states** — they own real bytes at
  their ``object_key`` plus a verified checksum — so they ARE expiry candidates
  once past ``expires_at`` (expiry flips the row to ``expired`` and then removes
  its bytes).  ``failed``/``expired``/``deleted``/``revoked`` are absorbing
  byte-less tombstones and are never expiry candidates themselves.  The
  transient statuses (``created`` … ``generating``) remain expiry candidates as
  today.
- An active legal hold blocks deletion (retention cannot know which subjects sit
  inside a packed object, so ANY matching hold blocks).  The decision is a pure
  function of a ``legal_hold_blocked`` boolean — the sweep decides how to obtain
  it (see ``jobs_ops.expire_artifacts``).
- Timestamps parse tolerantly: an unparseable ``expires_at`` is treated as NOT
  in the past (a malformed timestamp must never delete a record).

The module is pure and offline — no settings import at module load and no DB
touch.  Tests exercise the decisions directly with fabricated policy dicts and
injected ``now`` values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.data_exchange.contracts import DATA_ARTIFACT_TERMINAL_STATUSES
from shared.storage.ttl import is_expired
from shared.temporal.instant import coerce_utc_lenient

#: The storage-policy resource type that governs ``data_artifacts`` rows.
DATA_ARTIFACT_RESOURCE_TYPE = "data_artifacts"

#: Policy ``delete_behavior`` values lifecycle code understands.
HARD_DELETE = "hard_delete"
TOMBSTONE = "tombstone"
PRESERVE = "preserve"

#: Actions returned by :func:`decide_artifact_retention`.
ACTION_HARD_DELETE = "hard_delete"  # delete bytes + flip the row to a tombstone
ACTION_TOMBSTONE = "tombstone"      # delete bytes; row tombstone retains audit stub
ACTION_PRESERVE = "preserve"        # never delete bytes or mutate the row
ACTION_NONE = "none"                # not eligible yet (or blocked)

#: Policy ``retention_class`` values that are never swept by lifecycle.
LEGAL_RETENTION_CLASS = "legal"

#: Fallback retention window (days) when an artifact has no explicit
#: ``expires_at`` and ``apply_policy_default_ttl`` opts in.  Read lazily from
#: settings by the sweep; kept here so the pure decision stays parameterized.
DEFAULT_STANDARD_RETENTION_DAYS = 365

# ── byte-ownership vocabulary (derived from the contracts.py status strings) ─

#: Durable-byte states: these rows own real bytes at their ``object_key`` plus a
#: verified checksum.  Expiry-eligible when past ``expires_at``; cleanup never
#: purges their bytes; a durable-byte row whose key has no bytes is an anomaly.
DURABLE_BYTE_STATUSES: frozenset[str] = frozenset(
    {"available", "committed", "partially_committed"}
)

#: Absorbing byte-less tombstones (audit stubs): ``failed``/``expired``/
#: ``deleted``/``revoked``.  ``DATA_ARTIFACT_TERMINAL_STATUSES`` minus the
#: durable-byte members — kept derived so a contracts.py vocabulary change
#: stays single-source.  Cleanup MAY purge lingering bytes they reference.
TOMBSTONE_STATUSES: frozenset[str] = frozenset(
    set(DATA_ARTIFACT_TERMINAL_STATUSES) - DURABLE_BYTE_STATUSES
)


def parse_utc(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, tolerant of errors.

    ``None`` / already-aware ``datetime`` / ``datetime`` with naive UTC are
    normalized; anything unparseable returns ``None`` (failing open on a
    malformed timestamp — never a reason to delete).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return coerce_utc_lenient(value) or value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def artifact_owns_durable_bytes(status: Any) -> bool:
    """True when the row status owns durable bytes at its object_key.

    The durable-byte states (``available`` / ``committed`` /
    ``partially_committed``) require real bytes AND a verified checksum
    (contracts.py).  Cleanup must never purge bytes these rows reference;
    a durable-byte row whose object is missing is an anomaly.
    """
    return bool(status) and str(status) in DURABLE_BYTE_STATUSES


def artifact_is_tombstone(status: Any) -> bool:
    """True for an absorbing byte-less tombstone status.

    ``failed`` / ``expired`` / ``deleted`` / ``revoked`` own no bytes, have no
    outgoing transitions (audit stubs), and MAY have lingering bytes cleaned up.
    """
    return bool(status) and str(status) in TOMBSTONE_STATUSES


def artifact_status_is_live(status: Any) -> bool:
    """True for a transient (non-absorbing, work-in-progress) artifact status.

    ``created`` … ``generating`` are in-flight and own nothing absorbing yet.
    Durable-byte states (``available``/``committed``/``partially_committed``)
    and tombstones are NOT live — but they differ radically in byte ownership,
    so callers that care about bytes must use :func:`artifact_owns_durable_bytes`
    / :func:`artifact_is_tombstone` instead of this predicate.
    """
    return bool(status) and str(status) not in DATA_ARTIFACT_TERMINAL_STATUSES


def row_past_expires_at(row: Mapping[str, Any], *, now: Optional[datetime] = None) -> bool:
    """True when the row's ``expires_at`` is strictly in the past.

    A row with no ``expires_at`` or an unparseable one is NOT past expiry.
    """
    expires_at = parse_utc(row.get("expires_at"))
    if expires_at is None:
        return False
    now_utc = now if now is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = coerce_utc_lenient(now_utc) or now_utc
    return expires_at < now_utc


def row_beyond_policy_window(
    row: Mapping[str, Any],
    *,
    retention_days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    """True when the row is older than ``retention_days`` (created_at-based).

    Pure wrapper over ``shared.storage.ttl.is_expired``; a falsy or negative
    window, a missing ``created_at``, or an unparseable one → False (never
    silently ages out).  Only used when an artifact has no explicit
    ``expires_at`` and the caller opted into the policy default window.
    """
    if retention_days is None or int(retention_days or 0) <= 0:
        return False
    return is_expired(
        row.get("created_at"), retention_days=int(retention_days), now=now
    )


def _lookup(policy: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a ``StoragePolicy`` object or a plain mapping."""
    if hasattr(policy, "get"):
        return policy.get(key, default) if isinstance(policy, Mapping) else default
    return getattr(policy, key, default)


def delete_action_for_policy(policy: Any) -> str:
    """Normalize a policy ``delete_behavior`` onto the action vocabulary."""
    behavior = str(_lookup(policy, "delete_behavior", HARD_DELETE) or HARD_DELETE)
    if behavior in (TOMBSTONE, PRESERVE):
        return behavior
    return HARD_DELETE


def _retention_class(policy: Any) -> str:
    return str(_lookup(policy, "retention_class", "standard") or "standard")


def decide_artifact_retention(
    row: Mapping[str, Any],
    *,
    policy: Any = None,
    now: Optional[datetime] = None,
    legal_hold_blocked: bool = False,
    apply_policy_default_ttl: bool = False,
    standard_retention_days: Optional[int] = None,
) -> dict[str, Any]:
    """Decide one artifact row's expire-eligibility and deletion action.

    Pure (no DB, no store): ``policy`` may be a ``shared.storage.manager.
    StoragePolicy`` or a plain dict shaped like a ``config/storage_policies.yaml``
    row (default ``data_artifacts``).  ``legal_hold_blocked`` is supplied by the
    caller (the sweep resolves active holds once per tenant).

    Returns ``{"artifact_id", "status", "expire_eligible", "delete_behavior",
    "action", "reason"}`` where ``action`` is one of ``hard_delete`` /
    ``tombstone`` / ``preserve`` / ``none`` and ``reason`` explains a ``none`` /
    ``preserve`` outcome.

    ``hard_delete`` vs ``tombstone`` (both delete the ObjectStore bytes):
    ``hard_delete`` leaves the row as an ``expired``/``deleted`` terminal
    tombstone (the Data Artifact repo keeps tombstones as audit rows — physical
    row removal is not exposed), while ``tombstone`` additionally strips
    subject identifiers.  For the ``data_artifacts`` metadata envelope the two
    converge on the same byte+row actions; the distinction is preserved for
    policy fidelity and for resource types whose payload carries PII.
    """
    artifact_id = row.get("artifact_id")
    status = str(row.get("status") or "created")
    if policy is None:
        policy = _default_data_artifacts_policy()

    reason: str
    if artifact_is_tombstone(status):
        # Absorbing byte-less tombstones are never expiry candidates themselves.
        reason = "already_terminal"
        return _decision(artifact_id, status, False, policy, "none", reason)

    behavior = delete_action_for_policy(policy)
    if behavior == PRESERVE:
        reason = "preserve_never_swept"
        return _decision(artifact_id, status, False, policy, "preserve", reason)
    if _retention_class(policy) == LEGAL_RETENTION_CLASS:
        reason = "legal_retention_compliance_owned"
        return _decision(artifact_id, status, False, policy, "none", reason)
    if legal_hold_blocked:
        reason = "legal_hold"
        return _decision(artifact_id, status, False, policy, "none", reason)

    eligible = row_past_expires_at(row, now=now)
    if not eligible and apply_policy_default_ttl:
        days = standard_retention_days
        if days is None:
            days = DEFAULT_STANDARD_RETENTION_DAYS
        eligible = row_beyond_policy_window(
            row, retention_days=days, now=now
        )

    if not eligible:
        reason = "not_past_retention"
        return _decision(artifact_id, status, False, policy, "none", reason)

    reason = "expires_at_past" if row_past_expires_at(row, now=now) else "past_policy_window"
    return _decision(
        artifact_id,
        status,
        True,
        policy,
        HARD_DELETE if behavior == HARD_DELETE else TOMBSTONE,
        reason,
    )


def _decision(
    artifact_id: Any,
    status: str,
    eligible: bool,
    policy: Any,
    action: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "status": status,
        "expire_eligible": bool(eligible),
        "delete_behavior": delete_action_for_policy(policy),
        "retention_class": _retention_class(policy),
        "action": action,
        "reason": reason,
    }


# ── policy loading (canonical seam; lazy so this module stays import-light) ──

_default_policy: Any = None


def _default_data_artifacts_policy() -> Any:
    """StoragePolicy for ``data_artifacts`` via the canonical registry seam."""
    global _default_policy
    if _default_policy is None:
        from shared.storage.manager import policy_for  # lazy — avoids import cycles

        _default_policy = policy_for(DATA_ARTIFACT_RESOURCE_TYPE)
    return _default_policy


def data_artifacts_policy() -> dict[str, Any]:
    """The ``data_artifacts`` policy row as a plain dict (for reporting/tests)."""
    policy = _default_data_artifacts_policy()
    return {
        "resource_type": _lookup(policy, "resource_type", DATA_ARTIFACT_RESOURCE_TYPE),
        "retention_class": _retention_class(policy),
        "delete_behavior": delete_action_for_policy(policy),
        "legal_hold_supported": bool(_lookup(policy, "legal_hold_supported", True)),
    }


def default_ttl_from_policy(policy: Any = None) -> int:
    """Seconds a ``standard``-class artifact without ``expires_at`` may live.

    Returns 0 when no default window applies (``legal``/``preserve``/unknown) —
    the shared-store canonical "no TTL" sentinel.  Exists so a sweep that opts
    into ``apply_policy_default_ttl`` and the ``expires_at``-less case share one
    window source.
    """
    if policy is None:
        policy = _default_data_artifacts_policy()
    if _retention_class(policy) == LEGAL_RETENTION_CLASS:
        return 0
    behavior = delete_action_for_policy(policy)
    if behavior == PRESERVE:
        return 0
    return DEFAULT_STANDARD_RETENTION_DAYS * 86_400


__all__ = [
    "DATA_ARTIFACT_RESOURCE_TYPE",
    "HARD_DELETE",
    "TOMBSTONE",
    "PRESERVE",
    "ACTION_HARD_DELETE",
    "ACTION_TOMBSTONE",
    "ACTION_PRESERVE",
    "ACTION_NONE",
    "DEFAULT_STANDARD_RETENTION_DAYS",
    "DURABLE_BYTE_STATUSES",
    "TOMBSTONE_STATUSES",
    "parse_utc",
    "artifact_owns_durable_bytes",
    "artifact_is_tombstone",
    "artifact_status_is_live",
    "row_past_expires_at",
    "row_beyond_policy_window",
    "delete_action_for_policy",
    "decide_artifact_retention",
    "data_artifacts_policy",
    "default_ttl_from_policy",
]
