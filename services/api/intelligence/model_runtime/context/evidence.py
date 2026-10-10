"""Grounded-synthesis context data models (ADR-008 D6).

The grounded-synthesis pipeline runs retrieval-before-synthesis: Aether
retrieves a tenant-scoped, freshness-bounded evidence set and the model
synthesizes ONLY from that evidence. This module defines the secret-free,
frozen, ``extra="forbid"`` data models that every grounded-synthesis stage
(builder, retrieval, assembly, prompt, service) builds against.

Security posture is intentionally narrow:

- Credential leakage (``sk-`` keys, AWS access keys, bearer tokens, PEM
  blocks, auth headers) is rejected at the field layer via ``EvidenceUnsafe``.
  These are the fields a model may echo back verbatim, so they must never
  carry live secrets.
- Evidence volume/length is bounded at the set layer via ``EvidenceBounds``.
- Raw SQL/Gremlin/Cypher/GraphQL injection shielding is owned by the
  planner/validator layers, NOT here. ``metadata`` is a bounded
  plain-string-tag bucket and must never carry secrets.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

__all__ = [
    "ContextBundle",
    "EvidenceBounds",
    "EvidenceBudget",
    "EvidenceItem",
    "EvidenceSet",
    "EvidenceUnsafe",
]

# Default retrieval bounds. Module-level constants keep EvidenceBudget defaults
# and the EvidenceSet enforcement validator in lockstep (single source of truth).
_MAX_ITEMS = 64
_MAX_CONTENT_CHARS = 4096
_MAX_FRESHNESS_SECONDS = 300

# Secret markers forbidden anywhere in grounded-synthesis context. Stored
# lowercased and matched case-insensitively so "SK-", "sk-", "Bearer ",
# "BEARER ", "-----BEGIN" etc. all trip the guard. Deliberately NOT an
# allowlist for query shapes — SQL/Gremlin/Cypher/GraphQL safety belongs to the
# planner and validator layers.
_SECRET_MARKERS: tuple[str, ...] = (
    "sk-",
    "akia",
    "bearer ",
    "-----begin",
    "authorization:",
    "x-api-key:",
)


class EvidenceUnsafe(Exception):
    """Raised when credential-shaped text appears in grounded-synthesis context.

    Guards the fields a model may echo back verbatim (evidence content, source
    strings, and synthesis prompt wiring). A hard contract: the pipeline must
    never place live secrets in front of a model.
    """


class EvidenceBounds(Exception):
    """Raised when evidence volume or item length exceeds the configured budget."""


class EvidenceBudget(BaseModel):
    """Bounded retrieval budget for a grounded-synthesis run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_items: int = _MAX_ITEMS
    max_content_chars: int = _MAX_CONTENT_CHARS
    freshness_seconds: int = _MAX_FRESHNESS_SECONDS

    @field_validator("max_items", "max_content_chars", "freshness_seconds")
    @classmethod
    def _reject_non_positive(cls, value: int) -> int:
        if value <= 0:
            raise EvidenceBounds(f"EvidenceBudget values must be positive; got {value!r}")
        return value


class EvidenceItem(BaseModel):
    """A single retrieved evidence record, validated secret-free."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str
    source: str  # e.g. "aether.records.<kind>.<id>"
    tenant_id: str
    content: str
    collected_at: datetime
    metadata: dict[str, str] = {}  # bounded plain-string tags (never secrets)

    @field_validator("content", "source")
    @classmethod
    def _reject_secret_markers(cls, value: str) -> str:
        lowered = value.lower()
        for marker in _SECRET_MARKERS:
            if marker in lowered:
                raise EvidenceUnsafe(
                    f"secret-shaped value rejected in grounded evidence: contains {marker!r}"
                )
        return value


class EvidenceSet(BaseModel):
    """A tenant-scoped, freshness-bounded set of evidence for one query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    profile_id: str
    query: str
    items: tuple[EvidenceItem, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def _enforce_evidence_bounds(self) -> EvidenceSet:
        if len(self.items) > _MAX_ITEMS:
            raise EvidenceBounds(f"evidence set exceeds {_MAX_ITEMS} items: {len(self.items)}")
        for item in self.items:
            if len(item.content) > _MAX_CONTENT_CHARS:
                raise EvidenceBounds(
                    f"evidence content exceeds {_MAX_CONTENT_CHARS} chars "
                    f"(reference_id={item.reference_id!r})"
                )
        return self


class ContextBundle(BaseModel):
    """The complete synthesis context: evidence plus bounded instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    profile_id: str
    query: str
    evidence: EvidenceSet
    synthesis_instructions: str = ""  # bounded, no injection vector
    created_at: datetime

    @field_validator("query", "synthesis_instructions")
    @classmethod
    def _reject_secret_markers(cls, value: str) -> str:
        lowered = value.lower()
        for marker in _SECRET_MARKERS:
            if marker in lowered:
                raise EvidenceUnsafe(
                    f"secret-shaped value rejected in context bundle: contains {marker!r}"
                )
        return value
