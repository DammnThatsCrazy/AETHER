"""Continuation-plane Pydantic contract — twin of packages/shared/continuation.ts.

Drift-guarded by tests/contracts/test_continuation_contract_parity.py, which
scrapes the TS const arrays + interface field-sets and asserts set-equality
against the tuples and `model_fields` here.

HARD RULE (decision-log D6): every wire field is snake_case. The parity scraper
matches `^\\s{2}([a-z_][a-z0-9_]*)\\??:` on the TS side and cannot capture
camelCase; a camelCase twin would pass falsely. The camelCase names in the
program spec are frontend-mapped aliases only.

The continuation stores references + a bounded selection, never a whole graph:
`canonical_context.filters` (an optional, size-bounded ExplorationContextV1) or a
`saved_view_id` / replayable `query_id` is re-resolved to live context on read.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from shared.exploration.models import ExplorationContextV1

# --- Canonical vocabularies (snake_case, no digits — see parity scraper) -------
CONTINUATION_APP_KINDS: tuple[str, ...] = ("aether", "kyber")
CONTINUATION_SOURCE_CLIENTS: tuple[str, ...] = (
    "web",
    "desktop",
    "mobile_ios",
    "mobile_android",
    "agent",
    "system",
)
CONTINUATION_SURFACES: tuple[str, ...] = (
    "mission",
    "exploration",
    "investigation",
    "profile",
    "cluster",
    "campaign",
    "graph",
    "journey",
    "noesis",
    "notifications",
    "exception",
    "incident",
)
CONTINUATION_SENSITIVITIES: tuple[str, ...] = ("standard", "sensitive", "restricted")
CONTINUATION_FRESHNESS: tuple[str, ...] = ("live", "cached", "stale")
SELECTION_MODES: tuple[str, ...] = ("explicit", "query")

# Bound on an inline compact ExplorationContextV1 embedded in a continuation
# (references-not-payloads invariant). Larger contexts must use saved_view_id.
MAX_INLINE_CONTEXT_BYTES = 8192


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceReference(_Base):
    kind: str
    id: str


class ContinuationCanonicalContext(_Base):
    """References + bounded selection. All members optional; never a raw graph."""

    route: Optional[str] = None
    saved_view_id: Optional[str] = None
    query_id: Optional[str] = None
    filters: Optional[ExplorationContextV1] = None
    sort: Optional[dict] = None
    time_range: Optional[dict] = None
    selected_resource_ids: Optional[list[str]] = None
    comparison: Optional[dict] = None
    graph_view: Optional[dict] = None
    noesis_conversation_id: Optional[str] = None
    noesis_answer_id: Optional[str] = None
    notification_id: Optional[str] = None
    exception_id: Optional[str] = None
    incident_id: Optional[str] = None


class ContinuationSummary(_Base):
    title: str
    subtitle: Optional[str] = None
    last_meaningful_action: Optional[str] = None


class ContinuationContext(_Base):
    version: str = "1"
    id: str
    principal_id: str
    tenant_id: Optional[str] = None
    app_kind: str
    source_client: str
    surface: str
    resource_references: list[ResourceReference] = []
    canonical_context: ContinuationCanonicalContext = ContinuationCanonicalContext()
    summary: ContinuationSummary
    state_revision: int = 0
    sensitivity: str = "standard"
    freshness: Optional[str] = None
    expires_at: Optional[str] = None
    updated_at: str

    @field_validator("app_kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in CONTINUATION_APP_KINDS:
            raise ValueError(f"app_kind must be one of {CONTINUATION_APP_KINDS}")
        return v

    @field_validator("source_client")
    @classmethod
    def _client(cls, v: str) -> str:
        if v not in CONTINUATION_SOURCE_CLIENTS:
            raise ValueError(f"source_client must be one of {CONTINUATION_SOURCE_CLIENTS}")
        return v

    @field_validator("surface")
    @classmethod
    def _surface(cls, v: str) -> str:
        if v not in CONTINUATION_SURFACES:
            raise ValueError(f"surface must be one of {CONTINUATION_SURFACES}")
        return v

    @field_validator("sensitivity")
    @classmethod
    def _sensitivity(cls, v: str) -> str:
        if v not in CONTINUATION_SENSITIVITIES:
            raise ValueError(f"sensitivity must be one of {CONTINUATION_SENSITIVITIES}")
        return v

    @field_validator("freshness")
    @classmethod
    def _freshness(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CONTINUATION_FRESHNESS:
            raise ValueError(f"freshness must be one of {CONTINUATION_FRESHNESS}")
        return v


class ContinuationSelection(_Base):
    """The 'backend selection token' (decision-log D4). Minted at handoff; both
    Noesis exact-handoff and mobile deep-links resolve the same token."""

    token: str
    tenant_scope: str
    principal_id: str
    mode: str
    resource_ids: Optional[list[str]] = None
    saved_view_id: Optional[str] = None
    query_id: Optional[str] = None
    as_of: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in SELECTION_MODES:
            raise ValueError(f"mode must be one of {SELECTION_MODES}")
        return v
