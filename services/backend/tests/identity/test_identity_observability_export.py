from __future__ import annotations

import logging

from shared.logger.logger import MetricsCollector
from services.identity.observability import IdentityMetrics, IdentityTrace


def test_identity_metrics_export_bounded_counters_and_latency_histograms():
    collector = MetricsCollector()
    metrics = IdentityMetrics(collector=collector)

    metrics.record_source_identity_created()
    metrics.record_claim_created()
    metrics.record_resolution("resolved")
    metrics.record_resolution("provisional")
    metrics.record_resolution("review_required")
    metrics.record_resolution("conflicted")
    metrics.record_resolution("unexpected-caller-value")
    metrics.record_merge("auto")
    metrics.record_merge("manual")
    metrics.record_merge("blocked")
    metrics.record_split("candidate")
    metrics.record_split("executed")
    metrics.record_veto()
    metrics.record_cross_tenant_block()
    metrics.record_projection_restatement("queued")
    metrics.record_projection_restatement("failed")
    metrics.record_sdk_heartbeat()
    metrics.record_sdk_identify()
    metrics.record_connector_backfill()
    metrics.record_resolution_latency(12.5)
    metrics.record_restatement_latency(45.0)

    snapshot = collector.snapshot()
    assert snapshot["counters"]["identity.source_identity.created.count"] == 1
    assert snapshot["counters"]["identity.claim.created.count"] == 1
    assert snapshot["counters"]["identity.resolve.count"] == 5
    assert snapshot["counters"]["identity.resolve.resolved.count"] == 1
    assert snapshot["counters"]["identity.resolve.provisional.count"] == 1
    assert snapshot["counters"]["identity.resolve.review_required.count"] == 1
    assert snapshot["counters"]["identity.resolve.conflicted.count"] == 1
    assert "identity.resolve.other.count" not in snapshot["counters"]
    assert snapshot["counters"]["identity.merge.auto.count"] == 1
    assert snapshot["counters"]["identity.merge.manual.count"] == 1
    assert snapshot["counters"]["identity.merge.blocked.count"] == 1
    assert snapshot["counters"]["identity.split.candidate.count"] == 1
    assert snapshot["counters"]["identity.split.executed.count"] == 1
    assert snapshot["counters"]["identity.veto.count"] == 1
    assert snapshot["counters"]["identity.cross_tenant_block.count"] == 1
    assert snapshot["counters"]["identity.projection_restatement.queued.count"] == 1
    assert snapshot["counters"]["identity.projection_restatement.failed.count"] == 1
    assert snapshot["counters"]["sdk.heartbeat.received.count"] == 1
    assert snapshot["counters"]["sdk.identify.received.count"] == 1
    assert snapshot["counters"]["connector.backfill.identity_resolved.count"] == 1
    assert snapshot["histograms"]["identity.resolution.latency_ms"]["avg"] == 12.5
    assert snapshot["histograms"]["identity.restatement.latency_ms"]["avg"] == 45.0
    assert metrics.get_summary()["resolve_total"] == 5


def test_identity_trace_emits_correlated_pii_filtered_steps(caplog):
    trace = IdentityTrace("tenant-a", "sdk:web")

    with caplog.at_level(logging.INFO, logger="aether.identity.observability"):
        trace.identity_resolve("resolved", 0.91)
        trace.add_step("provider.event", {
            "source_identity_id": "source-1",
            "claim_count": 2,
            "email": "person@example.test",
            "raw_event": {"email": "person@example.test"},
            "event_name": "user@example.test",
        })

    summary = trace.get_trace_summary()
    events = [record for record in caplog.records if record.getMessage() == "identity.trace.step"]
    assert summary["trace_id"]
    assert len(events) == 2
    assert {event.identity_trace_id for event in events} == {summary["trace_id"]}
    assert [event.identity_trace_sequence for event in events] == [1, 2]
    assert events[0].identity_trace_details == {"outcome": "resolved", "confidence": 0.91}
    assert events[1].identity_trace_details == {"source_identity_id": "source-1", "claim_count": 2}
    assert "person@example.test" not in repr(events)
