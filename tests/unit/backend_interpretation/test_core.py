"""WS-D core tests: primitives, dedupe, stores, governance, correlation.

Covers shared/backend_interpretation primitives + Section-25 dedupe + durable
stores + derived-truth governance + correlation observer. Flag-gating is
asserted at each boundary (every mechanism default OFF).
"""

from __future__ import annotations

import pytest


# ── Typed RelationshipFact (item 1) ─────────────────────────────────────────


def test_relationship_fact_typed_fields_and_resolution(wsd_flags):
    from services.operational_intelligence.models import EntityRef
    from shared.backend_interpretation.facts import fact_from_assertion

    wsd_flags(relationship_fact_enabled=True)

    class FakeAssertion:
        tenant_id = "tenant-a"
        predicate = "SOCIAL_CONNECTION"
        source_entity_id = "u-1"
        target_entity_id = "u-2"
        evidence_refs = ["evt-a", "evt-b"]
        claim_ceiling = "observed"
        valid_from = "2026-09-06T00:00:00+00:00"

    fact = fact_from_assertion(
        FakeAssertion(), subject_kind="user", object_kind="user"
    )
    assert fact.tenant_id == "tenant-a"
    assert fact.subject == EntityRef(kind="user", id="u-1")
    assert fact.object == EntityRef(kind="user", id="u-2")
    assert fact.relationship_key == "SOCIAL_CONNECTION:u-1:u-2"
    assert fact.resolution_method == "observed"  # claim_ceiling observed
    assert fact.claim_type == "derived"
    assert fact.is_active is True
    assert [r.id for r in fact.evidence_refs] == ["evt-a", "evt-b"]
    # A derived claim ceiling maps to the inferred resolution method.
    class DerivedAssertion(FakeAssertion):
        claim_ceiling = "derived"

    derived = fact_from_assertion(
        DerivedAssertion(), subject_kind="user", object_kind="user"
    )
    assert derived.resolution_method == "inferred"


def test_relationship_fact_never_guesses_kind(wsd_flags):
    from shared.backend_interpretation.facts import fact_from_assertion

    class FakeAssertion:
        tenant_id = "tenant-a"
        predicate = "P"
        source_entity_id = "u-1"
        target_entity_id = "u-2"
        evidence_refs = []
        claim_ceiling = "observed"
        valid_from = None

    with pytest.raises(ValueError, match="kind"):
        fact_from_assertion(FakeAssertion())


# ── Section-25 evidence dedupe (item 4) ─────────────────────────────────────


def _obs(event_id, source_type, correlation_id=None):
    rec = {
        "source": {"type": source_type},
        "event": {"id": event_id, "type": "goal_achieved"},
        "subject": {"kind": "user", "id": "u-1"},
        "correlation": {},
    }
    if correlation_id:
        rec["correlation"]["correlation_id"] = correlation_id
    return rec


def test_section25_one_outcome_three_evidence_refs(wsd_flags):
    from shared.backend_interpretation.dedupe import dedupe_evidence

    wsd_flags(evidence_dedupe_enabled=True)
    # Same real-world outcome via browser SDK + webhook + connector sharing a
    # correlation family -> ONE canonical outcome, THREE distinct evidence refs.
    obs = [
        _obs("evt-1", "sdk", "fam-1"),
        _obs("evt-2", "webhook", "fam-1"),
        _obs("evt-3", "connector", "fam-1"),
    ]
    groups = dedupe_evidence(obs)
    assert len(groups) == 1
    group = groups[0]
    assert group.canonical_key == "correlation:fam-1"
    assert group.observation_count == 3
    assert len(group.evidence_refs) == 3
    assert {ref.id for ref in group.evidence_refs} == {"evt-1", "evt-2", "evt-3"}
    assert "sdk" in group.sources and "webhook" in group.sources


def test_section25_literal_duplicate_collapses_to_one_ref(wsd_flags):
    from shared.backend_interpretation.dedupe import dedupe_evidence

    wsd_flags(evidence_dedupe_enabled=True)
    # The SAME event delivered twice on the same channel is ONE evidence ref.
    obs = [_obs("evt-1", "sdk", "fam-1"), _obs("evt-1", "sdk", "fam-1")]
    groups = dedupe_evidence(obs)
    assert len(groups) == 1
    assert groups[0].observation_count == 2
    assert len(groups[0].evidence_refs) == 1


def test_section25_subject_type_day_fallback_and_keyless_skip(wsd_flags):
    from shared.backend_interpretation.dedupe import dedupe_evidence

    wsd_flags(evidence_dedupe_enabled=True)
    obs = [
        # No correlation block -> subject+type+day fallback groups the pair.
        {
            "source": {"type": "sdk"},
            "event": {"id": "a", "type": "order_completed"},
            "subject": {"kind": "user", "id": "u-1"},
            "temporal": {"source_time": "2026-09-06T01:00:00Z"},
        },
        {
            "source": {"type": "connector"},
            "event": {"id": "b", "type": "order_completed"},
            "subject": {"kind": "user", "id": "u-1"},
            "temporal": {"source_time": "2026-09-06T02:00:00Z"},
        },
        # Too sparse to key -> skipped.
        {"event": {"id": "c"}},
    ]
    groups = dedupe_evidence(obs)
    assert len(groups) == 1
    assert groups[0].observation_count == 2
    assert groups[0].canonical_key.startswith("subject-type:")


# ── Durable truth stores (items 1/2/3) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_durable_stores_round_trip_and_tenant_scope(wsd_flags):
    from shared.store import reset_in_memory_stores
    from services.operational_intelligence.models import EntityRef
    from shared.backend_interpretation.primitives import (
        EpisodeRecord,
        OutcomeTruthRecord,
        RelationshipFact,
        ValidityWindow,
    )
    from shared.backend_interpretation.stores import (
        EpisodeStore,
        OutcomeTruthStore,
        RelationshipFactStore,
    )

    reset_in_memory_stores()
    wsd_flags()
    fact_store = RelationshipFactStore()
    episode_store = EpisodeStore()
    outcome_store = OutcomeTruthStore()

    fact = RelationshipFact(
        tenant_id="tenant-a",
        fact_id="f1",
        relationship_key="SOCIAL_CONNECTION:u-1:u-2",
        subject=EntityRef(kind="user", id="u-1"),
        object=EntityRef(kind="user", id="u-2"),
        predicate="SOCIAL_CONNECTION",
        resolution_method="observed",
        validity=ValidityWindow(),
        evidence_refs=[],
    )
    await fact_store.upsert(fact)
    loaded = await fact_store.get("tenant-a", "f1")
    assert loaded is not None and loaded.fact_id == "f1"
    assert [f.fact_id for f in await fact_store.list_by_tenant("tenant-a")] == ["f1"]
    assert await fact_store.list_by_tenant("tenant-other") == []

    episode = EpisodeRecord(
        episode_id="ep1",
        tenant_id="tenant-a",
        subject=EntityRef(kind="user", id="u-1"),
        kind="support",
        observation_ids=["o1"],
    )
    await episode_store.upsert(episode)
    assert (await episode_store.get("tenant-a", "ep1")).status == "open"
    assert [e.episode_id for e in await episode_store.list_for_subject("tenant-a", "user", "u-1")] == ["ep1"]

    outcome = OutcomeTruthRecord(
        outcome_id="oc1",
        tenant_id="tenant-a",
        definition_ref="goal_achieved",
        subject=EntityRef(kind="user", id="u-1"),
        state="final",
        value_amount="12.50",
        value_currency="USD",
        value_state="present",
        evidence_refs=[],
        source_event_ids=["e1"],
    )
    await outcome_store.upsert(outcome)
    loaded_outcome = await outcome_store.get("tenant-a", "oc1")
    assert loaded_outcome.value_amount == "12.50"
    assert loaded_outcome.state == "final"
    assert len(await outcome_store.list_by_tenant("tenant-a")) == 1


# ── Derived-truth governance (item 8) ───────────────────────────────────────


def test_governance_off_is_pass_through(wsd_flags, mutation_mode):
    from shared.backend_interpretation.governance import assess_derived_write

    mutation_mode("off")
    decision = assess_derived_write(
        tenant_id="t", claim_type="derived", actor_kind="noesis",
        actor_id="a", model_version=None, evidence_ids=None,
        source_event_id=None, reason_code=None,
    )
    # Off reports no violations even for a lineage-less write (parity).
    assert decision.permit is True and decision.mode == "off"
    assert decision.violations == ()


def test_governance_shadow_reports_but_allows(wsd_flags, mutation_mode):
    from shared.backend_interpretation.governance import assess_derived_write

    mutation_mode("shadow")
    decision = assess_derived_write(
        tenant_id="t", claim_type="derived", actor_kind="noesis",
        actor_id="a", model_version="m", evidence_ids=[],
        source_event_id=None, reason_code="r",
    )
    assert decision.permit is True
    assert any("evidence" in v for v in decision.violations)


def test_governance_enforce_blocks_incomplete_derived_write(wsd_flags, mutation_mode):
    from shared.backend_interpretation.governance import assess_derived_write

    mutation_mode("enforce")
    decision = assess_derived_write(
        tenant_id="t", claim_type="derived", actor_kind="noesis",
        actor_id="a", model_version="m", evidence_ids=[],
        source_event_id=None, reason_code="r",
    )
    assert decision.permit is False and decision.would_block is True
    assert len(decision.violations) >= 2


def test_governance_enforce_allows_lineaged_write(wsd_flags, mutation_mode):
    from shared.backend_interpretation.governance import assess_derived_write

    mutation_mode("enforce")
    decision = assess_derived_write(
        tenant_id="t", claim_type="derived", actor_kind="measurement",
        actor_id="outcome_truth_recorder", model_version="m",
        policy_refs=["p:v1"], evidence_ids=["e1"], source_event_id="e1",
        reason_code="outcome-truth:record",
    )
    assert decision.permit is True


def test_enrich_derived_intent_carries_lineage(wsd_flags):
    from shared.backend_interpretation.governance import enrich_derived_intent

    intent = enrich_derived_intent(
        operation="edge_created",
        tenant_id="t",
        actor_kind="measurement",
        actor_id="recorder",
        model_version="model-v1",
        policy_refs=["p:v1"],
        evidence_refs=[{"id": "e1"}, {"id": "e2"}],
        source_event_id="e1",
        reason_code="rc",
    )
    assert intent.evidence_refs == ["e1", "e2"]
    assert intent.model_refs == ["model:model-v1"]
    assert intent.source_event_id == "e1"


# ── Correlation observer (item 6) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_correlation_registry_flag_gating_and_merge(wsd_flags):
    from shared.store import reset_in_memory_stores
    from shared.backend_interpretation.observe import (
        register_correlation_from_observation,
    )
    from shared.backend_interpretation.stores import CorrelationRegistry

    reset_in_memory_stores()
    wsd_flags(correlation_first_class_enabled=False)
    reg = CorrelationRegistry()
    rec = {
        "correlation": {"correlation_id": "fam-1", "causation_id": "cause-1"},
        "event": {"id": "evt-1"},
        "source": {"type": "sdk"},
    }
    assert await register_correlation_from_observation("tenant-a", rec, reg) is None

    wsd_flags(correlation_first_class_enabled=True)
    row1 = await register_correlation_from_observation("tenant-a", rec, reg)
    assert row1 is not None and row1["correlation_id"] == "fam-1"
    rec2 = {
        "correlation": {"correlation_id": "fam-1"},
        "event": {"id": "evt-2"},
        "source": {"type": "webhook"},
    }
    await register_correlation_from_observation("tenant-a", rec2, reg)
    row = await reg.get("tenant-a", "fam-1")
    assert row["observation_ids"] == ["evt-1", "evt-2"]
    assert len(row["evidence_refs"]) == 2
    assert "sdk" in row["sources"] and "webhook" in row["sources"]
