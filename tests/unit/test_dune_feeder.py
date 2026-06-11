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
    def test_ingest_records_provenance(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        resp = svc.ingest(req)
        assert resp.rows_submitted == 1
        assert resp.rows_accepted == 1
        assert resp.freshness_passed is True

    def test_provenance_chain_populated(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        svc.ingest(req)
        audit = svc.audit("test_batch_001")
        assert len(audit) == 1
        record = audit[0]
        assert record["provider"] == "dune"
        assert record["query_id"] == "123456"
        assert record["source_tag"] == "test_batch_001"
        assert len(record["provenance_chain"]) >= 1

    def test_row_hash_is_consistent(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc", "balance": 100.0}]
        req = _make_request(models_mod, rows)
        svc.ingest(req)
        audit = svc.audit("test_batch_001")
        hash1 = audit[0]["row_hash"]
        assert len(hash1) == 64  # SHA-256 hex

    def test_stale_ingest_raises_bad_request(self, feeder):
        """Freshness gate failure raises BadRequestError, preventing Bronze landing."""
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows, pulled_at=_stale_iso(7200), max_age_seconds=3600)
        with pytest.raises(Exception) as exc_info:
            svc.ingest(req)
        assert "Freshness gate" in str(exc_info.value)
        # No rows landed
        assert svc.audit("test_batch_001") == []

    def test_quality_threshold_rejects_low_quality(self, feeder):
        svc, models_mod = feeder
        rows = [{"balance": 100.0}]  # missing required 'address'
        req = _make_request(
            models_mod, rows,
            schema={"address": "str", "balance": "float"},
            required_fields=["address", "balance"],
            quality_threshold=0.8,
        )
        resp = svc.ingest(req)
        assert resp.rows_rejected >= 1


class TestGraphIsolation:
    def test_service_has_no_graph_mutation_methods(self, feeder):
        svc, _ = feeder
        graph_methods = [m for m in dir(svc) if any(
            kw in m.lower() for kw in ["neptune", "graph_write", "graph_mutate", "upsert_node", "upsert_edge"]
        )]
        assert graph_methods == [], f"Graph mutation methods found: {graph_methods}"

    def test_graph_isolation_flag_in_health(self, feeder):
        svc, _ = feeder
        health = svc.get_health()
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
    def test_rollback_removes_bronze_records(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        svc.ingest(req)
        assert len(svc.audit("test_batch_001")) == 2
        deleted = svc.rollback("test_batch_001")
        assert deleted >= 2
        assert len(svc.audit("test_batch_001")) == 0

    def test_rollback_unknown_tag_returns_zero(self, feeder):
        svc, _ = feeder
        deleted = svc.rollback("nonexistent_tag_xyz")
        assert deleted == 0

    def test_rollback_does_not_affect_other_tags(self, feeder):
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
        svc.ingest(req_a)
        svc.ingest(req_b)
        svc.rollback("test_batch_001")
        assert len(svc.audit("test_batch_002")) == 1


class TestSilverPromotion:
    def test_promote_valid_bronze_rows(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        svc.ingest(req)
        promoted = svc.promote_to_silver("test_batch_001")
        assert promoted >= 2

    def test_promote_unknown_tag_returns_zero(self, feeder):
        svc, _ = feeder
        promoted = svc.promote_to_silver("nonexistent_xyz")
        assert promoted == 0


class TestHealth:
    def test_health_ok_on_empty_store(self, feeder):
        svc, _ = feeder
        h = svc.get_health()
        assert h.status == "ok"
        assert h.total_bronze_records == 0
        assert h.graph_isolation_enforced is True

    def test_health_reflects_ingest(self, feeder):
        svc, models_mod = feeder
        rows = [{"address": "0xabc"}, {"address": "0xdef"}]
        req = _make_request(models_mod, rows)
        svc.ingest(req)
        h = svc.get_health()
        assert h.total_bronze_records == 2
        assert h.unique_source_tags == 1
