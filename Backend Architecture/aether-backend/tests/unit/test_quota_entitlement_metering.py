"""Direct unit tests for the billing/quota/metering substrate (§7, §21).

Covers the previously untested primitives — QuotaEngine, FeatureGate,
OverageCalculator, run_overage_cycle — plus the new §7 entitlement
enforcement seam, capability metering hook, and quota<->metering
reconciliation engine (including the RECONCILIATION_CONFLICT state).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores
from services.billing.cycle import run_overage_cycle
from services.billing.revops import (
    MeteringService,
    TenantEntitlement,
    TenantEntitlementRepository,
    UsageMeteringEvent,
    UsageMeteringEventRepository,
)
from services.metering_evidence.families import (
    CAPABILITY_FAMILIES,
    family_dimension,
    is_known_family,
    meter_family_usage,
    # Re-homed metering + entitlement enforcement seam (was the dropped
    # services.metering_evidence.hooks + services.capabilities.enforcement).
    DUPLICATE,
    ENTITLEMENT_DENIED,
    ENTITLEMENT_STATE_DENIED,
    ENTITLEMENT_STATE_INCLUDED,
    ENTITLEMENT_STATE_OVERAGE,
    CapabilityEntitlementService as EntitlementService,
    EnforcementResult,
    EntitlementDeniedError,
    METERED,
    METERING_ERROR,
    MeteringStoreError,
    MeterOutcome,
    enforce_entitlement,
    meter_capability_usage,
)
from services.metering_evidence.reconciliation import (
    EVIDENCE_DOUBLE_COUNT,
    EVIDENCE_MISSING,
    ENTITLED_NO_ENTITLEMENT,
    OVERAGE_UNMETERED,
    QUOTA_NOT_INCREMENTED,
    RECONCILED,
    RECONCILIATION_CONFLICT,
    ReconciliationEngine,
)
from services.metering_evidence.service import (
    EXCLUDED_DUPLICATE,
    MeteringEvidenceRepository,
    MeteringEvidenceService,
)
from shared.auth.auth import PlanTier
from shared.billing.overage import OverageCalculator
from shared.plans.catalog import PLAN_CATALOG
from shared.rate_limit.feature_gate import FeatureGate
from shared.rate_limit.quota import QuotaEngine


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


_WIDE_START = "2000-01-01T00:00:00Z"
_WIDE_END = "2999-01-01T00:00:00Z"


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _seed_entitlement(
    tenant_id: str,
    dimension: str,
    *,
    enabled: bool = True,
    included_quantity: float | None = None,
    overage_allowed: bool = False,
) -> dict:
    repo = TenantEntitlementRepository()
    ent = TenantEntitlement(
        tenant_id=tenant_id,
        feature_key=dimension,
        enabled=enabled,
        included_quantity=included_quantity,
        overage_allowed=overage_allowed,
    )
    data = ent.model_dump()
    await repo.insert(data["entitlement_id"], data)
    return data


# ═══════════════════════════════════════════════════════════════════════════
# QuotaEngine (in-memory mode)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_quota_engine_increments_and_flags_included():
    engine = QuotaEngine()  # no redis -> in-memory mode
    res = await engine.check_and_increment("t1", PlanTier.P1_HOBBYIST, "/v1/ingest/events")
    assert res.allowed is True
    assert res.included is True
    assert res.quota_limit == PLAN_CATALOG[PlanTier.P1_HOBBYIST].monthly_quota
    assert res.quota_used == 1
    assert res.remaining == res.quota_limit - 1
    assert res.overage_service is None
    assert res.reset  # ISO next-period start


@pytest.mark.asyncio
async def test_quota_engine_overage_after_quota_exhausted():
    engine = QuotaEngine()
    period = _current_period()
    qkey = QuotaEngine.quota_key("t1", period)
    plan = PLAN_CATALOG[PlanTier.P1_HOBBYIST]
    engine._memory_quota[qkey] = plan.monthly_quota  # simulate exhaustion

    res = await engine.check_and_increment("t1", PlanTier.P1_HOBBYIST, "/v1/ingest/events")
    assert res.allowed is True  # engine never blocks — overage is metered
    assert res.included is False
    assert res.remaining == 0
    assert res.overage_service == "Omni-Capture"

    overage = await engine.get_overage_counts("t1", period)
    assert overage == {"Omni-Capture": 1}


@pytest.mark.asyncio
async def test_quota_engine_get_total_used_and_overage_counts():
    engine = QuotaEngine()
    period = _current_period()
    qkey = QuotaEngine.quota_key("t1", period)
    engine._memory_quota[qkey] = plan = 7
    assert await engine.get_total_used("t1", period) == 7
    engine._memory_overage_increment(QuotaEngine.overage_key("t1", period), "Connectivity")
    engine._memory_overage_increment(QuotaEngine.overage_key("t1", period), "Connectivity")
    assert await engine.get_overage_counts("t1", period) == {"Connectivity": 2}
    assert engine.mode == "in-memory"


@pytest.mark.asyncio
async def test_quota_engine_keys_are_per_tenant_per_period():
    a = QuotaEngine.quota_key("t1", "2026-01")
    b = QuotaEngine.quota_key("t1", "2026-02")
    c = QuotaEngine.quota_key("t2", "2026-01")
    assert len({a, b, c}) == 3
    assert QuotaEngine.quota_key("t1", "2026-01") == "rl:quota:t1:2026-01"
    assert QuotaEngine.overage_key("t1", "2026-01") == "rl:overage:t1:2026-01"


# ═══════════════════════════════════════════════════════════════════════════
# FeatureGate
# ═══════════════════════════════════════════════════════════════════════════


def test_feature_gate_public_path_allowed():
    gate = FeatureGate()
    res = gate.check_access(PlanTier.P1_HOBBYIST, "/health")
    assert res.allowed is True
    assert res.service_name is None


def test_feature_gate_allowed_service():
    gate = FeatureGate()
    # Omni-Capture is included for P1.
    res = gate.check_access(PlanTier.P1_HOBBYIST, "/v1/ingest/events")
    assert res.allowed is True
    assert res.service_name == "Omni-Capture"
    assert res.minimum_plan is None


def test_feature_gate_blocked_service_reports_minimum_plan():
    gate = FeatureGate()
    # Unification (Identity) is not available on P1 — minimum is P2.
    res = gate.check_access(PlanTier.P1_HOBBYIST, "/v1/identity/resolve")
    assert res.allowed is False
    assert res.service_name == "Unification"
    assert res.minimum_plan is PlanTier.P2_PROFESSIONAL


def test_feature_gate_unrecognized_path_passes_through():
    gate = FeatureGate()
    res = gate.check_access(PlanTier.P1_HOBBYIST, "/v1/does-not-exist")
    assert res.allowed is True
    assert res.service_name is None


# ═══════════════════════════════════════════════════════════════════════════
# OverageCalculator
# ═══════════════════════════════════════════════════════════════════════════


class _FakeRedis:
    """Minimal async redis shim with the two reads OverageCalculator uses."""

    def __init__(self, overage: dict[str, int] | None = None, total: int | None = None):
        self._overage = overage or {}
        self._total = total

    async def hgetall(self, _key: str) -> dict[str, int]:
        return self._overage

    async def get(self, _key: str) -> str | None:
        if self._total is None:
            return None
        return str(self._total)


@pytest.mark.asyncio
async def test_overage_calculator_prices_line_items_from_overage():
    calc = OverageCalculator(
        redis_client=_FakeRedis(overage={"Omni-Capture": 1000}, total=26000),
        pricing_option="A",
    )
    invoice = await calc.calculate("t1", PlanTier.P1_HOBBYIST, "2026-01")
    assert invoice.total_requests == 26000
    assert invoice.overage_request_count == 1000
    assert len(invoice.line_items) == 1
    item = invoice.line_items[0]
    assert item.service_name == "Omni-Capture"
    assert item.overage_requests == 1000
    assert item.price_per_1k == Decimal("0.05")  # option A for Omni-Capture
    assert item.line_total == Decimal("0.05")
    assert invoice.total_overage == Decimal("0.05")
    assert invoice.period_total == Decimal("99.05")  # P1 option A fee + overage


@pytest.mark.asyncio
async def test_overage_calculator_skips_unknown_service():
    calc = OverageCalculator(
        redis_client=_FakeRedis(overage={"Not-A-Service": 500}, total=100),
        pricing_option="B",
    )
    invoice = await calc.calculate("t1", PlanTier.P1_HOBBYIST, "2026-01")
    assert invoice.overage_request_count == 500
    assert invoice.line_items == []


@pytest.mark.asyncio
async def test_overage_calculator_rejects_unknown_pricing_option():
    with pytest.raises(ValueError):
        OverageCalculator(pricing_option="Z")


# ═══════════════════════════════════════════════════════════════════════════
# run_overage_cycle
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_overage_cycle_disabled_returns_skip(monkeypatch):
    cfg = type(
        "StripeConfig", (), {
            "overage_invoicing_enabled": False,
        },
    )()
    import services.billing.cycle as cycle
    monkeypatch.setattr(cycle.settings, "stripe_billing", cfg)
    summary = await run_overage_cycle("2099-01")
    assert summary["reason"] == "overage_disabled"
    assert summary["processed"] == 0
    assert summary["skipped"] == 0
    assert summary["failed"] == 0


@pytest.mark.asyncio
async def test_run_overage_cycle_enabled_no_accounts(monkeypatch):
    cfg = type(
        "StripeConfig", (), {
            "overage_invoicing_enabled": True,
        },
    )()
    import dependencies.providers as providers_mod
    import services.billing.cycle as cycle

    class _FakeRegistry:
        def __init__(self) -> None:
            self.quota_engine = QuotaEngine()

    monkeypatch.setattr(cycle.settings, "stripe_billing", cfg)
    monkeypatch.setattr(providers_mod, "get_registry", lambda: _FakeRegistry())

    summary = await run_overage_cycle("2099-01")
    # No active billing accounts in the test environment -> nothing processed.
    assert summary["period"] == "2099-01"
    assert summary["processed"] == 0
    assert summary["skipped"] == 0
    assert summary["failed"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# EntitlementService.enforce_dimension
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_enforce_dimension_within_included_is_included():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    decision = await EntitlementService().enforce_dimension("t1", "event_ingested", 5)
    assert decision["state"] == ENTITLEMENT_STATE_INCLUDED
    assert decision["included_quantity"] == 100
    assert decision["overage_quantity"] == 0


@pytest.mark.asyncio
async def test_enforce_dimension_overage_allowed_returns_overage():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100, overage_allowed=True)
    decision = await EntitlementService().enforce_dimension("t1", "event_ingested", 120)
    assert decision["state"] == ENTITLEMENT_STATE_OVERAGE
    assert decision["overage_quantity"] == 20


@pytest.mark.asyncio
async def test_enforce_dimension_over_limit_without_overage_is_denied():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100, overage_allowed=False)
    decision = await EntitlementService().enforce_dimension("t1", "event_ingested", 101)
    assert decision["state"] == ENTITLEMENT_STATE_DENIED
    assert decision["reason"] == "overage_not_allowed"


@pytest.mark.asyncio
async def test_enforce_dimension_missing_entitlement_is_denied():
    decision = await EntitlementService().enforce_dimension("t1", "event_ingested", 1)
    assert decision["state"] == ENTITLEMENT_STATE_DENIED
    assert decision["reason"] == "not_entitled"


@pytest.mark.asyncio
async def test_enforce_dimension_disabled_entitlement_is_denied():
    await _seed_entitlement("t1", "event_ingested", enabled=False)
    decision = await EntitlementService().enforce_dimension("t1", "event_ingested", 1)
    assert decision["state"] == ENTITLEMENT_STATE_DENIED
    assert decision["reason"] == "disabled"


# ═══════════════════════════════════════════════════════════════════════════
# capabilities.enforcement seam
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_enforce_entitlement_fail_closed_raises_when_denied():
    await _seed_entitlement("t1", "event_ingested", included_quantity=10, overage_allowed=False)
    with pytest.raises(EntitlementDeniedError) as exc_info:
        await enforce_entitlement("t1", "event_ingested", 11)
    assert exc_info.value.details["dimension"] == "event_ingested"
    assert exc_info.value.details["reason"] == "overage_not_allowed"


@pytest.mark.asyncio
async def test_enforce_entitlement_fail_open_returns_denied_result():
    result = await enforce_entitlement(
        "t1", "event_ingested", 1, fail_closed=False,
    )
    assert isinstance(result, EnforcementResult)
    assert result.allowed is False
    assert result.state == ENTITLEMENT_STATE_DENIED
    assert result.reason == "not_entitled"


@pytest.mark.asyncio
async def test_enforce_entitlement_allowed_within_included():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    result = await enforce_entitlement("t1", "event_ingested", 5)
    assert result.allowed is True
    assert result.state == ENTITLEMENT_STATE_INCLUDED


# ═══════════════════════════════════════════════════════════════════════════
# Metering hook
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_hook_meters_entitled_usage_exactly_once():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    outcome = await meter_capability_usage(
        "t1",
        dimension="event_ingested",
        event_id="evt-1",
        dedupe_key="dk-1",
        source_path="/v1/ingest/events",
    )
    assert isinstance(outcome, MeterOutcome)
    assert outcome.state == METERED
    assert outcome.dimension == "event_ingested"
    assert outcome.quantity == 1

    # Both durable truths written: usage_metering_events + metering_evidence.
    events = await UsageMeteringEventRepository().find_many(filters={"tenant_id": "t1"})
    assert len(events) == 1
    assert events[0]["event_type"] == "event_ingested"
    evidence = await MeteringEvidenceRepository().find_many(filters={"tenant_id": "t1"})
    assert len(evidence) == 1
    assert evidence[0]["billable"] is True
    assert evidence[0]["usage_dimension"] == "event_ingested"


@pytest.mark.asyncio
async def test_hook_denies_unentitled_usage():
    with pytest.raises(EntitlementDeniedError) as exc_info:
        await meter_capability_usage(
            "t1",
            dimension="event_ingested",
            event_id="evt-1",
            dedupe_key="dk-1",
            source_path="/v1/ingest/events",
        )
    assert exc_info.value.details["reason"] == "not_entitled"


@pytest.mark.asyncio
async def test_hook_deny_without_raise_returns_explicit_state():
    outcome = await meter_capability_usage(
        "t1",
        dimension="event_ingested",
        event_id="evt-1",
        dedupe_key="dk-1",
        source_path="/v1/ingest/events",
        raise_on_denied=False,
    )
    assert outcome.state == ENTITLEMENT_DENIED
    assert outcome.reason == "not_entitled"
    # Nothing was written for a denied capability.
    events = await UsageMeteringEventRepository().find_many(filters={"tenant_id": "t1"})
    assert events == []


@pytest.mark.asyncio
async def test_hook_duplicate_dedupe_is_non_billable():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    first = await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-same", source_path="/v1/ingest/events",
    )
    second = await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-same", source_path="/v1/ingest/events",
    )
    assert first.state == METERED
    assert second.state == DUPLICATE
    evidence = await MeteringEvidenceRepository().find_many(filters={"tenant_id": "t1"})
    assert len(evidence) == 2
    dup = [e for e in evidence if e["excluded_reason"] == EXCLUDED_DUPLICATE]
    assert len(dup) == 1
    assert dup[0]["billable"] is False
    # Only ONE billable usage-meting event despite two calls (idempotent).
    events = await UsageMeteringEventRepository().find_many(filters={"tenant_id": "t1"})
    billable = [e for e in events if e.get("billable")]
    assert len(billable) == 1


class _ExplodingMetering(MeteringService):
    async def record_event(self, event: UsageMeteringEvent) -> dict | None:
        raise RuntimeError("metering store down")


@pytest.mark.asyncio
async def test_hook_metering_failure_raises_by_default():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    with pytest.raises(MeteringStoreError):
        await meter_capability_usage(
            "t1", dimension="event_ingested", event_id="evt-1",
            dedupe_key="dk-1", source_path="/v1/ingest/events",
            metering=_ExplodingMetering(),
        )


@pytest.mark.asyncio
async def test_hook_metering_failure_surfaces_explicit_error_state():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    outcome = await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-1", source_path="/v1/ingest/events",
        metering=_ExplodingMetering(),
        raise_on_metering_error=False,
    )
    assert outcome.state == METERING_ERROR
    assert outcome.reason == "usage_event_write_failed"


@pytest.mark.asyncio
async def test_hook_unknown_dimension_fails_closed_before_write():
    with pytest.raises(MeteringStoreError):
        await meter_capability_usage(
            "t1", dimension="not_a_real_dimension", event_id="evt-1",
            dedupe_key="dk-1", source_path="/v1/ingest/events",
        )
    assert await UsageMeteringEventRepository().find_many(filters={"tenant_id": "t1"}) == []
    assert await MeteringEvidenceRepository().find_many(filters={"tenant_id": "t1"}) == []


# ═══════════════════════════════════════════════════════════════════════════
# Capability-family registry
# ═══════════════════════════════════════════════════════════════════════════


def test_family_registry_covers_commercial_families():
    for family in (
        "ingestion", "graph", "profile360", "recommendations",
        "decisions", "actions", "outcomes", "playbooks", "audit_exports",
    ):
        assert is_known_family(family)
        assert family_dimension(family) == CAPABILITY_FAMILIES[family].dimension
    assert family_dimension("recommendations") == "recommendation_generated"
    assert family_dimension("audit_exports") == "audit_export_generated"


@pytest.mark.asyncio
async def test_meter_family_usage_writes_family_dimension():
    await _seed_entitlement("t1", "recommendation_generated", included_quantity=50)
    outcome = await meter_family_usage(
        "recommendations", "t1", event_id="rec-1",
    )
    assert outcome.state == METERED
    assert outcome.dimension == "recommendation_generated"
    events = await UsageMeteringEventRepository().find_many(filters={"tenant_id": "t1"})
    assert len(events) == 1
    assert events[0]["event_type"] == "recommendation_generated"


@pytest.mark.asyncio
async def test_meter_family_usage_unknown_family_raises():
    with pytest.raises(KeyError):
        await meter_family_usage("bogus-family", "t1", event_id="x")


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation engine
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reconciliation_reconciled_when_all_truths_agree():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-1", source_path="/v1/ingest/events",
    )
    report = await ReconciliationEngine().reconcile("t1", _WIDE_START, _WIDE_END)
    assert report.status == RECONCILED
    assert report.metering_by_dimension == {"event_ingested": 1.0}
    assert report.evidence_by_dimension == {"event_ingested": 1.0}
    assert report.discrepancies == []


@pytest.mark.asyncio
async def test_reconciliation_conflict_evidence_missing():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    # A usage event without durable billable evidence -> billable loss.
    await UsageMeteringEventRepository().insert(
        "evt_x",
        {"tenant_id": "t1", "event_type": "event_ingested", "quantity": 1,
         "billable": True, "occurred_at": "2026-01-15T00:00:00Z"},
    )
    report = await ReconciliationEngine().reconcile("t1", _WIDE_START, _WIDE_END)
    assert report.status == RECONCILIATION_CONFLICT
    kinds = {d.kind for d in report.discrepancies}
    assert EVIDENCE_MISSING in kinds


@pytest.mark.asyncio
async def test_reconciliation_conflict_evidence_double_count():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    # Billable evidence with no matching metering event -> double-count risk.
    await MeteringEvidenceService().record(
        tenant_id="t1", source_path="/v1/ingest/events",
        event_id="evt-1", dedupe_key="dk-1",
        usage_dimension="event_ingested", quantity=1, billable=True,
    )
    report = await ReconciliationEngine().reconcile("t1", _WIDE_START, _WIDE_END)
    assert report.status == RECONCILIATION_CONFLICT
    kinds = {d.kind for d in report.discrepancies}
    assert EVIDENCE_DOUBLE_COUNT in kinds


@pytest.mark.asyncio
async def test_reconciliation_conflict_entitled_no_entitlement():
    # Meter usage (enforce=False) for a dimension with NO entitlement.
    await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-1", source_path="/v1/ingest/events", enforce=False,
    )
    report = await ReconciliationEngine().reconcile("t1", _WIDE_START, _WIDE_END)
    assert report.status == RECONCILIATION_CONFLICT
    kinds = {d.kind for d in report.discrepancies}
    assert ENTITLED_NO_ENTITLEMENT in kinds


class _FakeQuotaEngine:
    """Deterministic quota-engine shim for reconciliation cross-checks."""

    def __init__(self, total: int | None = 0, overage: dict[str, int] | None = None):
        self.total = total
        self.overage = overage or {}

    async def get_total_used(self, tenant_id: str, period: str) -> int | None:
        return self.total

    async def get_overage_counts(self, tenant_id: str, period: str) -> dict[str, int]:
        return self.overage


@pytest.mark.asyncio
async def test_reconciliation_conflict_quota_not_incremented():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-1", source_path="/v1/ingest/events",
    )
    # Quota counter says zero while metering recorded usage.
    report = await ReconciliationEngine().reconcile(
        "t1", _WIDE_START, _WIDE_END, quota_engine=_FakeQuotaEngine(total=0),
    )
    assert report.status == RECONCILIATION_CONFLICT
    kinds = {d.kind for d in report.discrepancies}
    assert QUOTA_NOT_INCREMENTED in kinds


@pytest.mark.asyncio
async def test_reconciliation_reconciled_with_matching_quota():
    await _seed_entitlement("t1", "event_ingested", included_quantity=100)
    await meter_capability_usage(
        "t1", dimension="event_ingested", event_id="evt-1",
        dedupe_key="dk-1", source_path="/v1/ingest/events",
    )
    report = await ReconciliationEngine().reconcile(
        "t1", _WIDE_START, _WIDE_END, quota_engine=_FakeQuotaEngine(total=1),
    )
    assert report.status == RECONCILED


@pytest.mark.asyncio
async def test_reconciliation_conflict_overage_unmetered():
    # Quota engine priced overage requests but the meter recorded nothing.
    report = await ReconciliationEngine().reconcile(
        "t1", _WIDE_START, _WIDE_END,
        quota_engine=_FakeQuotaEngine(total=5, overage={"Omni-Capture": 5}),
    )
    assert report.status == RECONCILIATION_CONFLICT
    kinds = {d.kind for d in report.discrepancies}
    assert OVERAGE_UNMETERED in kinds
