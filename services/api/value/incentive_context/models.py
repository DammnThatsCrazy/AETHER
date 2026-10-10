"""Pydantic models mirroring ``incentive-context.schema.json`` (M1).

These models are the typed runtime carrier the M5 resolver returns. A context
built through these models serializes with ``to_dict()`` to exactly the property
set of the JSON schema (``additionalProperties: false``), so every resolved
context is schema-conformant by construction. Structural conformance is still
asserted in tests with a real Draft 2020-12 validator against the M1 JSON.

All datetimes are timezone-aware UTC instants. A naive datetime is rejected at
the model boundary (never silently assumed) — the resolver converts local /
naive boundaries through ``shared/temporal/windows.py`` BEFORE construction, so
a naive value reaching this model is a programmer error, not a DST choice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .canonical import (
    CONFIDENCE_KINDS,
    EVIDENCE_BASIS,
    INCENTIVE_CONTEXT_SCHEMA_VERSION,
    INCENTIVE_STATUSES,
    SOURCE_SCOPES,
    TEMPORAL_SEGMENTS,
)

__all__ = ["TemporalSegment", "IncentiveContext"]

_Status = Literal[
    "verified", "declared", "observed", "suspected", "none_observed",
    "unknown", "not_applicable",
]
_Scope = Literal[
    "olympus_corpus", "tenant_connected", "tenant_imported", "tenant_first_party",
]
_Basis = Literal[
    "provider_record", "provider_api", "imported_source", "first_party_sdk",
    "derived_aggregate", "semantic_classification", "unknown",
]
_ConfidenceKind = Literal[
    "provider_declared", "derived", "semantic_classification", "aggregated",
    "unknown",
]
_SegmentName = Literal["PRE_INCENTIVE", "INCENTIVE_WINDOW", "POST_INCENTIVE"]


def _ensure_aware_utc(value: object) -> datetime:
    """Coerce an ISO str / aware datetime to an aware UTC instant.

    Naive datetimes are REJECTED — a naive value here means a boundary reached
    the model without a DST decision, which the resolver must never make
    silently (blueprint treats boundary choice as an explicit decision).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"not an ISO datetime: {value!r}") from exc
    else:
        raise TypeError(f"expected datetime or ISO string, got {type(value).__name__}")
    if dt.tzinfo is None:
        raise ValueError(
            "naive datetime reached IncentiveContext without a zone decision; "
            "resolve local boundaries through shared/temporal/windows.py first"
        )
    return dt.astimezone(timezone.utc)


class TemporalSegment(BaseModel):
    """One §32 temporal segment (PRE_INCENTIVE / INCENTIVE_WINDOW / POST_INCENTIVE).

    Intervals are half-open UTC ``[started_at, ended_at)``. ``interaction_count``
    is the number of supplied timeline observations that fall in the interval —
    a real count over the timeline the context was resolved from, never a
    fabricated figure. When no count is derivable it stays ``None`` (a count of
    zero is only ever written after the segment's bounds were actually counted).
    """

    model_config = ConfigDict(extra="forbid")

    segment: _SegmentName
    started_at: datetime
    ended_at: datetime
    interaction_count: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def _aware(cls, value: object) -> datetime:
        return _ensure_aware_utc(value)

    @field_validator("segment")
    @classmethod
    def _in_enum(cls, value: object) -> str:
        if value not in TEMPORAL_SEGMENTS:
            raise ValueError(
                f"segment must be one of {TEMPORAL_SEGMENTS}, got {value!r}"
            )
        return value  # type: ignore[return-value]


class IncentiveContext(BaseModel):
    """First-class, temporal, provenance-bearing incentive context (§§30-33).

    Field set and ``additionalProperties: false`` exactly mirror the M1 schema.
    Honesty invariants enforced downstream (and in the resolver that builds
    these): ``none_observed`` never converts to ``organic``; ``unknown`` stays
    ``unknown``; absence of a detected incentive is never automatically organic.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = INCENTIVE_CONTEXT_SCHEMA_VERSION
    incentive_context_id: str = Field(min_length=1)
    subject_entity_ref: Optional[str] = None
    social_identity_ref: Optional[str] = None
    content_ref: Optional[str] = None
    interaction_ref: Optional[str] = None
    campaign_ref: Optional[str] = None
    reward_ref: Optional[str] = None
    economic_value_ref: Optional[str] = None
    status: _Status
    reward_condition: Optional[str] = None
    eligibility_rule_ref: Optional[str] = None
    exposure_started_at: Optional[datetime] = None
    exposure_ended_at: Optional[datetime] = None
    direct_incentive: bool
    upstream_incentive_origin: Optional[str] = None
    downstream_exposure: Optional[bool] = None
    temporal_segments: list[TemporalSegment] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    contradictory_evidence_refs: list[str] = Field(default_factory=list)
    source_scope: _Scope
    evidence_basis: _Basis
    confidence_kind: _ConfidenceKind
    confidence_value: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    policy_ref: str = Field(min_length=1)
    computed_at: datetime
    limitations: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _status_in_enum(cls, value: object) -> str:
        if value not in INCENTIVE_STATUSES:
            raise ValueError(
                f"status must be one of {INCENTIVE_STATUSES}, got {value!r}"
            )
        return value  # type: ignore[return-value]

    @field_validator("source_scope")
    @classmethod
    def _scope_in_enum(cls, value: object) -> str:
        if value not in SOURCE_SCOPES:
            raise ValueError(
                f"source_scope must be one of {SOURCE_SCOPES}, got {value!r}"
            )
        return value  # type: ignore[return-value]

    @field_validator("evidence_basis")
    @classmethod
    def _basis_in_enum(cls, value: object) -> str:
        if value not in EVIDENCE_BASIS:
            raise ValueError(
                f"evidence_basis must be one of {EVIDENCE_BASIS}, got {value!r}"
            )
        return value  # type: ignore[return-value]

    @field_validator("confidence_kind")
    @classmethod
    def _conf_in_enum(cls, value: object) -> str:
        if value not in CONFIDENCE_KINDS:
            raise ValueError(
                f"confidence_kind must be one of {CONFIDENCE_KINDS}, got {value!r}"
            )
        return value  # type: ignore[return-value]

    @field_validator("exposure_started_at", "exposure_ended_at")
    @classmethod
    def _aware_exposure(cls, value: object) -> Optional[datetime]:
        # Optional fields: None stays None (pydantic v2 still calls after
        # validators on None); a present value must be an aware UTC instant.
        if value is None:
            return None
        return _ensure_aware_utc(value)

    @field_validator("computed_at")
    @classmethod
    def _aware_computed(cls, value: object) -> datetime:
        # Required field: reject None loudly rather than silently storing it.
        if value is None:
            raise ValueError("computed_at is required")
        return _ensure_aware_utc(value)

    @field_validator("evidence_refs", "contradictory_evidence_refs")
    @classmethod
    def _dedupe_refs(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for ref in values:
            if ref and ref not in seen:
                seen.add(ref)
                out.append(ref)
        return out

    def to_dict(self) -> dict:
        """JSON-safe dict conforming to the M1 schema (extra keys forbidden)."""
        return self.model_dump(mode="json")
