"""ADR-008 D7 verification/faithfulness models — fail-closed verification surface.

Models for checking synthesized output against its cited evidence references and
for detecting leaked credential material before an answer surfaces. Verification
is deliberately strict and fail-closed (ADR-008 D7): ``VerificationResult``
defaults to ``faithful=False`` and the consuming service treats an absent
verification result as not faithful — unsupported claims and detected leaks
block the answer rather than presenting it as verified truth.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

VERIFICATION_SECRET_MARKERS: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
    "eyJ",
    "password=",
    "secret=",
    "key=",
)


class VerificationUnsafe(Exception):
    """Raised when claim/check text carries credential secret material (D7 fail-closed)."""


def _reject_secret_markers(value: str) -> str:
    """Reject text containing any ``VERIFICATION_SECRET_MARKERS`` entry, case-insensitively.

    The raised :class:`VerificationUnsafe` reports ONLY the matched marker —
    never the rejected ``value`` — so a credential that trips the guard cannot
    leak through ``__cause__``/traceback or ``exc_info`` logging. This matches
    the other model-runtime leak guards (``synthesis``, ``evaluation``,
    ``context``), which all identify the marker rather than echo the payload.
    """
    lowered = value.casefold()
    for marker in VERIFICATION_SECRET_MARKERS:
        if marker.casefold() in lowered:
            raise VerificationUnsafe(f"text contains a secret marker ({marker!r})")
    return value


try:  # synthesis/models.py lands in a sibling commit (Commit 9); degrade gracefully.
    from services.model_runtime.synthesis.models import SynthesisResult
except ImportError:  # pragma: no cover - exercised only before synthesis/ lands

    class SynthesisResult(BaseModel):
        """Forward-compat stand-in until ``synthesis/models.py`` lands."""


class ClaimStatement(BaseModel):
    """A single synthesized claim plus the evidence references asserted for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    evidence_refs: tuple[str, ...] = ()

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        _reject_secret_markers(value)
        if not value.strip():
            raise ValueError("claim text must be non-empty")
        return value


class CitationCheck(BaseModel):
    """Outcome of checking one claim against one cited evidence reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str
    claim_text: str
    supported: bool
    method: str  # e.g. "token-overlap"

    @field_validator("claim_text")
    @classmethod
    def _validate_claim_text(cls, value: str) -> str:
        return _reject_secret_markers(value)


class VerificationRequest(BaseModel):
    """Request to verify a synthesis result; ``result=None`` is treated as fail-closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    result: SynthesisResult | None = None  # what to verify; None -> fail-closed


class VerificationResult(BaseModel):
    """Outcome of a verification pass; fail-closed by construction (ADR-008 D7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    claims: tuple[ClaimStatement, ...]
    checks: tuple[CitationCheck, ...]
    faithful: bool = False  # False if ANY claim unsupported or leak detected (D7)
    leak_detected: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "VerificationUnsafe",
    "VERIFICATION_SECRET_MARKERS",
    "ClaimStatement",
    "CitationCheck",
    "VerificationRequest",
    "VerificationResult",
]
