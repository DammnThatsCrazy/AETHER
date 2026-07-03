"""Fraud evaluation pipeline — in-process load and throughput tests.

Validates that FraudEvaluationService meets its latency SLOs under concurrent
load using in-memory mocked repositories (no external dependencies).

SLO targets:
  Full evaluation (no TTL hit)   p95 < 200 ms
  TTL hit (cached return)        p95 < 20 ms
  50 concurrent evaluations      0 errors, all complete < 4 s wall-clock
  Failure isolation              repo exception → "monitor" decision, never "clear"

Run standalone:
  pytest tests/load/test_fraud_evaluation_load.py -v
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("fastapi", reason="Backend deps not installed")

os.environ.setdefault("AETHER_ENV", "local")

TENANT = "load-test-tenant"
CONCURRENCY = 50
ITERATIONS = 80
P95_FULL_MS = 200
P95_TTL_MS = 20
P99_CONCURRENT_MS = 4_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _percentile(latencies: list[float], p: int) -> float:
    sorted_l = sorted(latencies)
    idx = min(len(sorted_l) - 1, math.ceil(len(sorted_l) * p / 100) - 1)
    return sorted_l[idx]


def _make_service_with_mocks(existing_decision=None):
    """Return a FraudEvaluationService whose repositories are all mocked."""
    from services.fraud.evaluation import FraudEvaluationService

    svc = FraudEvaluationService.__new__(FraudEvaluationService)

    empty = AsyncMock(return_value=[])
    svc._sessions = AsyncMock()
    svc._sessions.list_for_entities = empty
    svc._wallets = AsyncMock()
    svc._wallets.find_many = empty
    svc._transfers = AsyncMock()
    svc._transfers.find_many = empty
    svc._delegations = AsyncMock()
    svc._delegations.find_many = empty
    svc._rewards = AsyncMock()
    svc._rewards.list_for_entities = empty
    svc._orders = AsyncMock()
    svc._orders.list_for_entities = empty
    svc._refunds = AsyncMock()
    svc._refunds.list_for_entities = empty

    svc._decisions = AsyncMock()
    svc._decisions.get_current_for_subject = AsyncMock(return_value=existing_decision)
    svc._decisions.create = AsyncMock(return_value={})
    svc._decisions.supersede = AsyncMock(return_value={})

    return svc


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_evaluation_latency_p95():
    """Full evaluation (no cached decision) must complete p95 < 200 ms."""
    svc = _make_service_with_mocks(existing_decision=None)
    latencies: list[float] = []

    for _ in range(ITERATIONS):
        t0 = time.monotonic()
        decision = await svc.evaluate_subject(
            tenant_id=TENANT,
            subject_type="entity",
            subject_id=f"e-{_uid()}",
            entity_id=f"e-{_uid()}",
        )
        latencies.append((time.monotonic() - t0) * 1000)
        assert decision.decision != "clear" or decision.evaluation_state == "evaluated"

    p95 = _percentile(latencies, 95)
    assert p95 < P95_FULL_MS, (
        f"Full evaluation p95={p95:.1f}ms exceeded SLO of {P95_FULL_MS}ms"
    )


@pytest.mark.asyncio
async def test_ttl_hit_latency_p95():
    """TTL cache path (existing decision within TTL) must complete p95 < 20 ms."""
    from datetime import datetime, timezone

    fresh_ts = datetime.now(timezone.utc).isoformat()
    cached = {
        "decision_id": _uid(),
        "tenant_id": TENANT,
        "subject_type": "entity",
        "subject_id": "cached-entity",
        "entity_id": "cached-entity",
        "decision": "monitor",
        "risk_score": 0.0,
        "risk_tier": "low",
        "evaluation_state": "evaluated",
        "evaluated_at": fresh_ts,
        "valid_from": fresh_ts,
        "status": "active",
        "review_state": "not_required",
        "signal_types": [],
        "reason_codes": [],
        "evidence_refs": [],
        "fraud_network_ids": [],
        "flow_trace_ids": [],
        "detector_versions": {},
        "model_versions": {},
        "policy_version": "v1",
        "machine_explanation": "",
        "metadata": {},
        "created_at": fresh_ts,
        "updated_at": fresh_ts,
    }
    svc = _make_service_with_mocks(existing_decision=cached)
    latencies: list[float] = []

    for _ in range(ITERATIONS):
        t0 = time.monotonic()
        decision = await svc.evaluate_subject(
            tenant_id=TENANT,
            subject_type="entity",
            subject_id="cached-entity",
        )
        latencies.append((time.monotonic() - t0) * 1000)
        assert decision.evaluation_state == "evaluated"

    p95 = _percentile(latencies, 95)
    assert p95 < P95_TTL_MS, (
        f"TTL-hit p95={p95:.1f}ms exceeded SLO of {P95_TTL_MS}ms"
    )


@pytest.mark.asyncio
async def test_concurrent_evaluation_throughput():
    """50 concurrent evaluations must all complete within 4 s wall-clock with 0 errors."""
    svc = _make_service_with_mocks(existing_decision=None)
    errors: list[Exception] = []

    async def _eval(i: int) -> float:
        t0 = time.monotonic()
        try:
            decision = await svc.evaluate_subject(
                tenant_id=TENANT,
                subject_type="entity",
                subject_id=f"concurrent-{i}-{_uid()}",
                entity_id=f"concurrent-{i}-{_uid()}",
            )
            assert decision.decision in ("allow", "monitor", "review", "block")
        except Exception as exc:
            errors.append(exc)
        return (time.monotonic() - t0) * 1000

    wall_start = time.monotonic()
    latencies = await asyncio.gather(*[_eval(i) for i in range(CONCURRENCY)])
    wall_ms = (time.monotonic() - wall_start) * 1000

    assert not errors, f"{len(errors)} error(s) during concurrent evaluation: {errors[:3]}"
    assert wall_ms < P99_CONCURRENT_MS, (
        f"50 concurrent evaluations took {wall_ms:.0f}ms, exceeded {P99_CONCURRENT_MS}ms"
    )


@pytest.mark.asyncio
async def test_failure_never_becomes_clear():
    """When repository raises, the decision must NOT be 'clear' — it must be 'monitor'."""
    from services.fraud.evaluation import FraudEvaluationService

    svc = FraudEvaluationService.__new__(FraudEvaluationService)
    svc._decisions = AsyncMock()
    svc._decisions.get_current_for_subject = AsyncMock(return_value=None)
    svc._decisions.create = AsyncMock(return_value={})
    svc._decisions.supersede = AsyncMock(return_value={})

    # All data repos raise
    for attr in ("_sessions", "_wallets", "_transfers", "_delegations", "_rewards", "_orders", "_refunds"):
        mock = AsyncMock()
        for method in ("list_for_entities", "find_many"):
            getattr(mock, method).side_effect = RuntimeError("DB unavailable")
        setattr(svc, attr, mock)

    for _ in range(10):
        decision = await svc.evaluate_subject(
            tenant_id=TENANT,
            subject_type="entity",
            subject_id=f"failing-{_uid()}",
        )
        assert decision.decision == "monitor", (
            "Evaluation failure must produce 'monitor', never 'allow'/'review'/'block' — "
            f"got: {decision.decision!r}, state: {decision.evaluation_state!r}"
        )
        assert decision.evaluation_state == "failed"


@pytest.mark.asyncio
async def test_tenant_isolation_under_load():
    """Concurrent evaluations across two tenants must not cross-contaminate."""
    svc = _make_service_with_mocks(existing_decision=None)

    results: dict[str, list[str]] = {"tenant-a": [], "tenant-b": []}

    async def _eval(tenant: str, i: int):
        subject_id = f"{tenant}-entity-{i}"
        decision = await svc.evaluate_subject(
            tenant_id=tenant,
            subject_type="entity",
            subject_id=subject_id,
        )
        results[tenant].append(decision.tenant_id)

    await asyncio.gather(*[
        _eval("tenant-a", i) for i in range(20)
    ] + [
        _eval("tenant-b", i) for i in range(20)
    ])

    assert all(t == "tenant-a" for t in results["tenant-a"]), "tenant-a got wrong tenant_id"
    assert all(t == "tenant-b" for t in results["tenant-b"]), "tenant-b got wrong tenant_id"
