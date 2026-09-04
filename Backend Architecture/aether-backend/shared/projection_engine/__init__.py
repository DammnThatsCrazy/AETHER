"""Aether projection engine (A8) — lens algebra + projection runtime.

The projection engine is the higher orchestration layer over the P0
intelligence projection plane. It adds the composable lens abstraction
(``lens-registry.json`` + composition algebra), the projection compiler /
planner / executor, typed degradation mapped onto the registered section-state
vocabulary, engine-level temporal modes, and the ``G @ C`` context operator —
all while keeping ``shared/intelligence_projections/`` pristine as the stable
contract boundary.

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record. The engine composes projections over that truth and
never owns canonical state.
"""

from shared.projection_engine.compiler import ProjectionCompiler
from shared.projection_engine.composition import (
    CompositionConflict,
    CompositionContext,
    CompositionResult,
    compose_economic_infrastructure,
    compose_economic_outcome,
    compose_operational_value_triangle,
    compose_outcome_infrastructure,
)
from shared.projection_engine.conflict import (
    ConflictClass,
    ConflictResolution,
    LensConflict,
    LensNotFound,
)
from shared.projection_engine.context_operator import (
    ContextOperation,
    ContextOperator,
)
from shared.projection_engine.degradation import (
    DegradationLevel,
    summarize_degradation,
)
from shared.projection_engine.digest import (
    canonical_json,
    compute_projection_digest,
)
from shared.projection_engine.executor import ProjectionExecutor
from shared.projection_engine.ir import ProjectionIR
from shared.projection_engine.lens_composition import (
    Composition,
    IncompatibleLens,
    compose_lenses,
)
from shared.projection_engine.lens_registry import (
    LensDescriptor,
    LensRegistry,
    lens_registry,
)
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.operators import Operator, OperatorSpec, validate_operators
from shared.projection_engine.plan import ProjectionPlan, ProjectionPlanNode
from shared.projection_engine.planner import ProjectionPlanner
from shared.projection_engine.runtime import DEFAULT_LENS_SET, ProjectionRuntime, runtime
from shared.projection_engine.temporal_modes import (
    TemporalMode,
    dispatch_temporal_mode,
    parse_temporal_mode,
)

__all__ = [
    "Composition",
    "CompositionConflict",
    "CompositionContext",
    "CompositionResult",
    "ConflictClass",
    "ConflictResolution",
    "ContextOperation",
    "ContextOperator",
    "DEFAULT_LENS_SET",
    "DegradationLevel",
    "IncompatibleLens",
    "LensConflict",
    "LensDescriptor",
    "LensNotFound",
    "LensRegistry",
    "LensSet",
    "Operator",
    "OperatorSpec",
    "ProjectionCompiler",
    "ProjectionExecutor",
    "ProjectionIR",
    "ProjectionPlan",
    "ProjectionPlanNode",
    "ProjectionPlanner",
    "ProjectionRuntime",
    "TemporalMode",
    "canonical_json",
    "compose_economic_infrastructure",
    "compose_economic_outcome",
    "compose_lenses",
    "compose_operational_value_triangle",
    "compose_outcome_infrastructure",
    "compute_projection_digest",
    "dispatch_temporal_mode",
    "lens_registry",
    "parse_temporal_mode",
    "runtime",
    "summarize_degradation",
    "validate_operators",
]
