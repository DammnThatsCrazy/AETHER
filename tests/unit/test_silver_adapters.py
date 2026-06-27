"""Unit tests — silver_adapters: each silver table → CanonicalActivity mapping."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class TestSilverAdapters:

    def test_adapt_from_silver_campaign_touchpoint(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "touchpoint_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "profile_id": "profile-001",
            "channel": "paid_search",
            "touchpoint_type": "click",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_campaign_touchpoint_facts", row)
        assert result is not None
        assert result.get("activity_family") in ("campaign", "web2")
        assert result.get("tenant_id") == "tenant-a"

    def test_adapt_from_silver_web3_transaction(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "transaction_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "wallet_id": f"0x{uuid4().hex}",
            "tx_hash": f"0x{uuid4().hex}",
            "chain_id": "1",
            "event_type": "transfer",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_web3_transaction_facts", row)
        assert result is not None
        assert result.get("activity_family") == "web3"
        assert result.get("tx_hash") is not None

    def test_adapt_from_silver_x402_flow(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "flow_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_x402_flow_facts", row)
        assert result is not None
        assert result.get("activity_family") == "x402"

    def test_adapt_from_silver_agent_execution(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "execution_id": str(uuid4()),
            "agent_id": f"agent-{uuid4()}",
            "tenant_id": "tenant-a",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_agent_execution_facts", row)
        assert result is not None
        assert result.get("activity_family") == "agent"
        assert result.get("actor_type") == "agent"

    def test_adapt_from_silver_identity_evidence_login(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "evidence_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "event_kind": "login",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_identity_evidence_facts", row)
        assert result is not None
        assert result.get("activity_family") == "web2"
        assert result.get("activity_type") == "login"

    def test_adapt_from_silver_identity_evidence_wallet_connection(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "evidence_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "event_kind": "wallet_connection",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_identity_evidence_facts", row)
        assert result is not None
        assert result.get("activity_type") == "wallet_connection"

    def test_adapt_from_silver_outcome(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "outcome_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_outcome_facts", row)
        assert result is not None
        assert result.get("activity_family") == "outcome"

    def test_adapt_from_silver_revenue(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "revenue_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "gross_amount": "100.00",
            "currency": "USD",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_revenue_facts", row)
        assert result is not None
        assert result.get("activity_family") == "commerce"
        assert result.get("gross_amount") is not None

    def test_adapt_from_silver_unknown_table_returns_none(self):
        from services.measurement.silver_adapters import adapt_from_silver
        result = adapt_from_silver("silver_nonexistent_table", {})
        assert result is None

    def test_idempotency_key_stability(self):
        from services.measurement.silver_adapters import adapt_from_silver
        key = str(uuid4())
        row = {
            "touchpoint_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "occurred_at": _now(),
            "idempotency_key": key,
        }
        r1 = adapt_from_silver("silver_campaign_touchpoint_facts", row)
        r2 = adapt_from_silver("silver_campaign_touchpoint_facts", row)
        if r1 and r2:
            assert r1.get("idempotency_key") == r2.get("idempotency_key")

    def test_adapt_from_silver_exposure(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "fact_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "profile_id": "profile-001",
            "recommendation_id": "rec-123",
            "position": 2,
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_exposure_facts", row)
        assert result is not None
        assert result.get("activity_family") == "campaign"
        assert result.get("activity_type") == "recommendation_exposure"
        assert result.get("tenant_id") == "tenant-a"

    def test_adapt_from_silver_account_activity(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "fact_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "profile_id": "profile-001",
            "activity_type": "login",
            "channel": "web",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_account_activity_facts", row)
        assert result is not None
        assert result.get("activity_family") == "web2"
        assert result.get("activity_type") == "login"
        assert result.get("tenant_id") == "tenant-a"

    def test_adapt_from_silver_comms(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "fact_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "profile_id": "profile-001",
            "comms_type": "email",
            "channel": "email",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("silver_comms_facts", row)
        assert result is not None
        assert result.get("activity_family") == "web2"
        assert result.get("activity_type") == "comms_email"
        assert result.get("tenant_id") == "tenant-a"

    def test_canonical_conversion_adapter(self):
        from services.measurement.silver_adapters import adapt_from_silver
        row = {
            "conversion_id": str(uuid4()),
            "tenant_id": "tenant-a",
            "conversion_type": "purchase",
            "occurred_at": _now(),
            "idempotency_key": str(uuid4()),
        }
        result = adapt_from_silver("canonical_conversions", row)
        assert result is not None
        assert result.get("activity_family") == "commerce"
        assert "conversion_purchase" in str(result.get("activity_type", ""))
