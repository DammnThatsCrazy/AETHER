"""Synthesis data models (ADR-008 D6 retrieval-before-synthesis).

Request/result shapes for the grounded-synthesis pipeline. Every field that
can carry model- or tenant-produced content is screened for credential-shaped
material and fails closed (``SynthesisUnsafe``) rather than passing secrets
downstream. The engine (``engine.py``) consumes these shapes; citations are
drawn only from the request's allowlisted evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.model_runtime.context.evidence import EvidenceSet

__all__ = [
    "EvidenceCitation",
    "SYNTHESIS_SECRET_MARKERS",
    "SynthesisRequest",
    "SynthesisResult",
    "SynthesisUnsafe",
]

SYNTHESIS_SECRET_MARKERS: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
    "eyJ",
)


class SynthesisUnsafe(Exception):
    """Raised when credential-shaped material enters a synthesis model."""


def _reject_secret_markers(value: str) -> str:
    lowered = value.casefold()
    for marker in SYNTHESIS_SECRET_MARKERS:
        if marker.casefold() in lowered:
            raise SynthesisUnsafe(
                f"synthesis content contains a secret marker ({marker!r})"
            )
    return value


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceCitation(BaseModel):
    """A citation back to the retrieved evidence item that grounded a claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_id: str
    source: str
    tenant_id: str
    excerpt: str

    @field_validator("excerpt")
    @classmethod
    def _excerpt_must_be_secret_free(cls, value: str) -> str:
        return _reject_secret_markers(value)


class SynthesisRequest(BaseModel):
    """A grounded-synthesis request.

    ``evidence`` is optional at request time; the grounding gate (D6) fails
    closed when it is None or empty. ``plan_kind`` is stored here but only
    allowlisted by ``plans.py``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    profile_id: str
    query: str
    plan_kind: str
    evidence: EvidenceSet | None = None
    synthesis_instructions: str = ""
    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("query")
    @classmethod
    def _query_must_be_secret_free(cls, value: str) -> str:
        return _reject_secret_markers(value)


class SynthesisResult(BaseModel):
    """A synthesized, grounded answer with its evidence citations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    plan_kind: str
    content: str
    citations: tuple[EvidenceCitation, ...]
    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("content")
    @classmethod
    def _content_must_be_secret_free(cls, value: str) -> str:
        return _reject_secret_markers(value)
