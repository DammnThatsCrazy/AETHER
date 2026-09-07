"""WS-3 intent picker + connect-plan derivation (service-level contracts).

Drives :class:`ActivationPlanner` directly (like the sibling unit suites drive
``ActivationService``). Covers:

* the intent picker projection (all ActivationIntent tokens + every
  experience category, never a hand-synced provider list);
* durable intent selection (canonical order, replace-on-reselect, unknown-token
  rejection, resume via the status view);
* the honest ``needs_selection`` plan before any intent is chosen; and
* connect-step derivation that reads REAL tenant connector rows — every
  connection state maps to exactly one honest next action (or an attention
  state with no fabricated forward step).

Rows are seeded into the shared ``integration_connector_configs`` store exactly
as ``connector_service`` persists them, so the plan projection is exercised over
the same facts the Settings surface reads.
"""
from __future__ import annotations

import pytest

from services.activation.models import ActivationState
from services.activation.planner import (
    ActivationPlanner,
    CONFIGURE_CREDENTIAL,
    CREATE_INTEGRATION,
    ENABLE_CONNECTION,
    FIRST_SYNC,
)
from services.activation.service import ActivationService
from services.integrations.connectors.base import ConnectorConfig
from services.integrations.connectors.service import connector_service
from shared.common.common import BadRequestError
from shared.integration_contracts.experience import ExperienceCategory
from shared.integration_contracts.lifecycle import ConnectionState

INTENT_TOKENS = [
    "grow_revenue",
    "run_advertising",
    "know_customers",
    "engage_customers",
    "understand_behavior",
    "grow_community",
    "support_customers",
    "streamline_work",
]


def _key(tenant_id: str, connector_type: str) -> str:
    return f"{tenant_id}:{connector_type}"


async def _seed_connector(
    tenant_id: str,
    connector_type: str,
    *,
    enabled: bool,
    secret_configured: bool,
    sync_status: str = "never_synced",
) -> None:
    """Persist a connector row with the exact facts the plan projects on.

    Mirrors what ``connector_service.configure``/``sync`` write (ConnectorConfig
    model) without requiring a provider round-trip, keeping each state branch
    deterministic.
    """
    record = ConnectorConfig(
        tenant_id=tenant_id,
        connector_type=connector_type,
        name=connector_type,
        enabled=enabled,
        secret_configured=secret_configured,
        sync_status=sync_status,  # type: ignore[arg-type]
    )
    await connector_service.repo.insert(
        _key(tenant_id, connector_type), record.model_dump()
    )


# ── Intent picker (catalog projection) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_picker_covers_eight_goals_and_all_categories() -> None:
    planner = ActivationPlanner()
    catalog = await planner.intent_catalog_view()
    intents = catalog["intents"]
    assert [i["token"] for i in intents] == INTENT_TOKENS
    assert {i["token"] for i in intents} == set(INTENT_TOKENS)
    # Every intent carries a label, description and ordered recommendations.
    for intent in intents:
        assert intent["label"] and intent["description"]
        assert intent["recommended_categories"], "each goal maps to >=1 experience"
    # All eight experience categories are surfaced to the picker.
    categories = catalog["experience_categories"]
    assert {c["token"] for c in categories} == {
        c.value for c in ExperienceCategory
    }
    assert all(c["label"] for c in categories)


# ── Durable intent selection ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_intents_persists_in_canonical_order() -> None:
    planner = ActivationPlanner()
    saved = await planner.select_intents(
        "t-intents", ["run_advertising", "grow_revenue", "grow_revenue"]
    )
    # Stored order is canonical INTENT_ORDER — never call order — and deduped.
    assert saved["intents"] == ["grow_revenue", "run_advertising"]
    assert saved["intents_updated_at"]


@pytest.mark.asyncio
async def test_select_intents_is_replace_not_accumulate() -> None:
    planner = ActivationPlanner()
    await planner.select_intents("t-intents", ["grow_revenue", "run_advertising"])
    reselect = await planner.select_intents("t-intents", ["know_customers"])
    assert reselect["intents"] == ["know_customers"]


@pytest.mark.asyncio
async def test_select_intents_unknown_token_is_client_error() -> None:
    with pytest.raises(BadRequestError):
        await ActivationPlanner().select_intents(
            "t-intents", ["grow_revenue", "definitely_not_a_goal"]
        )


@pytest.mark.asyncio
async def test_status_view_exposes_selected_intents() -> None:
    planner = ActivationPlanner()
    await planner.select_intents("t-intents", ["grow_revenue"])
    status = await ActivationService().get_status("t-intents")
    assert status["intents"] == ["grow_revenue"]
    assert status["intents_updated_at"]
    # Intent selection is orthogonal to the SDK machine: the record stays put.
    assert status["state"] in {
        ActivationState.not_started.value,
        ActivationState.account_verified.value,
    }


# ── Plan gating ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_plan_returns_needs_selection_before_intents() -> None:
    plan = await ActivationPlanner().build_plan("t-never")
    assert plan["needs_selection"] is True
    assert plan["selected_intents"] == []
    assert plan["categories"] == []


@pytest.mark.asyncio
async def test_build_plan_empty_tenant_shows_available_create_step() -> None:
    planner = ActivationPlanner()
    await planner.select_intents("t-empty", ["grow_revenue"])
    plan = await planner.build_plan("t-empty")
    assert plan["needs_selection"] is False
    commerce = next(
        c
        for c in plan["categories"]
        if c["experience_category"] == ExperienceCategory.COMMERCE_REVENUE.value
    )
    assert commerce["recommended_by_intents"] == ["grow_revenue"]
    assert commerce["connected_count"] == 0
    assert commerce["integrations"], "commerce has a connectable surface"
    # No row exists yet -> the only honest next step is create_tenant_integration.
    for integration in commerce["integrations"]:
        assert integration["connectable"] is True
        assert integration["connection_state"] == ConnectionState.AVAILABLE.value
        assert integration["next_action"] == CREATE_INTEGRATION
        assert integration["can_act"] is True
        assert integration["record"] is None


# ── Plan derivation from real tenant rows ────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_derives_credential_waiting_configure_step() -> None:
    """A row with no credential maps to configure_credential — never a fake sync."""
    tenant = "t-derive-cw"
    await _seed_connector(tenant, "shopify", enabled=True, secret_configured=False)
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    entry = _plan_integration(await planner.build_plan(tenant), "shopify")
    assert entry["connection_state"] == ConnectionState.CREDENTIAL_WAITING.value
    assert entry["next_action"] == CONFIGURE_CREDENTIAL
    assert entry["can_act"] is True


@pytest.mark.asyncio
async def test_plan_derives_disabled_enable_step() -> None:
    tenant = "t-derive-dis"
    await _seed_connector(tenant, "stripe", enabled=False, secret_configured=True)
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    entry = _plan_integration(await planner.build_plan(tenant), "stripe")
    assert entry["connection_state"] == ConnectionState.DISABLED.value
    assert entry["next_action"] == ENABLE_CONNECTION
    assert entry["can_act"] is True


@pytest.mark.asyncio
async def test_plan_derives_initial_sync_pending_first_sync() -> None:
    """Enabled + credential configured + never synced -> first_sync."""
    tenant = "t-derive-sync"
    await _seed_connector(tenant, "stripe", enabled=True, secret_configured=True)
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    entry = _plan_integration(await planner.build_plan(tenant), "stripe")
    assert entry["connection_state"] == ConnectionState.INITIAL_SYNC_PENDING.value
    assert entry["next_action"] == FIRST_SYNC
    assert entry["can_act"] is True


@pytest.mark.asyncio
async def test_plan_derives_connected_only_from_healthy_sync() -> None:
    tenant = "t-derive-ok"
    await _seed_connector(
        tenant, "stripe", enabled=True, secret_configured=True, sync_status="healthy"
    )
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    entry = _plan_integration(await planner.build_plan(tenant), "stripe")
    assert entry["connection_state"] == ConnectionState.CONNECTED.value
    assert entry["next_action"] is None
    assert entry["can_act"] is False


@pytest.mark.asyncio
async def test_plan_connected_count_reflects_only_real_healthy_rows() -> None:
    tenant = "t-derive-count"
    await _seed_connector(
        tenant, "stripe", enabled=True, secret_configured=True, sync_status="healthy"
    )
    await _seed_connector(tenant, "shopify", enabled=True, secret_configured=True)
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    plan = await planner.build_plan(tenant)
    commerce = next(
        c
        for c in plan["categories"]
        if c["experience_category"] == ExperienceCategory.COMMERCE_REVENUE.value
    )
    assert commerce["connected_count"] == 1


@pytest.mark.asyncio
async def test_plan_attention_states_have_no_fabricated_next_step() -> None:
    """A failed/degraded sync is surfaced honestly with no forward action."""
    for sync_status, expected_state in (
        ("failed", ConnectionState.SYNC_FAILED.value),
        ("degraded", ConnectionState.DEGRADED.value),
        ("syncing", ConnectionState.INITIAL_SYNC_RUNNING.value),
    ):
        tenant = f"t-attn-{sync_status}"
        await _seed_connector(
            tenant, "stripe", enabled=True, secret_configured=True, sync_status=sync_status
        )
        planner = ActivationPlanner()
        await planner.select_intents(tenant, ["grow_revenue"])
        entry = _plan_integration(await planner.build_plan(tenant), "stripe")
        assert entry["connection_state"] == expected_state
        assert entry["next_action"] is None
        assert entry["can_act"] is False


@pytest.mark.asyncio
async def test_plan_record_carries_honest_facts() -> None:
    tenant = "t-record"
    await _seed_connector(
        tenant, "shopify", enabled=True, secret_configured=True, sync_status="failed"
    )
    planner = ActivationPlanner()
    await planner.select_intents(tenant, ["grow_revenue"])
    entry = _plan_integration(await planner.build_plan(tenant), "shopify")
    assert entry["record"]["sync_status"] == "failed"
    assert entry["record"]["secret_configured"] is True
    assert entry["record"]["enabled"] is True


def _plan_integration(plan: dict, family: str) -> dict:
    """Find one integration entry across the plan's category blocks."""
    for block in plan["categories"]:
        for integration in block["integrations"]:
            if integration["family"] == family:
                return integration
    raise AssertionError(f"{family} not present in plan: {plan['categories']}")
