"""Runtime OFF gates for the identity continuity feature flags."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from config.settings import settings
from services.resolution.consumer import ResolutionEventConsumer
from shared.events.events import Event, Topic


def _request_with_tenant():
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [], "state": {}})

    class Tenant:
        tenant_id = "tenant-flags"

        def require_permission(self, _permission):
            return None

    request.state.tenant = Tenant()
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolution_enabled,late_binding_enabled",
    [(False, True), (True, False)],
)
async def test_resolution_consumer_obeys_identity_and_sdk_late_binding_off(
    monkeypatch, resolution_enabled, late_binding_enabled,
):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=resolution_enabled,
        sdk_late_binding_enabled=late_binding_enabled,
    ))
    engine_calls = []
    publish_calls = []

    async def resolve_event(tenant_id, payload):
        engine_calls.append((tenant_id, payload))
        return None

    async def publish(event):
        publish_calls.append(event)

    consumer = ResolutionEventConsumer(
        engine=SimpleNamespace(resolve_event=resolve_event),
        producer=SimpleNamespace(publish=publish),
    )
    await consumer.on_event_validated(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-a",
        payload={"event_type": "identify", "user_id": "user-a"},
    ))

    assert engine_calls == []
    assert publish_calls == []


@pytest.mark.asyncio
async def test_connector_backfill_flag_does_not_disable_sdk_event_resolution(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        connector_backfill_enabled=False,
        anonymous_to_known_binding_enabled=True,
    ))
    engine_calls = []

    async def resolve_event(tenant_id, payload):
        engine_calls.append((tenant_id, payload))
        return None

    async def publish(_event):
        return None

    consumer = ResolutionEventConsumer(
        engine=SimpleNamespace(resolve_event=resolve_event),
        producer=SimpleNamespace(publish=publish),
    )
    await consumer.on_event_validated(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-a",
        payload={"event_type": "identify", "user_id": "user-a"},
    ))

    assert len(engine_calls) == 1


@pytest.mark.asyncio
async def test_anonymous_binding_flag_blocks_anonymous_to_known_sdk_event(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=False,
    ))
    engine_calls = []

    async def resolve_event(tenant_id, payload):
        engine_calls.append((tenant_id, payload))
        return None

    async def publish(_event):
        return None

    consumer = ResolutionEventConsumer(
        engine=SimpleNamespace(resolve_event=resolve_event),
        producer=SimpleNamespace(publish=publish),
    )
    await consumer.on_event_validated(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-a",
        payload={"event_type": "identify", "user_id": "user-a", "anonymous_id": "anon-a"},
    ))

    assert engine_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_explainability_gate_uses_nested_setting(monkeypatch, enabled):
    from shared.common.common import NotFoundError
    from services.identity import routes

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, explainability_enabled=enabled
    ))
    calls = []

    class Explainability:
        async def get_profile_identity_explanation(self, *, profile_id, tenant_id):
            calls.append((profile_id, tenant_id))
            return {
                "canonical_entity_id": profile_id,
                "confidence": 1.0,
                "confidence_band": "very_high",
                "graph_version": "g1",
                "resolution_decision_summary": "linked",
            }

    if enabled:
        await routes.get_profile_identity_explanation(
            "profile-a", _request_with_tenant(), Explainability()
        )
        assert calls == [("profile-a", "tenant-flags")]
    else:
        with pytest.raises(NotFoundError):
            await routes.get_profile_identity_explanation(
                "profile-a", _request_with_tenant(), Explainability()
            )
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_activation_dashboard_gate_uses_nested_setting(monkeypatch, enabled):
    from shared.common.common import NotFoundError
    from services.identity import routes

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, activation_dashboard_enabled=enabled
    ))
    calls = []

    class AdminService:
        async def activation_status(self, tenant_id):
            calls.append(tenant_id)
            return {
                "tenant_id": tenant_id,
                "historical_data_status": "ready",
                "sdk_status": "ready",
                "projection_restatement_status": "queued",
                "computed_at": "2026-09-27T00:00:00+00:00",
            }

    if enabled:
        await routes.admin_activation_status(_request_with_tenant(), AdminService())
        assert calls == ["tenant-flags"]
    else:
        with pytest.raises(NotFoundError):
            await routes.admin_activation_status(_request_with_tenant(), AdminService())
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_tenant_activation_route_derives_scope_from_authenticated_context(monkeypatch, enabled):
    from shared.common.common import NotFoundError
    from services.identity import routes

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, activation_dashboard_enabled=enabled
    ))
    calls = []

    class AdminService:
        async def activation_status(self, tenant_id):
            calls.append(tenant_id)
            return {
                "tenant_id": tenant_id,
                "historical_data_status": "ready",
                "sdk_status": "ready",
                "resolution_counts": {},
                "conflict_counts": {},
                "projection_restatement_counts": {},
                "pending_review_counts": {},
                "runtime_flags": {},
                "projection_restatement_status": "idle",
                "sdk_last_seen_at": None,
                "computed_at": "2026-09-27T00:00:00+00:00",
            }

    if enabled:
        await routes.tenant_activation_status(_request_with_tenant(), AdminService())
        assert calls == ["tenant-flags"]
    else:
        with pytest.raises(NotFoundError):
            await routes.tenant_activation_status(_request_with_tenant(), AdminService())
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_tenant_review_route_derives_scope_from_authenticated_context(monkeypatch, enabled):
    from shared.common.common import NotFoundError
    from services.identity import routes

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, manual_review_enabled=enabled
    ))
    calls = []

    class AdminService:
        async def review_queue(self, tenant_id, *, limit):
            calls.append((tenant_id, limit))
            return []

    if enabled:
        await routes.tenant_review_queue(_request_with_tenant(), limit=23, admin_service=AdminService())
        assert calls == [("tenant-flags", 23)]
    else:
        with pytest.raises(NotFoundError):
            await routes.tenant_review_queue(_request_with_tenant(), limit=23, admin_service=AdminService())
        assert calls == []


@pytest.mark.asyncio
async def test_manual_merge_and_split_runtime_gates_fail_closed(monkeypatch):
    from services.identity.audit import IdentityAuditWriter
    from services.identity.conflicts import IdentityConflictManager
    from services.identity.graph_writer import IdentityGraphWriter
    from services.identity.metrics import IdentityMetrics
    from services.identity.repository import IdentityResolutionRepository
    from services.identity.resolver import IdentityResolutionService

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        manual_review_enabled=False,
        split_enabled=False,
        manual_split_enabled=False,
    ))
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )

    merge = await resolver.operator_merge(
        "tenant-flags", "primary", "secondary", "operator"
    )
    split = await resolver.operator_split(
        "tenant-flags", "primary", "operator"
    )
    fragment_split = await resolver.fragment_split(
        "tenant-flags", "primary", {"alias_ids": ["alias"]},
        "create_new_entity", "operator",
    )

    assert merge.reason_codes == ["manual_merge_disabled"]
    assert split["allowed"] is False
    assert split["reason_codes"] == ["manual_split_disabled"]
    assert fragment_split["allowed"] is False
    assert fragment_split["reason_codes"] == ["manual_split_disabled"]


@pytest.mark.asyncio
async def test_auto_merge_flag_downgrades_policy_merge_before_mutation(monkeypatch):
    from services.identity.audit import IdentityAuditWriter
    from services.identity.conflicts import IdentityConflictManager
    from services.identity.graph_writer import IdentityGraphWriter
    from services.identity.merge_policy import MergePolicyResult
    from services.identity.metrics import IdentityMetrics
    from services.identity.models import ConfidenceTier, MergeDecision
    from services.identity.repository import IdentityResolutionRepository
    from services.identity.resolver import IdentityResolutionService

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        auto_merge_enabled=False,
        manual_review_enabled=True,
    ))
    tenant_id = "tenant-auto-merge-disabled"
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    await repo.create_subject(tenant_id, "survivor")
    await repo.create_subject(tenant_id, "consumed")

    async def find_candidates(_tenant_id, _signal_type, _signal_hash):
        return ["survivor", "consumed"]

    monkeypatch.setattr(repo, "find_subjects_by_alias", find_candidates)
    monkeypatch.setattr(
        "services.identity.resolver.evaluate",
        lambda _context: MergePolicyResult(
            decision=MergeDecision.MERGE,
            confidence=1.0,
            confidence_tier=ConfidenceTier.DETERMINISTIC,
            reason_codes=["test_match"],
            merge_target_entity_id="survivor",
        ),
    )

    decision = await resolver.resolve_event(
        {"event_id": "disabled-merge-event", "user_id": "user-123"}, tenant_id
    )

    assert decision.decision is MergeDecision.CANDIDATE
    assert "auto_merge_disabled" in decision.reason_codes
    consumed = await repo.get_subject_by_canonical_entity_id(tenant_id, "consumed")
    assert consumed["status"] != "merged"
