"""Tests for the governed Dune Analytics feeder service.

Verifies:
- Freshness gate rejects stale rows
- Quality gate rejects invalid rows
- Bronze landing records full provenance
- Graph isolation: service has no graph mutation methods
- Rollback removes rows by source_tag
- Silver promotion only advances valid Bronze rows
- Health metrics reflect store state
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso(seconds: int = 7200) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture()
def feeder(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        svc_mod = importlib.import_module("services.dune_feeder.service")
        models_mod = importlib.import_module("services.dune_feeder.models")
        # Fresh singleton per test
        svc = svc_mod.DuneFeederService()
        yield svc, models_mod


def _make_request(models_mod, rows, pulled_at=None, max_age_seconds=3600, schema=None, required_fields=None, quality_threshold=0.8):
    return models_mod.FeederIngestRequest(
        query_result=models_mod.DuneQueryResult(
            query_id="123456",
            execution_id="exec_abc",
            query_name="test_query",
            rows=rows,
            pulled_at=pulled_at or _now_iso(),
        ),
        source_tag="test_batch_001",
        domain="onchain",
        schema=schema,
        required_fields=required_fields,
        max_age_seconds=max_age_seconds,
        quality_threshold=quality_threshold,
    )


class TestFreshnessGate:
    def test_fresh_row_passes(self, feeder):
        svc, _ = feeder
        result = svc.check_freshness(_now_iso(), max_age_seconds=3600)
        assert result.passed is True
        assert result.age_seconds < 5

    def test_stale_row_fails(self, feeder):
        svc, _ = feeder
        old = _stale_iso(7200)
        result = svc.check_freshness(old, max_age_seconds=3600)
        assert result.passed is False
        assert result.age_seconds >= 7200

    def test_boundary_at_exactly_max_age(self, feeder):
        svc, _ = feeder
        boundary = _stale_iso(3600)
        result = svc.check_freshness(boundary, max_age_seconds=3600)
        # Age >= max_age → stale
        assert result.passed is False

    def test_future_dated_timestamp_fails(self, feeder):
        """pulled_at in the far future should be rejected (impossible provenance)."""
        svc, _ = feeder
        future = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat()
        result = svc.check_freshness(future, max_age_seconds=3600)
        assert result.passed is False
        assert "future" in result.reason.lower()

    def test_small_clock_skew_passes(self, feeder):
        """Timestamps up to 5 minutes in the future are within clock-skew tolerance."""
        svc, _ = feeder
        near_future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        result = svc.check_freshness(near_future, max_age_seconds=3600)
        assert result.passed is True


class TestQualityGate:
    def test_valid_row_passes(self, feeder):
        svc, _ = feeder
        row = {"address": "0xabc", "balance": 100.0, "chain": "ethereum"}
        result = svc.check_quality(row, schema={"address": "str", "balance": "float"}, required_fields=["address", "balance"])
        assert result.passed is True
        assert result.score > 0

    def test_missing_required_field_fails(self, feeder):
        svc, _ = feeder
        row = {"balance": 100.0}  # missing 'address'
        result = svc.check_quality(row, schema={"address": "str", "balance": "float"}, required_fields=["address", "balance"])
        assert result.passed is False
        assert "address" in result.missing_fields

    def test_empty_row_zero_score(self, feeder):
        svc, _ = feeder
        result = svc.check_quality({}, schema={"address": "str"}, required_fields=["address"])
        assert result.passed is False
        assert result.score == 0.0

    def test_no_schema_no_required_fields_passes(self, feeder):
        svc, _ = feeder
        result = svc.check_quality({"any": "data"}, schema=None, required_fields=None)
        assert result.passed is True

    def test_partial_missing_fields_lower_score(self, feeder):
        svc, _ = feeder
        row = {"address": "0xabc"}  # only 1 of 3 required
        result = svc.check_quality(row, schema={"address": "str", "balance": "float", "chain": "str"}, required_fields=["address", "balance", "chain"])
        assert result.score < 1.0


class TestBronzeLanding:
    async def test_ingest_records_provenance(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        resp = await svc.ingest(req)
        assert resp.rows_submitted == 1
        assert resp.rows_accepted == 1
        assert resp.freshness_passed is True

    async def test_provenance_chain_populated(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        audit = await svc.audit("test_batch_001")
        assert len(audit) == 1
        record = audit[0]
        assert record["provider"] == "dune"
        assert record["query_id"] == "123456"
        assert record["source_tag"] == "test_batch_001"
        assert len(record["provenance_chain"]) >= 1

    async def test_row_hash_is_consistent(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        audit = await svc.audit("test_batch_001")
        hash1 = audit[0]["row_hash"]
        assert len(hash1) == 64  # SHA-256 hex

    async def test_stale_ingest_raises_bad_request(self, feeder):
        """Freshness gate failure raises BadRequestError, preventing Bronze landing."""
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows, pulled_at=_stale_iso(7200), max_age_seconds=3600)
        with pytest.raises(Exception) as exc_info:
            await svc.ingest(req)
        assert "Freshness gate" in str(exc_info.value)
        # No rows landed
        assert await svc.audit("test_batch_001") == []

    async def test_quality_threshold_rejects_low_quality(self, feeder):
        svc, models_mod = feeder
        rows = [{"balance": 100.0}]  # missing required 'address'
        req = _make_request(
            models_mod, rows,
            schema={"address": "str", "balance": "float"},
            required_fields=["address", "balance"],
            quality_threshold=0.8,
        )
        resp = await svc.ingest(req)
        assert resp.rows_rejected >= 1

    async def test_quality_gate_passed_false_rejects_above_threshold(self, feeder):
        """A row that quality.passed=False must be rejected even when its numeric score
        exceeds the quality_threshold. E.g. 9/10 fields present → score=0.9 > 0.8
        but the row has a missing required field so passed=False."""
        svc, models_mod = feeder
        # 10-field schema, 1 missing → score=0.9 which would pass a 0.8 threshold
        # but passed=False because 'field_j' is missing
        schema = {f"field_{c}": "str" for c in "abcdefghij"}
        required = list(schema.keys())
        row = {f"field_{c}": f"val_{c}" for c in "abcdefghi"}  # missing field_j
        rows = [row]
        req = _make_request(
            models_mod, rows,
            schema=schema,
            required_fields=required,
            quality_threshold=0.8,
        )
        resp = await svc.ingest(req)
        assert resp.rows_rejected == 1
        assert resp.rows_accepted == 0


class TestGraphIsolation:
    def test_service_has_no_graph_mutation_methods(self, feeder):
        svc, _ = feeder
        graph_methods = [m for m in dir(svc) if any(
            kw in m.lower() for kw in ["neptune", "graph_write", "graph_mutate", "upsert_node", "upsert_edge"]
        )]
        assert graph_methods == [], f"Graph mutation methods found: {graph_methods}"

    async def test_graph_isolation_flag_in_health(self, feeder):
        svc, _ = feeder
        health = await svc.get_health()
        assert health.graph_isolation_enforced is True

    def test_service_does_not_import_graph_module(self):
        """Verify no graph/neptune imports exist in the service module."""
        service_path = BACKEND_ROOT / "services" / "dune_feeder" / "service.py"
        source = service_path.read_text()
        assert "from shared.graph" not in source
        assert "import neptune" not in source.lower()
        assert "gremlin" not in source.lower()
        assert "graph_mutations" not in source


class TestRollback:
    async def test_rollback_removes_bronze_records(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        assert len(await svc.audit("test_batch_001")) == 2
        deleted = await svc.rollback("test_batch_001")
        assert deleted >= 2
        assert len(await svc.audit("test_batch_001")) == 0

    async def test_rollback_unknown_tag_returns_zero(self, feeder):
        svc, _ = feeder
        deleted = await svc.rollback("nonexistent_tag_xyz")
        assert deleted == 0

    async def test_rollback_does_not_affect_other_tags(self, feeder):
        svc, models_mod = feeder
        rows_a = [{"address": "0xabc"}]
        rows_b = [{"address": "0xdef"}]
        req_a = _make_request(models_mod, rows_a)
        req_b = models_mod.FeederIngestRequest(
            query_result=models_mod.DuneQueryResult(
                query_id="999",
                execution_id="exec_b",
                query_name="other_query",
                rows=rows_b,
                pulled_at=_now_iso(),
            ),
            source_tag="test_batch_002",
            domain="onchain",
        )
        await svc.ingest(req_a)
        await svc.ingest(req_b)
        await svc.rollback("test_batch_001")
        assert len(await svc.audit("test_batch_002")) == 1


class TestSilverPromotion:
    async def test_promote_valid_bronze_rows(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        promoted = await svc.promote_to_silver("test_batch_001")
        assert promoted >= 2

    async def test_promote_unknown_tag_returns_zero(self, feeder):
        svc, _ = feeder
        promoted = await svc.promote_to_silver("nonexistent_xyz")
        assert promoted == 0


class TestHealth:
    async def test_health_ok_on_empty_store(self, feeder):
        svc, _ = feeder
        h = await svc.get_health()
        assert h.status == "ok"
        assert h.total_bronze_records == 0
        assert h.graph_isolation_enforced is True

    async def test_health_reflects_ingest(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        h = await svc.get_health()
        assert h.total_bronze_records == 2
        assert h.unique_source_tags == 1


class TestQualityGateNumberType:
    async def test_number_schema_accepts_integer_values(self, feeder):
        """'number' type in schema must accept integer JSON values (Codex P2 fix)."""
        svc, models_mod = feeder
        rows = [{"count": 42, "volume": 1000}]
        req = models_mod.FeederIngestRequest(
            query_result=models_mod.DuneQueryResult(
                query_id="q1",
                execution_id="e1",
                query_name="count_query",
                rows=rows,
                pulled_at=_now_iso(),
            ),
            source_tag="test_number_type",
            domain="onchain",
            schema={"count": "number", "volume": "number"},
            required_fields=["count", "volume"],
        )
        resp = await svc.ingest(req)
        assert resp.rows_accepted == 1
        assert resp.rows_rejected == 0


class TestGoldMaterialization:
    async def test_materialize_gold_from_silver(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        await svc.promote_to_silver("test_batch_001")
        created = await svc.promote_to_gold("test_batch_001")
        assert created >= 1

    async def test_materialize_gold_idempotent(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        await svc.promote_to_silver("test_batch_001")
        first = await svc.promote_to_gold("test_batch_001")
        second = await svc.promote_to_gold("test_batch_001")
        assert first >= 1
        assert second == 0

    async def test_materialize_gold_cross_tenant_isolation(self, feeder):
        """Gold grouping key must include tenant_scope (Codex P1 fix)."""
        svc, models_mod = feeder
        for tenant in ("tenant_a", "tenant_b"):
            req = models_mod.FeederIngestRequest(
                query_result=models_mod.DuneQueryResult(
                    query_id="q1",
                    execution_id=f"exec_{tenant}",
                    query_name="shared_query",
                    rows=[{"address": f"0x{tenant}"}],
                    pulled_at=_now_iso(),
                ),
                source_tag="shared_tag",
                domain="onchain",
                tenant_scope=tenant,
            )
            await svc.ingest(req)
            await svc.promote_to_silver("shared_tag", tenant_scope=tenant)
        created = await svc.promote_to_gold("shared_tag")
        # Each tenant produces its own Gold record — no cross-tenant merging
        assert created == 2
        records = await svc.get_gold_records(source_tag="shared_tag")
        tenant_scopes = {r["tenant_scope"] for r in records}
        assert "tenant_a" in tenant_scopes
        assert "tenant_b" in tenant_scopes

    async def test_materialize_gold_unknown_tag_returns_zero(self, feeder):
        svc, _ = feeder
        assert await svc.promote_to_gold("nonexistent_xyz") == 0

    async def test_get_gold_records_filtered_by_source_tag(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        await svc.promote_to_silver("test_batch_001")
        await svc.promote_to_gold("test_batch_001")
        records = await svc.get_gold_records(source_tag="test_batch_001")
        assert len(records) >= 1
        assert records[0]["source_tag"] == "test_batch_001"
        assert records[0]["row_count"] >= 1

    async def test_rollback_removes_gold_records(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        await svc.promote_to_silver("test_batch_001")
        await svc.promote_to_gold("test_batch_001")
        assert len(await svc.get_gold_records(source_tag="test_batch_001")) >= 1
        await svc.rollback("test_batch_001")
        assert len(await svc.get_gold_records(source_tag="test_batch_001")) == 0

    async def test_health_reflects_gold_count(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}]
        req = _make_request(models_mod, rows)
        await svc.ingest(req)
        await svc.promote_to_silver("test_batch_001")
        await svc.promote_to_gold("test_batch_001")
        h = await svc.get_health()
        assert h.total_gold_records >= 1
