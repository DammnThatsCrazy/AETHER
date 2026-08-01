#!/usr/bin/env python3
"""
Load smoke gate — runs a short Locust headless burst against a local backend
and fails if key SLO thresholds are breached.

Usage:
    python scripts/load_smoke.py [--host http://localhost:8000] [--users 20] [--duration 30]

Exit codes:
    0  all thresholds passed, real traffic was observed, and Locust exited cleanly
    1  one or more thresholds breached, no traffic was observed, an endpoint
       had no configured threshold, or Locust itself exited non-zero
    2  backend unreachable or Locust unavailable

Thresholds (CI smoke gate — not staging signoff):
    POST /v1/batch [10-events]  p95 < 500ms   error_rate < 5%
    GET  /sdk/identity/resolve  p95 < 800ms   error_rate < 5%
    overall                                   error_rate < 5%

Every endpoint exercised by tests/load/locustfile.py MUST have a threshold
entry above (or be listed in ALLOWED_UNTHRESHOLDED below with a documented
reason) — an endpoint with no configured threshold is a silent monitoring
gap, not a pass.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The smoke gate deliberately exercises a single Locust user class
# (LOCUST_USER_CLASS below) rather than the full production-shaped
# locustfile — that keeps the set of exercised request names small,
# fixed, and enumerable so every one of them can carry a real threshold.
# `IngestHeavyUser` mixes BatchIngestTasks + IdentityResolveTasks, which
# together cover the two SLA-carrying paths this gate exists to protect:
# batch event ingest and SDK identity resolution.
LOCUST_USER_CLASS = "IngestHeavyUser"

THRESHOLDS: dict[str, dict] = {
    "/v1/ingest/events/batch [small-10]": {"p95_ms": 500, "error_pct": 5.0},
    "/v1/ingest/events/batch [medium-50]": {"p95_ms": 800, "error_pct": 5.0},
    "/v1/ingest/events/batch [duplicate]": {"p95_ms": 500, "error_pct": 5.0},
    "/v1/ingest/events/batch [schema-rejected]": {"p95_ms": 500, "error_pct": 5.0},
    "/v1/ingest/feed [feed-20]": {"p95_ms": 500, "error_pct": 5.0},
    "/sdk/identity/resolve [1-anchor]": {"p95_ms": 800, "error_pct": 5.0},
    "/sdk/identity/resolve [3-anchors]": {"p95_ms": 800, "error_pct": 5.0},
    "/sdk/identity/resolve [5-anchors]": {"p95_ms": 1000, "error_pct": 5.0},
    "/sdk/identity/resolve [anon-to-known]": {"p95_ms": 800, "error_pct": 5.0},
    "_overall_": {"error_pct": 5.0},
}


def _wait_for_backend(host: str, timeout: int = 10) -> bool:
    url = f"{host}/v1/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(1)
    return False


def _run_locust(host: str, users: int, duration: int, csv_prefix: str) -> int:
    cmd = [
        sys.executable, "-m", "locust",
        "-f", str(ROOT / "tests/load/locustfile.py"),
        "--host", host,
        "--headless",
        "-u", str(users),
        "-r", str(max(1, users // 5)),
        "--run-time", f"{duration}s",
        "--csv", csv_prefix,
        "--only-summary",
        "--loglevel", "WARNING",
        "--users", str(users),
        LOCUST_USER_CLASS,
    ]
    return subprocess.call(cmd, cwd=ROOT)


def _parse_stats(csv_prefix: str) -> list[dict]:
    stats_file = f"{csv_prefix}_stats.csv"
    if not Path(stats_file).exists():
        return []
    rows = []
    with open(stats_file, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _check_thresholds(rows: list[dict]) -> list[str]:
    failures: list[str] = []

    total_reqs = sum(int(r.get("Request Count", 0) or 0) for r in rows if r.get("Name") != "Aggregated")
    total_fails = sum(int(r.get("Failure Count", 0) or 0) for r in rows if r.get("Name") != "Aggregated")

    # Zero observed traffic is never a pass. Locust can write a stats CSV
    # containing only the synthetic "Aggregated" row (or per-endpoint rows
    # that are all zero-count) when it never actually sent a request — e.g.
    # spawning took longer than --run-time, or every connection was refused
    # before a request left the client. A 0/0 error-rate default would read
    # as a clean 0.0% and silently pass; treat "nothing was observed" as a
    # hard failure instead.
    if total_reqs == 0:
        failures.append(
            "No requests were observed during the load-smoke run (0 total "
            "requests) — the gate cannot certify anything and is treated as "
            "a failure, not a pass."
        )
        return failures

    overall_error_pct = (total_fails / total_reqs * 100) if total_reqs else 0.0

    overall_thresh = THRESHOLDS.get("_overall_", {})
    if overall_error_pct > overall_thresh.get("error_pct", 100):
        failures.append(
            f"OVERALL error rate {overall_error_pct:.1f}% > {overall_thresh['error_pct']}%"
        )

    exercised_names: set[str] = set()
    for row in rows:
        name = row.get("Name", "")
        if name == "Aggregated":
            continue
        exercised_names.add(name)

        reqs = int(row.get("Request Count", 0) or 0)
        fails = int(row.get("Failure Count", 0) or 0)
        p95 = float(row.get("95%", 0) or 0)
        error_pct = (fails / reqs * 100) if reqs else 0.0

        thresh = THRESHOLDS.get(name)
        if not thresh:
            # An endpoint the run actually exercised but that carries no
            # configured threshold is a monitoring gap, not a free pass.
            failures.append(
                f"{name}: no threshold configured in THRESHOLDS "
                f"({reqs} request(s) observed) — add one or the SLO for "
                f"this endpoint is unenforced"
            )
            continue

        if reqs == 0:
            # A thresholded endpoint that was never exercised proves
            # nothing about its SLO; treat it the same as a breach.
            failures.append(f"{name}: 0 requests observed — endpoint was never exercised")
            continue

        if "p95_ms" in thresh and p95 > thresh["p95_ms"]:
            failures.append(f"{name}: p95 {p95:.0f}ms > {thresh['p95_ms']}ms")
        if "error_pct" in thresh and error_pct > thresh["error_pct"]:
            failures.append(f"{name}: error rate {error_pct:.1f}% > {thresh['error_pct']}%")

    missing = set(THRESHOLDS) - {"_overall_"} - exercised_names
    for name in sorted(missing):
        failures.append(f"{name}: configured threshold never appeared in the run's stats output")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Load smoke gate")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--json-out", help="Write results JSON to this path")
    args = parser.parse_args()

    print(f"[load-smoke] checking backend at {args.host} ...")
    if not _wait_for_backend(args.host):
        print(f"[load-smoke] ERROR: backend at {args.host} is not reachable — skipping smoke gate")
        return 2

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_prefix = os.path.join(tmpdir, "smoke")
        print(f"[load-smoke] running {args.users} users for {args.duration}s ...")
        locust_rc = _run_locust(args.host, args.users, args.duration, csv_prefix)
        rows = _parse_stats(csv_prefix)

    if not rows:
        print("[load-smoke] ERROR: no stats produced — Locust may not be installed or crashed before writing results")
        return 2

    failures = _check_thresholds(rows)

    # The Locust process's own exit code matters independently of the stats
    # it managed to write: a non-zero exit (crash, invalid CLI usage, worker
    # failure) must fail the gate even if the partial stats it wrote happen
    # to look clean.
    if locust_rc != 0:
        failures.append(f"locust exited with non-zero status {locust_rc}")

    result = {
        "host": args.host,
        "users": args.users,
        "duration_s": args.duration,
        "locust_exit_code": locust_rc,
        "rows": rows,
        "failures": failures,
        "passed": len(failures) == 0,
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2))

    if failures:
        print("[load-smoke] FAILED — threshold breaches:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1

    print(f"[load-smoke] PASSED — {len(rows)} endpoint(s) within thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
