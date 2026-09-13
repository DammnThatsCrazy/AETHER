"""Product Catalog contracts — Pydantic v2, ``extra="forbid"``.

CatalogNode is the single node type for the whole catalog tree (kind
discriminates product / product_area / feature / feature_version / surface /
control). MappingRule binds a raw instrumentation match to catalog targets;
MappingProposal is a not-yet-reviewed rule candidate carried with evidence.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Vocabularies ────────────────────────────────────────────────────────────

CatalogNodeKind = Literal[
    "product",
    "product_area",
    "feature",
    "feature_version",
    "surface",
    "control",
]

CatalogNodeStatus = Literal["draft", "active", "deprecated", "retired"]

MappingMatchKind = Literal[
    "instrumentation_id",
    "route",
    "selector",
    "component",
    "operation_id",
    "contract_method",
    "agent_tool",
    "event_name",
]

# Ordered strongest → weakest; the resolver in mapping.py depends on this
# exact order for deterministic precedence.
MappingPrecedenceClass = Literal[
    "explicit_instrumentation",
    "tenant_catalog",
    "verified_framework",
    "reviewed_discovery",
    "inferred",
    "unmapped",
]

MappingProposalStatus = Literal["pending", "approved", "rejected"]


# ── Models ──────────────────────────────────────────────────────────────────

class CatalogNode(BaseModel):
    """One node of the tenant's product catalog tree."""

    model_config = ConfigDict(extra="forbid")

    kind: CatalogNodeKind
    stable_id: str = Field(min_length=1)
    # Optional on input — routes force it to the authenticated tenant.
    tenant_id: Optional[str] = None
    display_name: str = Field(min_length=1)
    description: Optional[str] = None
    status: CatalogNodeStatus = "active"
    owner: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    parent_id: Optional[str] = None
    # Materialized path of stable_ids from the product root, '/'-joined.
    path: Optional[str] = None
    version: int = Field(default=1, ge=1)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MappingRule(BaseModel):
    """Deterministic binding from a raw instrumentation match to the catalog."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: Optional[str] = None
    rule_id: str = Field(min_length=1)
    match_kind: MappingMatchKind
    match_value: str = Field(min_length=1)
    target_feature_id: Optional[str] = None
    target_surface_id: Optional[str] = None
    target_control_id: Optional[str] = None
    precedence_class: MappingPrecedenceClass
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    version: int = Field(default=1, ge=1)


class MappingProposal(BaseModel):
    """A candidate MappingRule awaiting review (discovery / inference output)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: Optional[str] = None
    rule_id: str = Field(min_length=1)
    match_kind: MappingMatchKind
    match_value: str = Field(min_length=1)
    target_feature_id: Optional[str] = None
    target_surface_id: Optional[str] = None
    target_control_id: Optional[str] = None
    precedence_class: MappingPrecedenceClass
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    version: int = Field(default=1, ge=1)
    status: MappingProposalStatus = "pending"
    evidence_count: int = Field(default=0, ge=0)
