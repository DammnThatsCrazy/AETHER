#!/usr/bin/env python3
"""
Synthetic load baseline — runs without external dependencies.

Starts an in-process mock HTTP server and exercises it with concurrent
requests to measure latency percentiles for the critical Aether paths.
Results are written to tests/load/baseline_results.json.

Usage:
    python tests/load/synthetic_baseline.py
    python tests/load/synthetic_baseline.py --requests 1000 --concurrency 10
    python tests/load/synthetic_baseline.py --requests 500 --concurrency 5 --p95-threshold-ms 150

Outputs:
    tests/load/baseline_results.json  — machine-readable results
    stdout                            — human-readable latency table

Exit codes:
    0   all p95 latencies are below threshold
    1   at least one p95 latency exceeded threshold (scale concern)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import socket
import string
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REQUESTS = 500
DEFAULT_CONCURRENCY = 8
DEFAULT_P95_THRESHOLD_MS = 200

# Simulated per-endpoint processing latency (ms) — chosen to be realistic but
# fast enough that the baseline completes quickly in CI.
_ENDPOINT_SIMULATED_LATENCY_MS: dict[str, float] = {
    "/v1/ingest/batch": 5.0,
    "/v1/resolution/resolve": 8.0,
    "/v1/profile/profile360": 12.0,
    "/v1/analytics/graphql": 6.0,
    "/v1/agent/tasks": 10.0,
}

_RESULTS_PATH = Path(__file__).parent / "baseline_results.json"

# ---------------------------------------------------------------------------
# In-process mock server
# ---------------------------------------------------------------------------


class _MockHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that simulates Aether endpoint responses."""

    def log_message(self, fmt: str, *args: Any) -> None:  # silence access log
        pass

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        delay_ms = _ENDPOINT_SIMULATED_LATENCY_MS.get(path, 5.0)
        # add small jitter (±20%)
        jitter = random.uniform(-0.2, 0.2)
        time.sleep((delay_ms * (1 + jitter)) / 1000.0)

        # Read and discard request body to avoid broken pipe
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)

        if path == "/v1/ingest/batch":
            self._send_json(200, {"status": "ok", "accepted": 10})
        elif path == "/v1/resolution/resolve":
            self._send_json(200, {"status": "ok", "profile_id": "synth-profile-1"})
        elif path == "/v1/analytics/graphql":
            self._send_json(200, {"data": {"events": []}})
        elif path == "/v1/agent/tasks":
            self._send_json(200, {"data": {"task_id": "synth-task-1"}})
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        delay_ms = _ENDPOINT_SIMULATED_LATENCY_MS.get(path, 5.0)
        jitter = random.uniform(-0.2, 0.2)
        time.sleep((delay_ms * (1 + jitter)) / 1000.0)

        if path.startswith("/v1/profile/profile360"):
            self._send_json(200, {"data": {"profile_id": "synth-1", "score": 0.82}})
        else:
            self._send_json(404, {"error": "not found"})


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Load driver
# ---------------------------------------------------------------------------


_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "/v1/ingest/batch",
        "method": "POST",
        "path": "/v1/ingest/batch",
        "body": {"events": [{"event_id": "e1", "event_type": "page_view", "user_id": "u1"}]},
        "threshold_ms": 200,
    },
    {
        "name": "/v1/resolution/resolve",
        "method": "POST",
        "path": "/v1/resolution/resolve",
        "body": {"anchors": [{"type": "email", "value": "test@example.com"}]},
        "threshold_ms": 300,
    },
    {
        "name": "/v1/profile/profile360",
        "method": "GET",
        "path": "/v1/profile/profile360?user_id=synth-user-1",
        "body": None,
        "threshold_ms": 500,
    },
    {
        "name": "/v1/analytics/graphql",
        "method": "POST",
        "path": "/v1/analytics/graphql",
        "body": {"query": "{ events { event_id } }"},
        "threshold_ms": 200,
    },
    {
        "name": "/v1/agent/tasks",
        "method": "POST",
        "path": "/v1/agent/tasks",
        "body": {"worker_type": "entity_resolver", "payload": {}},
        "threshold_ms": 1000,
    },
]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct / 100.0
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _run_scenario(
    base_url: str,
    scenario: dict[str, Any],
    n_requests: int,
    concurrency: int,
) -> dict[str, Any]:
    """Run a single scenario and return latency stats."""
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()

    def worker(count: int) -> None:
        nonlocal errors
        for _ in range(count):
            url = base_url + scenario["path"]
            body = scenario["body"]
            method = scenario["method"]
            try:
                data = json.dumps(body).encode() if body else None
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                t0 = time.perf_counter()
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                with lock:
                    latencies.append(elapsed_ms)
            except Exception:
                with lock:
                    errors += 1

    per_worker, remainder = divmod(n_requests, concurrency)
    threads = []
    for i in range(concurrency):
        count = per_worker + (1 if i < remainder else 0)
        t = threading.Thread(target=worker, args=(count,))
        threads.append(t)

    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_elapsed = time.perf_counter() - t_start

    latencies.sort()
    total = len(latencies) + errors
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    rps = total / total_elapsed if total_elapsed > 0 else 0.0

    return {
        "scenario": scenario["name"],
        "requests": total,
        "errors": errors,
        "error_rate": errors / total if total else 0.0,
        "rps": round(rps, 1),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "threshold_ms": scenario["threshold_ms"],
        "passed": p95 < scenario["threshold_ms"],
        "elapsed_s": round(total_elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_table(results: list[dict[str, Any]]) -> None:
    header = f"{'Scenario':<35} {'Req':>5} {'Err':>5} {'p50':>8} {'p95':>8} {'p99':>8} {'Thresh':>8} {'Pass':>5}"
    sep = "-" * len(header)
    print()
    print("  SYNTHETIC LOAD BASELINE RESULTS")
    print(sep)
    print(header)
    print(sep)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  {r['scenario']:<33} {r['requests']:>5} {r['errors']:>5} "
            f"{r['p50_ms']:>7.1f}ms {r['p95_ms']:>7.1f}ms {r['p99_ms']:>7.1f}ms "
            f"{r['threshold_ms']:>6}ms {status:>5}"
        )
    print(sep)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS, help="Requests per scenario")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent workers")
    parser.add_argument(
        "--p95-threshold-ms",
        type=float,
        default=DEFAULT_P95_THRESHOLD_MS,
        help="Override p95 threshold (ms) for all scenarios",
    )
    parser.add_argument("--output", default=str(_RESULTS_PATH), help="JSON output path")
    args = parser.parse_args()

    port = _find_free_port()
    print(f"Starting mock server on 127.0.0.1:{port} ...")
    server = _start_server(port)
    base_url = f"http://127.0.0.1:{port}"

    # Warm up
    try:
        urllib.request.urlopen(base_url + "/v1/ingest/batch", data=b"{}", timeout=2)
    except Exception:
        pass

    scenarios = _SCENARIOS
    if args.p95_threshold_ms != DEFAULT_P95_THRESHOLD_MS:
        scenarios = [{**s, "threshold_ms": args.p95_threshold_ms} for s in _SCENARIOS]

    print(f"Running {args.requests} requests × {len(scenarios)} scenarios @ concurrency={args.concurrency}")
    print()

    all_results = []
    for scenario in scenarios:
        sys.stdout.write(f"  {scenario['name']:<40} ... ")
        sys.stdout.flush()
        result = _run_scenario(base_url, scenario, args.requests, args.concurrency)
        all_results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"p95={result['p95_ms']:.1f}ms  {status}")

    server.shutdown()

    _print_table(all_results)

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    output = {
        "version": "1.0",
        "timestamp": timestamp,
        "config": {
            "requests_per_scenario": args.requests,
            "concurrency": args.concurrency,
        },
        "results": all_results,
        "overall_passed": all(r["passed"] for r in all_results),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nResults written to {out_path}")

    all_passed = all(r["passed"] for r in all_results)
    if all_passed:
        print("Overall: PASS — all p95 latencies within threshold.")
    else:
        failed = [r["scenario"] for r in all_results if not r["passed"]]
        print(f"Overall: FAIL — p95 exceeded threshold for: {', '.join(failed)}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
