"""CI-gated test for the synthetic load-data generator (no Locust needed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gen():
    spec = importlib.util.spec_from_file_location("gen_synth", ROOT / "tests/load/generate_synthetic.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_steady_records_are_well_formed():
    mod = _gen()
    records = list(mod.generate(tenants=5, events=50, scenario="steady"))
    assert len(records) == 50
    r = records[0]
    assert {"event_id", "tenant_id", "event_type", "user_id", "session_id", "timestamp"} <= set(r)
    assert len({rec["tenant_id"] for rec in records}) == 5


def test_high_cardinality_unique_users():
    mod = _gen()
    records = list(mod.generate(tenants=2, events=100, scenario="high_cardinality"))
    assert len({r["user_id"] for r in records}) == 100  # every event a new user


def test_duplicate_spike_repeats_event_ids():
    mod = _gen()
    records = list(mod.generate(tenants=2, events=100, scenario="duplicate_spike"))
    assert len({r["event_id"] for r in records}) < 100  # duplicates present


def test_scenarios_enumerated():
    mod = _gen()
    assert set(mod.SCENARIOS) == {"steady", "high_cardinality", "duplicate_spike", "schema_drift", "out_of_order"}
