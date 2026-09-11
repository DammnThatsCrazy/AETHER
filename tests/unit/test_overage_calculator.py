"""Unit tests for shared.billing.overage.OverageCalculator.

Tests the overage calculation logic using pure in-memory mocks — no DB or
Redis required.  Each test verifies a specific billing concern:
  - Line-item building from per-service overage counts
  - Pricing options A / B / C
  - Unknown service names are skipped gracefully
  - Zero-count services are excluded from line items
  - Total calculations and rounding
  - Redis hot-path vs Postgres cold-path fallback
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_STUBBED: list[str] = []
for _mod in ("jwt", "cryptography", "cryptography.hazmat",
             "cryptography.hazmat.primitives",
             "cryptography.hazmat.primitives.asymmetric",
             "cryptography.hazmat.primitives.asymmetric.ec",
             "cryptography.hazmat.bindings",
             "cryptography.hazmat.bindings._rust",
             "cryptography.hazmat._oid"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
        _STUBBED.append(_mod)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="module", autouse=True)
def _remove_crypto_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calculator(redis=None, db=None, pricing_option="B"):
    from shared.billing.overage import OverageCalculator
    return OverageCalculator(
        redis_client=redis,
        db_pool=db,
        pricing_option=pricing_option,
    )


def _make_service_mock(name: str, endpoint: str, price_a, price_b, price_c,
                       pillar: str = "Ingestion"):
    """Build a minimal ServiceDefinition-like mock."""
    pricing = MagicMock()
    pricing.option_a_per_1k = Decimal(str(price_a))
    pricing.option_b_per_1k = Decimal(str(price_b))
    pricing.option_c_per_1k = Decimal(str(price_c))
    svc = MagicMock()
    svc.endpoint_pattern = endpoint
    svc.pricing = pricing
    svc.pillar = pillar
    return svc


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_invalid_pricing_option_raises():
    from shared.billing.overage import OverageCalculator
    with pytest.raises(ValueError, match="pricing_option must be A/B/C"):
        OverageCalculator(pricing_option="D")


def test_pricing_option_stored():
    calc = _make_calculator(pricing_option="A")
    assert calc.pricing_option == "A"


# ---------------------------------------------------------------------------
# _build_line_items
# ---------------------------------------------------------------------------

@patch("shared.billing.overage.find_service_by_name")
def test_build_line_items_skips_zero_counts(mock_find):
    from shared.auth.auth import PlanTier
    calc = _make_calculator()
    items = calc._build_line_items({"svc_a": 0, "svc_b": 0}, PlanTier.ALPHA)
    assert items == []
    mock_find.assert_not_called()


@patch("shared.billing.overage.find_service_by_name")
def test_build_line_items_skips_unknown_service(mock_find):
    from shared.auth.auth import PlanTier
    mock_find.return_value = None
    calc = _make_calculator()
    items = calc._build_line_items({"unknown_svc": 500}, PlanTier.ALPHA)
    assert items == []


@patch("shared.billing.overage.find_service_by_name")
def test_build_line_items_uses_plan_rate(mock_find):
    from shared.auth.auth import PlanTier
    svc = _make_service_mock("svc_a", "/v1/svc/*", "2.00", "1.50", "1.00")
    mock_find.return_value = svc

    calc = _make_calculator()
    items = calc._build_line_items({"svc_a": 2000}, PlanTier.ALPHA)

    assert len(items) == 1
    item = items[0]
    assert item.service_name == "svc_a"
    assert item.overage_requests == 2000
    # Alpha event_overage_per_1k = 0.060; 2000 / 1000 * 0.060 = 0.12
    assert item.line_total == Decimal("0.12")
    assert item.pricing_option == "alpha"


@patch("shared.billing.overage.find_service_by_name")
def test_build_line_items_sorted_descending(mock_find):
    from shared.auth.auth import PlanTier
    svc_event = _make_service_mock("event_svc", "/v1/cheap/*", "0.10", "0.10", "0.10",
                                   pillar="Ingestion")
    svc_acu = _make_service_mock("acu_svc", "/v1/exp/*", "5.00", "5.00", "5.00",
                                 pillar="Agentic")

    def _find(name):
        return svc_event if name == "event_svc" else svc_acu

    mock_find.side_effect = _find
    calc = _make_calculator()
    items = calc._build_line_items({"event_svc": 1000, "acu_svc": 1000}, PlanTier.ALPHA)
    # acu_svc (Alpha acu_overage_per_1k=7.00) should sort before event_svc (0.060)
    assert items[0].service_name == "acu_svc"
    assert items[1].service_name == "event_svc"


@patch("shared.billing.overage.find_service_by_name")
def test_build_line_items_alpha_vs_delta_rates(mock_find):
    from shared.auth.auth import PlanTier
    svc = _make_service_mock("svc", "/v1/*", "3.00", "2.00", "1.00")
    mock_find.return_value = svc

    calc = _make_calculator()
    items_alpha = calc._build_line_items({"svc": 1000}, PlanTier.ALPHA)
    items_delta = calc._build_line_items({"svc": 1000}, PlanTier.DELTA)

    # Alpha event rate ($0.060) > Delta event rate ($0.030)
    assert items_alpha[0].line_total > items_delta[0].line_total
    assert items_alpha[0].line_total == Decimal("0.06")
    assert items_delta[0].line_total == Decimal("0.03")


# ---------------------------------------------------------------------------
# Redis / DB data sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_overage_counts_from_redis():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={"svc_x": "150", "svc_y": "300"})

    calc = _make_calculator(redis=redis)
    counts = await calc._read_overage_counts("tenant1", "2026-05")

    redis.hgetall.assert_called_once_with("rl:overage:tenant1:2026-05")
    assert counts == {"svc_x": 150, "svc_y": 300}


@pytest.mark.asyncio
async def test_read_overage_counts_falls_back_to_postgres():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value=None)

    row = {"overage_by_service": '{"svc_z": 99}'}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    calc = _make_calculator(redis=redis, db=pool)
    counts = await calc._read_overage_counts("tenant1", "2026-05")
    assert counts.get("svc_z") == 99


@pytest.mark.asyncio
async def test_read_total_requests_from_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="12500")

    calc = _make_calculator(redis=redis)
    total = await calc._read_total_requests("tenant1", "2026-05")
    assert total == 12500


@pytest.mark.asyncio
async def test_read_total_requests_returns_zero_when_no_redis_no_db():
    calc = _make_calculator()
    total = await calc._read_total_requests("tenant1", "2026-05")
    assert total == 0


# ---------------------------------------------------------------------------
# Full calculate() path (mocked data sources)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.billing.overage.find_service_by_name")
@patch("shared.billing.overage.OVERAGE_COST")
async def test_calculate_returns_invoice(mock_metric, mock_find):
    svc = _make_service_mock("svc_a", "/v1/*", "2.00", "1.50", "1.00")
    mock_find.return_value = svc
    mock_metric.labels.return_value.inc = MagicMock()

    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={"svc_a": "500"})
    redis.get = AsyncMock(return_value="5500")

    from shared.auth.auth import PlanTier
    calc = _make_calculator(redis=redis)

    invoice = await calc.calculate("tenant1", PlanTier.ALPHA, "2026-05")

    assert invoice.tenant_id == "tenant1"
    assert invoice.billing_period == "2026-05"
    assert invoice.overage_request_count == 500
    assert invoice.total_requests == 5500
    assert len(invoice.line_items) == 1
    # Alpha event_overage_per_1k = 0.060; 500 / 1000 * 0.060 = 0.03
    assert invoice.line_items[0].line_total == Decimal("0.03")
    assert invoice.total_overage == Decimal("0.03")
    # period_total = plan_fee + 0.03
    assert invoice.period_total == invoice.plan_fee + Decimal("0.03")


@pytest.mark.asyncio
@patch("shared.billing.overage.find_service_by_name")
@patch("shared.billing.overage.OVERAGE_COST")
async def test_calculate_no_overage_invoice(mock_metric, mock_find):
    """When there's no overage data, invoice should have empty line items."""
    mock_find.return_value = None

    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.get = AsyncMock(return_value="100")

    from shared.auth.auth import PlanTier
    calc = _make_calculator(redis=redis)
    invoice = await calc.calculate("tenant1", PlanTier.ALPHA, "2026-05")

    assert invoice.line_items == []
    assert invoice.total_overage == Decimal("0")
    assert invoice.overage_request_count == 0
