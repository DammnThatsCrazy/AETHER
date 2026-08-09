"""Payment-rail rollout-control lifecycle + readiness demotion + replay (2E).

Covers the observability-closure gaps that are pure/logic-testable in local
mode:

- Entitlement gate: the plan-tier gate blocks a tenant whose plan ranks below
  the configured minimum (403), and is a no-op when disabled.
- Rollout-control lifecycle gate: each default-OFF control (derived alert
  evaluator, canonical outbox, usage metering) runs only when its flag is on AND
  the capability lifecycle stage is at/above the control's minimum; an
  un-declared stage fails OPEN to the flag.
- Readiness demotion: failed signature verification / provider silence /
  credential-invalid → DEGRADED / CREDENTIAL_INVALID on the canonical capability
  readiness model — monotonic (never re-promotes), idempotent, audited.
- Replay operator endpoint: dead-lettered receipts flip back into the pipeline
  and are re-driven.

Nothing here needs live credentials. ``AETHER_ENV=local`` uses the shared
in-memory stores, reset per-test.
"""

from __future__ import annotations

import dataclasses
import os
import types
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import (  # noqa: E402
    _IN_MEMORY_STORES,
    reset_in_memory_stores as reset_typed_stores,
)
from shared.auth.auth import PlanTier  # noqa: E402
from shared.certification.readiness import CredentialReadiness  # noqa: E402
from shared.common.common import ForbiddenError  # noqa: E402
from shared.store import reset_in_memory_stores as reset_shared_stores  # noqa: E402

from services.capabilities.readiness_repo import CapabilityReadinessService  # noqa: E402
from services.integrations.providers.payment_rails import (  # noqa: E402
    ADAPTERS,
    readiness_demotion,
)
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    payload_hash,
)
from services.integrations.providers.payment_rails import lifecycle  # noqa: E402
from services.integrations.providers.payment_rails import entitlement_gate  # noqa: E402
from services.integrations.providers.payment_rails.alert_worker import (  # noqa: E402
    run_alert_eval_cycle,
)
from services.integrations.providers.payment_rails.entitlement_gate import (  # noqa: E402
    require_payment_rails_entitlement,
)
from services.integrations.providers.payment_rails.lifecycle import (  # noqa: E402
    PAYMENT_RAILS_CAPABILITY,
    ROLLOUT_CONTROLS,
    controls_for_readiness,
)
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    ReceiptState,
    ReceiptStage,
)
from services.integrations.providers.payment_rails.readiness_demotion import (  # noqa: E402
    DemotionThresholds,
    classify_demotion,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_typed_stores()
    reset_shared_stores()
    yield
    reset_typed_stores()
    reset_shared_stores()


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _svc() -> PaymentRailsService:
    return PaymentRailsService(repositories=PaymentRailsRepositories())


async def _seed_readiness(tenant_id: str, target: CredentialReadiness) -> None:
    await CapabilityReadinessService().seed(
        tenant_id, PAYMENT_RAILS_CAPABILITY,
        target=target, evidence={"plane": "payment_rails"}, reason="test", actor="test",
    )


async def _snapshot_state(tenant_id: str) -> str:
    snap = await CapabilityReadinessService().snapshot(tenant_id, PAYMENT_RAILS_CAPABILITY)
    return (snap or {}).get("state", "missing")


def _thresh(*, window: float = 3600, warn: float = 1, silence: float = 86400) -> DemotionThresholds:
    return DemotionThresholds(
        verification_failure_window_seconds=window,
        verification_failure_warn=warn,
        provider_silence_seconds=silence,
    )


# ── Entitlement gate ───────────────────────────────────────────────────────


class _FakeTenant:
    def __init__(self, tenant_id: str, tier, permission: str = "read"):
        self.tenant_id = tenant_id
        self.plan_tier = tier
        self._permission = permission

    def require_permission(self, permission: str) -> None:
        if permission != self._permission:
            raise ForbiddenError("permission denied")


class _FakeRequest:
    def __init__(self, tenant):
        self.state = types.SimpleNamespace(tenant=tenant)


async def test_entitlement_gate_disabled_is_pass_through(monkeypatch):
    monkeypatch.setattr(entitlement_gate, "entitlement_gate_enabled", lambda: False)
    req = _FakeRequest(_FakeTenant(_tenant(), PlanTier.P1_HOBBYIST))
    assert require_payment_rails_entitlement(req, "read") == req.state.tenant.tenant_id


async def test_entitlement_gate_blocks_below_min_plan(monkeypatch):
    tenant = _tenant()
    monkeypatch.setattr(entitlement_gate, "entitlement_gate_enabled", lambda: True)
    monkeypatch.setattr(entitlement_gate, "configured_min_plan_tier", lambda: PlanTier.P2_PROFESSIONAL)
    req = _FakeRequest(_FakeTenant(tenant, PlanTier.P1_HOBBYIST))
    with pytest.raises(ForbiddenError):
        require_payment_rails_entitlement(req, "read")


async def test_entitlement_gate_allows_at_or_above_min_plan(monkeypatch):
    tenant = _tenant()
    monkeypatch.setattr(entitlement_gate, "entitlement_gate_enabled", lambda: True)
    monkeypatch.setattr(entitlement_gate, "configured_min_plan_tier", lambda: PlanTier.P2_PROFESSIONAL)
    req = _FakeRequest(_FakeTenant(tenant, PlanTier.P3_GROWTH_INTELLIGENCE))
    assert require_payment_rails_entitlement(req, "read") == tenant


async def test_entitlement_gate_still_enforces_permission_first(monkeypatch):
    monkeypatch.setattr(entitlement_gate, "entitlement_gate_enabled", lambda: True)
    req = _FakeRequest(_FakeTenant(_tenant(), PlanTier.P4_PROTOCOL_MASTER, permission="admin"))
    with pytest.raises(ForbiddenError):
        require_payment_rails_entitlement(req, "read")


# ── Rollout-control lifecycle gate ─────────────────────────────────────────


async def test_controls_for_readiness_pure_mapping():
    on = controls_for_readiness(CredentialReadiness.SANDBOX_VALIDATED)
    assert on["derived_alert_evaluator"] is True
    assert on["canonical_outbox"] is True
    assert on["usage_metering"] is True
    off = controls_for_readiness(CredentialReadiness.SCAFFOLDED)
    assert off == {"derived_alert_evaluator": False, "canonical_outbox": False, "usage_metering": False}


async def test_rollout_control_permitted_flag_off_blocks():
    assert await lifecycle.rollout_control_permitted("derived_alert_evaluator", flag=False) is False


async def test_rollout_control_permitted_fails_open_when_stage_undeclared(monkeypatch):
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: None)
    assert await lifecycle.rollout_control_permitted("derived_alert_evaluator", flag=True) is True


async def test_rollout_control_permitted_blocks_below_minimum_stage(monkeypatch):
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.SCAFFOLDED)
    assert await lifecycle.rollout_control_permitted("derived_alert_evaluator", flag=True) is False


async def test_rollout_control_permitted_allows_at_or_above_minimum_stage(monkeypatch):
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.SANDBOX_VALIDATED)
    assert await lifecycle.rollout_control_permitted("usage_metering", flag=True) is True
    assert await lifecycle.rollout_control_permitted("canonical_outbox", flag=True) is True
    assert await lifecycle.rollout_control_permitted("derived_alert_evaluator", flag=True) is True


async def test_rollout_control_registry_minima():
    assert ROLLOUT_CONTROLS["derived_alert_evaluator"].min_readiness == CredentialReadiness.CREDENTIAL_WAITING
    assert ROLLOUT_CONTROLS["canonical_outbox"].min_readiness == CredentialReadiness.OFFLINE_VALIDATED
    assert ROLLOUT_CONTROLS["usage_metering"].min_readiness == CredentialReadiness.SANDBOX_VALIDATED


# ── Alert worker lifecycle gate ────────────────────────────────────────────


async def test_alert_eval_cycle_blocked_when_flag_off():
    report = await run_alert_eval_cycle()
    assert report.conditions == ()
    assert report.worst_severity == "ok"


async def test_alert_eval_cycle_blocked_when_stage_below_minimum(monkeypatch):
    monkeypatch.setattr(
        settings, "payment_rails", types.SimpleNamespace(alert_eval_enabled=True),
    )
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.SCAFFOLDED)
    report = await run_alert_eval_cycle()
    assert report.conditions == ()
    assert report.worst_severity == "ok"


# ── Outbox + metering consumption points are lifecycle-gated ──────────────


class _RecordingProducer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


def _moonpay_event(adapter, tenant, *, tx_id="mp-life-1"):
    data = {"id": tx_id, "status": "completed", "externalCustomerId": "u1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    return adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]


def _patch_control_flag(monkeypatch, **flags):
    monkeypatch.setattr(
        settings, "payment_rails", dataclasses.replace(settings.payment_rails, **flags),
    )


async def test_outbox_lifecycle_gate_blocks_below_minimum(monkeypatch):
    """Flag ON but capability stage below the outbox minimum → direct publish.

    The durable-outbox rollout control must not engage until the capability has
    reached the outbox's minimum lifecycle stage — even when an operator set the
    flag early. The emission path fails closed once a stage is declared.
    """
    reset_typed_stores()
    _patch_control_flag(monkeypatch, canonical_outbox_enabled=True)
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.SCAFFOLDED)
    svc = PaymentRailsService(repositories=PaymentRailsRepositories(), producer=_RecordingProducer())
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    assert svc.producer.events          # direct publish (outbox path did NOT engage)
    assert _IN_MEMORY_STORES.get("event_outbox") in (None, {})
    assert _IN_MEMORY_STORES.get("bronze_sdk_events") in (None, {})


async def test_outbox_lifecycle_gate_allows_at_or_above_minimum(monkeypatch):
    """Flag ON and capability stage at/above the outbox minimum → durable spine."""
    reset_typed_stores()
    _patch_control_flag(monkeypatch, canonical_outbox_enabled=True)
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.OFFLINE_VALIDATED)
    svc = PaymentRailsService(repositories=PaymentRailsRepositories(), producer=_RecordingProducer())
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    assert svc.producer.events == []    # no direct publish on the outbox path
    assert len(_IN_MEMORY_STORES.get("event_outbox") or {}) == 2
    assert len(_IN_MEMORY_STORES.get("bronze_sdk_events") or {}) == 2


async def test_metering_lifecycle_gate_blocks_below_minimum(monkeypatch):
    """Flag ON but capability stage below the metering minimum → nothing metered."""
    from services.billing.revops import UsageMeteringEventRepository

    reset_typed_stores()
    _patch_control_flag(monkeypatch, usage_metering_enabled=True)
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.OFFLINE_VALIDATED)
    svc = PaymentRailsService(repositories=PaymentRailsRepositories(), producer=_RecordingProducer())
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    assert svc.producer.events                      # observation still emitted
    meters = await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})
    assert meters == []                              # metering gate blocked the hook


async def test_metering_lifecycle_gate_allows_at_or_above_minimum(monkeypatch):
    """Flag ON and capability stage at/above the metering minimum → metered."""
    from services.billing.revops import UsageMeteringEventRepository

    reset_typed_stores()
    _patch_control_flag(monkeypatch, usage_metering_enabled=True)
    monkeypatch.setattr(lifecycle, "settings_lifecycle_stage", lambda: CredentialReadiness.SANDBOX_VALIDATED)
    svc = PaymentRailsService(repositories=PaymentRailsRepositories(), producer=_RecordingProducer())
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    meters = await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})
    assert len(meters) == 2  # payment_initiated + payment_completed


# ── Readiness demotion: pure classification ───────────────────────────────


async def test_classify_verification_failures_demotes_to_degraded():
    v = classify_demotion(
        provider="moonpay", verification_failures=3, verification_warn=2,
        webhook_observed=True, webhook_age_seconds=60, silence_seconds=86400,
        poll_health="ok",
    )
    assert v.firing and v.target == CredentialReadiness.DEGRADED
    assert "webhook_verification_failures" in v.signals


async def test_classify_auth_error_demotes_to_credential_invalid():
    v = classify_demotion(
        provider="moonpay", verification_failures=0, verification_warn=1,
        webhook_observed=True, webhook_age_seconds=10, silence_seconds=86400,
        poll_health="auth_error",
    )
    assert v.firing and v.target == CredentialReadiness.CREDENTIAL_INVALID


async def test_classify_provider_silence_demotes_to_degraded():
    v = classify_demotion(
        provider="bridge", verification_failures=0, verification_warn=1,
        webhook_observed=True, webhook_age_seconds=2 * 86400, silence_seconds=86400,
        poll_health=None,
    )
    assert v.firing and v.target == CredentialReadiness.DEGRADED
    assert "provider_silence" in v.signals


async def test_classify_never_observed_is_not_demotion_signal():
    v = classify_demotion(
        provider="bridge", verification_failures=0, verification_warn=1,
        webhook_observed=False, webhook_age_seconds=None, silence_seconds=86400,
        poll_health=None,
    )
    assert not v.firing and v.target is None


async def test_classify_degraded_poll_demotes_to_degraded():
    v = classify_demotion(
        provider="bridge", verification_failures=0, verification_warn=1,
        webhook_observed=False, webhook_age_seconds=None, silence_seconds=86400,
        poll_health="server_error",
    )
    assert v.firing and v.target == CredentialReadiness.DEGRADED
    assert "poll_degraded" in v.signals


# ── Readiness demotion: applied, monotonic, gated ─────────────────────────


async def test_apply_demotion_requires_gate_enabled(monkeypatch):
    tenant = _tenant()
    await _seed_readiness(tenant, CredentialReadiness.OFFLINE_VALIDATED)
    await _svc().repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.REJECTED, body_hash="h1",
        source="webhook", reason="signature_invalid",
    )
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: False)
    result = await readiness_demotion.apply_demotion_if_warranted(
        _svc(), tenant, "moonpay", actor="test",
    )
    assert result["applied"] is False and result["reason"] == "disabled"
    assert await _snapshot_state(tenant) == CredentialReadiness.OFFLINE_VALIDATED.value


async def test_apply_demotion_on_signature_failures(monkeypatch):
    tenant = _tenant()
    await _seed_readiness(tenant, CredentialReadiness.OFFLINE_VALIDATED)
    svc = _svc()
    await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.REJECTED, body_hash="h1",
        source="webhook", reason="signature_invalid",
    )
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: True)
    result = await readiness_demotion.apply_demotion_if_warranted(
        svc, tenant, "moonpay", actor="test", thresholds=_thresh(warn=1),
    )
    assert result["applied"] is True
    assert result["target"] == CredentialReadiness.DEGRADED.value
    assert await _snapshot_state(tenant) == CredentialReadiness.DEGRADED.value


async def test_apply_demotion_is_monotonic_and_idempotent(monkeypatch):
    tenant = _tenant()
    await _seed_readiness(tenant, CredentialReadiness.OFFLINE_VALIDATED)
    svc = _svc()
    await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.REJECTED, body_hash="h1",
        source="webhook", reason="signature_invalid",
    )
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: True)
    first = await readiness_demotion.apply_demotion_if_warranted(
        svc, tenant, "moonpay", actor="test", thresholds=_thresh(warn=1),
    )
    assert first["applied"] is True
    second = await readiness_demotion.apply_demotion_if_warranted(
        svc, tenant, "moonpay", actor="test", thresholds=_thresh(warn=1),
    )
    assert second["applied"] is False
    assert second["reason"] in ("already_at_or_below", "no_demotion")
    assert await _snapshot_state(tenant) == CredentialReadiness.DEGRADED.value


async def test_apply_demotion_skips_unseeded_capability(monkeypatch):
    tenant = _tenant()
    svc = _svc()
    await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.REJECTED, body_hash="h1",
        source="webhook", reason="signature_invalid",
    )
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: True)
    result = await readiness_demotion.apply_demotion_if_warranted(
        svc, tenant, "moonpay", actor="test", thresholds=_thresh(warn=1),
    )
    assert result["applied"] is False and result["reason"] == "not_seeded"


async def test_apply_demotion_credential_invalid_from_poll_auth_error(monkeypatch):
    tenant = _tenant()
    await _seed_readiness(tenant, CredentialReadiness.OFFLINE_VALIDATED)
    svc = _svc()
    await svc.repos.accounts.upsert(
        tenant, "moonpay", {"provider_poll_health": "auth_error"},
    )
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: True)
    result = await readiness_demotion.apply_demotion_if_warranted(
        svc, tenant, "moonpay", actor="test", thresholds=_thresh(),
    )
    assert result["applied"] is True
    assert result["target"] == CredentialReadiness.CREDENTIAL_INVALID.value
    assert await _snapshot_state(tenant) == CredentialReadiness.CREDENTIAL_INVALID.value


async def test_evaluate_demotion_silence_signal(monkeypatch):
    tenant = _tenant()
    svc = _svc()
    await svc.repos.receipts.open(
        tenant, "moonpay", body_hash="h1", source="webhook",
        stage=ReceiptStage.COMPLETED,
    )
    verdict = await readiness_demotion.evaluate_demotion(
        svc, tenant, "moonpay", now=_future(), thresholds=_thresh(silence=86400),
    )
    assert verdict.firing and verdict.target == CredentialReadiness.DEGRADED
    assert "provider_silence" in verdict.signals


def _future():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(days=3)


# ── Replay operator endpoint ───────────────────────────────────────────────


async def test_replay_dead_lettered_flips_receipt_back_into_pipeline():
    tenant = _tenant()
    svc = _svc()
    dead = await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.DEAD_LETTERED, body_hash="h1",
        source="webhook", reason="no_funding_session_after_max_repair",
    )
    rid = dead["receipt_id"]
    result = await svc.replay_dead_lettered(tenant, actor="test_operator")
    assert rid in result["replayed"]
    assert result["count"] == 1
    live = await svc.repos.receipts.get(tenant, rid)
    # Back in the recoverable pipeline (repair re-incremented the counter from
    # the reset 0 to 1 on the re-drive — a FRESH bounded budget, not terminal).
    assert live["current_stage"] != ReceiptState.DEAD_LETTERED
    assert int(live.get("repair_attempts", 0)) < PaymentRailsService.MAX_REPAIR_ATTEMPTS


async def test_replay_dead_lettered_skips_non_dead_lettered():
    tenant = _tenant()
    svc = _svc()
    await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.REJECTED, body_hash="h1",
        source="webhook", reason="signature_invalid",
    )
    result = await svc.replay_dead_lettered(tenant, actor="test_operator")
    assert result["count"] == 0
    assert result["replayed"] == []


async def test_replay_dead_lettered_scoped_by_provider():
    tenant = _tenant()
    svc = _svc()
    a = await svc.repos.receipts.open_terminal(
        tenant, "moonpay", state=ReceiptState.DEAD_LETTERED, body_hash="h1",
        source="webhook", reason="r1",
    )
    b = await svc.repos.receipts.open_terminal(
        tenant, "bridge", state=ReceiptState.DEAD_LETTERED, body_hash="h2",
        source="webhook", reason="r2",
    )
    by_provider = await svc.replay_dead_lettered(tenant, provider="bridge", actor="test_operator")
    assert by_provider["replayed"] == [b["receipt_id"]]
    assert by_provider["count"] == 1
    # The moonpay dead-lettered receipt is untouched by a bridge-scoped replay.
    assert (await svc.repos.receipts.get(tenant, a["receipt_id"]))["current_stage"] == ReceiptState.DEAD_LETTERED
    assert (await svc.repos.receipts.get(tenant, b["receipt_id"]))["current_stage"] != ReceiptState.DEAD_LETTERED


# ── Cross-cutting: demotion via the service webhook rejection hook ─────────


async def test_service_webhook_rejection_demotes_when_enabled(monkeypatch):
    """The verified-webhook path's rejection hook feeds the readiness off-ramp."""
    tenant = _tenant()
    await _seed_readiness(tenant, CredentialReadiness.OFFLINE_VALIDATED)
    monkeypatch.setattr(readiness_demotion, "demotion_enabled", lambda: True)
    svc = _svc()
    # Simulate the durable signal a signature rejection writes (REJECTED receipts)
    # at/above the deployment default warn threshold (5 in a 5m window).
    for i in range(5):
        await svc.repos.receipts.open_terminal(
            tenant, "moonpay", state=ReceiptState.REJECTED, body_hash=f"h{i}",

            source="webhook", reason="signature_invalid",
        )
    result = await svc._maybe_demote(tenant, "moonpay", actor="test")
    assert result["applied"] is True
    assert await _snapshot_state(tenant) == CredentialReadiness.DEGRADED.value
