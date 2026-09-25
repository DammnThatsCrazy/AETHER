"""DSR erasure completeness: every component terminal, every store really erased.

Before the completeness planes (``services/consent/erasure_planes.py``) fifteen
``DSR_COMPONENTS`` stayed ``pending`` forever on a real erasure and Silver /
Bronze had no component at all. These suites seed the subject's data into EVERY
in-memory store the planes cover — plus a second subject in the same tenant and
the same ``user_id`` in another tenant — run the durable ``consent.erasure``
handler, and pin:

1. every ``DSR_COMPONENTS`` step ends terminal (none ``pending`` / ``running``)
   and the request rolls up to ``completed``;
2. per store: the subject's rows are gone (or tombstoned / lawfully retained,
   as the receipt says) while the other subject and the other tenant are
   untouched, and each component carries the store's own count;
3. the Bronze and outbox hash chains still verify after the erasure;
4. a retry is idempotent and keeps the committed receipts;
5. the policy branches: indexed ML artifacts → ``requires_manual_review``,
   a Bronze legal hold → ``skipped_legal_hold``, a failed plane defers the
   identity erasure so a retry can still resolve the subject;
6. the no-store proof for the asset-level value snapshot stores.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import uuid
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories.jobs_repo import reset_jobs_memory  # noqa: E402
from repositories.repos import (  # noqa: E402
    _IN_MEMORY_STORES,
    BehaviorProfileRepository,
    EntityRepository,
    EventEnvelopeRepository,
    IdentityClusterRepository,
    JourneyChainRepository,
    _ProfileStore,
    reset_in_memory_stores,
)
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from services.consent import erasure_jobs, erasure_planes  # noqa: E402
from services.consent.erasure_jobs import (  # noqa: E402
    ERASURE_JOB_TYPE,
    register_consent_erasure_handler,
)
from services.dsr_propagation.models import (  # noqa: E402
    DSR_COMPONENTS,
    DSR_TERMINAL_STATUSES,
)
from services.dsr_propagation.service import dsr_propagation_service  # noqa: E402
from services.jobs.handlers import HANDLER_REGISTRY, JobContext  # noqa: E402
from services.measurement import privacy as privacy_mod  # noqa: E402
from shared.integrity import hash_chain  # noqa: E402

pytestmark = pytest.mark.asyncio

USER = "user-erase-me"
ANON = "anon-erase-me"
OTHER_USER = "user-keep-me"
OTHER_ANON = "anon-keep-me"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _reset_all() -> None:
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    reset_jobs_memory()
    from services.comms.repository import reset_local_stores as reset_comms
    from services.silver.repositories.social_facts import reset_local_stores as reset_social
    from services.silver.writer import reset_local_tables

    from services.measurement.repositories import touchpoint_repo

    reset_comms()
    reset_social()
    reset_local_tables()
    touchpoint_repo._local_store.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _reset_all()
    register_consent_erasure_handler()
    # The measurement plane is exercised elsewhere; neutralise it here.
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    from services.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    # Fresh module singletons for stores that keep their own in-memory dicts.
    from repositories import artifacts as artifacts_mod
    from repositories import data_artifacts as data_artifacts_mod

    monkeypatch.setattr(artifacts_mod, "_repo", None)
    data_artifacts_mod.reset_data_artifact_in_memory_store()
    yield
    _reset_all()


class World:
    """Unique tenant / entity ids per test (graph + cache are process-wide)."""

    def __init__(self) -> None:
        tag = uuid.uuid4().hex[:8]
        self.tenant = f"t-dsr-{tag}"
        self.other_tenant = f"t-dsr-other-{tag}"
        self.entity = f"ent-{tag}"
        self.merged_entity = f"ent-merged-{tag}"
        self.other_entity = f"ent-other-{tag}"
        self.b_entity = f"ent-b-{tag}"
        self.job_id = f"job_{tag}"


def _ctx(world: World) -> JobContext:
    return JobContext(
        job_id=world.job_id,
        tenant_id=world.tenant,
        correlation_id="corr",
        worker_id="test_worker",
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )


async def _run(world: World, propagation_id: str, *, anonymous_id: str | None = ANON):
    handler = HANDLER_REGISTRY[ERASURE_JOB_TYPE]
    return await handler(
        {"user_id": USER, "anonymous_id": anonymous_id,
         "propagation_request_id": propagation_id},
        _ctx(world),
    )


async def _steps(world: World, propagation_id: str) -> dict[str, dict]:
    status = copy.deepcopy(
        await dsr_propagation_service.status(propagation_id, tenant_id=world.tenant)
    )
    return {c["component"]: c for c in status["components"]} | {"__overall__": status}


# ── seeding ───────────────────────────────────────────────────────────────────


async def _seed_identity(world: World) -> None:
    from services.identity.models import ConfidenceTier, EdgeType, IdentitySignalType
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    t, e = world.tenant, world.entity
    await repo.upsert_alias(t, e, "user_id", alias_value_hash=USER)
    await repo.upsert_alias(t, e, "anonymous_id", alias_value_hash=ANON)
    await repo.upsert_alias(t, e, "email_hash", alias_value_hash="hmac-email-subject")
    await repo.create_subject(t, e)
    await repo.create_subject(t, world.merged_entity)
    await repo.mark_subject_merged_by_canonical_id(t, world.merged_entity, e)
    await repo.upsert_alias(t, world.merged_entity, "email_hash", alias_value_hash="hmac-old")
    await repo.create_signal_observation(
        t, "ev-1", "web", "sdk", IdentitySignalType.USER_ID, USER, canonical_entity_id=e,
    )
    await repo.upsert_cluster(t, e, 0.9, ["deterministic"])
    await repo.create_identity_edge(
        t, e, world.other_entity, EdgeType.SAME_AS, 0.5, ConfidenceTier.WEAK, [], [],
    )
    await IdentityClusterRepository().link(f"cl-{e}", e, t, "wallet", "0xabc")
    await EntityRepository().create_entity(e, t, "human", display_name="Subject")
    # Another subject in the same tenant, and the same user_id in another tenant.
    await repo.upsert_alias(t, world.other_entity, "user_id", alias_value_hash=OTHER_USER)
    await repo.create_subject(t, world.other_entity)
    await EntityRepository().create_entity(world.other_entity, t, "human")
    await repo.upsert_alias(world.other_tenant, world.b_entity, "user_id", alias_value_hash=USER)
    await repo.create_subject(world.other_tenant, world.b_entity)


async def _seed_graph(world: World) -> None:
    from shared.graph.graph import Edge, Vertex, get_graph_client

    graph = get_graph_client()
    for vid in (world.entity, world.other_entity, "wallet-x"):
        await graph.add_vertex(Vertex(vertex_type="User", vertex_id=vid,
                                      properties={"tenant_id": world.tenant}))
    await graph.add_edge(Edge("OWNS_WALLET", world.entity, "wallet-x",
                              {"tenant_id": world.tenant}))
    await graph.add_edge(Edge("SIMILAR_TO", world.other_entity, world.entity,
                              {"tenant_id": world.tenant}))
    await graph.add_edge(Edge("OWNS_WALLET", world.other_entity, "wallet-x",
                              {"tenant_id": world.tenant}))
    # Same vertex id carrying another tenant's edge: never touched.
    await graph.add_edge(Edge("OWNS_WALLET", world.entity, "wallet-b",
                              {"tenant_id": world.other_tenant}))


async def _seed_profile(world: World) -> None:
    t = world.tenant
    await _ProfileStore().insert(USER, {"tenant_id": t, "traits": {"email": "s@x"}})
    await _ProfileStore().insert(OTHER_USER, {"tenant_id": t, "traits": {}})
    await BehaviorProfileRepository().upsert_snapshot(world.entity, t, "w0", "w1")
    await BehaviorProfileRepository().upsert_snapshot(world.other_entity, t, "w0", "w1")
    await JourneyChainRepository().upsert_chain(
        f"chain-{world.entity}", world.entity, t, "j1", "j2", 2, "a", "b",
    )
    await JourneyChainRepository().upsert_chain(
        f"chain-{world.other_entity}", world.other_entity, t, "j3", "j3", 1, "a", "b",
    )


async def _seed_features(world: World, cache) -> None:
    from repositories.lake import GoldRepository
    from shared.cache.cache import CacheKey

    gold = GoldRepository("trading_profile")
    await gold.materialize("score", world.entity, "entity", {"v": 1},
                           tenant_id=world.tenant, model_training_eligible=True)
    await gold.materialize("score", world.other_entity, "entity", {"v": 2},
                           tenant_id=world.tenant)
    await gold.materialize("score", world.entity, "entity", {"v": 3},
                           tenant_id=world.other_tenant)
    await cache.set_json(CacheKey.custom(f"features:{world.tenant}:{world.entity}"), {"f": 1})
    await cache.set_json(CacheKey.custom(f"features:{world.tenant}:{world.other_entity}"), {"f": 2})


async def _seed_predictions(world: World, cache) -> None:
    from shared.cache.cache import CacheKey

    await cache.set_json(CacheKey.prediction("churn_prediction", world.entity), {"p": 1})
    await cache.set_json(
        CacheKey.prediction("churn_prediction", world.entity, "v1", "h"), {"p": 1}
    )
    # A different entity whose id merely extends the subject's: never matched.
    await cache.set_json(
        CacheKey.prediction("churn_prediction", f"{world.entity}0", "v1", "h"), {"p": 2}
    )


def _json_bytes(rows: list[dict]) -> bytes:
    return json.dumps(rows).encode()


def _csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=sorted(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


async def _seed_exports(world: World) -> dict[str, str]:
    from repositories.artifacts import get_artifact_repository

    repo = get_artifact_repository()

    async def _put(tenant, export_type, content, ctype):
        return (await repo.put(tenant, export_type=export_type, filename="x",
                               content=content, content_type=ctype, manifest={}))["id"]

    return {
        "subject": await _put(world.tenant, "targeting_package",
                              _json_bytes([{"user_id": USER, "score": 1}]), "application/json"),
        "clean": await _put(world.tenant, "targeting_package",
                            _json_bytes([{"user_id": OTHER_USER}]), "application/json"),
        # ``USER`` as a substring of another value must NOT match.
        "substring": await _put(world.tenant, "targeting_package",
                                _json_bytes([{"note": f"{USER}-suffix"}]), "application/json"),
        "audit": await _put(world.tenant, "audit_log",
                            _csv_bytes([{"actor": USER, "action": "login"}]), "text/csv"),
        "other_tenant": await _put(world.other_tenant, "targeting_package",
                                   _json_bytes([{"user_id": USER}]), "application/json"),
    }


async def _seed_replay(world: World) -> None:
    repo = EventEnvelopeRepository()
    base = {"type": "page", "occurredAt": "2026-09-01T00:00:00Z", "replayable": True}
    await repo.create({**base, "id": f"env-s-{world.tenant}", "tenantId": world.tenant,
                       "subject": {"kind": "user", "id": USER}, "payload": {}})
    await repo.create({**base, "id": f"env-a-{world.tenant}", "tenantId": world.tenant,
                       "payload": {"anonymous_id": ANON}})
    await repo.create({**base, "id": f"env-o-{world.tenant}", "tenantId": world.tenant,
                       "subject": {"kind": "user", "id": OTHER_USER}, "payload": {}})
    await repo.create({**base, "id": f"env-b-{world.tenant}", "tenantId": world.other_tenant,
                       "subject": {"kind": "user", "id": USER}, "payload": {}})


async def _seed_rewards(world: World) -> None:
    from services.rewards.repositories import RewardDecisionRepository

    repo = RewardDecisionRepository()
    await repo.create(world.tenant, {"user_id": USER, "campaign_id": "c1", "eligible": True})
    await repo.create(world.tenant, {"user_id": OTHER_USER, "campaign_id": "c1", "eligible": True})


async def _seed_connectors(world: World) -> None:
    from services.comms.identity_bridge import ProviderIdentity, ProviderIdentityRepository
    from services.identity.models import SourceIdentityRecord
    from services.identity.repository import IdentityResolutionRepository

    bridge = ProviderIdentityRepository()
    await bridge.upsert(ProviderIdentity(
        identity_id=f"pid-s-{world.tenant}", tenant_id=world.tenant, provider="klaviyo",
        provider_profile_id="kl-subject", email_alias_hash="h-subject",
        canonical_entity_id=world.entity, resolution_status="resolved",
    ))
    await bridge.upsert(ProviderIdentity(
        identity_id=f"pid-o-{world.tenant}", tenant_id=world.tenant, provider="klaviyo",
        provider_profile_id="kl-other", canonical_entity_id=world.other_entity,
        resolution_status="resolved",
    ))
    repo = IdentityResolutionRepository()
    for user, tenant in ((USER, world.tenant), (OTHER_USER, world.tenant),
                         (USER, world.other_tenant)):
        source = await repo.create_source_identity(SourceIdentityRecord(
            id="", tenant_id=tenant, source_system_id="crm", source_kind="crm",
            source_namespace="contacts", user_id=user,
        ))
        await repo._claims.insert(f"claim-{source['id']}", {
            "tenant_id": tenant, "source_identity_id": source["id"], "claim": "email",
        })


async def _seed_financial(world: World) -> None:
    from repositories.derivatives_repos import PnlSnapshotRepo, TradingAccountRepo

    for acct, owner in (("acct-s", world.entity), ("acct-o", world.other_entity)):
        await TradingAccountRepo().insert({
            "tenant_id": world.tenant, "trading_account_id": f"{acct}-{world.tenant}",
            "owner_entity_id": owner, "idempotency_key": acct,
        })
        await PnlSnapshotRepo().insert({
            "tenant_id": world.tenant, "pnl_snapshot_id": f"pnl-{acct}",
            "trading_account_id": f"{acct}-{world.tenant}", "idempotency_key": f"pnl-{acct}",
        })


async def _seed_silver(world: World) -> None:
    from repositories.lake import SilverRepository
    from services.comms.repository import CommsFactsRepository
    from services.silver.projectors.base import ProjectionResult
    from services.silver.repositories.social_facts import SocialIdentityFactsRepository
    from services.silver.writer import SilverFactWriter

    t = world.tenant
    rows = [
        {"tenant_id": t, "idempotency_key": "x1", "user_id": USER},
        {"tenant_id": t, "idempotency_key": "x2", "anonymous_id": ANON},
        {"tenant_id": t, "idempotency_key": "x3", "user_id": OTHER_USER},
        {"tenant_id": world.other_tenant, "idempotency_key": "x4", "user_id": USER},
    ]
    await SilverFactWriter().persist([
        ProjectionResult(table="silver_exposure_facts", rows=rows),
        ProjectionResult(table="card_linked_flow_facts",
                         rows=[{"tenant_id": t, "idempotency_key": "c1", "user_id": USER}]),
        # Owned by attribution_records — the Silver plane must leave it alone.
        ProjectionResult(table="silver_campaign_touchpoint_facts",
                         rows=[{"tenant_id": t, "idempotency_key": "tp1",
                                "profile_id": world.entity}]),
    ])
    await CommsFactsRepository().upsert(
        {"tenant_id": t, "idempotency_key": "cm1", "profile_id": world.entity}
    )
    await CommsFactsRepository().upsert(
        {"tenant_id": t, "idempotency_key": "cm2", "profile_id": world.other_entity}
    )
    await SocialIdentityFactsRepository().upsert(
        {"tenant_id": t, "idempotency_key": "so1", "actor_id": USER}
    )
    await SilverRepository("identity").upsert_record(
        world.entity, "human", "crm", "tag", {"email": "s@x"}, tenant_id=t,
    )
    await SilverRepository("identity").upsert_record(
        world.other_entity, "human", "crm", "tag", {}, tenant_id=t,
    )


def _bronze_event(tenant, event_id, user_id, anonymous_id):
    from services.ingestion.bronze_bulk import BronzeSDKEvent

    return BronzeSDKEvent(
        tenant_id=tenant, event_id=event_id, schema_version="2.0", batch_id="b1",
        event_type="track", event_family="behavioral",
        event_timestamp="2026-09-01T00:00:00+00:00",
        received_at="2026-09-01T00:00:00+00:00", session_id=f"s-{event_id}",
        anonymous_id=anonymous_id, user_id=user_id,
        entity_id=user_id or anonymous_id,
        payload={"user_id": user_id, "anonymous_id": anonymous_id, "props": {"k": 1}},
    )


async def _seed_bronze(world: World) -> None:
    from services.ingestion.bronze_bulk import OutboxEvent, ingest_many

    specs = [
        (world.tenant, "e1", USER, ANON),
        (world.tenant, "e2", None, ANON),
        (world.tenant, "e3", OTHER_USER, OTHER_ANON),
        (world.tenant, "e4", USER, ANON),
        (world.other_tenant, "e5", USER, ANON),
    ]
    events = [_bronze_event(*s) for s in specs]
    outbox = [
        OutboxEvent(tenant_id=e.tenant_id, event_id=e.event_id, topic="sdk.events.validated",
                    partition_key=e.entity_id, payload=dict(e.payload))
        for e in events
    ]
    result = await ingest_many(events, outbox)
    assert result.accepted_count == len(events)
    # One outbox row already published: it keeps its status, only the payload goes.
    store = _IN_MEMORY_STORES["event_outbox"]
    published = next(r for r in store.values() if r["event_id"] == "e4")
    published["status"] = "published"


async def _seed_caches(world: World, cache) -> None:
    from shared.cache.cache import CacheKey

    await cache.set_json(f"aether:graph:query:{world.tenant}:h1", {"rows": [USER]})
    await cache.set_json(f"aether:graph:facets:{world.tenant}:h1", {"n": 1})
    await cache.set_json(f"aether:graph:query:{world.other_tenant}:h1", {"rows": [USER]})
    await cache.set_json(CacheKey.profile(world.tenant, USER), {"p": 1})
    await cache.set_json(CacheKey.consent(world.tenant, USER), {"c": 1})
    await cache.set_json(CacheKey.profile(world.tenant, OTHER_USER), {"p": 2})


async def _seed_everything(world: World) -> None:
    from dependencies.providers import get_registry

    cache = get_registry().cache
    await _seed_identity(world)
    await _seed_graph(world)
    await _seed_profile(world)
    await _seed_features(world, cache)
    await _seed_predictions(world, cache)
    world.exports = await _seed_exports(world)
    await _seed_replay(world)
    await _seed_rewards(world)
    await _seed_connectors(world)
    await _seed_financial(world)
    await _seed_silver(world)
    await _seed_bronze(world)
    await _seed_caches(world, cache)


# ── 1+2: every component terminal, every store erased ──────────────────────────


async def test_full_erasure_leaves_no_component_pending_and_erases_every_store():
    world = World()
    await _seed_everything(world)
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")

    outcome = await _run(world, propagation_id)
    assert outcome.status == "succeeded", outcome.error

    steps = await _steps(world, propagation_id)
    overall = steps.pop("__overall__")
    assert set(steps) == set(DSR_COMPONENTS)
    not_terminal = {c: s["status"] for c, s in steps.items()
                    if s["status"] not in DSR_TERMINAL_STATUSES}
    assert not_terminal == {}
    assert overall["overall"] == "completed"
    for component, step in steps.items():
        assert step["audit_event_id"] == world.job_id, component

    def records(component: str) -> int:
        return steps[component]["records_impacted"]

    # identity_aliases: 3 subject aliases + merged fragment's alias + 1 observation.
    assert records("identity_aliases") == 5
    # identity_subjects: 2 subject rows (live + merged) + cluster_v2 + legacy
    # cluster + entities row.
    assert records("identity_subjects") == 5
    # graph_edges: 1 identity_edges row + 2 graph edges (tenant-scoped).
    assert records("graph_edges") == 3
    assert records("profile360_snapshots") == 3
    assert records("feature_rows") == 1
    assert steps["feature_rows"]["artifacts_impacted"] == 1
    assert records("prediction_drift_buffers") == 2
    assert steps["exports"]["artifacts_impacted"] == 1
    assert steps["audit_exports"]["artifacts_impacted"] == 1
    assert records("replay_bundles") == 2
    assert steps["reward_decisions"]["status"] == "skipped_legal_hold"
    assert records("reward_decisions") == 1
    assert steps["reward_decisions"]["policy_decision_id"] == erasure_planes.POLICY_REWARD_RETENTION
    # connector: 1 provider identity tombstoned + 1 source identity + 1 claim.
    assert records("connector_derived_records") == 3
    assert records("financial_value_snapshots") == 1
    # silver: exposure x2 + card-linked + comms + social + lake silver_identity.
    assert records("silver_facts") == 6
    # bronze: 3 subject rows tombstoned + 3 outbox rows redacted.
    assert records("bronze_events") == 6
    assert records("cached_tenant_views") == 4
    # ML: no backend store; the subject's Gold row was training-eligible.
    for component in ("training_datasets", "model_artifacts"):
        assert steps[component]["status"] == "completed"
        assert steps[component]["policy_decision_id"]
    assert steps["training_datasets"]["records_impacted"] == 1
    assert steps["training_datasets"]["requires_retrain"] is True
    assert steps["model_artifacts"]["requires_retrain"] is True

    await _assert_stores_erased(world)


async def _assert_stores_erased(world: World) -> None:
    from dependencies.providers import get_registry
    from repositories.artifacts import get_artifact_repository
    from repositories.derivatives_repos import PnlSnapshotRepo
    from services.comms.repository import _local_facts
    from services.identity.repository import IdentityResolutionRepository
    from services.integrity.chain_verifier import verify_tenant_chain
    from services.silver.repositories.social_facts import local_rows
    from services.silver.writer import _local_tables
    from shared.cache.cache import CacheKey
    from shared.graph.graph import get_graph_client

    t, ot = world.tenant, world.other_tenant
    repo = IdentityResolutionRepository()
    # identity: subject gone, other subject + other tenant intact.
    assert await repo.get_entity_aliases(t, world.entity, include_revoked=True) == []
    assert await repo.get_entity_aliases(t, world.merged_entity, include_revoked=True) == []
    assert await repo.get_subject_by_canonical_entity_id(t, world.entity) is None
    assert await repo.get_subject_by_canonical_entity_id(t, world.merged_entity) is None
    assert await repo.get_observations_for_entity(t, world.entity) == []
    assert await repo.get_entity_graph(t, world.entity) == []
    assert await repo.find_entities_by_alias(t, "user_id", OTHER_USER) == [world.other_entity]
    assert await repo.find_entities_by_alias(ot, "user_id", USER) == [world.b_entity]
    assert await EntityRepository().find_by_id(world.entity) is None
    assert await EntityRepository().find_by_id(world.other_entity) is not None
    assert await IdentityClusterRepository().list_for_entity(world.entity) == []

    graph = get_graph_client()
    live = await graph.get_edges(world.entity, direction="both")
    assert [e.properties["tenant_id"] for e in live] == [ot]
    other_live = await graph.get_edges(world.other_entity, direction="both")
    assert [(e.to_vertex_id) for e in other_live] == ["wallet-x"]

    # profile360
    assert await _ProfileStore().find_by_id(USER) is None
    assert await _ProfileStore().find_by_id(OTHER_USER) is not None
    assert await BehaviorProfileRepository().find_by_id(world.entity) is None
    assert await BehaviorProfileRepository().find_by_id(world.other_entity) is not None
    assert await JourneyChainRepository().find_by_id(f"chain-{world.entity}") is None
    assert await JourneyChainRepository().find_by_id(f"chain-{world.other_entity}") is not None

    # feature rows (Gold) + caches
    gold = _IN_MEMORY_STORES["gold_trading_profile"].values()
    assert sorted((r["tenant_id"], r["entity_id"]) for r in gold) == sorted(
        [(t, world.other_entity), (ot, world.entity)]
    )
    cache = get_registry().cache
    assert not await cache.exists(CacheKey.custom(f"features:{t}:{world.entity}"))
    assert await cache.exists(CacheKey.custom(f"features:{t}:{world.other_entity}"))
    assert not await cache.exists(CacheKey.prediction("churn_prediction", world.entity))
    assert await cache.exists(
        CacheKey.prediction("churn_prediction", f"{world.entity}0", "v1", "h")
    )
    assert not await cache.exists(f"aether:graph:query:{t}:h1")
    assert await cache.exists(f"aether:graph:query:{ot}:h1")
    assert not await cache.exists(CacheKey.profile(t, USER))
    assert not await cache.exists(CacheKey.consent(t, USER))
    assert await cache.exists(CacheKey.profile(t, OTHER_USER))

    # exports: subject + audit purged (tombstone kept), everything else live.
    artifacts = get_artifact_repository()
    for key in ("subject", "audit"):
        meta = await artifacts.get_meta(t, world.exports[key])
        assert meta["deleted_at"] and meta["sha256"]
    for key in ("clean", "substring"):
        assert await artifacts.verify(t, world.exports[key])
    assert await artifacts.verify(ot, world.exports["other_tenant"])

    # replay bundles
    envelopes = {e["id"] for e in _IN_MEMORY_STORES["event_envelopes"].values()}
    assert envelopes == {f"env-o-{t}", f"env-b-{t}"}

    # rewards retained (legal), connectors
    decisions = _IN_MEMORY_STORES["reward_eligibility_decisions"].values()
    assert sorted(d["user_id"] for d in decisions) == sorted([OTHER_USER, USER])
    bridge = _IN_MEMORY_STORES["comms_provider_identities"]
    subject_row = bridge[f"pid-s-{t}"]
    assert subject_row["resolution_status"] == "erased"
    assert not subject_row["canonical_entity_id"] and not subject_row["provider_profile_id"]
    assert bridge[f"pid-o-{t}"]["canonical_entity_id"] == world.other_entity
    sources = _IN_MEMORY_STORES["source_identities"].values()
    assert sorted((s["tenant_id"], s["user_id"]) for s in sources) == sorted(
        [(t, OTHER_USER), (ot, USER)]
    )
    assert len(_IN_MEMORY_STORES["identity_claims"]) == 2

    # financial
    pnl = await PnlSnapshotRepo().find_many({"tenant_id": t})
    assert [p["pnl_snapshot_id"] for p in pnl] == ["pnl-acct-o"]

    # silver: subject rows gone everywhere; other subject / tenant / the
    # attribution-owned touchpoint table untouched.
    exposure = _local_tables["silver_exposure_facts"].values()
    assert sorted((r["tenant_id"], r["idempotency_key"]) for r in exposure) == sorted(
        [(t, "x3"), (ot, "x4")]
    )
    assert _local_tables["card_linked_flow_facts"] == {}
    from services.measurement.repositories import touchpoint_repo

    assert [r["profile_id"] for r in touchpoint_repo._local_store.values()
            if r.get("tenant_id") == t] == [world.entity]
    assert [r["profile_id"] for r in _local_facts.values()] == [world.other_entity]
    assert local_rows("silver_social_identity_facts") == []
    lake = _IN_MEMORY_STORES["silver_identity"].values()
    assert [r["entity_id"] for r in lake] == [world.other_entity]

    # bronze: tombstoned, chain verifies; outbox redacted, chain verifies.
    bronze = [r for r in _IN_MEMORY_STORES["bronze_sdk_events"].values()
              if r["tenant_id"] == t]
    assert len(bronze) == 4  # nothing hard-deleted from the chain
    for row in bronze:
        if row["event_id"] == "e3":
            assert row["user_id"] == OTHER_USER and row["payload"]["props"] == {"k": 1}
        else:
            assert row["tombstoned"] and row["payload"] == {}
            assert not row["user_id"] and not row["anonymous_id"] and not row["entity_id"]
    for tenant in (t, ot):
        result = await verify_tenant_chain(tenant)
        assert result.verified, result
    other_bronze = [r for r in _IN_MEMORY_STORES["bronze_sdk_events"].values()
                    if r["tenant_id"] == ot]
    assert other_bronze[0]["user_id"] == USER

    outbox = {r["event_id"]: r for r in _IN_MEMORY_STORES["event_outbox"].values()}
    for event_id in ("e1", "e2", "e4"):
        assert outbox[event_id]["payload"] == {} and outbox[event_id]["dsr_erased"]
    assert outbox["e1"]["status"] == "dead_letter"  # never published after erasure
    assert outbox["e4"]["status"] == "published"
    assert outbox["e3"]["payload"]["user_id"] == OTHER_USER
    assert outbox["e5"]["payload"]["user_id"] == USER  # other tenant
    for tenant in (t, ot):
        assert _verify_outbox_chain(tenant)["chain_intact"]


def _verify_outbox_chain(tenant: str) -> dict:
    from services.ingestion import bronze_bulk

    rows = [r for r in _IN_MEMORY_STORES["event_outbox"].values()
            if r.get("tenant_id") == tenant and r.get("integrity_hash")]
    return hash_chain.verify_chain(
        rows,
        partition_key=bronze_bulk._outbox_chain_partition,
        sort_key=bronze_bulk._outbox_chain_sort_key,
        canonical_field_variants=lambda r: [bronze_bulk._outbox_canonical_fields(r)],
        stored_hash=lambda r: r.get("integrity_hash"),
        record_id=lambda r: r["event_id"],
    )


# ── 4: idempotent retry keeps the committed receipts ───────────────────────────


async def test_rerun_is_idempotent_and_keeps_receipts():
    world = World()
    await _seed_everything(world)
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")
    assert (await _run(world, propagation_id)).status == "succeeded"
    first = await _steps(world, propagation_id)

    assert (await _run(world, propagation_id)).status == "succeeded"
    second = await _steps(world, propagation_id)
    assert second.pop("__overall__")["overall"] == "completed"
    first.pop("__overall__")
    for component, step in first.items():
        assert second[component]["status"] == step["status"], component
        assert second[component]["records_impacted"] == step["records_impacted"], component
        assert second[component]["artifacts_impacted"] == step["artifacts_impacted"], component


# ── 5: policy branches ────────────────────────────────────────────────────────


async def test_indexed_ml_artifacts_require_manual_review():
    from services.dsr_propagation.indexes import ArtifactIndex

    world = World()
    await _seed_identity(world)
    await ArtifactIndex().record_artifact(world.tenant, "ds-2026-09", "training_dataset", [USER])
    await ArtifactIndex().record_artifact(world.tenant, "model-v7", "model_artifact",
                                          [world.entity])
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")
    assert (await _run(world, propagation_id)).status == "succeeded"

    steps = await _steps(world, propagation_id)
    overall = steps.pop("__overall__")
    for component in ("training_datasets", "model_artifacts"):
        assert steps[component]["status"] == "requires_manual_review"
        assert steps[component]["requires_retrain"] is True
        assert steps[component]["artifacts_impacted"] == 1
    assert overall["overall"] == "requires_manual_review"
    assert all(s["status"] in DSR_TERMINAL_STATUSES for s in steps.values())


async def test_bronze_legal_hold_is_a_lawful_skip():
    from shared.storage.lifecycle import StorageLifecycle

    world = World()
    await _seed_bronze(world)
    hold = await StorageLifecycle().place_hold(
        world.tenant, reason="regulatory inquiry", subject_ref=USER,
    )
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")
    assert (await _run(world, propagation_id)).status == "succeeded"

    step = (await _steps(world, propagation_id))["bronze_events"]
    assert step["status"] == "skipped_legal_hold"
    assert step["policy_decision_id"] == f"storage_legal_hold:{hold['hold_id']}"
    assert "regulatory inquiry" in step["blocked_reason"]
    rows = [r for r in _IN_MEMORY_STORES["bronze_sdk_events"].values()
            if r["tenant_id"] == world.tenant and r.get("user_id") == USER]
    assert len(rows) == 2  # nothing mutated under the hold


async def test_failed_plane_defers_identity_erasure_and_retry_completes(monkeypatch):
    world = World()
    await _seed_identity(world)
    await _seed_silver(world)
    real = erasure_planes.erase_silver_plane
    calls = {"n": 0}

    async def _flaky(subject):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("silver store down")
        return await real(subject)

    planes = tuple(
        (name, comps, _flaky if name == "silver" else fn)
        for name, comps, fn in erasure_planes.ENTITY_PLANES
    )
    monkeypatch.setattr(erasure_planes, "ENTITY_PLANES", planes)
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")

    outcome = await _run(world, propagation_id)
    assert outcome.status == "failed" and "silver" in outcome.error
    steps = await _steps(world, propagation_id)
    assert steps["silver_facts"]["status"] == "failed"
    for component in erasure_planes.IDENTITY_COMPONENTS:
        assert steps[component]["status"] == "failed"
    # The mapping a retry needs survived the failed attempt.
    from services.identity.repository import IdentityResolutionRepository

    assert await IdentityResolutionRepository().find_entities_by_alias(
        world.tenant, "user_id", USER
    ) == [world.entity]

    outcome = await _run(world, propagation_id)
    assert outcome.status == "succeeded", outcome.error
    steps = await _steps(world, propagation_id)
    assert steps.pop("__overall__")["overall"] == "completed"
    assert steps["silver_facts"]["records_impacted"] == 6
    assert steps["identity_aliases"]["records_impacted"] == 5


async def test_plane_failure_marks_only_that_plane_failed(monkeypatch):
    world = World()
    planes = tuple(
        (name, comps, AsyncMock(side_effect=RuntimeError("export store down")))
        if name == "export" else (name, comps, fn)
        for name, comps, fn in erasure_planes.ENTITY_PLANES
    )
    monkeypatch.setattr(erasure_planes, "ENTITY_PLANES", planes)
    propagation_id = await dsr_propagation_service.open_request(world.tenant, USER, "erasure")
    outcome = await _run(world, propagation_id)
    assert outcome.status == "failed"
    steps = await _steps(world, propagation_id)
    assert steps["exports"]["status"] == "failed"
    assert steps["audit_exports"]["status"] == "failed"
    assert steps["silver_facts"]["status"] == "completed"
    assert steps.pop("__overall__")["overall"] == "failed"


# ── subject resolution ─────────────────────────────────────────────────────────


async def test_anonymous_alias_of_another_identified_person_is_not_the_subject():
    from services.identity.repository import IdentityResolutionRepository

    world = World()
    repo = IdentityResolutionRepository()
    await repo.upsert_alias(world.tenant, world.entity, "user_id", alias_value_hash=USER)
    # A shared device: its anonymous id resolved to ANOTHER identified person.
    await repo.upsert_alias(world.tenant, world.other_entity, "user_id",
                            alias_value_hash=OTHER_USER)
    await repo.upsert_alias(world.tenant, world.other_entity, "anonymous_id",
                            alias_value_hash=ANON)
    subject = await erasure_planes.resolve_subject(world.tenant, USER, ANON)
    assert subject.entity_ids == frozenset({world.entity})
    assert subject.refs == frozenset({world.entity, USER, ANON})


# ── 6: no-store proof ─────────────────────────────────────────────────────────


async def test_value_snapshot_stores_carry_no_subject_key():
    """financial_value_snapshots: the value-semantics snapshot stores record
    asset / metric valuations only — no column or written key identifies a
    data subject — so the DSR erases the per-subject P&L snapshots and these
    stores legitimately hold nothing to erase."""
    from repositories.stablecoin_repos import (
        ValuationSnapshotRepo as StablecoinValuationSnapshotRepo,
    )
    from services.valuation.repositories import ValuationSnapshotRepo
    from services.value.repositories import ValueSnapshotService

    subject_keys = set(erasure_planes.SILVER_SUBJECT_COLUMNS) | {
        "wallet_address", "trading_account_id", "account_id", "customer_id",
    }
    world = World()
    service = ValueSnapshotService()
    valuation = await service.record_valuation(
        world.tenant, {"valuation": {"usd_value": "1"}, "native": {"amount": "1"}}
    )
    rollup = await service.record_rollup(world.tenant, "gmv", {"total_usd": "1"})
    assert not (set(valuation) & subject_keys)
    assert not (set(rollup) & subject_keys)
    assert not (set(ValuationSnapshotRepo.columns) & subject_keys)
    assert not (set(StablecoinValuationSnapshotRepo.columns) & subject_keys)


# ── erasure primitives: tenant-scoped, idempotent, fail-closed ─────────────────


async def test_base_repository_delete_for_tenant_where_is_tenant_scoped():
    repo = JourneyChainRepository()
    for chain, tenant, entity in (("c1", "ta", "e1"), ("c2", "ta", "e2"), ("c3", "tb", "e1")):
        await repo.upsert_chain(chain, entity, tenant, "j", "j", 1, "a", "b")
    assert await repo.delete_for_tenant_where("ta", "entity_id", ["e1"]) == 1
    assert await repo.delete_for_tenant_where("ta", "entity_id", ["e1"]) == 0  # idempotent
    assert await repo.find_by_id("c3") is not None  # same entity, other tenant
    assert await repo.find_by_id("c2") is not None
    assert await repo.delete_for_tenant_where("ta", "entity_id", []) == 0
    with pytest.raises(ValueError):
        await repo.delete_for_tenant_where("", "entity_id", ["e2"])
    with pytest.raises(ValueError):
        await repo.delete_for_tenant_where("ta", "entity_id OR 1=1", ["e2"])


async def test_typed_repository_delete_for_tenant_where_is_tenant_scoped():
    from repositories.derivatives_repos import PnlSnapshotRepo

    repo = PnlSnapshotRepo()
    for pid, tenant, acct in (("p1", "ta", "a1"), ("p2", "ta", "a2"), ("p3", "tb", "a1")):
        await repo.insert({"tenant_id": tenant, "pnl_snapshot_id": pid,
                           "trading_account_id": acct, "idempotency_key": pid})
    assert await repo.delete_for_tenant_where("ta", "trading_account_id", ["a1"]) == 1
    assert await repo.delete_for_tenant_where("ta", "trading_account_id", ["a1"]) == 0
    remaining = sorted(r["pnl_snapshot_id"] for r in await repo.find_many())
    assert remaining == ["p2", "p3"]
    with pytest.raises(ValueError):
        await repo.delete_for_tenant_where("", "trading_account_id", ["a2"])
    with pytest.raises(ValueError):
        await repo.delete_for_tenant_where("ta", "not_a_column", ["a2"])
