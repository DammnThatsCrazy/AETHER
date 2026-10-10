"""Contracts for the account-deletion workflow.

The workflow is intentionally explicit: an account is suspended immediately,
remains recoverable for 30 days, and is then processed as an irreversible
erasure.  Re-authentication evidence is metadata only; raw passwords, tokens,
or MFA assertions must never be persisted here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, Field

from shared.common.common import BadRequestError
from shared.temporal import SYSTEM_CLOCK, TemporalError, ensure_aware_utc, parse_instant_strict, to_iso_utc

RECOVERY_WINDOW_DAYS = 30
STEP_UP_MAX_AGE_SECONDS = 15 * 60


class DeletionStatus(str, Enum):
    RECOVERY = "recovery"
    PROCESSING = "processing"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class StorageResultStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    REVOKED = "revoked"
    RETAINED = "retained"
    UNAVAILABLE = "unavailable"
    DEFERRED = "deferred"
    FAILED = "failed"


class StepUpEvidence(BaseModel):
    """Trusted, short-lived evidence produced by an authentication service."""

    verified: bool
    method: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=256)
    verified_at: datetime
    assurance_level: str = Field(default="step_up", min_length=1, max_length=64)
    provider: str | None = Field(default=None, max_length=128)


def _parse_verified_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = parse_instant_strict(value)
        except TemporalError as exc:
            raise BadRequestError("reauth_evidence.verified_at must be ISO-8601") from exc
    else:
        raise BadRequestError("reauth_evidence.verified_at is required")
    try:
        return ensure_aware_utc(parsed)
    except TemporalError as exc:
        raise BadRequestError("reauth_evidence.verified_at must include a timezone") from exc


def validate_step_up_evidence(
    evidence: Mapping[str, Any] | StepUpEvidence | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and safely normalize re-authentication evidence.

    This function does not authenticate a password or MFA assertion. The
    orchestrator must supply evidence from the trusted auth provider, with
    ``verified=True`` and a provider-issued evidence identifier.  Only
    non-secret metadata is returned for persistence.
    """

    if isinstance(evidence, StepUpEvidence):
        raw = evidence.model_dump()
    elif isinstance(evidence, Mapping):
        raw = dict(evidence)
    else:
        raise BadRequestError("step-up re-authentication evidence is required")

    if raw.get("verified") is not True:
        raise BadRequestError("step-up re-authentication was not verified")
    method = str(raw.get("method", "")).strip().lower()
    if method not in {"password", "mfa", "webauthn", "identity_provider"}:
        raise BadRequestError("reauth_evidence.method is not supported")
    evidence_id = str(raw.get("evidence_id") or raw.get("challenge_id") or "").strip()
    if not evidence_id:
        raise BadRequestError("reauth_evidence.evidence_id is required")
    verified_at = _parse_verified_at(raw.get("verified_at"))
    try:
        current = ensure_aware_utc(now or SYSTEM_CLOCK.now())
    except TemporalError as exc:
        raise BadRequestError("current time must include a timezone") from exc
    age = (current - verified_at).total_seconds()
    if age < -60 or age > STEP_UP_MAX_AGE_SECONDS:
        raise BadRequestError("step-up re-authentication evidence is expired")
    assurance = str(raw.get("assurance_level", "step_up")).strip().lower()
    if assurance not in {"step_up", "high", "aal2", "aal3"}:
        raise BadRequestError("reauth_evidence.assurance_level is insufficient")

    return {
        "verified": True,
        "method": method,
        "evidence_id": evidence_id,
        "verified_at": to_iso_utc(verified_at),
        "assurance_level": assurance,
        "provider": str(raw["provider"]) if raw.get("provider") else None,
    }
