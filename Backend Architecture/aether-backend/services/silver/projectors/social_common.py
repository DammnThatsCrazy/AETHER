"""Shared helpers for the Social Silver projectors (M3 Social Silver plane).

The six ``social_*`` projectors turn Bronze social events (the generic provider
event envelope produced by UPR ingestion / a social normalizer) into canonical
Social Silver rows on ``silver_social_*_facts`` tables. This module owns the
parts they share:

- reading the provider envelope (provenance) off a Bronze event,
- resolving the canonical ``sourceScope`` / ``evidenceBasis`` members,
- extracting per-fact records from a payload,
- stable idempotency-key composition.

Consent decision (documented for the whole plane)
-------------------------------------------------
Silver projectors record ``consent_snapshot_id`` and ``privacy_class`` (via
``BaseProjector._base_row``) and do NOT introduce a new insert-time consent
enforcement gate: consent is enforced at ingestion and at the graph-projection
boundary, never at Silver insert (that would change behavior for the entire
Silver plane). Social facts follow the same convention — the data-rights
authorization the fact was collected under is carried as ``rights_ref`` from the
event's ``consent_snapshot_id`` when the producer supplies one, and the module
docstrings do not add any gating that the existing projectors lack.

Provenance (provider envelope) contract
---------------------------------------
No live social provider exists yet (M2 UPR social scaffolds land in parallel),
so the projectors are designed against the generic provider event envelope. The
UPR ingestion bridge places provider provenance under ``event.context.provider``
as a sub-object whose keys mirror ``RawProviderRecord`` / ``AetherEvent.context``
(snake_case; camelCase accepted):

    "provider": {
        "provider":            "x",                    # provider family
        "provider_identity":   "social.x.account_read",# family.product.capability
        "account_id":          "xacct-1",
        "acquisition_mode":    "poll",                 # sdk|webhook|poll|report|stream|import|reconciliation
        "source_scope":        "tenant_connected",     # optional explicit canonical stamp
        "evidence_basis":      "provider_api",         # optional explicit canonical stamp
        "provider_record_id":  "xr-777",
        "observed_at":         "2026-09-01T00:00:00+00:00",
    }

``sourceScope`` / ``evidenceBasis`` are never guessed: an explicit canonical
stamp wins; otherwise they are derived 1:1 from ``acquisition_mode``; otherwise
``source_scope`` stays ``None`` (there is no ``unknown`` source-scope member)
and ``evidence_basis`` is ``unknown``. ``olympus_corpus`` is never auto-derived
(corpus→tenant projection is D-OPEN in the program ledger).
"""

from __future__ import annotations

from typing import Any

from shared.social360.canonical import (
    EVIDENCE_BASIS,
    EVIDENCE_BASIS_BY_ACQUISITION_MODE,
    SOURCE_SCOPES,
    SOURCE_SCOPE_BY_ACQUISITION_MODE,
)

# acquisition modes accepted by the generic provider envelope.
_VALID_ACQUISITION_MODES = frozenset(
    {"sdk", "webhook", "poll", "report", "stream", "import", "reconciliation"}
)

# Keys under event.context.provider (and event.context) we recognise.
def _provider_envelope(event: dict[str, Any]) -> dict[str, Any]:
    ctx = event.get("context")
    if not isinstance(ctx, dict):
        return {}
    env = ctx.get("provider")
    return env if isinstance(env, dict) else {}


def acquisition_mode(event: dict[str, Any]) -> str | None:
    """Provider-envelope acquisition mode (sdk|webhook|poll|...|None)."""
    env = _provider_envelope(event)
    mode = env.get("acquisition_mode") or env.get("acquisitionMode")
    if mode is not None:
        mode = str(mode).lower()
        return mode if mode in _VALID_ACQUISITION_MODES else None
    ctx = event.get("context")
    if isinstance(ctx, dict):
        mode = ctx.get("acquisitionMode") or ctx.get("acquisition_mode")
        if mode is not None:
            mode = str(mode).lower()
            return mode if mode in _VALID_ACQUISITION_MODES else None
    return None


def resolve_source_scope(
    event: dict[str, Any], record: dict[str, Any] | None = None
) -> str | None:
    """Canonical sourceScope for the event, or None when not derivable.

    Priority: record-level explicit stamp > provider-envelope stamp > context
    stamp > acquisition-mode derivation. Never guessed; no ``olympus_corpus``
    auto-derivation.
    """
    if isinstance(record, dict):
        for key in ("source_scope", "sourceScope"):
            candidate = record.get(key)
            if candidate in SOURCE_SCOPES:
                return candidate
    env = _provider_envelope(event)
    for key in ("source_scope", "sourceScope"):
        candidate = env.get(key)
        if candidate in SOURCE_SCOPES:
            return candidate
    ctx = event.get("context")
    if isinstance(ctx, dict):
        for key in ("sourceScope", "source_scope"):
            candidate = ctx.get(key)
            if candidate in SOURCE_SCOPES:
                return candidate
    scope = SOURCE_SCOPE_BY_ACQUISITION_MODE.get(str(acquisition_mode(event) or ""))
    return scope if scope in SOURCE_SCOPES else None


def resolve_evidence_basis(
    event: dict[str, Any], record: dict[str, Any] | None = None
) -> str:
    """Canonical evidenceBasis for the event, defaulting to ``unknown``."""
    if isinstance(record, dict):
        for key in ("evidence_basis", "evidenceBasis"):
            candidate = record.get(key)
            if candidate in EVIDENCE_BASIS:
                return candidate
    env = _provider_envelope(event)
    for key in ("evidence_basis", "evidenceBasis"):
        candidate = env.get(key)
        if candidate in EVIDENCE_BASIS:
            return candidate
    ctx = event.get("context")
    if isinstance(ctx, dict):
        for key in ("evidenceBasis", "evidence_basis"):
            candidate = ctx.get(key)
            if candidate in EVIDENCE_BASIS:
                return candidate
    basis = EVIDENCE_BASIS_BY_ACQUISITION_MODE.get(str(acquisition_mode(event) or ""))
    return basis if basis else "unknown"


def provider_identity_of(
    event: dict[str, Any], record: dict[str, Any] | None = None
) -> str | None:
    """Provider family/product identity (e.g. ``social.x.account_read``)."""
    if isinstance(record, dict) and record.get("provider_identity"):
        return str(record["provider_identity"])
    env = _provider_envelope(event)
    if env.get("provider_identity"):
        return str(env["provider_identity"])
    if env.get("provider"):
        return str(env["provider"])
    if env.get("providerFamily"):
        return str(env["providerFamily"])
    return None


def provider_family_of(
    event: dict[str, Any], record: dict[str, Any] | None = None
) -> str | None:
    """Short provider family (e.g. ``x``)."""
    if isinstance(record, dict) and record.get("provider"):
        return str(record["provider"])
    env = _provider_envelope(event)
    if env.get("provider"):
        return str(env["provider"])
    identity = provider_identity_of(event, record)
    if identity and "." in identity:
        return identity.split(".")[0]
    return None


def provider_platform_of(
    event: dict[str, Any], record: dict[str, Any] | None = None
) -> str | None:
    """Canonical provider (platform) identity, e.g. ``x`` / ``twitter``.

    Prefers the envelope ``provider`` key; otherwise derives the product segment
    from a ``family.product.capability`` ``provider_identity``
    (``social.x.account_read`` -> ``x``). Falls back to a bare token
    (``twitter``) verbatim. This is the ``provider_identity`` value the Social
    Silver fact schemas expect (the platform an account/edge lives on).
    """
    if isinstance(record, dict) and record.get("provider"):
        return str(record["provider"])
    env = _provider_envelope(event)
    if env.get("provider"):
        return str(env["provider"])
    identity = provider_identity_of(event, record)
    if not identity:
        return None
    if "." in identity:
        segments = identity.split(".")
        return segments[1] if len(segments) >= 3 else segments[0]
    return identity


def records_of(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize a payload to a list of provider-shaped record dicts.

    Accepts either a single record object or a ``records`` array (a normalizer
    may batch several provider records into one Bronze event). Non-dict members
    are dropped deterministically.
    """
    if not isinstance(payload, dict):
        return []
    batch = payload.get("records")
    if isinstance(batch, list):
        return [r for r in batch if isinstance(r, dict)]
    return [payload]


def compose_idempotency_key(source_event_id: Any, *parts: str) -> str:
    """Deterministic per-fact idempotency key within a single source event.

    A Bronze event may fan out to several facts (a follower-list pull, a metric
    bundle). The writer dedupes on ``(tenant_id, idempotency_key)`` and real
    tables UNIQUE on ``idempotency_key``, so each row needs its own stable key
    derived from the source event id plus a stable natural discriminator —
    exactly like ``ImportProjector`` (``<commit>:<file>:<row>:<primitive>``).
    """
    if not parts:
        return str(source_event_id)
    joined = ":".join(_safe(part) for part in parts if _safe(part))
    return f"{source_event_id}:{joined}" if joined else str(source_event_id)


def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def as_str(value: Any) -> str | None:
    """Stringify a scalar, returning None for blanks (honest null)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [value]
    return None


__all__ = [
    "acquisition_mode",
    "as_list",
    "as_str",
    "compose_idempotency_key",
    "provider_family_of",
    "provider_identity_of",
    "provider_platform_of",
    "records_of",
    "resolve_evidence_basis",
    "resolve_source_scope",
]
