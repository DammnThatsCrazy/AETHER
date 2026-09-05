"""Contract honesty tests for the Social360 + Relationship Fidelity M1 contracts.

Covers the standalone JSON-Schema contracts authored under
packages/shared/contracts/ for the Social360 + Relationship Fidelity program
(blueprint §§6-11, §§30-33, §§34-38) and the UPR social capability vocabulary
(blueprint §§15-19):

- social-silver-facts.schema.json         (six SocialSilver fact records)
- incentive-context.schema.json           (IncentiveContext + temporal segments)
- relationship-fidelity-vector.schema.json (multidimensional fidelity vector)
- social-provider-capability-vocabulary.json (UPR social capability vocabulary)

These contracts are the M1 canonical shapes that Milestones M2/M3/M5/M6/M7 build
against. They are not generated into twins in M1 (the predicate + motif
registries are); their enforcement here is structural + doctrinal: valid
draft-2020-12 layout, additionalProperties:false on canonical objects, and the
blueprint's anti-dishonesty invariants (unknown metrics never default to 0,
none_observed never converts to organic, the fidelity vector is never one scalar,
cross-file source-scope/evidence-basis enums stay in parity).
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "packages" / "shared" / "contracts"

SILVER_FACTS = CONTRACTS / "social-silver-facts.schema.json"
INCENTIVE_CONTEXT = CONTRACTS / "incentive-context.schema.json"
FIDELITY_VECTOR = CONTRACTS / "relationship-fidelity-vector.schema.json"
CAPABILITY_VOCAB = CONTRACTS / "social-provider-capability-vocabulary.json"


def _load(path: Path) -> dict:
    assert path.exists(), f"missing contract {path.name}"
    with path.open() as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def silver_facts():
    return _load(SILVER_FACTS)


@pytest.fixture(scope="module")
def incentive_context():
    return _load(INCENTIVE_CONTEXT)


@pytest.fixture(scope="module")
def fidelity_vector():
    return _load(FIDELITY_VECTOR)


@pytest.fixture(scope="module")
def capability_vocab():
    return _load(CAPABILITY_VOCAB)


# ---------------------------------------------------------------------------
# Shared schema layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [SILVER_FACTS, INCENTIVE_CONTEXT, FIDELITY_VECTOR])
def test_schema_layout(path):
    doc = _load(path)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "$id" in doc and doc["$id"].startswith("aether://contracts/")
    assert doc["$id"].endswith(path.name)
    assert doc.get("type") == "object"
    assert doc.get("additionalProperties") is False


# ---------------------------------------------------------------------------
# SocialSilver facts
# ---------------------------------------------------------------------------


def test_silver_facts_declares_all_six_fact_defs(silver_facts):
    defs = set(silver_facts["$defs"])
    required = {
        "socialIdentityFact",
        "socialConnectionFact",
        "socialInteractionFact",
        "socialContentFact",
        "socialCommunityMembership",
        "socialMetricObservation",
    }
    assert required <= defs, required - defs


def test_silver_fact_type_consts(silver_facts):
    mapping = {
        "socialIdentityFact": "social_identity",
        "socialConnectionFact": "social_connection",
        "socialInteractionFact": "social_interaction",
        "socialContentFact": "social_content",
        "socialCommunityMembership": "social_community_membership",
        "socialMetricObservation": "social_metric_observation",
    }
    for def_name, expected in mapping.items():
        props = silver_facts["$defs"][def_name]["properties"]
        assert props["fact_type"]["const"] == expected


def test_metric_observation_never_defaults_zero(silver_facts):
    metric = silver_facts["$defs"]["socialMetricObservation"]
    value = metric["properties"]["value"]
    # unavailable data -> null value with explicit status, never a synthetic 0
    assert value["type"] == ["number", "null"]
    assert "default" not in value
    status = metric["properties"]["status"]["enum"]
    assert {"observed", "unavailable", "not_authorized", "not_supported"} <= set(status)


def test_friend_requires_explicit_assertion_rule_present(silver_facts):
    # the schema must carry the doctrine that friend is never manufactured from
    # mutual follow (blueprint §7)
    conn = silver_facts["$defs"]["socialConnectionFact"]["properties"]["connection_type"]
    assert "friend" in conn["enum"]
    assert "mutual_follow" in conn["enum"]
    description = conn.get("description", "").lower()
    assert "never" in description and "mutual_follow" in description


def test_silver_connection_claim_type_bounded(silver_facts):
    claim = silver_facts["$defs"]["claimType"]["enum"]
    assert "observed" in claim and "inferred" in claim
    # claim_type is an epistemic class, not a strength or probability
    assert "strength" not in claim


# ---------------------------------------------------------------------------
# IncentiveContext
# ---------------------------------------------------------------------------


def test_incentive_status_enum(incentive_context):
    status = incentive_context["$defs"]["incentiveStatus"]
    assert {"verified", "declared", "observed", "suspected", "none_observed",
            "unknown", "not_applicable"} <= set(status["enum"])


def test_incentive_status_has_no_organic_conversion(incentive_context):
    # blueprint §31: none_observed -> organic is forbidden; the schema must
    # contain no "organic" conversion surface and status must have no default.
    status = incentive_context["$defs"]["incentiveStatus"]
    assert "default" not in status
    raw = json.dumps(incentive_context)
    assert '"organic"' not in raw, "IncentiveContext schema must not encode an organic conversion"


def test_incentive_temporal_segments(incentive_context):
    seg = incentive_context["$defs"]["temporalSegment"]["properties"]["segment"]["enum"]
    assert seg == ["PRE_INCENTIVE", "INCENTIVE_WINDOW", "POST_INCENTIVE"]


# ---------------------------------------------------------------------------
# Fidelity vector
# ---------------------------------------------------------------------------


def test_fidelity_vector_is_not_a_scalar(fidelity_vector):
    props = set(fidelity_vector["properties"])
    # no universal composite / single-scalar representation is permitted
    assert not (props & {"fidelity_score", "overall_fidelity", "strength", "score"})
    assert "relationship_ref" in props and "definition_version" in props


def test_fidelity_dimensions_nullable_no_default(fidelity_vector):
    dim = fidelity_vector["$defs"]["dimension"]
    assert dim["oneOf"][1]["type"] == "null"
    dimensions = [
        "persistence", "reciprocity", "interaction_frequency",
        "incentive_exposure", "incentive_independence_support",
        "coordination_indicator_strength", "evidence_confidence",
    ]
    for d in dimensions:
        assert d in fidelity_vector["properties"]
        assert "default" not in fidelity_vector["properties"][d]


# ---------------------------------------------------------------------------
# UPR social capability vocabulary
# ---------------------------------------------------------------------------


def test_capability_vocabulary_recommended_set(capability_vocab):
    recommended = {
        "account_read", "content_read", "relationship_read", "interaction_read",
        "community_read", "metrics_read", "incremental_pull", "backfill",
        "webhook_receive", "deletion_observe",
    }
    assert recommended <= set(capability_vocab["capabilities"])
    assert capability_vocab["capabilityGrammar"] == "family.product.capability"


def test_capability_vocabulary_acquisition_and_lifecycle(capability_vocab):
    assert set(capability_vocab["acquisitionClasses"]) == {
        "olympus_managed", "tenant_connected", "tenant_imported", "tenant_first_party",
    }
    states = set(capability_vocab["lifecycleStates"])
    assert "code_complete" in states and "partner_live" in states
    # the honesty rule text is present, not just the enum
    rules = "\n".join(capability_vocab["rules"])
    assert "code_complete" in rules and "partner_live" in rules


# ---------------------------------------------------------------------------
# Cross-file parity
# ---------------------------------------------------------------------------


def test_source_scope_evidence_basis_parity(silver_facts, incentive_context):
    sf_scope = set(silver_facts["$defs"]["sourceScope"]["enum"])
    ic_scope = set(incentive_context["$defs"]["sourceScope"]["enum"])
    assert sf_scope == ic_scope
    sf_basis = set(silver_facts["$defs"]["evidenceBasis"]["enum"])
    ic_basis = set(incentive_context["$defs"]["evidenceBasis"]["enum"])
    assert sf_basis == ic_basis
