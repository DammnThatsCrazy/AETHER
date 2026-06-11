#!/usr/bin/env python3
"""
Load smoke gate — runs a short Locust headless burst against a local backend
and fails if key SLO thresholds are breached.

Usage:
    python scripts/load_smoke.py [--host http://localhost:8000] [--users 20] [--duration 30]

Exit codes:
    0  all thresholds passed
    1  one or more thresholds breached (see output)
    2  backend unreachable or Locust unavailable

Thresholds (CI smoke gate — not staging signoff):
    POST /v1/batch [10-events]  p95 < 500ms   error_rate < 5%
    GET  /sdk/identity/resolve  p95 < 800ms   error_rate < 5%
    overall                                   error_rate < 5%
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

THRESHOLDS: dict[str, dict] = {
    "/v1/batch [10-events]": {"p95_ms": 500, "error_pct": 5.0},
    "/sdk/identity/resolve [anon]": {"p95_ms": 800, "error_pct": 5.0},
    "/sdk/identity/resolve [user]": {"p95_ms": 800, "error_pct": 5.0},
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
    overall_error_pct = (total_fails / total_reqs * 100) if total_reqs else 0.0

    overall_thresh = THRESHOLDS.get("_overall_", {})
    if overall_error_pct > overall_thresh.get("error_pct", 100):
        failures.append(
            f"OVERALL error rate {overall_error_pct:.1f}% > {overall_thresh['error_pct']}%"
        )

    for row in rows:
        name = row.get("Name", "")
        if name == "Aggregated":
            continue
        thresh = THRESHOLDS.get(name)
        if not thresh:
            continue

        reqs = int(row.get("Request Count", 0) or 0)
        fails = int(row.get("Failure Count", 0) or 0)
        p95 = float(row.get("95%", 0) or 0)
        error_pct = (fails / reqs * 100) if reqs else 0.0

        if "p95_ms" in thresh and p95 > thresh["p95_ms"]:
            failures.append(f"{name}: p95 {p95:.0f}ms > {thresh['p95_ms']}ms")
        if "error_pct" in thresh and error_pct > thresh["error_pct"]:
            failures.append(f"{name}: error rate {error_pct:.1f}% > {thresh['error_pct']}%")

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
        _run_locust(args.host, args.users, args.duration, csv_prefix)
        rows = _parse_stats(csv_prefix)

    if not rows:
        print("[load-smoke] WARNING: no stats produced — Locust may not be installed")
        return 2

    failures = _check_thresholds(rows)

    result = {
        "host": args.host,
        "users": args.users,
        "duration_s": args.duration,
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
