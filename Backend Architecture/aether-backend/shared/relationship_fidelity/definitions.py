"""Canonical Relationship-Fidelity Computation Definitions (M7).

Every definition is registered on the Canonical Computation Substrate
(``shared.computation.registry``) by :func:`register_fidelity_definitions`,
additive and idempotent — the central seed registry
(``shared/computation/registry.py``) and its generated twin
(``shared/computation/generated_registry.py``) are owned elsewhere and are never
edited here.

The definitions mirror the MULTIDIMENSIONAL fidelity vector of
``packages/shared/contracts/relationship-fidelity-vector.schema.json`` — one
definition per dimension plus the three observation/count facts. There is NO
"overall fidelity" / composite definition: the schema forbids a universal
scalar, and use-case composites may only exist later as separately-versioned
definitions.

Math-type discipline: dimension values are handcrafted, UNcalibrated heuristics
in [0, 1] → :class:`MathType.HEURISTIC_SCORE`, never ``PROBABILITY``. Counts are
``INTEGER_COUNT``. Every definition is governed (owner, version, description,
null/zero policy = null-not-zero / evidence-backed, decision-impact class,
executor reference, test declarations).
"""

from __future__ import annotations

from shared.computation.aggregation import AggregationType
from shared.computation.definition import (
    ComputationDefinition,
    ComputationKind,
    DecisionImpactClass,
    LifecycleState,
)
from shared.computation.registry import register
from shared.computation.types import MathType

FIDELITY_DEFINITION_VERSION: str = "1"
FIDELITY_OWNER: str = "relationship-fidelity@aether"
FIDELITY_DOMAIN: str = "relationship_fidelity"
FIDELITY_TESTS: list[str] = [
    "tests/relationship_fidelity/test_definitions_registration.py",
]

# Canonical, ordered fidelity dimensions — exactly the vector dimensions of the
# M1 schema, in schema order. The vector is never reduced to a scalar.
FIDELITY_DIMENSIONS: tuple[str, ...] = (
    "evidence_confidence",
    "source_reliability",
    "identity_confidence",
    "persistence",
    "reciprocity",
    "interaction_frequency",
    "interaction_depth",
    "context_diversity",
    "temporal_continuity",
    "semantic_specificity",
    "semantic_originality",
    "preexisting_affinity_support",
    "incentive_exposure",
    "incentive_independence_support",
    "coordination_indicator_strength",
    "economic_significance",
    "social_significance",
    "organizational_significance",
    "agentic_significance",
    "outcome_support",
)

# Dimensions whose honest value may only be derived from INDEPENDENT evidence
# grouping (correlated evidence is not independent evidence). When the M6
# evidence engine is absent (independence unknown) these stay null.
INDEPENDENCE_GATED_DIMENSIONS: frozenset[str] = frozenset(
    {
        "persistence",
        "reciprocity",
        "incentive_independence_support",
        "coordination_indicator_strength",
    }
)

# Dimensions whose value is a measured pass-through from an upstream domain
# system (identity resolver, semantic engine, economic/campaign/community
# context) rather than derived here. Absent upstream input => null, never 0.
MEASURED_PASSTHROUGH_DIMENSIONS: frozenset[str] = frozenset(
    {
        "identity_confidence",
        "semantic_specificity",
        "semantic_originality",
        "preexisting_affinity_support",
        "economic_significance",
        "social_significance",
        "organizational_significance",
        "agentic_significance",
        "outcome_support",
    }
)

# Field names of the M1 contract that are envelope/accounting (not dimensions).
FIDELITY_COUNT_FIELDS: tuple[str, ...] = (
    "observation_count",
    "independent_evidence_count",
    "independent_source_count",
)


def _score_definition(
    dimension: str,
    *,
    description: str,
    required_inputs: tuple[str, ...],
    dependency_definitions: tuple[str, ...] = (),
    executor_reference: str,
) -> ComputationDefinition:
    """Build one uncalibrated-heuristic dimension definition in [0, 1]."""
    return ComputationDefinition(
        definition_id=f"relationship_fidelity.{dimension}",
        definition_version=FIDELITY_DEFINITION_VERSION,
        display_name=f"Relationship Fidelity — {dimension.replace('_', ' ')}",
        description=description,
        owner=FIDELITY_OWNER,
        domain=FIDELITY_DOMAIN,
        lifecycle_state=LifecycleState.ACTIVE,
        computation_kind=ComputationKind.HEURISTIC_SCORE,
        output_type=MathType.HEURISTIC_SCORE,
        unit="score",
        valid_range_low=0.0,
        valid_range_high=1.0,
        precision=4,
        null_policy="null_not_zero",
        zero_policy="evidence_backed",
        minimum_sample_size=1,
        aggregation_type=AggregationType.NON_AGGREGATABLE,
        required_inputs=list(required_inputs),
        dependency_definitions=list(dependency_definitions),
        executor_type="python",
        executor_reference=executor_reference,
        decision_impact_class=DecisionImpactClass.OPERATIONAL,
        tests=FIDELITY_TESTS,
    )


def _count_definition(name: str, *, description: str) -> ComputationDefinition:
    return ComputationDefinition(
        definition_id=f"relationship_fidelity.{name}",
        definition_version=FIDELITY_DEFINITION_VERSION,
        display_name=f"Relationship Fidelity — {name.replace('_', ' ')}",
        description=description,
        owner=FIDELITY_OWNER,
        domain=FIDELITY_DOMAIN,
        lifecycle_state=LifecycleState.ACTIVE,
        computation_kind=ComputationKind.DETERMINISTIC_METRIC,
        output_type=MathType.INTEGER_COUNT,
        unit="count",
        valid_range_low=0.0,
        null_policy="null_not_zero",
        zero_policy="evidence_backed",
        aggregation_type=AggregationType.NON_AGGREGATABLE,
        required_inputs=["evidence.observations"],
        executor_type="python",
        executor_reference="shared.relationship_fidelity.scoring:derive_observation_count",
        decision_impact_class=DecisionImpactClass.OPERATIONAL,
        tests=FIDELITY_TESTS,
    )


def _dimension_definitions() -> tuple[ComputationDefinition, ...]:
    observed = ("evidence.observations",)
    independent = ("evidence.observations", "evidence.independent_groups")
    dims: list[ComputationDefinition] = []

    dims.append(
        _score_definition(
            "evidence_confidence",
            description=(
                "Existence confidence for the relationship evidence (NOT relationship "
                "strength — a separate dimension). Heuristic over independent "
                "corroboration (or distinct raw sources when M6 grouping is absent): "
                "confidence only materializes when at least one observation from a "
                "known source exists; it stays null when corroboration cannot be "
                "assessed. Uncalibrated HEURISTIC, never a probability."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_evidence_confidence",
        )
    )
    dims.append(
        _score_definition(
            "source_reliability",
            description=(
                "Mean source reliability of the underlying observations. Requires at "
                "least one observation carrying an assessed reliability; otherwise null."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_source_reliability",
        )
    )
    dims.append(
        _score_definition(
            "identity_confidence",
            description=(
                "MEASURED pass-through from the identity-resolution domain. Never "
                "derived here; null when upstream identity confidence is not supplied."
            ),
            required_inputs=("upstream.identity_confidence",),
            executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
        )
    )
    dims.append(
        _score_definition(
            "persistence",
            description=(
                "Durability of the relationship across independent observations and "
                "time. INDEPENDENCE-GATED: requires M6 evidence grouping; when "
                "independence is unknown persistence is null, never fabricated from "
                "possibly-duplicated raw reports."
            ),
            required_inputs=independent,
            dependency_definitions=("relationship_fidelity.independent_evidence_count",),
            executor_reference="shared.relationship_fidelity.scoring:derive_persistence",
        )
    )
    dims.append(
        _score_definition(
            "reciprocity",
            description=(
                "Reciprocity: requires INDEPENDENT evidence of both directions across "
                "distinct groups. A single-direction observation never yields a low "
                "reciprocity value (absence of observed opposite evidence is unknown, "
                "not 0) — reciprocity is null unless both directions are independently "
                "observed."
            ),
            required_inputs=independent,
            dependency_definitions=("relationship_fidelity.independent_evidence_count",),
            executor_reference="shared.relationship_fidelity.scoring:derive_reciprocity",
        )
    )
    dims.append(
        _score_definition(
            "interaction_frequency",
            description=(
                "Observed interaction rate normalized by the observation window "
                "(damped for correlated siblings when grouping is available). Null "
                "when no temporal window is supplied. A raw rate is disclosed as "
                "independence-unverified rather than silently damped."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_interaction_frequency",
        )
    )
    dims.append(
        _score_definition(
            "interaction_depth",
            description=(
                "Mean observed interaction intensity in [0, 1]. Requires observations "
                "carrying an intensity; otherwise null."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_interaction_depth",
        )
    )
    dims.append(
        _score_definition(
            "context_diversity",
            description=(
                "Diversity of contexts across which the relationship is observed: "
                "ratio of distinct context tags to total observations. Null when "
                "observations carry no context tags."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_context_diversity",
        )
    )
    dims.append(
        _score_definition(
            "temporal_continuity",
            description=(
                "Temporal continuity: distinct observation days over the span. Null "
                "when the span cannot be established from observation timestamps."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_temporal_continuity",
        )
    )
    dims.append(
        _score_definition(
            "semantic_specificity",
            description=(
                "MEASURED pass-through from the semantic domain. Null when the "
                "upstream semantic signal is not supplied."
            ),
            required_inputs=("upstream.semantic_specificity",),
            executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
        )
    )
    dims.append(
        _score_definition(
            "semantic_originality",
            description=(
                "MEASURED pass-through from the semantic domain. Null when the "
                "upstream semantic signal is not supplied."
            ),
            required_inputs=("upstream.semantic_originality",),
            executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
        )
    )
    dims.append(
        _score_definition(
            "preexisting_affinity_support",
            description=(
                "MEASURED pass-through of pre-existing affinity context. Null when "
                "not supplied; never inferred from behavioral similarity."
            ),
            required_inputs=("upstream.preexisting_affinity_support",),
            executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
        )
    )
    dims.append(
        _score_definition(
            "incentive_exposure",
            description=(
                "Fraction of INCENTIVE-ASSESSED observations that occurred under an "
                "incentive. Computed only over observations whose incentive presence "
                "/ absence was actually assessed; unassessed observations are never "
                "read as organic (absent incentive detection is not organic). A 0 is "
                "therefore evidence-backed: assessed and none incentivized."
            ),
            required_inputs=observed,
            executor_reference="shared.relationship_fidelity.scoring:derive_incentive_exposure",
        )
    )
    dims.append(
        _score_definition(
            "incentive_independence_support",
            description=(
                "INDEPENDENCE-GATED: the share of independent observation groups "
                "carrying no detected incentive. Requires M6 grouping AND incentive "
                "assessment; otherwise null."
            ),
            required_inputs=independent,
            dependency_definitions=("relationship_fidelity.independent_evidence_count",),
            executor_reference="shared.relationship_fidelity.scoring:derive_incentive_independence_support",
        )
    )
    dims.append(
        _score_definition(
            "coordination_indicator_strength",
            description=(
                "INDEPENDENCE-GATED strength of correlation/coordination structure "
                "across independent groups (correlated families damped at 0.4). "
                "Requires M6 grouping; null when independence is unknown."
            ),
            required_inputs=independent,
            dependency_definitions=("relationship_fidelity.independent_evidence_count",),
            executor_reference="shared.relationship_fidelity.scoring:derive_coordination_indicator_strength",
        )
    )
    for dim in (
        "economic_significance",
        "social_significance",
        "organizational_significance",
        "agentic_significance",
    ):
        dims.append(
            _score_definition(
                dim,
                description=(
                    f"MEASURED pass-through of {dim.replace('_', ' ')} context from "
                    "the cross-domain graph. Null when not supplied."
                ),
                required_inputs=(f"upstream.{dim}",),
                executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
            )
        )
    dims.append(
        _score_definition(
            "outcome_support",
            description=(
                "MEASURED pass-through of outcome/realized-consequence evidence "
                "(e.g. economic outcome correlated with the relationship). Null when "
                "not supplied."
            ),
            required_inputs=("upstream.outcome_support",),
            executor_reference="shared.relationship_fidelity.scoring:measured_passthrough",
        )
    )
    return tuple(dims)


def _count_definitions() -> tuple[ComputationDefinition, ...]:
    return (
        _count_definition(
            "observation_count",
            description=(
                "Number of raw relationship observations (a raw count of evidence "
                "items — NOT an independence claim). Always a measurement once "
                "observations exist; 0 only when a verified empty set is supplied."
            ),
        ),
        _count_definition(
            "independent_evidence_count",
            description=(
                "Number of INDEPENDENT observation groups (from the M6 evidence "
                "engine). NULL/unknown when M6 grouping is unavailable — never a "
                "fabricated number, never 0 for absent independence."
            ),
        ),
        _count_definition(
            "independent_source_count",
            description=(
                "Number of distinct independent sources across groups. NULL/unknown "
                "when group sources are not labelled."
            ),
        ),
    )


FIDELITY_DEFINITIONS: tuple[ComputationDefinition, ...] = (
    *_dimension_definitions(),
    *_count_definitions(),
)


def get_fidelity_definition(definition_id: str) -> ComputationDefinition | None:
    """Look up a fidelity definition by its full ``definition_id``."""
    key = f"{definition_id}@{FIDELITY_DEFINITION_VERSION}"
    for definition in FIDELITY_DEFINITIONS:
        if definition.key() == key:
            return definition
    return None


def register_fidelity_definitions() -> int:
    """Register all fidelity definitions on the Computation Substrate.

    Additive + idempotent; never edits the central seed registry or its generated
    twin. Returns the number of definitions registered (present after the call).
    """
    for definition in FIDELITY_DEFINITIONS:
        register(definition)
    return len(FIDELITY_DEFINITIONS)


__all__ = [
    "FIDELITY_DEFINITION_VERSION",
    "FIDELITY_OWNER",
    "FIDELITY_DOMAIN",
    "FIDELITY_TESTS",
    "FIDELITY_DIMENSIONS",
    "INDEPENDENCE_GATED_DIMENSIONS",
    "MEASURED_PASSTHROUGH_DIMENSIONS",
    "FIDELITY_COUNT_FIELDS",
    "FIDELITY_DEFINITIONS",
    "get_fidelity_definition",
    "register_fidelity_definitions",
]
