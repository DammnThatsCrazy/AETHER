# DO NOT EDIT — generated from packages/shared/contracts/surface-capability-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated surface-capability registry (surfaces, temporal modes, views, dispositions)."""

from __future__ import annotations

SURFACE_CAPABILITIES_CONTRACT_VERSION = "1.0.0"

# Exploration surfaces registered with the fabric (sorted).
EXPLORATION_SURFACE_IDS: tuple[str, ...] = (
    "campaign360",
    "cluster360",
    "comparison_workbench",
    "connection360",
    "economic360",
    "geo",
    "graph",
    "infrastructure360",
    "journeys",
    "outcome360",
    "population360",
    "product_intelligence",
    "profile360",
    "temporal360",
    "temporal_observatory",
    "timeline",
)

# Temporal query modes a surface may support.
EXPLORATION_TEMPORAL_MODES: tuple[str, ...] = ("window", "as_of", "compare", "relative")

# Render views a surface may support.
EXPLORATION_VIEWS: tuple[str, ...] = ("graph", "table", "map", "timeline", "flow", "comparison")

# What the fabric did with one filter on one surface — never silently dropped.
FILTER_DISPOSITIONS: tuple[str, ...] = (
    "applied",
    "translated",
    "unsupported",
    "suppressed",
    "not_applicable",
)

# Declared capabilities per surface (sorted by surface id).
SURFACE_CAPABILITIES: dict[str, dict] = {
    "campaign360": {
        "supported_field_categories": ("entity", "time", "geography", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "compare", "relative"),
        "supported_views": ("table", "flow", "timeline"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "cluster360": {
        "supported_field_categories": ("entity", "time", "graph", "risk", "truth"),
        "supported_temporal_modes": ("window", "as_of"),
        "supported_views": ("graph", "table"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": False,
        "supports_export": True,
    },
    "comparison_workbench": {
        "supported_field_categories": ("entity", "time", "geography", "device", "graph", "risk", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "as_of", "compare", "relative"),
        "supported_views": ("comparison", "table", "graph", "timeline"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "connection360": {
        "supported_field_categories": ("entity", "time", "graph", "truth"),
        "supported_temporal_modes": ("window", "as_of", "relative"),
        "supported_views": ("table", "flow"),
        "supports_facets": False,
        "supports_comparison": False,
        "supports_selection_sets": False,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "economic360": {
        "supported_field_categories": ("entity", "time", "device", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "compare", "relative"),
        "supported_views": ("table", "graph"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "geo": {
        "supported_field_categories": ("entity", "time", "geography", "campaign", "risk"),
        "supported_temporal_modes": ("window", "compare", "relative"),
        "supported_views": ("map", "table"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "graph": {
        "supported_field_categories": ("entity", "time", "geography", "device", "graph", "risk", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "as_of", "relative"),
        "supported_views": ("graph", "table"),
        "supports_facets": True,
        "supports_comparison": False,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "infrastructure360": {
        "supported_field_categories": ("entity", "time", "graph", "risk", "truth"),
        "supported_temporal_modes": ("window", "as_of", "compare", "relative"),
        "supported_views": ("table", "graph", "map"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "journeys": {
        "supported_field_categories": ("entity", "time", "device", "campaign", "truth"),
        "supported_temporal_modes": ("window", "relative"),
        "supported_views": ("flow", "table", "timeline"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "outcome360": {
        "supported_field_categories": ("entity", "time", "geography", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "compare", "relative"),
        "supported_views": ("table", "graph"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "population360": {
        "supported_field_categories": ("entity", "graph", "time", "truth"),
        "supported_temporal_modes": ("window", "relative"),
        "supported_views": ("table", "timeline", "comparison"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "product_intelligence": {
        "supported_field_categories": ("entity", "time", "device", "campaign", "economic", "truth"),
        "supported_temporal_modes": ("window", "compare", "relative"),
        "supported_views": ("table", "timeline", "flow"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "profile360": {
        "supported_field_categories": ("entity", "time", "geography", "device", "campaign", "economic", "risk", "truth"),
        "supported_temporal_modes": ("window", "as_of", "relative"),
        "supported_views": ("table", "timeline"),
        "supports_facets": False,
        "supports_comparison": True,
        "supports_selection_sets": False,
        "supports_saved_views": False,
        "supports_export": True,
    },
    "temporal360": {
        "supported_field_categories": ("entity", "time", "truth"),
        "supported_temporal_modes": ("window", "as_of", "compare", "relative"),
        "supported_views": ("timeline", "table"),
        "supports_facets": True,
        "supports_comparison": True,
        "supports_selection_sets": True,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "temporal_observatory": {
        "supported_field_categories": ("entity", "time", "truth"),
        "supported_temporal_modes": ("window", "as_of", "compare", "relative"),
        "supported_views": ("timeline", "table"),
        "supports_facets": False,
        "supports_comparison": True,
        "supports_selection_sets": False,
        "supports_saved_views": True,
        "supports_export": True,
    },
    "timeline": {
        "supported_field_categories": ("entity", "time", "device", "campaign", "truth"),
        "supported_temporal_modes": ("window", "as_of", "relative"),
        "supported_views": ("timeline", "table"),
        "supports_facets": False,
        "supports_comparison": False,
        "supports_selection_sets": True,
        "supports_saved_views": False,
        "supports_export": True,
    },
}

__all__ = [
    "SURFACE_CAPABILITIES_CONTRACT_VERSION",
    "EXPLORATION_SURFACE_IDS",
    "EXPLORATION_TEMPORAL_MODES",
    "EXPLORATION_VIEWS",
    "FILTER_DISPOSITIONS",
    "SURFACE_CAPABILITIES",
]
