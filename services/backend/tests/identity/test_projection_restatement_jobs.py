"""End-to-end checks for durable, truthful identity restatement jobs."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import replace

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.jobs_repo import reset_jobs_memory  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.models import (  # noqa: E402
    ConfidenceBand,
    DecisionType,
    IdentityDecisionRecord,
    ProjectionType,
)
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.merge_policy import MergePolicyResult  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.jobs.handlers import unregister_handler  # noqa: E402
from services.jobs.service import get_jobs_service  # noqa: E402
from services.jobs.worker import JobWorker  # noqa: E402
from services.projections.projection_restatement_orchestrator import (  # noqa: E402
    PROJECTION_RESTATEMENT_JOB_TYPE,
    ProjectionRestatementOrchestrator,
    register_projection_restatement_handler,
)
from shared.events.events import Event, Topic  # noqa: E402


TENANT = "tenant_projection_jobs"


def _decision(*, tenant_id: str = TENANT) -> IdentityDecisionRecord:
    return IdentityDecisionRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        decision_type=DecisionType.AUTO_MERGE,
        candidate_source_identity_ids=[],
        candidate_canonical_entity_ids=["profile_survivor", "profile_consumed"],
        selected_canonical_entity_id="profile_survivor",
        confidence=0.98,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[],
        negative_evidence=[],
        vetoes=[],
        policy_version="1.0.0",
        graph_version_before="g10",
        graph_version_after="g11",
        explanation="test decision",
        decided_by="system",
        decided_at="2026-09-27T00:00:00+00:00",
    )


@pytest.fixture(autouse=True)
def _reset_state():
    reset_in_memory_stores()
    reset_jobs_memory()
    import services.jobs.service as jobs_service_module

    jobs_service_module._service = None
    unregister_handler(PROJECTION_RESTATEMENT_JOB_TYPE)
    yield
    unregister_handler(PROJECTION_RESTATEMENT_JOB_TYPE)
    jobs_service_module._service = None


@pytest.mark.asyncio
async def test_queue_is_durable_idempotent_and_tenant_scoped():
    decision = _decision()
    first = await ProjectionRestatementOrchestrator().queue_restatement(decision)
    second = await ProjectionRestatementOrchestrator().queue_restatement(decision)

    assert first.id == second.id
    assert first.status == "queued"
    assert first.graph_version_after == "g11"
    assert first.affected_canonical_entity_ids == [
        "profile_survivor", "profile_consumed"
    ]
    fresh = ProjectionRestatementOrchestrator()
    assert (await fresh.get_job_status(TENANT, first.id)).id == first.id
    assert await fresh.get_job_status("another_tenant", first.id) is None


@pytest.mark.asyncio
async def test_actual_identity_merged_topic_queues_merge_projection_surfaces():
    event = Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=TENANT,
        payload={
            "decision_id": "persisted-merge-decision",
            "resolution_revision_before": 4,
            "resolution_revision_after": 5,
            "affected_canonical_entity_ids": ["profile-survivor", "profile-consumed"],
        },
    )

    job = await ProjectionRestatementOrchestrator().queue_restatement_from_event(event)

    assert job is not None
    assert job.trigger_decision_id == "persisted-merge-decision"
    assert ProjectionType.CAMPAIGN_360 in job.projections
    assert ProjectionType.VALUE in job.projections


@pytest.mark.asyncio
async def test_fragment_split_restatement_carries_durable_split_evidence():
    repository = IdentityResolutionRepository()
    split_event = await repository.create_split_event(
        tenant_id=TENANT,
        original_entity_id="profile-original",
        resulting_entity_ids=["profile-original", "profile-fragment"],
        reason="operator fragment split",
        actor_type="operator",
        actor_id="operator-1",
        fragment={
            "alias_ids": ["source-alias"],
            "moved_alias_ids": ["fragment-alias"],
            "moved_alias_map": [{
                "source_alias_id": "source-alias",
                "resulting_alias_id": "fragment-alias",
            }],
            "observation_ids": ["observation-1"],
            "moved_observation_ids": ["observation-1"],
        },
        mode="create_new_entity",
    )
    decision = _decision()
    decision.id = split_event["id"]
    decision.decision_type = DecisionType.MANUAL_SPLIT
    decision.candidate_canonical_entity_ids = [
        "profile-original", "profile-fragment"
    ]
    decision.selected_canonical_entity_id = "profile-original"

    queued = await ProjectionRestatementOrchestrator().queue_restatement(decision)
    platform_job = await get_jobs_service().get_job(TENANT, queued.id)

    assert platform_job["payload"]["identity_context"]["split_event"] == split_event


@pytest.mark.asyncio
async def test_restatement_and_campaign_value_flags_gate_queue_surfaces(monkeypatch):
    from config.settings import settings

    orchestrator = ProjectionRestatementOrchestrator()
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, projection_restatement_enabled=False
    ))
    assert await orchestrator.queue_restatement_from_event(Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=TENANT,
        payload={
            "decision_id": "disabled-decision",
            "resolution_revision_after": 2,
            "affected_canonical_entity_ids": ["profile-survivor", "profile-consumed"],
        },
    )) is None
    with pytest.raises(RuntimeError, match="projection restatement is disabled"):
        await orchestrator.queue_restatement(_decision())

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        projection_restatement_enabled=True,
        campaign_restatement_enabled=False,
        value_restatement_enabled=False,
    ))
    projections = orchestrator._determine_projections(_decision())
    assert ProjectionType.CAMPAIGN_360 not in projections
    assert ProjectionType.VALUE not in projections


@pytest.mark.asyncio
async def test_worker_executes_supported_surfaces_and_completes_restatement(monkeypatch):
    from services.profile.aggregator import Profile360Aggregator
    from services.projections.projection_restatement_orchestrator import Account360ProjectionComposer

    calls: list[tuple[str, str]] = []
    original_summary = Profile360Aggregator.summary

    async def observed_summary(self, entity_id: str, tenant_id: str):
        calls.append((tenant_id, entity_id))
        return await original_summary(self, entity_id, tenant_id)

    monkeypatch.setattr(Profile360Aggregator, "summary", observed_summary)

    async def compose_account(self, tenant_id, affected_entity_ids):
        assert tenant_id == TENANT
        return {}, {
            "status": "recomposed",
            "mode": "canonical_read",
            "authority": "account_organization+account_lifecycle",
            "person_relationship_count": 1,
        }

    monkeypatch.setattr(Account360ProjectionComposer, "compose", compose_account)
    decision = _decision()
    queued = await ProjectionRestatementOrchestrator().queue_restatement(decision)
    register_projection_restatement_handler()

    assert await JobWorker(job_types=[PROJECTION_RESTATEMENT_JOB_TYPE]).run_once()

    platform_job = await get_jobs_service().get_job(TENANT, queued.id)
    assert platform_job["status"] == "succeeded"
    assert calls == [
        (TENANT, "profile_survivor"),
        (TENANT, "profile_consumed"),
    ]
    payload = platform_job["payload"]["restatement"]
    assert payload["projection_status"][ProjectionType.PROFILE_360.value] == "completed"
    assert payload["projection_status"][ProjectionType.JOURNEY.value] == "completed"
    assert payload["projection_status"][ProjectionType.COMMUNICATIONS_360.value] == "completed"
    assert payload["projection_status"][ProjectionType.SIGNALS.value] == "completed"
    assert payload["projection_status"][ProjectionType.ACCOUNT_360.value] == "completed"
    assert payload["projection_evidence"][ProjectionType.ACCOUNT_360.value]["person_relationship_count"] == 1
    assert payload["projection_status"][ProjectionType.CAMPAIGN_360.value] == "completed"
    assert payload["projection_status"][ProjectionType.VALUE.value] == "completed"
    assert payload["status"] == "completed"
    assert payload["error"] is None

    # A fresh orchestrator reads the durable record and reports completion.
    status = await ProjectionRestatementOrchestrator().get_job_status(TENANT, queued.id)
    assert status is not None
    assert status.status == "completed"
    assert status.error is None


@pytest.mark.asyncio
async def test_worker_keeps_syndicates_membership_unchanged_on_unattributed_split(monkeypatch):
    from services.projections.projection_restatement_orchestrator import Account360ProjectionComposer

    async def compose_account(self, tenant_id, affected_entity_ids):
        return {}, {"status": "recomposed", "mode": "canonical_read"}

    monkeypatch.setattr(Account360ProjectionComposer, "compose", compose_account)
    decision = _decision()
    decision.decision_type = DecisionType.MANUAL_SPLIT
    queued = await ProjectionRestatementOrchestrator().queue_restatement(decision)
    register_projection_restatement_handler()

    assert await JobWorker(job_types=[PROJECTION_RESTATEMENT_JOB_TYPE]).run_once()

    platform_job = await get_jobs_service().get_job(TENANT, queued.id)
    restatement = platform_job["payload"]["restatement"]
    assert platform_job["status"] == "partially_succeeded"
    assert restatement["projection_status"][ProjectionType.SYNDICATES.value] == "unsupported"
    evidence = restatement["projection_evidence"][ProjectionType.SYNDICATES.value]
    assert evidence["reason_code"] == "syndicates_split_event_missing"
    assert evidence["membership_unchanged"] is True


@pytest.mark.asyncio
async def test_agent_and_execution_restatement_use_tenant_scoped_profile_composer(monkeypatch):
    from services.profile.agent import AgentProfile360Composer
    from services.projections.projection_restatement_orchestrator import Account360ProjectionComposer

    calls: list[tuple[str, str]] = []

    async def compose(self, entity_id: str, tenant_id: str, limit: int = 100):
        calls.append((tenant_id, entity_id))
        return {
            "tenant_id": tenant_id,
            "agent_id": entity_id,
            "task_history": {"execution_count": 3},
        }

    monkeypatch.setattr(AgentProfile360Composer, "compose", compose)

    async def compose_account(self, tenant_id, affected_entity_ids):
        assert tenant_id == TENANT
        return {}, {
            "status": "recomposed",
            "mode": "canonical_read",
            "authority": "account_organization+account_lifecycle",
        }

    monkeypatch.setattr(Account360ProjectionComposer, "compose", compose_account)
    queued = await ProjectionRestatementOrchestrator().queue_restatement(_decision())
    register_projection_restatement_handler()

    assert await JobWorker(job_types=[PROJECTION_RESTATEMENT_JOB_TYPE]).run_once()

    platform_job = await get_jobs_service().get_job(TENANT, queued.id)
    payload = platform_job["payload"]["restatement"]
    statuses = payload["projection_status"]
    assert statuses[ProjectionType.AGENT_360.value] == "completed"
    assert statuses[ProjectionType.EXECUTION_360.value] == "completed"
    # No explicitly opted-in Syndicates groups exist in this fixture. The
    # merge executor safely completes as a no-op over the canonical registry.
    assert statuses[ProjectionType.SYNDICATES.value] == "completed"
    assert statuses[ProjectionType.ACCOUNT_360.value] == "completed"
    assert payload["projection_evidence"][ProjectionType.ACCOUNT_360.value]["mode"] == "canonical_read"
    assert calls == [
        (TENANT, "profile_survivor"),
        (TENANT, "profile_consumed"),
        (TENANT, "profile_survivor"),
        (TENANT, "profile_consumed"),
    ]


@pytest.mark.asyncio
async def test_signal_restatement_refresh_is_tenant_scoped_and_retry_idempotent():
    from repositories.repos import BehaviorProfileRepository, SignalRepository
    from services.signals.recompute import recompute_signals_for_entity

    profiles = BehaviorProfileRepository()
    signals = SignalRepository()
    await profiles.insert("profile-signal", {
        "entity_id": "profile-signal",
        "tenant_id": TENANT,
        "churn_probability": 0.91,
        "days_since_last_visit": 75,
        "discount_usage_rate": 0.8,
        "referral_count": 0,
    })

    first = await recompute_signals_for_entity(
        "profile-signal", TENANT, behavior_repo=profiles, signal_repo=signals
    )
    rows_after_first = await signals.list_for_entity(
        "profile-signal", TENANT, include_stale=True
    )
    second = await recompute_signals_for_entity(
        "profile-signal", TENANT, behavior_repo=profiles, signal_repo=signals
    )
    rows_after_second = await signals.list_for_entity(
        "profile-signal", TENANT, include_stale=True
    )
    foreign = await recompute_signals_for_entity(
        "profile-signal", "other-tenant", behavior_repo=profiles, signal_repo=signals
    )

    assert first["signals_computed"] > 0
    assert second["signals_computed"] == first["signals_computed"]
    assert {row["signal_id"] for row in rows_after_first} == {
        row["signal_id"] for row in rows_after_second
    }
    assert all(row["tenant_id"] == TENANT for row in rows_after_second)
    assert foreign["signals_computed"] == 0

    await signals.upsert_signal({
        "signal_id": "manually-authored-signal",
        "entity_id": "profile-signal",
        "tenant_id": TENANT,
        "signal_type": "manual_review",
    })
    await profiles.insert("profile-signal", {
        "entity_id": "profile-signal",
        "tenant_id": TENANT,
        "churn_probability": 0.0,
    })
    await recompute_signals_for_entity(
        "profile-signal", TENANT, behavior_repo=profiles, signal_repo=signals
    )
    final_rows = await signals.list_for_entity(
        "profile-signal", TENANT, include_stale=True
    )
    assert [row["signal_id"] for row in final_rows] == ["manually-authored-signal"]


@pytest.mark.asyncio
async def test_campaign_restatement_recomputes_tenant_campaign_and_gold(monkeypatch):
    from datetime import date

    from services.measurement.engine import gold_materializer
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository
    from services.projections.projection_restatement_orchestrator import (
        _recompute_campaign_360,
    )

    touchpoints = TouchpointRepository()
    conversions = ConversionRepository()
    await touchpoints.upsert({
        "tenant_id": TENANT,
        "profile_id": "profile_campaign",
        "campaign_id": "campaign-42",
        "occurred_at": "2026-09-14T12:00:00+00:00",
        "source_event_id": "evt-campaign-restatement",
    })
    await conversions.upsert({
        "tenant_id": TENANT,
        "conversion_id": "conversion-campaign-restatement",
        "profile_id": "profile_campaign",
        "campaign_id": "campaign-42",
        "occurred_at": "2026-09-14T13:00:00+00:00",
        "attribution_eligible": True,
        "deduplication_key": "dedupe-campaign-restatement",
    })

    materialized: list[tuple[str, date, str | None]] = []

    async def materialize(tenant_id, target_date, *, restatement_reason=None):
        materialized.append((tenant_id, target_date, restatement_reason))
        return 2

    monkeypatch.setattr(
        gold_materializer, "materialize_campaign_performance_daily", materialize
    )
    result = await _recompute_campaign_360(
        TENANT, ["profile_campaign"], "restatement-campaign-key"
    )

    assert result == {"campaigns_recomputed": 1, "gold_rows_written": 2}
    assert materialized == [(
        TENANT, date(2026, 9, 14), "identity_restatement:restatement-campaign-key"
    )]


@pytest.mark.asyncio
async def test_value_restatement_persists_current_entity_rollups_idempotently():
    from repositories.repos import TransferRepository
    from services.projections.projection_restatement_orchestrator import (
        _recompute_value_for_entity,
    )
    from services.value.repositories import ValueRollupSnapshotRepository

    transfers = TransferRepository()
    await transfers.insert("value-restatement-transfer", {
        "transfer_id": "value-restatement-transfer",
        "tenant_id": TENANT,
        "from_entity_id": "counterparty",
        "to_entity_id": "profile_value",
        "asset_id": "fiat:USD",
        "currency": "USD",
        "amount": "125.50",
        "value_usd": "125.50",
    })
    await transfers.insert("value-restatement-outflow", {
        "transfer_id": "value-restatement-outflow",
        "tenant_id": TENANT,
        "from_entity_id": "profile_value",
        "to_entity_id": "counterparty",
        "asset_id": "fiat:USD",
        "currency": "USD",
        "amount": "25.50",
        "value_usd": "25.50",
    })

    first = await _recompute_value_for_entity(
        TENANT, "profile_value", "restatement-value-key"
    )
    rows_after_first = await ValueRollupSnapshotRepository().list_for_tenant(TENANT)
    second = await _recompute_value_for_entity(
        TENANT, "profile_value", "restatement-value-key"
    )
    rows_after_second = await ValueRollupSnapshotRepository().list_for_tenant(TENANT)
    snapshots = {
        row["metric"]: row for row in rows_after_second
        if row.get("data", {}).get("entity_id") == "profile_value"
    }

    assert first == second == 3
    assert len(rows_after_first) == len(rows_after_second) == 3
    assert snapshots["identity_inflow"]["total_usd"] == "125.50"
    assert snapshots["identity_outflow"]["total_usd"] == "25.50"
    assert snapshots["identity_net_flow"]["total_usd"] == "100.00"
    assert all(row["tenant_id"] == TENANT for row in snapshots.values())
    assert all(
        row["data"]["restatement_key"] == "restatement-value-key"
        for row in snapshots.values()
    )


@pytest.mark.asyncio
async def test_campaign_materializer_unavailable_is_retryable_failure(monkeypatch):
    from services.projections import projection_restatement_orchestrator as module

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("materializer unavailable")

    monkeypatch.setattr(module, "_recompute_campaign_360", unavailable)
    queued = await ProjectionRestatementOrchestrator().queue_restatement(_decision())
    register_projection_restatement_handler()

    assert await JobWorker(job_types=[PROJECTION_RESTATEMENT_JOB_TYPE]).run_once()

    row = await get_jobs_service().get_job(TENANT, queued.id)
    restatement = row["payload"]["restatement"]
    assert row["status"] == "retrying"
    assert restatement["projection_status"][ProjectionType.CAMPAIGN_360.value] == "retryable_failure"
    assert restatement["status"] == "retryable_failure"
    assert "campaign_360: RuntimeError" in restatement["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entity_ids", "expected_job_decision", "revision_available"),
    [
        (["resolver_survivor", "resolver_consumed"], DecisionType.AUTO_MERGE, True),
        (["resolver_linked"], DecisionType.AUTO_RESOLVE, True),
        (["resolver_unversioned", "resolver_unversioned_source"], DecisionType.AUTO_MERGE, False),
    ],
)
async def test_real_resolver_merge_and_link_enqueue_from_persisted_revision(
    monkeypatch, entity_ids, expected_job_decision, revision_available
):
    from services.identity.models import ConfidenceTier, MergeDecision

    tenant = f"{TENANT}_{expected_job_decision.value}"
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()

    class Producer:
        async def publish(self, _event):
            return None

    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
        producer=Producer(),
    )
    if not revision_available:
        async def no_revision(_tenant_id, _entity_id):
            return None, None

        monkeypatch.setattr(resolver, "_advance_resolution_revision", no_revision)
    for entity_id in entity_ids:
        await repo.create_subject(tenant, entity_id)

    async def find_subjects_by_alias(_tenant_id, _signal_type, _signal_hash):
        return list(entity_ids)

    monkeypatch.setattr(repo, "find_subjects_by_alias", find_subjects_by_alias)
    merge_decision = (
        MergeDecision.MERGE
        if expected_job_decision is DecisionType.AUTO_MERGE
        else MergeDecision.LINK
    )
    target = entity_ids[0]

    def evaluate(_context):
        return MergePolicyResult(
            decision=merge_decision,
            confidence=0.99,
            confidence_tier=ConfidenceTier.DETERMINISTIC,
            reason_codes=["test_deterministic_match"],
            merge_target_entity_id=target,
        )

    monkeypatch.setattr("services.identity.resolver.evaluate", evaluate)
    decision = await resolver.resolve_event(
        {"event_id": f"evt_{expected_job_decision.value}", "user_id": "resolved-user"},
        tenant,
    )

    assert decision.decision is merge_decision
    audit = await repo.get_entity_audit(tenant, decision.canonical_entity_id, limit=5)
    persisted_decision = next(item for item in audit if item["id"] == decision.audit_id)
    if not revision_available:
        assert decision.restatement_status == "non_queueable"
        assert decision.restatement_error == "persisted resolution revision is unavailable"
        assert decision.restatement_job_id is None
        assert persisted_decision["resolution_revision_after"] is None
        assert await get_jobs_service().list_jobs(
            tenant, job_type=PROJECTION_RESTATEMENT_JOB_TYPE
        ) == []
        return

    assert decision.restatement_status == "queued"
    assert decision.restatement_job_id
    assert decision.resolution_revision_before is None
    assert decision.resolution_revision_after == 1
    assert persisted_decision["resolution_revision_before"] is None
    assert persisted_decision["resolution_revision_after"] == 1
    platform_job = await get_jobs_service().get_job(tenant, decision.restatement_job_id)
    assert platform_job is not None
    assert platform_job["job_type"] == PROJECTION_RESTATEMENT_JOB_TYPE
    restatement = platform_job["payload"]["restatement"]
    assert restatement["trigger_decision_id"] == decision.audit_id
    assert restatement["graph_version_after"] == ""
    assert restatement["resolution_revision_before"] is None
    assert restatement["resolution_revision_after"] == 1
    assert restatement["affected_canonical_entity_ids"] == entity_ids
