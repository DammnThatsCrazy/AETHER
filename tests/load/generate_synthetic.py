#!/usr/bin/env python3
"""Synthetic data generator for load/scale testing.

Deterministic, dependency-free generator of synthetic tenants, users, and SDK
events for load profiles. Emits NDJSON (one JSON object per line) so it can feed
a Locust/k6 harness or a bulk ingest. No real data.

Usage:
  python tests/load/generate_synthetic.py --tenants 10 --events 1000 > events.ndjson
  python tests/load/generate_synthetic.py --scenario duplicate_spike --events 5000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone

EVENT_TYPES = ("page_view", "click", "identify", "purchase", "wallet", "support_ticket")
SCENARIOS = ("steady", "high_cardinality", "duplicate_spike", "schema_drift", "out_of_order")


def _id(prefix: str, n: int) -> str:
    return f"{prefix}_{hashlib.sha256(f'{prefix}{n}'.encode()).hexdigest()[:12]}"


def generate(tenants: int, events: int, scenario: str):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(events):
        tenant = _id("tenant", i % max(1, tenants))
        # high_cardinality → unique user per event; else reuse a small pool.
        user_n = i if scenario == "high_cardinality" else i % 500
        evt_type = EVENT_TYPES[i % len(EVENT_TYPES)]
        event_id = _id("evt", 0 if scenario == "duplicate_spike" and i % 3 else i)
        ts = base + timedelta(seconds=(-i if scenario == "out_of_order" else i))
        props = {"n": i}
        if scenario == "schema_drift" and i % 100 == 0:
            props = {"renamed_field": i}  # simulate a drifted payload shape
        yield {
            "event_id": event_id,
            "tenant_id": tenant,
            "event_type": evt_type,
            "user_id": _id("user", user_n),
            "session_id": _id("sess", user_n),
            "properties": props,
            "timestamp": ts.isoformat(),
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenants", type=int, default=10)
    p.add_argument("--events", type=int, default=1000)
    p.add_argument("--scenario", choices=SCENARIOS, default="steady")
    args = p.parse_args()
    for record in generate(args.tenants, args.events, args.scenario):
        sys.stdout.write(json.dumps(record) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
