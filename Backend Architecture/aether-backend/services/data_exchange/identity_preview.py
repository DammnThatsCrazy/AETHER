"""Data Exchange Plane — identity-preview adapter (M3).

Net-new preview over the canonical identity-resolution seam
(``docs/plans/data-exchange-api.md`` M3 ``preview/identity``).  For each
identity-bearing field of a mapped import the tenant can preview, **before
commit**, what the canonical resolution would decide for a sample value —
new entity vs. a single existing link vs. an ambiguous candidate set vs. a
blocked/suppressed/conflicting value — without persisting anything.

Design constraints (the Data Exchange Plane is a *control envelope*, never a
second import state machine, never a second identity engine):

- This adapter is **read-only**: it never invokes the mutating
  ``IdentityResolutionService.resolve_event`` path (which persists signal
  observations, creates subjects, writes graph edges and audit rows).  Instead
  it composes the canonical *read* seams — deterministic normalization
  (``services/identity/normalization``), canonical hashing
  (``services/identity/hashing``), the identity repository's tenant-scoped
  alias lookup and suppression check (``IdentityResolutionRepository``) — and
  renders a coarse preview decision in the canonical decision vocabulary
  (``MergeDecision`` / ``ConfidenceTier``).  This keeps the preview truly
  non-committing; full merge-policy parity (which candidate wins a multi-way
  merge, deterministic-conflict nuance) is intentionally out of scope for the
  preview and is surfaced by the real resolver during ingestion instead.
- The canonical seams are reachable through module-level functions so route
  tests can inject fakes and stay DB-free (same pattern as the M1 storage
  migration tests).
- Identity signal type per field is inferred from the field name / sample value
  shape; an explicit ``signal_type`` on a probe (or on the envelope mapping's
  ``identity_policy``) always wins over the inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from repositories.imports_repo import get_imports_repository
from services.identity.hashing import (
    hash_email,
    hash_external_id,
    hash_phone,
    hash_wallet,
)
from services.identity.models import ConfidenceTier, IdentitySignalType, MergeDecision
from services.identity.normalization import (
    normalize_email,
    normalize_external_id,
    normalize_phone,
    normalize_wallet_address,
)
from shared.common.common import BadRequestError

# ── identity field families (field-name hints → canonical signal) ──────────

# Canonical signal types whose values come straight out of an imported source
# column.  ``user_id``/``anonymous_id`` are SDK-derived and never imported, so
# the preview only models the durable identifier families the import engine can
# actually carry.
IDENTITY_SIGNAL_TYPES: tuple[str, ...] = (
    "email_hash",
    "phone_hash",
    "external_id",
    "wallet_address",
)

_FIELD_NAME_HINTS: tuple[tuple[tuple[str, ...], IdentitySignalType], ...] = (
    (("email", "mail"), IdentitySignalType.EMAIL_HASH),
    (("phone", "mobile", "tel", "sms"), IdentitySignalType.PHONE_HASH),
    (("wallet", "address0x", "onchain"), IdentitySignalType.WALLET_ADDRESS),
)


def infer_signal_type(field_name: str, value: Any) -> Optional[IdentitySignalType]:
    """Best-effort signal type for an import source column + sample value.

    Explicit probe/identity-policy signal hints are resolved before calling
    this; the inference is a fallback only.  Value shape (``@``-containing,
    ``0x``-prefixed) is a tiebreaker when the field name is ambiguous.
    """
    name = (field_name or "").strip().lower()
    text = str(value or "").strip().lower()
    for hints, sig_type in _FIELD_NAME_HINTS:
        if any(h in name for h in hints):
            return sig_type
    if "@" in text:
        return IdentitySignalType.EMAIL_HASH
    if text.startswith("0x"):
        return IdentitySignalType.WALLET_ADDRESS
    digits = sum(ch.isdigit() for ch in text)
    if digits >= 7:
        return IdentitySignalType.PHONE_HASH
    # A bare opaque identifier (customer id, account id, …) is tenant-scoped.
    return IdentitySignalType.EXTERNAL_ID


# ── canonical read-side seams (swappable in DB-free tests) ─────────────────

AliasSeam = Callable[[str, str, str], Awaitable[list[str]]]
SuppressionSeam = Callable[[str, str, str], Awaitable[bool]]
SessionSeam = Callable[[str, str], Awaitable[dict]]


async def _session_seam(tenant_id: str, import_id: str) -> dict:
    """Canonical import-session tenant guard (mirrors the engine's reads)."""
    return await get_imports_repository().get_session(tenant_id, import_id)


async def _alias_seam(
    tenant_id: str, signal_type: str, value_hash: str
) -> list[str]:
    """Existing canonical entities owning a hashed identity signal."""
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    return await repo.find_subjects_by_alias(tenant_id, signal_type, value_hash)


async def _suppression_seam(
    tenant_id: str, signal_type: str, value_hash: str
) -> bool:
    """Whether the hashed identity signal is suppressed for the tenant."""
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    return await repo.check_suppression(tenant_id, signal_type, value_hash)


async def _mapping_seam(tenant_id: str, import_id: str) -> Optional[dict]:
    """Latest canonical mapping for the import (identity-column check)."""
    return await get_imports_repository().get_latest_mapping(tenant_id, import_id)


# ── request/response models ────────────────────────────────────────────────


class IdentityFieldProbe(BaseModel):
    """One sample value to preview for one identity-bearing source column."""

    field: str = Field(..., min_length=1)
    value: Any
    index: Optional[int] = None
    signal_type: Optional[str] = None  # optional override of the inference


class IdentityPreviewBody(BaseModel):
    identity_fields: list[IdentityFieldProbe] = Field(..., min_length=1)


@dataclass
class _ProbeResult:
    field: str
    index: int
    value: Any
    decision: str
    confidence: float
    tier: str
    reason: Optional[str] = None


# ── decision synthesis (read-only) ─────────────────────────────────────────

# Preview decision grammar maps straight onto the canonical MergeDecision
# values; the few extra coarse cases reuse ``blocked``/``noop``.
_PREVIEW_DECISIONS: tuple[str, ...] = (
    "create",
    "link",
    "candidate",
    "blocked",
    "noop",
)

_STRONG_DETERMINISTIC = frozenset({"external_id", "wallet_address"})


def _confidence_for(sig_type: str, *, matched: bool) -> tuple[float, str]:
    """Canonical-style confidence + tier for a signal family.

    Deterministic tenant-owned identifiers (external_id, wallet) resolve at
    DETERMINISTIC strength when a match exists; probabilistic identifiers
    (email, phone) resolve at STRONG/PROBABLE.  A *new* value carries the same
    family strength as the *claim* it would create.
    """
    if sig_type in _STRONG_DETERMINISTIC:
        return (1.0, ConfidenceTier.DETERMINISTIC.value)
    if sig_type == IdentitySignalType.PHONE_HASH.value:
        return (0.9, ConfidenceTier.STRONG.value)
    if sig_type == IdentitySignalType.EMAIL_HASH.value:
        return (0.8, ConfidenceTier.PROBABLE.value) if not matched else (0.85, ConfidenceTier.STRONG.value)
    return (0.7, ConfidenceTier.PROBABLE.value)


def _hash_probe(sig_type: IdentitySignalType, raw_value: Any, tenant_id: str) -> str:
    value = str(raw_value).strip()
    if sig_type == IdentitySignalType.EMAIL_HASH:
        if not normalize_email(value):
            return ""
        return hash_email(value, tenant_id)
    if sig_type == IdentitySignalType.PHONE_HASH:
        if not normalize_phone(value):
            return ""
        return hash_phone(value, tenant_id)
    if sig_type == IdentitySignalType.WALLET_ADDRESS:
        if not normalize_wallet_address(value):
            return ""
        return hash_wallet(value)
    if sig_type == IdentitySignalType.EXTERNAL_ID:
        # Canonical extraction (services/identity/signals.py) hashes the
        # *tenant-scoped* key ``"{tenant_id}:{raw}"`` — ``normalize_external_id``
        # is not just a validity gate here; its result IS the hash input.  Hashing
        # the raw value instead would never match an alias the resolver stored.
        normalized = normalize_external_id(value, tenant_id)
        if not normalized:
            return ""
        return hash_external_id(normalized, tenant_id)
    return ""


def _field_is_identity_mapped(field: str, mapping: Optional[dict]) -> bool:
    """True when a mapped column targets the canonical identifier primitive."""
    if mapping is None:
        return True  # no mapping yet → do not over-restrict the preview
    for fm in mapping.get("fields", []):
        if isinstance(fm, dict) and fm.get("source_column") == field:
            if fm.get("primitive") == "identifier":
                return True
    return False


async def _decide_probe(
    tenant_id: str,
    probe: IdentityFieldProbe,
    *,
    alias_seam: AliasSeam,
    suppression_seam: SuppressionSeam,
) -> _ProbeResult:
    sig_type = _resolve_signal_type(probe)
    if sig_type is None:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.NOOP.value,
            confidence=0.0,
            tier=ConfidenceTier.BLOCKED.value,
            reason="unsupported_identity_field",
        )
    value_hash = _hash_probe(sig_type, probe.value, tenant_id)
    if not value_hash:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.NOOP.value,
            confidence=0.0,
            tier=ConfidenceTier.BLOCKED.value,
            reason="unparseable_value",
        )
    sig_type_str = sig_type.value

    suppressed = await suppression_seam(tenant_id, sig_type_str, value_hash)
    if suppressed:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.BLOCKED.value,
            confidence=0.0,
            tier=ConfidenceTier.BLOCKED.value,
            reason="suppressed_identifier",
        )

    matches = await alias_seam(tenant_id, sig_type_str, value_hash)
    confidence, tier = _confidence_for(sig_type_str, matched=bool(matches))

    if not matches:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.CREATE.value,
            confidence=confidence,
            tier=tier,
            reason="no_existing_match",
        )
    if len(matches) == 1:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.LINK.value,
            confidence=confidence,
            tier=tier,
            reason="single_existing_match",
        )
    # Multiple distinct canonical entities own the SAME identifier: a
    # deterministic family is a hard conflict (blocked); a probabilistic one
    # needs operator review (candidate).
    if sig_type_str in _STRONG_DETERMINISTIC:
        return _ProbeResult(
            field=probe.field,
            index=probe.index if probe.index is not None else 0,
            value=probe.value,
            decision=MergeDecision.BLOCKED.value,
            confidence=0.0,
            tier=ConfidenceTier.BLOCKED.value,
            reason="deterministic_conflict",
        )
    return _ProbeResult(
        field=probe.field,
        index=probe.index if probe.index is not None else 0,
        value=probe.value,
        decision=MergeDecision.CANDIDATE.value,
        confidence=0.5,
        tier=ConfidenceTier.PROBABLE.value,
        reason="ambiguous_multiple_matches",
    )


def _resolve_signal_type(probe: IdentityFieldProbe) -> Optional[IdentitySignalType]:
    override = (probe.signal_type or "").strip().lower()
    if override:
        try:
            return IdentitySignalType(override)
        except ValueError:
            raise BadRequestError(f"unsupported identity signal_type {override!r}") from None
    return infer_signal_type(probe.field, probe.value)


# ── public adapter ─────────────────────────────────────────────────────────

def _summary(results: list[_ProbeResult]) -> dict:
    counts: dict[str, int] = {d: 0 for d in _PREVIEW_DECISIONS}
    for r in results:
        counts[r.decision] = counts.get(r.decision, 0) + 1
    return {"total": len(results), **counts}


async def preview_identity_decisions(
    tenant_id: str,
    import_id: str,
    *,
    identity_fields: list[IdentityFieldProbe],
    session_seam: Optional[SessionSeam] = None,
    alias_seam: Optional[AliasSeam] = None,
    suppression_seam: Optional[SuppressionSeam] = None,
    mapping_seam: Optional[Callable[[str, str], Awaitable[Optional[dict]]]] = None,
) -> dict:
    """Preview canonical identity resolution over mapped identity columns.

    Returns ``{"decisions": [...], "summary": {...}}``.  Non-mutating.
    """
    if not identity_fields:
        raise BadRequestError("identity_fields must not be empty")
    session_seam = session_seam or _session_seam
    alias_seam = alias_seam or _alias_seam
    suppression_seam = suppression_seam or _suppression_seam
    mapping_seam = mapping_seam or _mapping_seam

    await session_seam(tenant_id, import_id)  # tenant guard (raises when absent)
    mapping = await mapping_seam(tenant_id, import_id)

    results: list[_ProbeResult] = []
    for probe in identity_fields:
        if not _field_is_identity_mapped(probe.field, mapping):
            results.append(
                _ProbeResult(
                    field=probe.field,
                    index=probe.index if probe.index is not None else 0,
                    value=probe.value,
                    decision=MergeDecision.NOOP.value,
                    confidence=0.0,
                    tier=ConfidenceTier.BLOCKED.value,
                    reason="field_not_mapped_as_identifier",
                )
            )
            continue
        results.append(
            await _decide_probe(
                tenant_id, probe, alias_seam=alias_seam, suppression_seam=suppression_seam
            )
        )

    decisions = [
        {
            "field": r.field,
            "index": r.index,
            "value": r.value,
            "decision": r.decision,
            "confidence": r.confidence,
            "tier": r.tier,
        }
        for r in results
    ]
    return {"decisions": decisions, "summary": _summary(results)}


__all__ = [
    "IDENTITY_SIGNAL_TYPES",
    "IdentityFieldProbe",
    "IdentityPreviewBody",
    "infer_signal_type",
    "preview_identity_decisions",
    "_field_is_identity_mapped",
]
