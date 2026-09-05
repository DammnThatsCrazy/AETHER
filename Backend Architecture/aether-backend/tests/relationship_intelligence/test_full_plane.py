"""Wave 4b — full-plane replay/backfill-readiness integration (recorded social
events → silver facts → relationship fidelity).

Hermetic proof that the Social360 → Relationship-Fidelity spine plane is wired
end to end when the fidelity rollout flag is forced to ``enforce``:

    ``social_*_observed`` Bronze events
      → ``SilverDispatcher`` (real projectors)
      → ``SilverFactWriter`` → the ``silver_social_*_facts`` repositories
      → pair-scoped row mapping (the spine-writer seam, owned by this test)
      → ``materialize_observations`` (real M7 observation materializer)
      → ``RelationshipSpineCoordinator.run_for_relationship`` (real M7 engine
        + real M6 D-04 independence resolver)
      → ``persist_fidelity`` through the Computation Substrate
      → ``read_latest_fidelity`` read-back.

Honesty invariants under test:
* A social fact becomes a relationship observation ONLY when it binds to the
  pair being run. Pair binding + canonical-predicate projection are
  relationship-domain decisions no runtime caller has made while the plane is
  flag-gated OFF, so this test owns that seam explicitly. Facts about other
  pairs and single-entity facts (content authorship, community membership)
  contribute nothing — never fabricated.
* Replay is first-write-wins at the silver level; re-computing IDENTICAL
  evidence is guarded by the Computation Substrate's active-result discipline
  (an identical re-run is recorded as a persist failure, never a duplicate or
  divergent vector); NEW evidence backfills a fresh run for the relationship.
* The whole plane is OFF by default: without an explicit fidelity-mode override
  a coordinator run records ``rollout write OFF`` and persists nothing.

Full replay/backfill *machinery*, the live provider pull and the enforce-flag
flip remain release-gated residuals (recorded in
``reports/social360/PROGRAM_STATE.yaml``); this suite proves the activated plane
is real, hermetic and read-back-correct.
"""

from __future__ import annotations

import pytest

from services.computation.repositories import get_computation_repository
from services.relationship_fidelity import engine as _fidelity_engine
from services.relationship_intelligence.coordinator import (
    RelationshipSpineCoordinator,
    materialize_observations,
    relationship_ref_for,
)
from services.relationship_intelligence.reads import read_latest_fidelity
from services.silver import writer as writer_module
from services.silver.dispatcher import SilverDispatcher
from services.silver.repositories import social_facts as sf
from services.silver.writer import SilverFactWriter

INTERACTION_TABLE = "silver_social_interaction_facts"
CONTENT_TABLE = "silver_social_content_facts"
COMMUNITY_TABLE = "silver_social_community_facts"

# Canonical M6 relationship predicate that an observed social interaction
# evidences between a pair.
PAIR_PREDICATE = "SOCIAL_INTERACTS_WITH"


def _social_event(
    type_: str,
    *,
    message_id: str,
    tenant_id: str,
    timestamp: str,
    provider: str,
    props: dict,
) -> dict:
    """A Bronze social event carrying one provider record in ``properties``."""
    return {
        "type": type_,
        "messageId": message_id,
        "timestamp": timestamp,
        "context": {
            "tenantId": tenant_id,
            "provider": {
                "provider": provider,
                "acquisition_mode": "poll",
                "provider_record_id": f"{provider}-{message_id}",
            },
        },
        "properties": props,
    }


async def _dispatch(event: dict) -> None:
    """Feed one recorded Bronze event through the real silver forward path."""
    outcome = await SilverDispatcher().project_with_outcome(event)
    await SilverFactWriter().persist(outcome.results)


@pytest.fixture(autouse=True)
def _local_no_pool_stores(monkeypatch: pytest.MonkeyPatch):
    """Force the in-memory branches of the writer + social repositories."""

    async def _no_pool():
        return None

    monkeypatch.setattr(sf, "get_pool", _no_pool)
    monkeypatch.setattr(writer_module, "get_pool", _no_pool)
    sf.reset_local_stores()
    writer_module.reset_local_tables()
    yield
    sf.reset_local_stores()
    writer_module.reset_local_tables()


@pytest.fixture
def enforce_mode(monkeypatch: pytest.MonkeyPatch):
    """Force the fidelity rollout flag to ``enforce`` for one test."""
    monkeypatch.setattr(_fidelity_engine, "fidelity_mode", lambda: "enforce")


def _row_to_pair_record(row: dict, source: str, target: str) -> dict | None:
    """Observation-shaped record for a silver row scoped to one (source, target).

    Returns ``None`` when the row does not bind to the pair (no actor/target, or
    the actor/target are not exactly the two pair members) or carries no usable
    observed-at timestamp. Pair binding + canonical-predicate projection are the
    spine-writer seam this test owns — the relationship-domain interpretation a
    runtime spine caller will make once the plane is activated. Facts that cannot
    bind are never bent into fabricated relationship observations.
    """
    actor = row.get("actor_social_identity_ref")
    target_ref = row.get("target_social_identity_ref")
    if not actor or not target_ref:
        return None
    if {actor, target_ref} != {source, target}:
        return None
    if actor == source and target_ref == target:
        direction = "outgoing"
    elif actor == target and target_ref == source:
        direction = "incoming"
    else:
        return None
    observed_at = row.get("observed_at") or row.get("occurred_at")
    if not observed_at:
        return None
    return {
        "observation_id": row.get("interaction_id") or row.get("fact_id"),
        "predicate": PAIR_PREDICATE,
        "direction": direction,
        "source_key": row.get("provider_identity") or "",
        "observed_at": observed_at,
    }


# ---------------------------------------------------------------------------
# Full happy path: interaction events → silver facts → spine run → read-back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_plane_interaction_events_to_persisted_fidelity_read_back(
    enforce_mode,
) -> None:
    tenant = "fp-enforce-1"
    source, target = "alice", "bob"
    pair = relationship_ref_for(source, target)

    events = [
        # provider x — alice likes bob's post (outgoing for alice::bob)
        _social_event(
            "social_interaction_observed",
            message_id="it-1",
            tenant_id=tenant,
            timestamp="2026-08-01T00:00:00+00:00",
            provider="x",
            props={
                "actor_social_identity_ref": source,
                "target_social_identity_ref": target,
                "interaction_type": "like",
                "content_ref": "post-1",
                "observed_at": "2026-08-01T00:00:00+00:00",
            },
        ),
        # provider x — bob replies to alice (incoming for alice::bob)
        _social_event(
            "social_interaction_observed",
            message_id="it-2",
            tenant_id=tenant,
            timestamp="2026-08-10T00:00:00+00:00",
            provider="x",
            props={
                "actor_social_identity_ref": target,
                "target_social_identity_ref": source,
                "interaction_type": "reply",
                "content_ref": "post-1",
                "observed_at": "2026-08-10T00:00:00+00:00",
            },
        ),
        # provider y — independent corroboration: alice mentions bob
        _social_event(
            "social_interaction_observed",
            message_id="it-3",
            tenant_id=tenant,
            timestamp="2026-08-20T00:00:00+00:00",
            provider="y",
            props={
                "actor_social_identity_ref": source,
                "target_social_identity_ref": target,
                "interaction_type": "mention",
                "content_ref": "post-2",
                "observed_at": "2026-08-20T00:00:00+00:00",
            },
        ),
        # non-pair noise: a content fact and a community membership fact must
        # NOT become relationship observations for the pair.
        _social_event(
            "social_content_observed",
            message_id="ct-1",
            tenant_id=tenant,
            timestamp="2026-08-20T00:00:00+00:00",
            provider="x",
            props={
                "author_social_identity_ref": source,
                "provider_content_id": "post-9",
                "content_type": "post",
                "content_hash": "abc",
            },
        ),
        _social_event(
            "social_community_membership_observed",
            message_id="cm-1",
            tenant_id=tenant,
            timestamp="2026-08-20T00:00:00+00:00",
            provider="x",
            props={
                "social_identity_ref": source,
                "community_ref": "comm-1",
                "membership_role": "member",
            },
        ),
    ]
    for event in events:
        await _dispatch(event)

    # The forward write path is real: each fact lands in its silver repository.
    interaction_rows = sf.local_rows(INTERACTION_TABLE)
    assert len(interaction_rows) == 3
    assert len(sf.local_rows(CONTENT_TABLE)) == 1
    assert len(sf.local_rows(COMMUNITY_TABLE)) == 1
    assert {r["provider_identity"] for r in interaction_rows} == {"x", "y"}

    # Pair-scoped seam: only the three interaction rows bind to (alice, bob).
    all_rows = (
        interaction_rows
        + sf.local_rows(CONTENT_TABLE)
        + sf.local_rows(COMMUNITY_TABLE)
    )
    records = [
        record
        for record in (_row_to_pair_record(row, source, target) for row in all_rows)
        if record
    ]
    assert len(records) == 3
    obs = materialize_observations(records)
    assert len(obs) == 3
    assert sum(1 for o in obs if o.direction == "outgoing") == 2
    assert sum(1 for o in obs if o.direction == "incoming") == 1
    assert {o.source_key for o in obs} == {"x", "y"}

    # Full spine run in enforce mode — real M7 engine + real D-04 resolver.
    coord = RelationshipSpineCoordinator()
    result = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=source,
        target_entity_id=target,
        observations=obs,
        enrich_incentives=False,
    )
    assert result.mode == "enforce"
    assert result.persisted is True
    assert result.run_id
    assert result.independence_known is True
    assert result.vector is not None
    assert result.vector.independent_evidence_count == 2
    assert result.vector.independent_source_count == 2
    assert (result.vector.coverage or {}).get("independence_unknown") is False

    # Read-back through the sanctioned helper finds the same run.
    read = await read_latest_fidelity(tenant, pair)
    assert read is not None
    assert read["available"] is True
    assert read["degraded"] is False
    assert read["mode"] == "enforce"
    assert read["relationship_ref"] == pair
    vector = read["vector"]
    assert vector["status"] == "current"
    assert vector["observation_count"] == 3
    assert vector["independent_evidence_count"] == 2
    assert vector["independent_source_count"] == 2
    # Independence being known unlocked at least one independence-gated
    # dimension (bidirectional raw evidence across two sources => reciprocity).
    assert vector["reciprocity"] is not None
    assert (vector["coverage"] or {}).get("independence_unknown") is False


# ---------------------------------------------------------------------------
# Honest degraded case: facts that do not bind the pair are never fabricated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_plane_out_of_pair_and_single_entity_facts_never_fabricate(
    enforce_mode,
) -> None:
    tenant = "fp-degraded-1"
    pair_source, pair_target = "erin", "frank"
    pair = relationship_ref_for(pair_source, pair_target)
    third = "carol"

    events = [
        # erin↔carol interaction — evidence about (erin, carol), NOT (erin,
        # frank). Pair-scoped replay must not bend it into a (erin, frank)
        # observation.
        _social_event(
            "social_interaction_observed",
            message_id="it-off-1",
            tenant_id=tenant,
            timestamp="2026-08-01T00:00:00+00:00",
            provider="z",
            props={
                "actor_social_identity_ref": pair_source,
                "target_social_identity_ref": third,
                "interaction_type": "mention",
                "observed_at": "2026-08-01T00:00:00+00:00",
            },
        ),
        # single-entity content authorship — author only, no pair edge at all.
        _social_event(
            "social_content_observed",
            message_id="ct-off-1",
            tenant_id=tenant,
            timestamp="2026-08-01T00:00:00+00:00",
            provider="z",
            props={
                "author_social_identity_ref": third,
                "provider_content_id": "post-3",
                "content_type": "post",
                "content_hash": "def",
            },
        ),
    ]
    for event in events:
        await _dispatch(event)

    interaction_rows = sf.local_rows(INTERACTION_TABLE)
    assert len(interaction_rows) == 1

    self_rows = interaction_rows + sf.local_rows(CONTENT_TABLE)
    # The erin↔carol row IS mappable — but only to its own pair (erin, carol).
    bound_own_pair = [
        record for record in (_row_to_pair_record(r, pair_source, third) for r in self_rows) if record
    ]
    assert len(bound_own_pair) == 1
    # ...and contributes nothing to the (erin, frank) pair under run.
    pair_records = [_row_to_pair_record(r, pair_source, pair_target) for r in self_rows]
    assert all(record is None for record in pair_records)

    obs = materialize_observations([r for r in pair_records if r])
    assert obs == []

    coord = RelationshipSpineCoordinator()
    result = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=pair_source,
        target_entity_id=pair_target,
        observations=obs,
        enrich_incentives=False,
    )
    # Honest unknown: no evidence for the pair => nothing computed, nothing
    # persisted, no fabricated zero vector, no read-back.
    assert result.vector is None
    assert result.persisted is False
    assert result.run_id is None
    assert any("fidelity unknown" in line for line in result.limitations)
    assert await read_latest_fidelity(tenant, pair) is None


# ---------------------------------------------------------------------------
# Default flag posture: OFF means nothing persists without an override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_plane_default_flag_off_persists_nothing() -> None:
    tenant = "fp-off-1"
    source, target = "grace", "heidi"
    pair = relationship_ref_for(source, target)

    await _dispatch(
        _social_event(
            "social_interaction_observed",
            message_id="it-default",
            tenant_id=tenant,
            timestamp="2026-08-01T00:00:00+00:00",
            provider="x",
            props={
                "actor_social_identity_ref": source,
                "target_social_identity_ref": target,
                "interaction_type": "like",
                "content_ref": "post-1",
                "observed_at": "2026-08-01T00:00:00+00:00",
            },
        )
    )
    rows = sf.local_rows(INTERACTION_TABLE)
    assert len(rows) == 1
    obs = materialize_observations(
        [r for r in [_row_to_pair_record(rows[0], source, target)] if r]
    )
    assert len(obs) == 1

    # No fidelity-mode override anywhere: the rollout flag defaults OFF, so even
    # a fully mappable run must not persist through the substrate.
    coord = RelationshipSpineCoordinator()
    result = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=source,
        target_entity_id=target,
        observations=obs,
        enrich_incentives=False,
    )
    assert result.mode == "off"
    assert result.persisted is False
    assert result.run_id is None
    assert any("rollout write OFF" in line for line in result.limitations)
    assert await read_latest_fidelity(tenant, pair) is None
# ---------------------------------------------------------------------------
# Replay / backfill semantics end to end
#
# Silver replay is first-write-wins (proven above). At the fidelity-run level
# the Computation Substrate enforces ONE active result per
# (definition_id, context_hash): re-computing IDENTICAL evidence is guarded —
# an identical re-run is recorded as a persist failure, never a duplicate or
# divergent vector — while NEW evidence (a new observation set => a new context
# hash) backfills a fresh run for the relationship. This is the honest shape a
# backfill harness will sit on once the plane is activated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_plane_replay_is_silver_idempotent_and_run_recompute_is_guarded(
    enforce_mode,
) -> None:
    tenant = "fp-replay-1"
    source, target = "ivy", "jack"
    pair = relationship_ref_for(source, target)

    def _batch_a() -> list[dict]:
        return [
            _social_event(
                "social_interaction_observed",
                message_id="it-r1",
                tenant_id=tenant,
                timestamp="2026-08-01T00:00:00+00:00",
                provider="x",
                props={
                    "actor_social_identity_ref": source,
                    "target_social_identity_ref": target,
                    "interaction_type": "like",
                    "content_ref": "post-1",
                    "observed_at": "2026-08-01T00:00:00+00:00",
                },
            ),
            _social_event(
                "social_interaction_observed",
                message_id="it-r2",
                tenant_id=tenant,
                timestamp="2026-08-02T00:00:00+00:00",
                provider="y",
                props={
                    "actor_social_identity_ref": target,
                    "target_social_identity_ref": source,
                    "interaction_type": "reply",
                    "content_ref": "post-1",
                    "observed_at": "2026-08-02T00:00:00+00:00",
                },
            ),
        ]

    def _extra_b() -> dict:
        # NEW evidence: one more interaction on the pair from provider y.
        return _social_event(
            "social_interaction_observed",
            message_id="it-r3",
            tenant_id=tenant,
            timestamp="2026-08-03T00:00:00+00:00",
            provider="y",
            props={
                "actor_social_identity_ref": target,
                "target_social_identity_ref": source,
                "interaction_type": "mention",
                "content_ref": "post-2",
                "observed_at": "2026-08-03T00:00:00+00:00",
            },
        )

    def _obs_for(rows: list[dict]) -> list:
        return materialize_observations(
            [r for r in (_row_to_pair_record(row, source, target) for row in rows) if r]
        )

    # Three replays of the same recorded batch stay first-write-wins in silver.
    for _ in range(3):
        for event in _batch_a():
            await _dispatch(event)
    assert len(sf.local_rows(INTERACTION_TABLE)) == 2

    obs_a = _obs_for(sf.local_rows(INTERACTION_TABLE))
    assert len(obs_a) == 2

    coord = RelationshipSpineCoordinator()
    run1 = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=source,
        target_entity_id=target,
        observations=obs_a,
        enrich_incentives=False,
    )
    assert run1.persisted is True
    read1 = await read_latest_fidelity(tenant, pair)
    assert read1 is not None and read1["vector"]["observation_count"] == 2

    # Identical re-run: the substrate guards the active per-dimension result.
    # The re-run is recorded honestly as a persist failure — it must NOT create
    # a duplicate or divergent vector.
    run2 = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=source,
        target_entity_id=target,
        observations=obs_a,
        enrich_incentives=False,
    )
    assert run2.persisted is False
    assert any("Fidelity persistence failed" in line for line in run2.limitations)
    read_again = await read_latest_fidelity(tenant, pair)
    assert read_again is not None
    assert read_again["vector"]["observation_count"] == 2
    assert read_again["vector"]["status"] == "current"

    # NEW evidence backfills a fresh run for the relationship.
    await _dispatch(_extra_b())
    assert len(sf.local_rows(INTERACTION_TABLE)) == 3
    obs_b = _obs_for(sf.local_rows(INTERACTION_TABLE))
    assert len(obs_b) == 3
    run3 = await coord.run_for_relationship(
        tenant_id=tenant,
        relationship_ref=pair,
        source_entity_id=source,
        target_entity_id=target,
        observations=obs_b,
        enrich_incentives=False,
    )
    assert run3.persisted is True
    read3 = await read_latest_fidelity(tenant, pair)
    assert read3 is not None
    assert read3["vector"]["observation_count"] == 3
    assert read3["vector"]["independent_source_count"] == 2
    assert (
        await get_computation_repository().get_run(tenant, read3["run_id"]) is not None
    )

