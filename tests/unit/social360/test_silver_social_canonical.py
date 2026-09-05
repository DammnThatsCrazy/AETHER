"""Canonical Social Silver enums stay aligned to the M1 JSON $defs.

``shared/social360/canonical.py`` is the hand-authored backend carrier for the
``sourceScope`` / ``evidenceBasis`` $defs of
``packages/shared/contracts/social-silver-facts.schema.json``. This suite fails
loudly if that carrier drifts from the JSON contract, and locks in the honesty
rules the vocabulary encodes:

- ``sourceScope`` has NO ``unknown`` member (an un-attributable event is left
  NULL, never guessed);
- ``evidenceBasis`` DOES carry ``unknown`` (its honest default);
- the Social360 evidenceBasis vocabulary is DISTINCT from the product-intelligence
  ``interaction-vocabulary.json`` evidenceBasis — the two are never merged;
- acquisition-mode derivations stay inside the canonical members and never
  auto-derive ``olympus_corpus`` (corpus -> tenant projection is D-OPEN);
- each SocialSilver fact kind maps 1:1 to its schema $defs ``fact_type`` const.
"""
from __future__ import annotations

import json
from pathlib import Path

# conftest.py in this package has already prepended the worktree backend path,
# so `shared.social360` resolves to THIS checkout.
from shared.social360.canonical import (  # noqa: E402
    EVIDENCE_BASIS,
    EVIDENCE_BASIS_BY_ACQUISITION_MODE,
    FACT_KIND_BY_EVENT_TYPE,
    SOCIAL_SILVER_CONTRACT_VERSION,
    SOURCE_SCOPES,
    SOURCE_SCOPE_BY_ACQUISITION_MODE,
    fact_kind_for,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = (
    _REPO_ROOT / "packages" / "shared" / "contracts" / "social-silver-facts.schema.json"
)
_INTERACTION_VOCAB_PATH = (
    _REPO_ROOT / "packages" / "shared" / "contracts" / "interaction-vocabulary.json"
)

# Canonical social event type -> the schema $def that declares its fact.
_EVENT_TYPE_TO_DEF = {
    "social_identity_observed": "socialIdentityFact",
    "social_connection_observed": "socialConnectionFact",
    "social_interaction_observed": "socialInteractionFact",
    "social_content_observed": "socialContentFact",
    "social_community_membership_observed": "socialCommunityMembership",
    "social_metric_observed": "socialMetricObservation",
}

_VALID_ACQUISITION_MODES = {
    "sdk", "webhook", "poll", "report", "stream", "import", "reconciliation",
}


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _interaction_vocabulary_evidence_basis() -> list[str]:
    data = json.loads(_INTERACTION_VOCAB_PATH.read_text(encoding="utf-8"))
    return list(data["evidenceBasis"])


# ── enum alignment to the M1 JSON $defs ─────────────────────────────────────


def test_source_scopes_match_schema_defs():
    expected = _schema()["$defs"]["sourceScope"]["enum"]
    assert list(SOURCE_SCOPES) == expected
    # canonical members are unique and ordered as declared
    assert len(set(SOURCE_SCOPES)) == len(SOURCE_SCOPES)
    assert tuple(dict.fromkeys(expected)) == tuple(expected)


def test_evidence_basis_matches_schema_defs():
    expected = _schema()["$defs"]["evidenceBasis"]["enum"]
    assert list(EVIDENCE_BASIS) == expected
    assert len(set(EVIDENCE_BASIS)) == len(EVIDENCE_BASIS)


def test_schema_version_matches_json_contract():
    assert SOCIAL_SILVER_CONTRACT_VERSION == _schema()["properties"]["schema_version"]["const"]
    assert SOCIAL_SILVER_CONTRACT_VERSION == "1.0.0"


def test_source_scope_has_no_unknown_member_but_evidence_basis_does():
    # Honesty rule (canonical module docstring): un-attributable events leave
    # source_scope NULL; evidence_basis keeps an explicit "unknown" member.
    assert "unknown" not in SOURCE_SCOPES
    assert "unknown" in EVIDENCE_BASIS


def test_olympus_corpus_is_never_auto_derived():
    # corpus -> tenant projection is D-OPEN, so no acquisition mode may map to
    # the corpus scope, and no derivation may manufacture it.
    assert "olympus_corpus" not in SOURCE_SCOPE_BY_ACQUISITION_MODE.values()


def test_evidence_basis_is_disjoint_from_interaction_vocabulary():
    # The two evidenceBasis vocabularies are DISTINCT by design — this carrier
    # must never grow an interaction-vocabulary member, and vice versa.
    interaction_basis = _interaction_vocabulary_evidence_basis()
    overlap = set(EVIDENCE_BASIS) & set(interaction_basis)
    assert overlap == set()
    # Sanity: neither vocabulary collapsed into a subset of the other.
    assert not set(EVIDENCE_BASIS) <= set(interaction_basis)
    assert not set(interaction_basis) <= set(EVIDENCE_BASIS)


# ── fact-kind routing ───────────────────────────────────────────────────────


def test_fact_kind_by_event_type_matches_schema_fact_type_consts():
    schema = _schema()
    assert set(FACT_KIND_BY_EVENT_TYPE) == set(_EVENT_TYPE_TO_DEF)
    for event_type, def_name in _EVENT_TYPE_TO_DEF.items():
        expected_const = schema["$defs"][def_name]["properties"]["fact_type"]["const"]
        assert FACT_KIND_BY_EVENT_TYPE[event_type] == expected_const


def test_fact_kind_for_returns_none_for_non_social_events():
    assert fact_kind_for("email_sent") is None
    assert fact_kind_for("page") is None
    assert fact_kind_for("") is None
    assert fact_kind_for("social_identity_observed") == "social_identity"
    assert fact_kind_for("social_metric_observed") == "social_metric_observation"


# ── acquisition-mode derivations stay canonical ─────────────────────────────


def test_source_scope_derivations_are_canonical_members():
    assert set(SOURCE_SCOPE_BY_ACQUISITION_MODE) == _VALID_ACQUISITION_MODES
    for scope in SOURCE_SCOPE_BY_ACQUISITION_MODE.values():
        assert scope in SOURCE_SCOPES


def test_evidence_basis_derivations_are_canonical_members():
    assert set(EVIDENCE_BASIS_BY_ACQUISITION_MODE) == _VALID_ACQUISITION_MODES
    for basis in EVIDENCE_BASIS_BY_ACQUISITION_MODE.values():
        assert basis in EVIDENCE_BASIS
        assert basis != "unknown"  # an acquisition mode is real evidence, never unknown


def test_acquisition_mode_pairings_are_documented_reading():
    # The 1:1 documented reading of how the record was acquired.
    assert SOURCE_SCOPE_BY_ACQUISITION_MODE["sdk"] == "tenant_first_party"
    assert SOURCE_SCOPE_BY_ACQUISITION_MODE["import"] == "tenant_imported"
    assert SOURCE_SCOPE_BY_ACQUISITION_MODE["reconciliation"] == "tenant_imported"
    for web_mode in ("webhook", "poll", "report", "stream"):
        assert SOURCE_SCOPE_BY_ACQUISITION_MODE[web_mode] == "tenant_connected"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["sdk"] == "first_party_sdk"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["webhook"] == "provider_record"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["poll"] == "provider_api"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["report"] == "provider_api"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["stream"] == "provider_api"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["import"] == "imported_source"
    assert EVIDENCE_BASIS_BY_ACQUISITION_MODE["reconciliation"] == "imported_source"
