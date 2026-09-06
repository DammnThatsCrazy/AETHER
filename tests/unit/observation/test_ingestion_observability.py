"""WS-E 1 — ingestion funnel observability ledger (flag-gated, default OFF).

Unit tests for :mod:`services.ingestion.ingestion_observability`:

* flag OFF = zero recording / no-op; the operator snapshots report
  ``enabled: false`` with zeroed counters (stable health surface, never errors).
* flag ON  = per-stage funnel buckets (received / validated / bronze + the
  disposition split accepted / duplicate / rejected / degraded), rollup, and
  the blueprint §17 ladder vocabulary with ``monitored`` truth per stage.
* Observation Inspector traces: one observation's stage spans, outcome,
  ``complete`` semantics, bounded store, and lookups by ``tenant:event``.
* ``pipeline_snapshot()`` health tri-state: disabled / healthy / degraded.

Recording is a pure side channel — these tests assert it never rejects and that
the flag OFF path costs nothing but a boolean read.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.ingestion import ingestion_observability as obs


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a pristine funnel + trace store and a clean flag setting.

    The module keeps in-process singletons (mirroring the MetricsCollector
    convention); we rebind them to keep tests independent, and replace the
    module's ``settings`` with a minimal fake so we never depend on the shared
    config singleton's generation across test modules.
    """
    monkeypatch.setattr(obs, "_funnel", obs.IngestionFunnel())
    monkeypatch.setattr(obs, "_traces", obs.TraceStore())
    monkeypatch.setattr(
        obs,
        "settings",
        SimpleNamespace(
            ingestion_observability=SimpleNamespace(enabled=False),
        ),
    )


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        obs,
        "settings",
        SimpleNamespace(
            ingestion_observability=SimpleNamespace(enabled=True),
        ),
    )


def _record_ok_and_bad() -> None:
    """Record a canonical 2-event scenario: one accepted, one rejected."""
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", event_type="track",
        stage="received", path="sdk",
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-bad", event_type="page_view",
        stage="received", path="sdk",
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", stage="validated",
        status="accepted", path="sdk",
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-bad", stage="validated",
        status="rejected", path="sdk",
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", stage="bronze",
        status="accepted", path="sdk",
    )


# ── Flag OFF: no-op, zeroed snapshots ────────────────────────────────────────

def test_flag_off_records_nothing_and_snapshots_report_disabled():
    _record_ok_and_bad()
    obs.record_degraded(tenant_id="t1", event_id="e-ok")

    snap = obs.funnel_snapshot()
    assert snap["enabled"] is False
    assert snap["rollup"] == {
        "received": 0, "accepted": 0, "duplicates": 0, "rejected": 0, "degraded": 0,
    }

    pipe = obs.pipeline_snapshot()
    assert pipe["status"] == "disabled"
    assert pipe["enabled"] is False
    assert pipe["pipeline"]["received"] == 0

    assert obs.trace_snapshot("t1", "e-ok") is None
    assert obs.recent_trace_snapshot() == []


def test_flag_off_recording_is_a_noop_not_a_rejection():
    """OFF must never reject — recording returns None and changes nothing."""
    _record_ok_and_bad()
    # Guard: the whole ladder is present but no stage shows a count.
    stages = obs.funnel_snapshot()["stages"]
    assert len(stages) == len(obs.FUNNEL_STAGES)
    assert all(s["total"] == 0 for s in stages)


# ── Flag ON: funnel rollup + per-stage buckets ───────────────────────────────

def test_flag_on_records_funnel_rollup_and_monitored_ladder(monkeypatch):
    _enable(monkeypatch)
    _record_ok_and_bad()
    obs.record_degraded()

    snap = obs.funnel_snapshot()
    assert snap["enabled"] is True
    assert snap["rollup"] == {
        "received": 2, "accepted": 1, "duplicates": 0, "rejected": 1, "degraded": 1,
    }
    assert snap["instrumentation"]["monitored_stages"] == sorted(
        obs._MONITORED_STAGES
    )

    by_stage = {s["stage"]: s for s in snap["stages"]}
    assert by_stage["received"]["total"] == 2
    assert by_stage["received"]["by_status"] == {"observed": 2}
    assert by_stage["validated"]["by_status"] == {"accepted": 1, "rejected": 1}
    assert by_stage["bronze"]["by_status"] == {"accepted": 1}
    assert by_stage["normalized"]["total"] == 0  # recorded by the worker slice
    # Declared-but-unmonitored stages keep ladder slots and render as monitored=false.
    assert by_stage["resolved"]["monitored"] is False
    assert by_stage["metrics_findings"]["monitored"] is False
    assert by_stage["received"]["monitored"] is True


def test_flag_on_stage_order_and_vocabulary():
    assert list(obs.FUNNEL_STAGES) == [
        "raw", "received", "validated", "bronze", "normalized",
        "resolved", "relationships", "graph_mutations", "projections",
        "metrics_findings",
    ]
    assert obs._MONITORED_STAGES <= set(obs.FUNNEL_STAGES)


def test_record_stage_ignores_unknown_stage_and_disposition(monkeypatch):
    _enable(monkeypatch)
    obs.record_stage(tenant_id="t1", event_id="e-x", stage="not_a_stage")
    obs.record_stage(tenant_id="t1", event_id="e-x", stage="received", status="bogus")
    snap = obs.funnel_snapshot()
    assert snap["rollup"]["received"] == 1  # the bogus disposition normalized
    assert snap["stages"][1]["by_status"] == {"observed": 1}


# ── Observation Inspector traces ─────────────────────────────────────────────

def test_trace_records_spans_outcome_and_complete(monkeypatch):
    _enable(monkeypatch)
    _record_ok_and_bad()

    ok = obs.trace_snapshot("t1", "e-ok")
    assert ok is not None
    assert ok["event_id"] == "e-ok"
    assert ok["event_type"] == "track"
    assert ok["path"] == "sdk"
    assert ok["outcome"] == "accepted"
    assert ok["complete"] is True
    stages = [sp["stage"] for sp in ok["spans"]]
    assert stages == ["received", "validated", "bronze"]
    assert ok["spans"][0]["status"] == "observed"
    assert ok["spans"][1]["status"] == "accepted"

    bad = obs.trace_snapshot("t1", "e-bad")
    assert bad["outcome"] == "rejected"
    assert bad["complete"] is True
    assert [sp["stage"] for sp in bad["spans"]] == ["received", "validated"]

    assert obs.trace_snapshot("t1", "nope") is None
    assert obs.trace_snapshot("t2", "e-ok") is None  # tenant-scoped key


def test_record_degraded_appends_annotated_bronze_span(monkeypatch):
    _enable(monkeypatch)
    obs.record_stage(
        tenant_id="t1", event_id="e-1", stage="received", path="sdk"
    )
    obs.record_degraded(tenant_id="t1", event_id="e-1")

    trace = obs.trace_snapshot("t1", "e-1")
    assert trace is not None
    # accepted A-side, then flag fail-open degrade to the flat SDK path.
    assert trace["spans"][-1]["stage"] == "bronze"
    assert trace["spans"][-1]["status"] == "degraded"
    assert "envelope_or_gateway_degraded" in trace["spans"][-1]["detail"]
    assert obs.funnel_snapshot()["rollup"]["degraded"] == 1


def test_trace_store_is_bounded(monkeypatch):
    _enable(monkeypatch)
    for i in range(5):
        event_id = f"evt-{i}"
        obs.record_stage(
            tenant_id="t1", event_id=event_id, stage="received",
            status="observed", path="sdk",
        )
    assert len(obs._traces) == 5
    recent = obs.recent_trace_snapshot(limit=2)
    assert len(recent) == 2
    assert recent[-1]["event_id"] == "evt-4"
    # Full browse returns newest-last in start order.
    full = obs.recent_trace_snapshot(limit=100)
    assert [t["event_id"] for t in full] == [f"evt-{i}" for i in range(5)]


# ── pipeline_snapshot health tri-state ───────────────────────────────────────

def test_pipeline_snapshot_healthy_when_no_rejections(monkeypatch):
    _enable(monkeypatch)
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", stage="received", path="sdk"
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", stage="validated",
        status="accepted", path="sdk",
    )
    obs.record_stage(
        tenant_id="t1", event_id="e-ok", stage="bronze",
        status="accepted", path="sdk",
    )
    pipe = obs.pipeline_snapshot()
    assert pipe["status"] == "healthy"
    assert pipe["enabled"] is True
    assert pipe["probe"] == "ingestion-pipeline"
    assert pipe["pipeline"] == {
        "received": 1, "accepted": 1, "duplicates": 0, "rejected": 0, "degraded": 0,
    }


def test_pipeline_snapshot_degraded_on_rejection_or_degrade(monkeypatch):
    _enable(monkeypatch)
    _record_ok_and_bad()
    assert obs.pipeline_snapshot()["status"] == "degraded"

    # Fresh: degrade alone also flips degraded.
    monkeypatch.setattr(obs, "_funnel", obs.IngestionFunnel())
    obs.record_degraded()
    assert obs.pipeline_snapshot()["status"] == "degraded"
