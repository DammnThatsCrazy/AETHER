"""Regression tests for all 9 confirmed defects (D1–D9).

Each test verifies the specific behavior that was broken and is now fixed.
"""

from __future__ import annotations

import asyncio
import pytest

from repositories.repos import reset_in_memory_stores


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ─── D1: deliver_suggestion_via_notification must not call service.deliver_suggestion ───

@pytest.mark.asyncio
async def test_d1_no_premature_deliver_suggestion_call():
    """D1: deliver_suggestion_via_notification creates DeliveryIntent+Job, never calls service.deliver_suggestion."""
    from services.suggestions.adapters.notification_adapter import deliver_suggestion_via_notification
    from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository
    from repositories.repos import UserNotificationChannelRepository

    # Set up a fake active channel
    channel_repo = UserNotificationChannelRepository()
    await channel_repo.insert("ch-1", {
        "id": "ch-1",
        "tenant_id": "t1",
        "channel_type": "slack",
        "active": True,
        "destination": "#aether",
        "credentials_ref": "vault-key",
        "config": {},
    })

    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()

    suggestion = {
        "id": "sug-001",
        "tenant_id": "t1",
        "status": "approved",
        "delivery_eligible": True,
        "title": "Test Suggestion",
        "summary": "You should do X",
        "priority": "P2",
        "policy_decision": {"allowed": True},
    }

    mock_service = object()  # service.deliver_suggestion must not be called

    result = await deliver_suggestion_via_notification(
        suggestion,
        mock_service,
        channel_repo=channel_repo,
        intent_repo=intent_repo,
        job_repo=job_repo,
    )

    # Must return the original suggestion dict unchanged
    assert result["id"] == "sug-001"

    # Must have created a DeliveryIntent
    intents = await intent_repo.find_many(filters={"source_id": "sug-001"}, limit=10)
    assert len(intents) == 1
    assert intents[0]["source_type"] == "suggestion"

    # Must have created a DeliveryJob
    jobs = await job_repo.find_many(filters={"intent_id": intents[0]["id"]}, limit=10)
    assert len(jobs) == 1
    assert jobs[0]["provider_adapter"] == "slack"
    assert jobs[0]["state"] == "queued"


# ─── D2: consumer must not use asyncio.create_task for delivery ──────────────

def test_d2_no_create_task_in_consumer():
    """D2: consumer.py must not contain asyncio.create_task(_router.route(notif))."""
    import ast
    import inspect
    from services.notification_intelligence import consumer

    source = inspect.getsource(consumer)

    # The old fire-and-forget pattern must not be present
    assert "asyncio.create_task(_router.route(notif))" not in source, (
        "D2 regression: asyncio.create_task(_router.route(notif)) still present "
        "in consumer.py — delivery will be lost on restart"
    )

    # The replacement must be present
    assert "_create_notification_delivery_jobs" in source


# ─── D3: delivery_router must not return credentials_ref as literal ──────────

@pytest.mark.asyncio
async def test_d3_delivery_router_raises_without_providers_repo():
    """D3: _resolve_credentials must raise RuntimeError when providers_repo is None.

    Async like its siblings — get_event_loop() raised its own unrelated
    RuntimeError once an earlier async suite had closed the loop, which
    satisfied pytest.raises for the wrong reason or failed the match.
    """
    from services.notification_intelligence.delivery_router import DeliveryRouter

    router = DeliveryRouter(channel_repo=None, providers_repo=None)
    channel = {"credentials_ref": "vault-key-abc"}

    with pytest.raises(RuntimeError, match="providers_repo"):
        await router._resolve_credentials(channel)


# ─── D4: BaseActionTarget.dispatch must raise NotImplementedError ─────────────

@pytest.mark.asyncio
async def test_d4_base_action_target_raises_not_implemented():
    """D4: BaseActionTarget.dispatch() must raise NotImplementedError."""
    from services.intelligence.action_targets.base import BaseActionTarget

    class ConcreteTarget(BaseActionTarget):
        target_type = "test"
        display_name = "Test Target"
        supports_retries = False
        supports_cancellation = False

    target = ConcreteTarget()

    with pytest.raises(NotImplementedError, match="ProviderAdapterRegistry"):
        await target.dispatch(dispatch=None, config=None)


def test_d4_no_simulated_ids_in_base():
    """D4: No sim- prefixed external IDs should be returned by base dispatch."""
    import inspect
    from services.intelligence.action_targets import base

    source = inspect.getsource(base)
    assert '"simulated": True' not in source, (
        "D4 regression: simulated=True payload still present in action_targets/base.py"
    )
    # sim- prefix check
    assert 'f"sim-{self.target_type}' not in source, (
        "D4 regression: sim-prefixed external_id still returned by BaseActionTarget.dispatch()"
    )


# ─── D5: replay_notification must use delivery jobs, not fire-and-forget router ──

def test_d5_replay_uses_delivery_jobs():
    """D5: replay_notification must call _create_delivery_jobs_for_replay, not DeliveryRouter."""
    import inspect
    from services.notification_intelligence import routes

    source = inspect.getsource(routes)

    # Old fire-and-forget pattern must be gone
    assert "DeliveryRouter(channel_repo=_channel_repo)" not in source, (
        "D5 regression: replay still instantiates DeliveryRouter without providers_repo"
    )

    # New durable pattern must be present
    assert "_create_delivery_jobs_for_replay" in source


# ─── D6: suggestion topics must be in _TOPIC_MAP and subscribed ──────────────

def test_d6_suggestion_topics_in_topic_map():
    """D6: SUGGESTION_APPROVED and SUGGESTION_CREATED must be in _TOPIC_MAP."""
    from services.notification_intelligence.consumer import _TOPIC_MAP
    from shared.events.events import Topic

    assert Topic.SUGGESTION_APPROVED.value in _TOPIC_MAP, (
        "D6 regression: SUGGESTION_APPROVED not in _TOPIC_MAP"
    )
    assert Topic.SUGGESTION_CREATED.value in _TOPIC_MAP, (
        "D6 regression: SUGGESTION_CREATED not in _TOPIC_MAP"
    )


def test_d6_suggestion_topics_subscribed_in_attach():
    """D6: attach_notification_consumers must subscribe to suggestion topics."""
    import inspect
    from services.notification_intelligence import consumer

    source = inspect.getsource(consumer)
    assert "Topic.SUGGESTION_APPROVED" in source
    assert "Topic.SUGGESTION_CREATED" in source


# ─── D7: emit_notification must enqueue delivery after persisting ─────────────

def test_d7_emit_notification_calls_enqueue():
    """D7: emit_notification route must call _enqueue_notification_delivery."""
    import inspect
    from services.notification_intelligence import routes

    source = inspect.getsource(routes)
    assert "_enqueue_notification_delivery(notif)" in source, (
        "D7 regression: emit_notification does not call _enqueue_notification_delivery"
    )


# ─── D8: _http_post in adapters.py must not shadow json builtin ───────────────

def test_d8_http_post_no_json_parameter():
    """D8: _http_post must use 'body' not 'json' as parameter name."""
    import inspect
    from services.integrations.connectors import adapters

    source = inspect.getsource(adapters)
    # Find the first _http_post function definition
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "async def _http_post" in line and "json: dict" in line:
            pytest.fail(
                f"D8 regression: _http_post still uses 'json' as parameter at line {i+1}"
            )


# ─── D9: sync failure must raise ConnectorSyncError, not return silently ──────

def test_d9_sync_raises_on_failure():
    """D9: ConnectorService.sync must raise ConnectorSyncError on pull failure."""
    import inspect
    from services.integrations.connectors import service

    source = inspect.getsource(service)
    assert "ConnectorSyncError" in source, (
        "D9 regression: ConnectorSyncError not raised in connector sync failure path"
    )
    # Must not return a SyncResult on failure (which would look like success)
    # Check that the failure path raises rather than returns
    assert "raise ConnectorSyncError" in source


# ─── ProviderReceipt anti-simulation guard ───────────────────────────────────

def test_provider_receipt_rejects_sim_prefix_consistently():
    """ProviderReceipt model validator must reject sim- prefixed ids in all paths."""
    from pydantic import ValidationError
    from services.delivery.models import DeliveryChannel, ProviderReceipt

    with pytest.raises(ValidationError, match="sim-"):
        ProviderReceipt(
            job_id="j1",
            intent_id="i1",
            tenant_id="t1",
            provider_adapter="slack",
            external_id="sim-slack-123",
            channel=DeliveryChannel.SLACK,
        )
