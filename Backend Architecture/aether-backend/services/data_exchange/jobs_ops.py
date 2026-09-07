"""Data Exchange Plane — ops + hardening durable jobs (M7).

Four durable job types plus their DB-free core functions.  Each core is a plain
async function (unit-testable without the durable-job runtime); each ``register``
-ed handler is a thin ``(payload, ctx) -> JobOutcome`` adapter onto the jobs
platform (see ``services/jobs/handlers.py``), mirroring the M1
``jobs_migrate.py`` pattern exactly.

- ``data_exchange.expire_artifacts``  — scan ``data_artifacts`` rows whose
  ``expires_at`` is in the past.  Tombstone rows are already absorbing and are
  skipped; **durable-byte rows** (``available``/``committed``/
  ``partially_committed``) and transient rows that are past ``expires_at`` (and
  not held/preserved) are expired: the row is flipped to ``expired`` FIRST, then
  its ObjectStore bytes are deleted.  Every byte delete is scoped to the
  tenant's OWN ``data-exchange/<tenant>/...`` key scheme (see
  ``services/data_exchange/storage.py``); a row whose key is not under the
  operating tenant's prefix is refused, never deleted.  A row with no object is
  tombstoned anyway (its metadata is past expiry) and reported — never a
  whole-job failure.
- ``data_exchange.reconcile_artifacts`` — read-only reconciliation of
  ``data_artifacts`` metadata vs ObjectStore state per tenant: (a) rows whose
  ``object_key`` is absent from the store where the row still OWNS bytes
  (durable-byte ``available``/``committed``/``partially_committed`` or a
  transient in-flight row) are genuine **missing-object anomalies**, reported
  under ``missing_objects`` — never hidden; (b) absorbing tombstone rows whose
  bytes are already gone are the expected post-expiry state (informational
  ``tombstoned_without_bytes`` bucket); (c) objects under the tenant's
  ``data-exchange`` prefix with no byte-owning row — including bytes lingering
  under tombstone rows — are **orphans**.  Returns a structured report with
  capped lists; mutates nothing.  Idempotent.
- ``data_exchange.cleanup_artifacts`` — consumes a reconcile-style scan (re-runs
  it internally when no explicit targets are given) and deletes orphan object
  bytes (objects with no byte-owning row — never a durable-byte or transient
  row's payload) plus any rows explicitly flagged for cleanup (tombstoned to
  ``deleted``), strictly tenant-prefix-scoped.  Out-of-tenant keys are refused
  and reported, never deleted.
- ``data_exchange.finalize_pending_egress`` — egress finalization bridge for
  M4/M5 stragglers (see below).

Tenant scoping.  Every job runs for an explicit tenant scope (``tenant_id`` or a
``tenant_ids`` list).  ``DataArtifactRepository`` exposes no cross-tenant read
and this module deliberately adds none: "across tenants" means the caller
enumerates the tenants (operator/coordinator seam) and the sweep fans out per
tenant.  Deletion is gated by a strict key-shape validator — a key is only ever
deleted when it sits under the operating tenant's own prefix AND matches the
``direction/artifact_id`` scheme (no ``..``, ``.``, empty, or backslash
segments).  This is the load/security harness' core invariant.

Egress finalization bridge (M4/M5 seam).  Both live egress flows now finalize
inline: the M5 report flow (``render_report``) puts bytes then flips the row to
``available`` (failures flip to ``failed``); the M4 export flow materializes
through the egress bridge (``services/data_exchange/egress.py``), which the
canonical ``export.generate`` handler invokes best-effort after its own artifact
is checksum-verified — mirroring the bytes at the envelope's tenant-scoped
object key and flipping the row to ``available``.  Because both inline flips are
best-effort, this job reconciles their crash-window stragglers (bytes persisted
but the status flip never ran):

- flips to ``available`` ONLY rows whose durable-job record shows terminal
  success AND whose bytes are actually present at the row's object key (the
  ``available`` terminal state requires durable bytes — see ``contracts.py``);
- flips to ``failed`` rows whose job ended ``failed``/``cancelled`` (genuine
  terminal reconciliation — the M5 failure path is best-effort and can strand a
  ``generating`` row);
- leaves every other row untouched: jobs still ``queued``/``running`` are
  mid-flight; a succeeded job with no bytes at the key is not terminal-ready
  (materialization pending — a re-run of the canonical export re-attempts the
  inline bridge); a row with no corroborating job record is left for operator
  review (never fabricated to terminal).

It never creates artifacts and never mutates rows that are mid-flight.  Rows the
inline bridge already flipped are terminal (``available``) and fall outside the
transient statuses this job manages.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.metrics import (
    record_artifacts_expired,
    record_cleanup_refused,
    record_egress_finalized,
    record_legal_hold_blocked,
    record_objects_deleted,
    record_orphan_objects_deleted,
    record_reconcile_missing,
    record_reconcile_orphans,
    record_sweep_error,
)
from services.data_exchange.retention import (
    DATA_ARTIFACT_RESOURCE_TYPE,
    artifact_is_tombstone,
    artifact_owns_durable_bytes,
    data_artifacts_policy,
    decide_artifact_retention,
)
from services.data_exchange.storage import tenant_object_prefix
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger
from shared.temporal.instant import coerce_utc_lenient
from shared.storage.object_store import (
    ObjectNotFoundError,
    ObjectStore,
    get_object_store,
)

logger = get_logger("aether.data_exchange.ops")

# ── durable job types this module registers ─────────────────────────────────

JOB_EXPIRE_ARTIFACTS = "data_exchange.expire_artifacts"
JOB_RECONCILE_ARTIFACTS = "data_exchange.reconcile_artifacts"
JOB_CLEANUP_ARTIFACTS = "data_exchange.cleanup_artifacts"
JOB_FINALIZE_PENDING_EGRESS = "data_exchange.finalize_pending_egress"

DATA_EXCHANGE_OPS_JOB_TYPES: tuple[str, ...] = (
    JOB_EXPIRE_ARTIFACTS,
    JOB_RECONCILE_ARTIFACTS,
    JOB_CLEANUP_ARTIFACTS,
    JOB_FINALIZE_PENDING_EGRESS,
)

# ── scan / report tuning ────────────────────────────────────────────────────

#: Repository page size for full-coverage scans (paged to exhaustion — a single
#: capped fetch would silently skip data past the cap).
_PAGE_SIZE = 200
#: Cap on per-artifact / per-key lists in job result dicts (JobOutcome.result
#: must stay small and JSON-serializable).  Counts are always exact.
_MAX_REPORTED = 100

#: Egress artifact types the finalization bridge reconciles.  Mirrors
#: ``routes_export.EGRESS_ARTIFACT_TYPE == "export"`` and
#: ``services/reports/service.REPORT_ARTIFACT_TYPE == "report"`` (kept literal
#: here so this ops module does not import the route/report surfaces).
EXPORT_ARTIFACT_TYPE = "export"
REPORT_ARTIFACT_TYPE = "report"
EGRESS_ARTIFACT_TYPES: tuple[str, ...] = (EXPORT_ARTIFACT_TYPE, REPORT_ARTIFACT_TYPE)

#: Live (non-absorbing) egress statuses a row may be stranded in.
TRANSIENT_EGRESS_STATUSES: frozenset[str] = frozenset(
    {"created", "generating", "processing"}
)

#: Durable-job statuses that corroborate a completed artifact.
_JOB_TERMINAL_SUCCESS: frozenset[str] = frozenset(
    {"succeeded", "partially_succeeded"}
)
_JOB_TERMINAL_FAILURE: frozenset[str] = frozenset({"failed", "cancelled"})
_JOB_LIVE_STATUSES: frozenset[str] = frozenset(
    {"queued", "running", "pending", "retrying", "cancel_requested"}
)


# ── tenant / key scope helpers ──────────────────────────────────────────────


class TenantScopeViolationError(RuntimeError):
    """A delete was attempted on an object key outside the tenant's own prefix."""


def _validate_key_shape(key: str) -> Optional[str]:
    """Return ``key`` when it matches the safe object-key scheme, else None.

    The scheme is ``data-exchange/<tenant>/<direction>/<artifact_id>`` where the
    two segments after the tenant prefix must be non-empty and free of ``.`` /
    ``..`` / empty / backslash / NUL.  Crafted ``../``, absolute-path, and other
    tenants' prefixes all fail here.
    """
    if not isinstance(key, str) or not key:
        return None
    parts = key.split("/")
    # data-exchange / tenant / direction / artifact_id
    if len(parts) != 4 or parts[0] != "data-exchange":
        return None
    for segment in parts:
        if (
            not segment
            or segment in (".", "..")
            or any(ch in segment for ch in "/\\\x00")
        ):
            return None
    return key


def validate_object_key_for_delete(tenant_id: str, key: Any) -> Optional[str]:
    """Return ``key`` when it is safe to delete within the tenant's own scope.

    Requires the key to be well-shaped AND to start with this tenant's own
    ``data-exchange/<tenant>/`` prefix (trailing-slash guarded, so ``acme`` never
    matches ``acme2``).  Returns None to *refuse* — callers must never delete on
    a None return.
    """
    if _validate_key_shape(key) is None:
        return None
    prefix = tenant_object_prefix(tenant_id)  # validates tenant_id itself
    if not str(key).startswith(prefix):
        return None
    return str(key)


def assert_key_in_tenant_scope(tenant_id: str, key: Any) -> str:
    """Raise ``TenantScopeViolationError`` when ``key`` is outside tenant scope."""
    safe = validate_object_key_for_delete(tenant_id, key)
    if safe is None:
        raise TenantScopeViolationError(
            f"refusing object key {key!r} outside tenant {tenant_id!r} scope"
        )
    return safe


def _normalize_tenant_ids(tenant_ids: Any) -> list[str]:
    """Accept a single tenant id or a list; validate non-empty and well-shaped."""
    if isinstance(tenant_ids, str):
        items = [tenant_ids]
    else:
        items = list(tenant_ids or [])
    if not items:
        raise BadRequestError("tenant_id / tenant_ids is required")
    seen: list[str] = []
    for raw in items:
        tenant_id = str(raw).strip()
        if not tenant_id:
            raise BadRequestError("tenant_id must be a non-empty string")
        tenant_object_prefix(tenant_id)  # validates the segment (raises BadRequest)
        if tenant_id not in seen:
            seen.append(tenant_id)
    return seen


def _now_utc(now: Optional[datetime]) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    return now if now.tzinfo else (coerce_utc_lenient(now) or now)


def _capped_append(items: list[dict], item: dict) -> None:
    if len(items) < _MAX_REPORTED:
        items.append(item)


async def _iter_rows_for_tenant(
    repo: DataArtifactRepository, tenant_id: str
) -> Any:
    """Page every row for a tenant to exhaustion (newest-first, repository page)."""
    offset = 0
    while True:
        page = await repo.list_for_tenant(tenant_id, limit=_PAGE_SIZE, offset=offset)
        for row in page:
            yield row
        if len(page) < _PAGE_SIZE:
            return
        offset += _PAGE_SIZE


async def _collect_rows_for_tenant(
    repo: DataArtifactRepository, tenant_id: str
) -> list[dict]:
    return [row async for row in _iter_rows_for_tenant(repo, tenant_id)]


async def _resolve_legal_hold_blocked(
    tenant_id: str,
    checker: Optional[Callable[[str], Awaitable[bool]]],
) -> bool:
    """Whether an active legal hold blocks expiry for ``tenant_id``.

    An injected checker wins (DB-free tests).  The default is local-aware: no DB
    pool (``AETHER_ENV=local`` in-memory path) means no ``storage_legal_holds``
    table exists, so no hold can be blocking.  With a real pool the check
    consults ``StorageLifecycle.active_hold`` and FAILS CLOSED (block delete) if
    the check itself errors — retention can never prove an absence of holds
    while the holds store is unhealthy.
    """
    if checker is not None:
        return bool(await checker(tenant_id))
    from repositories.repos import get_pool  # lazy — local seam

    pool = await get_pool()
    if pool is None:
        return False
    try:
        from shared.storage.lifecycle import StorageLifecycle  # lazy — heavy

        hold = await StorageLifecycle().active_hold(
            tenant_id, DATA_ARTIFACT_RESOURCE_TYPE
        )
        return hold is not None
    except Exception as exc:  # noqa: BLE001 — fail closed on an unhealthy hold store
        logger.warning(
            "expire_artifacts legal-hold check failed tenant=%s -> blocking: %s",
            tenant_id,
            exc,
        )
        return True


# ═══════════════════════════════════════════════════════════════════════════
# data_exchange.expire_artifacts
# ═══════════════════════════════════════════════════════════════════════════


async def expire_artifacts(
    tenant_ids: Any,
    *,
    now: Optional[datetime] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
    legal_hold_checker: Optional[Callable[[str], Awaitable[bool]]] = None,
    policy: Any = None,
    apply_policy_default_ttl: bool = False,
    standard_retention_days: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Expire tenant artifact rows whose ``expires_at`` is in the past.

    For every non-terminal row that is past its ``expires_at`` (and not held):
    delete the tenant-scoped ObjectStore bytes and tombstone the row to the
    terminal ``expired`` status via the artifact repo's own status vocabulary.
    Rows whose ``expires_at`` is still in the future, rows already terminal,
    rows under an active legal hold, and rows whose ``object_key`` escapes the
    tenant's own prefix are all left untouched (counted + reported).

    Returns a JSON-serializable report: exact counts plus capped per-artifact
    outcomes.
    """
    now_utc = _now_utc(now)
    tenants = _normalize_tenant_ids(tenant_ids)
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()
    effective_policy = policy if policy is not None else data_artifacts_policy()

    total: dict[str, int] = {
        "rows_scanned": 0,
        "expired": 0,
        "objects_deleted": 0,
        "objects_missing": 0,
        "already_terminal": 0,
        "not_eligible": 0,
        "preserved": 0,
        "held": 0,
        "refused": 0,
    }
    tenants_report: list[dict] = []

    for tenant_id in tenants:
        # A per-tenant sweep may error; one tenant's failure never aborts the
        # multi-tenant job — the tenant report carries the error instead.
        try:
            tenant_report = await _expire_tenant(
                tenant_id,
                repo,
                store,
                now=now_utc,
                legal_hold_checker=legal_hold_checker,
                policy=effective_policy,
                apply_policy_default_ttl=apply_policy_default_ttl,
                standard_retention_days=standard_retention_days,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 — sweep resilience
            record_sweep_error()
            logger.error("expire_artifacts failed for tenant=%s: %s", tenant_id, exc)
            tenant_report = {
                "tenant_id": tenant_id,
                "rows_scanned": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        for key in total:
            total[key] += int(tenant_report.get(key, 0))
        tenants_report.append(tenant_report)

    return {"dry_run": bool(dry_run), "tenants": tenants_report, "totals": total}


async def _expire_tenant(
    tenant_id: str,
    repo: DataArtifactRepository,
    store: ObjectStore,
    *,
    now: datetime,
    legal_hold_checker: Optional[Callable[[str], Awaitable[bool]]],
    policy: Any,
    apply_policy_default_ttl: bool,
    standard_retention_days: Optional[int],
    dry_run: bool,
) -> dict:
    blocked = await _resolve_legal_hold_blocked(tenant_id, legal_hold_checker)
    report: dict[str, Any] = {
        "tenant_id": tenant_id,
        "rows_scanned": 0,
        "expired": 0,
        "objects_deleted": 0,
        "objects_missing": 0,
        "already_terminal": 0,
        "not_eligible": 0,
        "preserved": 0,
        "held": 0,
        "refused": 0,
        "outcomes": [],
    }

    async for row in _iter_rows_for_tenant(repo, tenant_id):
        report["rows_scanned"] += 1
        await _expire_one(
            tenant_id,
            row,
            repo,
            store,
            report=report,
            now=now,
            blocked=blocked,
            policy=policy,
            apply_policy_default_ttl=apply_policy_default_ttl,
            standard_retention_days=standard_retention_days,
            dry_run=dry_run,
        )
    return report


async def _expire_one(
    tenant_id: str,
    row: dict,
    repo: DataArtifactRepository,
    store: ObjectStore,
    *,
    report: dict,
    now: datetime,
    blocked: bool,
    policy: Any,
    apply_policy_default_ttl: bool,
    standard_retention_days: Optional[int],
    dry_run: bool,
) -> None:
    artifact_id = row.get("artifact_id")
    status = str(row.get("status") or "created")
    outcome: dict[str, Any] = {"artifact_id": artifact_id, "status": status}

    if artifact_is_tombstone(status):
        # Absorbing byte-less tombstones are never expiry candidates.
        report["already_terminal"] += 1
        outcome.update(action="skip", reason="already_terminal")
        _capped_append(report["outcomes"], outcome)
        return

    decision = decide_artifact_retention(
        row,
        policy=policy,
        now=now,
        legal_hold_blocked=blocked,
        apply_policy_default_ttl=apply_policy_default_ttl,
        standard_retention_days=standard_retention_days,
    )
    action = decision["action"]
    if action not in ("hard_delete", "tombstone"):
        reason = decision["reason"]
        if reason == "legal_hold":
            report["held"] += 1
            record_legal_hold_blocked()
        elif reason == "preserve_never_swept":
            report["preserved"] += 1
        else:
            report["not_eligible"] += 1
        outcome.update(action="skip", reason=reason)
        _capped_append(report["outcomes"], outcome)
        return

    key = validate_object_key_for_delete(tenant_id, row.get("object_key"))
    if key is None:
        # Out-of-tenant / malformed key: never delete, never tombstone the row
        # to a state whose byte reference we could not honor.
        report["refused"] += 1
        record_cleanup_refused()
        outcome.update(action="refused", reason="out_of_tenant_key_scope")
        _capped_append(report["outcomes"], outcome)
        return

    object_present = store.head(key) is not None
    outcome["object_present"] = object_present
    if dry_run:
        report["expired"] += 1
        if object_present:
            report["objects_deleted"] += 1
        else:
            report["objects_missing"] += 1
        outcome.update(action="would_expire", reason=decision["reason"])
        _capped_append(report["outcomes"], outcome)
        return

    # Tombstone FIRST, bytes second.  Expiring a durable-byte row (available /
    # committed / partially_committed) flips it to ``expired`` before its bytes
    # are removed, so a crash mid-expiry leaves only lingering bytes under an
    # absorbing tombstone (which reconcile reports / cleanup purges) — never an
    # ``available`` row that silently lost the bytes it advertises.
    await repo.mark_expired(tenant_id, artifact_id)
    if object_present:
        store.delete(key)
        report["objects_deleted"] += 1
        record_objects_deleted()
    else:
        report["objects_missing"] += 1
    report["expired"] += 1
    record_artifacts_expired()
    outcome.update(action="expired", reason=decision["reason"])
    _capped_append(report["outcomes"], outcome)


# ═══════════════════════════════════════════════════════════════════════════
# data_exchange.reconcile_artifacts  (read-only, idempotent)
# ═══════════════════════════════════════════════════════════════════════════


async def reconcile_artifacts(
    tenant_ids: Any,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
) -> dict:
    """Reconcile ``data_artifacts`` metadata vs ObjectStore state (read-only).

    Detects, per tenant: (a) byte-owning rows — durable-byte
    (``available``/``committed``/``partially_committed``) or transient
    in-flight — whose ``object_key`` is absent from the store (a genuine
    missing-object anomaly, reported under ``missing_objects``); absorbing
    tombstone rows whose bytes are already gone land in the separate
    informational ``tombstoned_without_bytes`` bucket; and (b) objects under the
    tenant's ``data-exchange`` prefix that no byte-owning row claims — including
    bytes lingering under tombstone rows — reported as orphans.

    Mutates NOTHING (idempotent and read-only).  Returns exact counts + capped
    lists of artifact ids / object keys.
    """
    tenants = _normalize_tenant_ids(tenant_ids)
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()

    tenants_report: list[dict] = []
    totals: dict[str, int] = {
        "rows_scanned": 0,
        "objects_scanned": 0,
        "consistent": 0,
        "missing_objects": 0,
        "orphan_objects": 0,
        "tombstoned_without_bytes": 0,
    }
    for tenant_id in tenants:
        rows = await _collect_rows_for_tenant(repo, tenant_id)
        prefix = tenant_object_prefix(tenant_id)
        stored_keys = sorted(store.list(prefix))
        stored_set = set(stored_keys)

        row_by_key: dict[str, list[dict]] = {}
        rows_without_key = 0
        for row in rows:
            key = row.get("object_key")
            if not isinstance(key, str) or not key:
                rows_without_key += 1
                continue
            row_by_key.setdefault(key, []).append(row)

        # An object key is OWNED while any byte-owning row (durable-byte or
        # transient in-flight) references it.  Tombstone rows own nothing, so a
        # key they alone reference is orphaned payload to be purged.
        owned_keys: set[str] = set()
        for key, owners in row_by_key.items():
            if key not in stored_set:
                continue
            if any(
                not artifact_is_tombstone(r.get("status")) for r in owners
            ):
                owned_keys.add(key)
        orphan_keys = sorted(stored_set - owned_keys)

        missing_rows: list[dict] = []
        for key, owners in row_by_key.items():
            if key not in stored_set:
                missing_rows.extend(owners)
        # A byte-owning row (durable-byte state OR transient in-flight) whose
        # object is absent is a genuine missing-object anomaly.
        missing_owned = [
            r for r in missing_rows if not artifact_is_tombstone(r.get("status"))
        ]
        tombstoned_missing = [
            r for r in missing_rows if artifact_is_tombstone(r.get("status"))
        ]
        consistent_rows = [
            r
            for r in rows
            if isinstance(r.get("object_key"), str)
            and r.get("object_key") in owned_keys
        ]

        report: dict[str, Any] = {
            "tenant_id": tenant_id,
            "rows_scanned": len(rows),
            "rows_without_object_key": rows_without_key,
            "objects_scanned": len(stored_keys),
            "consistent": len(consistent_rows),
            "missing_objects": len(missing_owned),
            "tombstoned_without_bytes": len(tombstoned_missing),
            "orphan_objects": len(orphan_keys),
            "missing_artifact_ids": [
                {"artifact_id": r.get("artifact_id"), "object_key": r.get("object_key")}
                for r in missing_owned[:_MAX_REPORTED]
            ],
            "orphan_object_keys": orphan_keys[:_MAX_REPORTED],
        }
        record_reconcile_missing(len(missing_owned))
        record_reconcile_orphans(len(orphan_keys))
        for key in totals:
            if key == "missing_objects":
                totals[key] += len(missing_owned)
            elif key == "orphan_objects":
                totals[key] += len(orphan_keys)
            elif key == "tombstoned_without_bytes":
                totals[key] += len(tombstoned_missing)
            elif key == "consistent":
                totals[key] += len(consistent_rows)
            elif key == "rows_scanned":
                totals[key] += len(rows)
            elif key == "objects_scanned":
                totals[key] += len(stored_keys)
        tenants_report.append(report)

    return {"tenants": tenants_report, "totals": totals}


# ═══════════════════════════════════════════════════════════════════════════
# data_exchange.cleanup_artifacts
# ═══════════════════════════════════════════════════════════════════════════


async def cleanup_artifacts(
    tenant_id: str,
    *,
    orphan_keys: Optional[list[str]] = None,
    artifact_ids: Optional[list[str]] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
    scan_for_orphans: Optional[bool] = None,
    purge_lingering_tombstone_payloads: bool = True,
    dry_run: bool = False,
) -> dict:
    """Delete orphaned object bytes and explicitly-flagged artifact rows.

    Cleanup NEVER purges bytes owned by a durable-byte row (``available`` /
    ``committed`` / ``partially_committed``) or a transient in-flight row — those
    are this plane's live payloads.  Targets, strictly within ``tenant_id``'s
    own key prefix:

    - ``orphan_keys`` (or, when none are given and ``scan_for_orphans`` is not
      False, a re-run of the reconcile orphan scan): object bytes with no
      byte-owning metadata row → deleted.
    - ``artifact_ids``: rows explicitly flagged for cleanup → the row is
      tombstoned to ``deleted`` via ``mark_deleted`` (the strongest row removal
      the DataArtifactRepository exposes — tombstones are the audit) and its
      bytes are then deleted.  An already-tombstoned flagged row is not
      re-transitioned (no-op); only its lingering bytes are purged.
    - lingering payload bytes under absorbing tombstone rows (a partial delete
      left the object behind) → purged when ``purge_lingering_tombstone_payloads``.

    A key that is not well-shaped or not under the tenant's own prefix is
    REFUSED and reported (never deleted) — the security invariant the
    load/security harness asserts.  Rows referencing keys that are refused are
    not tombstoned either.
    """
    tenants = _normalize_tenant_ids(tenant_id)
    tenant_id = tenants[0]
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()

    report: dict[str, Any] = {
        "tenant_id": tenant_id,
        "orphans_deleted": 0,
        "rows_deleted": 0,
        "rows_already_tombstoned": 0,
        "lingering_payloads_purged": 0,
        "objects_deleted": 0,
        "refused_keys": [],
        "not_found_rows": [],
        "dry_run": bool(dry_run),
    }

    # ── 1. orphan object bytes ──────────────────────────────────────────────
    explicit_orphans = bool(orphan_keys)
    scan = (
        scan_for_orphans
        if scan_for_orphans is not None
        else (not explicit_orphans)
    )
    keys_to_delete: list[str] = []
    if explicit_orphans:
        keys_to_delete.extend(str(k) for k in orphan_keys)
    if scan:
        keys_to_delete.extend(await _orphan_keys(tenant_id, repo, store))

    for raw_key in keys_to_delete:
        key = validate_object_key_for_delete(tenant_id, raw_key)
        if key is None:
            report["refused_keys"].append(raw_key)
            record_cleanup_refused()
            continue
        if not dry_run:
            store.delete(key)
            record_orphan_objects_deleted()
        report["orphans_deleted"] += 1
        report["objects_deleted"] += 1

    # ── 2. rows explicitly flagged for cleanup ──────────────────────────────
    for artifact_id in artifact_ids or []:
        try:
            row = await repo.get(tenant_id, str(artifact_id))
        except Exception:  # NotFoundError etc.
            report["not_found_rows"].append(str(artifact_id))
            continue
        already_tombstoned = artifact_is_tombstone(row.get("status"))
        key = validate_object_key_for_delete(tenant_id, row.get("object_key"))
        if key is None:
            report["refused_keys"].append(row.get("object_key"))
            record_cleanup_refused()
            continue
        object_present = store.head(key) is not None
        if not dry_run:
            # Tombstone the row FIRST (an explicitly-flagged durable/transient
            # row transitions to ``deleted``), then purge its bytes — never a
            # live row that lost the bytes it advertises.  An already-tombstoned
            # flagged row is a no-op transition (a tombstone has no outgoing
            # moves), so only its lingering bytes are purged.
            if not already_tombstoned:
                await repo.mark_deleted(tenant_id, str(artifact_id))
            if object_present:
                store.delete(key)
                report["objects_deleted"] += 1
                record_orphan_objects_deleted()
        if already_tombstoned:
            report["rows_already_tombstoned"] += 1
        else:
            report["rows_deleted"] += 1

    # ── 3. lingering payload bytes under absorbing tombstone rows ───────────
    if purge_lingering_tombstone_payloads:
        async for row in _iter_rows_for_tenant(repo, tenant_id):
            # Durable-byte and transient rows OWN their object bytes — only
            # absorbing byte-less tombstones can have "lingering" payloads.
            if not artifact_is_tombstone(row.get("status")):
                continue
            key = validate_object_key_for_delete(tenant_id, row.get("object_key"))
            if key is None:
                continue
            if store.head(key) is None:
                continue
            if not dry_run:
                store.delete(key)
                record_orphan_objects_deleted()
            report["lingering_payloads_purged"] += 1
            report["objects_deleted"] += 1

    return report


async def _orphan_keys(
    tenant_id: str, repo: DataArtifactRepository, store: ObjectStore
) -> list[str]:
    """Keys under the tenant's prefix with no metadata row (reconcile scan)."""
    rows = await _collect_rows_for_tenant(repo, tenant_id)
    referenced = {
        str(r["object_key"])
        for r in rows
        if isinstance(r.get("object_key"), str) and r["object_key"]
    }
    prefix = tenant_object_prefix(tenant_id)
    return sorted(set(store.list(prefix)) - referenced)


# ═══════════════════════════════════════════════════════════════════════════
# data_exchange.finalize_pending_egress
# ═══════════════════════════════════════════════════════════════════════════


async def _load_job_status(
    tenant_id: str,
    job_id: Optional[str],
    loader: Optional[Callable[[str, str], Awaitable[Optional[str]]]],
) -> Optional[str]:
    """Resolve a durable job's status string (or None when unrecorded).

    An injected ``loader(tenant_id, job_id) -> Optional[str]`` wins (DB-free
    tests).  The default reads the job through the jobs-platform service; any
    error or missing record resolves to None (the bridge leaves such rows for
    operator review — never fabricates terminal state).
    """
    if loader is not None:
        try:
            return await loader(tenant_id, job_id or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "finalize_pending_egress job-loader failed tenant=%s job=%s: %s",
                tenant_id,
                job_id,
                exc,
            )
            return None
    if not job_id:
        return None
    try:
        from services.jobs.service import get_jobs_service  # lazy — heavy seam

        job = await get_jobs_service().get_job(tenant_id, job_id)
    except Exception as exc:  # noqa: BLE001 — a queryable job store is required
        logger.warning(
            "finalize_pending_egress could not read job tenant=%s job=%s: %s",
            tenant_id,
            job_id,
            exc,
        )
        return None
    if job is None:
        return None
    return job.get("status")


async def finalize_pending_egress(
    tenant_id: str,
    *,
    now: Optional[datetime] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
    job_loader: Optional[Callable[[str, str], Awaitable[Optional[str]]]] = None,
    artifact_types: Optional[tuple[str, ...]] = None,
    dry_run: bool = False,
) -> dict:
    """Idempotently reconcile egress stragglers to a genuine terminal status.

    See the module docstring for the exact seam analysis.  In short:
    ``available`` requires a terminal-success job record AND durable bytes at
    the row's OWN tenant-scoped object key (key shape re-validated here), whose
    content is hashed so the row is flipped via the repository's verified
    ``mark_available(size_bytes=..., sha256=...)`` — real metadata is always
    back-filled, never fabricated.  ``failed`` requires a failed/cancelled job
    record (``generating`` → ``failed``).  Everything else (mid-flight,
    succeeded-without-bytes, succeeded with an out-of-scope key, no job record)
    is left untouched and reported.  Never re-creates artifacts; never mutates a
    row that is mid-flight.
    """
    del now  # reserved: a future "stuck for > X" guard; current bridge is per-row
    tenants = _normalize_tenant_ids(tenant_id)
    tenant_id = tenants[0]
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()
    if artifact_types is None:
        artifact_types = EGRESS_ARTIFACT_TYPES

    report: dict[str, Any] = {
        "tenant_id": tenant_id,
        "rows_scanned": 0,
        "finalized_available": 0,
        "finalized_failed": 0,
        "in_flight": 0,
        "success_without_bytes": 0,
        "no_job_record": 0,
        "dry_run": bool(dry_run),
        "outcomes": [],
    }

    async for row in _iter_rows_for_tenant(
        repo, tenant_id
    ):
        status = str(row.get("status") or "created")
        if status not in TRANSIENT_EGRESS_STATUSES:
            continue  # terminal or a live status the bridge does not manage
        if row.get("direction") != "egress":
            continue
        if artifact_types and row.get("artifact_type") not in artifact_types:
            continue
        report["rows_scanned"] += 1

        artifact_id = row.get("artifact_id")
        key = row.get("object_key")
        # Only a tenant-scoped, scheme-shaped object key can ever be finalized:
        # the ``available`` row must own real bytes at its OWN envelope key
        # (``data-exchange/<tenant>/<direction>/<artifact_id>``).  Anything else
        # is left for operator review / reconcile — never fabricated.
        safe_key: Optional[str] = None
        if isinstance(key, str) and key:
            safe_key = validate_object_key_for_delete(tenant_id, key)
        object_present = safe_key is not None and store.head(safe_key) is not None

        job_status = await _load_job_status(
            tenant_id, row.get("job_id"), job_loader
        )
        outcome: dict[str, Any] = {
            "artifact_id": artifact_id,
            "status": status,
            "object_present": bool(object_present),
            "job_status": job_status,
        }

        if job_status in _JOB_TERMINAL_SUCCESS:
            if object_present:
                # Hash the durable bytes and let the repository's verified
                # mark_available back-fill the real size/sha256 onto the row.
                try:
                    content = store.get(safe_key)
                except ObjectNotFoundError:
                    content = None
                if content is None:
                    # Vanished between head and get — do not fabricate.
                    report["success_without_bytes"] += 1
                    record_egress_finalized("success_without_bytes")
                    outcome.update(
                        action="leave_success_without_bytes",
                        reason="object_vanished_between_head_and_get",
                    )
                else:
                    size_bytes = len(content)
                    sha256 = hashlib.sha256(content).hexdigest()
                    if not dry_run:
                        await repo.mark_available(
                            tenant_id,
                            artifact_id,
                            size_bytes=size_bytes,
                            sha256=sha256,
                        )
                    report["finalized_available"] += 1
                    record_egress_finalized("available")
                    outcome.update(
                        action="finalize_available",
                        size_bytes=size_bytes,
                        sha256=sha256,
                    )
            else:
                report["success_without_bytes"] += 1
                record_egress_finalized("success_without_bytes")
                outcome.update(action="leave_success_without_bytes")
        elif job_status in _JOB_TERMINAL_FAILURE:
            if not dry_run:
                await repo.update_status(tenant_id, artifact_id, "failed")
            report["finalized_failed"] += 1
            record_egress_finalized("failed")
            outcome.update(action="finalize_failed")
        elif job_status in _JOB_LIVE_STATUSES:
            report["in_flight"] += 1
            record_egress_finalized("in_flight")
            outcome.update(action="leave_in_flight")
        else:
            report["no_job_record"] += 1
            record_egress_finalized("no_job_record")
            outcome.update(action="leave_no_job_record")
        _capped_append(report["outcomes"], outcome)

    return report


# ═══════════════════════════════════════════════════════════════════════════
# handlers + registration (thin adapters onto the jobs platform)
# ═══════════════════════════════════════════════════════════════════════════


async def _maybe_heartbeat(ctx: Any) -> None:
    fn = getattr(ctx, "heartbeat", None)
    if fn is None:
        return
    try:
        await fn()
    except Exception:  # noqa: BLE001 — lease heartbeats are best-effort here
        pass


def _payload_tenant_ids(payload: dict, ctx: Any) -> list[str]:
    payload_tenant_ids = payload.get("tenant_ids")
    if payload_tenant_ids is None:
        payload_tenant_ids = payload.get("tenant_id")
    if payload_tenant_ids is None:
        payload_tenant_ids = getattr(ctx, "tenant_id", None)
    return _normalize_tenant_ids(payload_tenant_ids)


async def expire_artifacts_job(payload: dict, ctx: Any) -> Any:
    """``data_exchange.expire_artifacts`` durable-job handler."""
    from services.jobs.handlers import JobOutcome

    tenant_ids = _payload_tenant_ids(payload, ctx)
    result = await expire_artifacts(
        tenant_ids, dry_run=bool(payload.get("dry_run", False))
    )
    await _maybe_heartbeat(ctx)
    return JobOutcome(status="succeeded", result=result)


async def reconcile_artifacts_job(payload: dict, ctx: Any) -> Any:
    """``data_exchange.reconcile_artifacts`` durable-job handler (read-only)."""
    from services.jobs.handlers import JobOutcome

    tenant_ids = _payload_tenant_ids(payload, ctx)
    result = await reconcile_artifacts(tenant_ids)
    await _maybe_heartbeat(ctx)
    return JobOutcome(status="succeeded", result=result)


async def cleanup_artifacts_job(payload: dict, ctx: Any) -> Any:
    """``data_exchange.cleanup_artifacts`` durable-job handler."""
    from services.jobs.handlers import JobOutcome

    tenant_ids = _payload_tenant_ids(payload, ctx)
    result = await cleanup_artifacts(
        tenant_ids[0],
        orphan_keys=payload.get("orphan_keys"),
        artifact_ids=payload.get("artifact_ids"),
        dry_run=bool(payload.get("dry_run", False)),
    )
    await _maybe_heartbeat(ctx)
    return JobOutcome(status="succeeded", result=result)


async def finalize_pending_egress_job(payload: dict, ctx: Any) -> Any:
    """``data_exchange.finalize_pending_egress`` durable-job handler."""
    from services.jobs.handlers import JobOutcome

    tenant_ids = _payload_tenant_ids(payload, ctx)
    result = await finalize_pending_egress(
        tenant_ids[0], dry_run=bool(payload.get("dry_run", False))
    )
    await _maybe_heartbeat(ctx)
    return JobOutcome(status="succeeded", result=result)


def register() -> None:
    """Register the four M7 ops handlers (idempotent).

    Called from the FastAPI lifespan alongside
    ``register_data_exchange_migrate_handlers()``.  Registration is inert until a
    job is enqueued — the coordinator schedules these (operator-triggered /
    cron) under the same ``settings.data_exchange.enabled`` gate.
    """
    from services.jobs.handlers import HANDLER_REGISTRY, register_handler

    for job_type, handler in (
        (JOB_EXPIRE_ARTIFACTS, expire_artifacts_job),
        (JOB_RECONCILE_ARTIFACTS, reconcile_artifacts_job),
        (JOB_CLEANUP_ARTIFACTS, cleanup_artifacts_job),
        (JOB_FINALIZE_PENDING_EGRESS, finalize_pending_egress_job),
    ):
        if job_type in HANDLER_REGISTRY:
            continue
        register_handler(job_type)(handler)
        logger.info("registered %s job handler", job_type)


__all__ = [
    "JOB_EXPIRE_ARTIFACTS",
    "JOB_RECONCILE_ARTIFACTS",
    "JOB_CLEANUP_ARTIFACTS",
    "JOB_FINALIZE_PENDING_EGRESS",
    "DATA_EXCHANGE_OPS_JOB_TYPES",
    "EXPORT_ARTIFACT_TYPE",
    "REPORT_ARTIFACT_TYPE",
    "EGRESS_ARTIFACT_TYPES",
    "TRANSIENT_EGRESS_STATUSES",
    "TenantScopeViolationError",
    "validate_object_key_for_delete",
    "assert_key_in_tenant_scope",
    "expire_artifacts",
    "reconcile_artifacts",
    "cleanup_artifacts",
    "finalize_pending_egress",
    "expire_artifacts_job",
    "reconcile_artifacts_job",
    "cleanup_artifacts_job",
    "finalize_pending_egress_job",
    "register",
]
