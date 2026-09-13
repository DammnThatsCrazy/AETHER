"""DB-free tests for the M7 ops metric surface (``services/data_exchange/metrics.py``).

The shared ``MetricsCollector`` is a module-global singleton shared across the
process, so these tests assert DELTAS of counter values (snapshot before/after)
rather than absolute counts — robust to any other test having incremented the
same counters earlier.

Asserts the authoritative ``METRIC_NAMES`` surface, that every ``record_*``
helper lands on the collector under its documented name, and that the
egress-finalization label remains bounded (an unknown disposition falls back to
``no_job_record`` instead of letting a raw tenant id / key explode cardinality).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.data_exchange import metrics as m  # noqa: E402
from shared.logger.logger import metrics as _collector  # noqa: E402


def _counters() -> dict[str, int]:
    snapshot = _collector.snapshot()
    return dict(snapshot.get("counters", {}))


def _delta(before: dict[str, int], key: str) -> int:
    return _counters().get(key, 0) - before.get(key, 0)


class TestMetricSurface:
    def test_metric_names_are_the_documented_family(self):
        assert "data_exchange_ops_expired_total" in m.METRIC_NAMES
        assert "data_exchange_ops_objects_deleted_total" in m.METRIC_NAMES
        assert "data_exchange_ops_orphans_deleted_total" in m.METRIC_NAMES
        assert "data_exchange_ops_reconcile_missing_total" in m.METRIC_NAMES
        assert "data_exchange_ops_reconcile_orphans_total" in m.METRIC_NAMES
        assert "data_exchange_ops_cleanup_refused_total" in m.METRIC_NAMES
        assert "data_exchange_ops_egress_finalized_total" in m.METRIC_NAMES
        assert "data_exchange_ops_legal_hold_blocked_total" in m.METRIC_NAMES
        assert "data_exchange_ops_sweep_errors_total" in m.METRIC_NAMES
        assert len(m.METRIC_NAMES) == 9

    def test_egress_dispositions_are_bounded(self):
        assert set(m.EGRESS_FINALIZED_DISPOSITIONS) == {
            "available",
            "failed",
            "in_flight",
            "success_without_bytes",
            "no_job_record",
        }

    def test_register_metrics_is_noop_and_returns_names(self):
        before = _counters()
        assert m.register_metrics() == m.METRIC_NAMES
        assert _counters() == before  # registration never mutates counters


class TestRecordHelpers:
    def test_expire_and_delete_records_land_on_collector(self):
        before = _counters()
        m.record_artifacts_expired(3)
        m.record_objects_deleted(2)
        m.record_orphan_objects_deleted(5)
        m.record_legal_hold_blocked()
        m.record_sweep_error()
        m.record_reconcile_missing(7)
        m.record_reconcile_orphans(1)
        m.record_cleanup_refused()
        assert _delta(before, "data_exchange_ops_expired_total") == 3
        assert _delta(before, "data_exchange_ops_objects_deleted_total") == 2
        assert _delta(before, "data_exchange_ops_orphans_deleted_total") == 5
        assert _delta(before, "data_exchange_ops_legal_hold_blocked_total") == 1
        assert _delta(before, "data_exchange_ops_sweep_errors_total") == 1
        assert _delta(before, "data_exchange_ops_reconcile_missing_total") == 7
        assert _delta(before, "data_exchange_ops_reconcile_orphans_total") == 1
        assert _delta(before, "data_exchange_ops_cleanup_refused_total") == 1

    def test_zero_counts_are_noops(self):
        before = _counters()
        m.record_artifacts_expired(0)
        m.record_reconcile_missing(0)
        m.record_orphan_objects_deleted(0)
        assert _counters() == before

    def test_egress_finalized_records_with_label(self):
        before = _counters()
        m.record_egress_finalized("available")
        m.record_egress_finalized("available")
        m.record_egress_finalized("in_flight")
        assert (
            _delta(before, "data_exchange_ops_egress_finalized_total{disposition=available}")
            == 2
        )
        assert (
            _delta(before, "data_exchange_ops_egress_finalized_total{disposition=in_flight}")
            == 1
        )

    def test_unknown_disposition_falls_back_to_no_job_record(self):
        # A hostile/raw label (tenant id, object key) must never reach the
        # collector as a new series — it collapses onto the bounded bucket.
        before = _counters()
        m.record_egress_finalized("tnt_evil/../../secret")
        m.record_egress_finalized(None)  # type: ignore[arg-type]
        assert (
            _delta(
                before,
                "data_exchange_ops_egress_finalized_total{disposition=no_job_record}",
            )
            == 2
        )

    def test_summary_selects_only_ops_family(self):
        # Populate an unrelated counter to prove the summary is selective.
        _collector.increment("some_unrelated_total")
        summary = m.ops_metrics_summary()
        selected = summary["data_exchange_ops"]
        assert all(key.split("{", 1)[0] in m.METRIC_NAMES for key in selected)
        assert not any("some_unrelated_total" in key for key in selected)
