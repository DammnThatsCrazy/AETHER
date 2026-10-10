"""Surface-adapter contract for the exploration fabric.

An adapter binds one registered exploration surface to a real, tenant-scoped
read plane. It declares which filter-field categories (hence which registry
fields) it can honour, executes the ``applied`` filters the planner routed to
it, and returns typed results with explicit truncation metadata. It never
fabricates data: an empty backing store yields an honest empty result, never a
placeholder row.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as _dc_field
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts_models.filters import FilterExpression
from shared.exploration.generated_fields import FILTER_FIELDS
from shared.exploration.generated_surfaces import SURFACE_CAPABILITIES
from shared.exploration.models import ExplorationContextV1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdapterTruncation(_Model):
    """Whether the adapter returned everything it matched."""

    truncated: bool = False
    reason: Optional[str] = None
    returned_count: int = 0
    total_estimate: Optional[int] = None


class AdapterResult(_Model):
    """Typed result returned by a surface adapter."""

    surface: str
    backend: str  # honest name of the store actually read
    data: Any = None
    truncation: AdapterTruncation = Field(default_factory=AdapterTruncation)
    cursor: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    populated: bool = False  # True iff the backing store returned any records


@dataclass
class AdapterContext:
    """Everything an adapter needs to execute one exploration query."""

    tenant_id: str
    context: ExplorationContextV1
    applied_filters: list[FilterExpression]
    as_of: Optional[str] = None
    limit: int = 100
    cursor: Optional[str] = None
    # Optional wiring for adapters that delegate to an existing plane. These are
    # injected by the route (which already authenticated the tenant); adapters
    # that do not need them ignore them.
    request: Any = None
    graph: Any = None
    cache: Any = None
    extras: dict[str, Any] = _dc_field(default_factory=dict)


class SurfaceAdapter(ABC):
    """Base class for exploration surface adapters."""

    surface_id: str

    @property
    def capabilities(self) -> dict:
        return SURFACE_CAPABILITIES[self.surface_id]

    @property
    def supported_categories(self) -> frozenset[str]:
        return frozenset(self.capabilities["supported_field_categories"])

    def supported_fields(self) -> frozenset[str]:
        """Registry field ids this surface can honour, derived from categories."""
        return frozenset(
            fid
            for fid, spec in FILTER_FIELDS.items()
            if spec["category"] in self.supported_categories
        )

    def supports_field(self, field_id: str) -> bool:
        spec = FILTER_FIELDS.get(field_id)
        return spec is not None and spec["category"] in self.supported_categories

    @abstractmethod
    async def execute(self, ctx: AdapterContext) -> AdapterResult:
        """Execute the routed filters against the surface's read plane."""


__all__ = [
    "AdapterContext",
    "AdapterResult",
    "AdapterTruncation",
    "SurfaceAdapter",
]
