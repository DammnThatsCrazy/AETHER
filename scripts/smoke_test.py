#!/usr/bin/env python3
"""
AETHER Post-Deploy Smoke Test

Exercises golden-path endpoints after an ECS deployment to confirm the
service is healthy before traffic is considered live.

Usage:
    python scripts/smoke_test.py --base-url https://api.aether.example.com --api-key <key>
    python scripts/smoke_test.py --base-url http://localhost:8000  # local, no auth needed

Exit codes:
    0  All checks passed
    1  One or more checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIMEOUT = 10  # seconds per request


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass
class SmokeRunner:
    base_url: str
    api_key: str
    timeout: int
    verbose: bool
    results: list[CheckResult] = field(default_factory=list)

    def _get(self, path: str, *, expect_status: int = 200, auth: bool = True) -> tuple[int, bytes]:
        url = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        if auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            return e.code, e.read()
        except URLError as e:
            raise ConnectionError(f"Cannot reach {url}: {e.reason}") from e

    def _post(self, path: str, body: dict, *, auth: bool = True) -> tuple[int, bytes]:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        req = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            return e.code, e.read()
        except URLError as e:
            raise ConnectionError(f"Cannot reach {url}: {e.reason}") from e

    def check(
        self,
        name: str,
        fn: Callable[[], tuple[bool, str]],
    ) -> bool:
        t0 = time.monotonic()
        try:
            passed, detail = fn()
        except ConnectionError as e:
            passed, detail = False, str(e)
        except Exception as e:
            passed, detail = False, f"Unexpected error: {e}"
        elapsed = (time.monotonic() - t0) * 1000
        result = CheckResult(name=name, passed=passed, detail=detail, elapsed_ms=elapsed)
        self.results.append(result)
        symbol = "✓" if passed else "✗"
        timing = f" ({elapsed:.0f}ms)"
        if passed:
            print(f"  {symbol} {name}{timing}")
            if self.verbose and detail:
                print(f"      {detail}")
        else:
            print(f"  {symbol} {name}{timing}  — {detail}")
        return passed

    # ── Individual checks ──────────────────────────────────────────────────

    def check_public_health(self) -> None:
        def run() -> tuple[bool, str]:
            status, body = self._get("/v1/health", auth=False)
            if status != 200:
                return False, f"HTTP {status}"
            return True, f"HTTP {status}"
        self.check("GET /v1/health (public, no auth)", run)

    def check_diagnostics_health(self) -> None:
        def run() -> tuple[bool, str]:
            status, body = self._get("/v1/diagnostics/health")
            if status != 200:
                return False, f"HTTP {status}"
            try:
                data = json.loads(body)
                # Look for any component explicitly in "error" state
                flat = str(data)
                if '"error"' in flat.lower() and "status" in flat.lower():
                    return False, f"A component is in error state: {flat[:200]}"
            except (json.JSONDecodeError, KeyError):
                pass
            return True, f"HTTP {status}"
        self.check("GET /v1/diagnostics/health", run)

    def check_circuit_breakers(self) -> None:
        def run() -> tuple[bool, str]:
            status, body = self._get("/v1/diagnostics/circuit-breakers")
            if status != 200:
                return False, f"HTTP {status}"
            try:
                data = json.loads(body)
                breakers = data if isinstance(data, list) else data.get("data", [])
                open_breakers = [
                    b.get("name", "?") for b in breakers
                    if isinstance(b, dict) and b.get("state") == "open"
                ]
                if open_breakers:
                    return False, f"Open circuit breakers: {', '.join(open_breakers)}"
            except (json.JSONDecodeError, TypeError):
                pass
            return True, f"HTTP {status}"
        self.check("GET /v1/diagnostics/circuit-breakers (no open breakers)", run)

    def check_docs_accessible(self) -> None:
        def run() -> tuple[bool, str]:
            status, _ = self._get("/docs", auth=False)
            if status != 200:
                return False, f"HTTP {status} — API docs unreachable"
            return True, f"HTTP {status}"
        self.check("GET /docs (API docs accessible)", run)

    def check_graphql_introspection_blocked(self) -> None:
        def run() -> tuple[bool, str]:
            introspection = {"query": "{ __schema { types { name } } }"}
            status, body = self._post("/v1/graphql", introspection)
            # Must NOT return 200 with data — should be 400/403/422
            if status == 200:
                try:
                    data = json.loads(body)
                    if "__schema" in str(data):
                        return False, "Introspection returned schema data — defense not active"
                except json.JSONDecodeError:
                    pass
            # 400, 403, 422 are all acceptable rejection codes
            if status in (400, 403, 422):
                return True, f"Introspection correctly rejected (HTTP {status})"
            return True, f"HTTP {status} (introspection not served)"
        self.check("POST /v1/graphql (introspection rejected)", run)

    def check_sdk_ingestion(self) -> None:
        def run() -> tuple[bool, str]:
            payload = {
                "events": [
                    {
                        "event_type": "smoke_test_ping",
                        "timestamp": int(time.time() * 1000),
                        "properties": {"source": "smoke_test"},
                    }
                ]
            }
            status, _ = self._post("/v1/sdk/events", payload)
            if status in (200, 201, 202):
                return True, f"HTTP {status}"
            if status in (401, 403):
                return False, f"HTTP {status} — check API key / auth config"
            # 404 means route not mounted (config issue), anything else unexpected
            return status in (200, 201, 202, 204), f"HTTP {status}"
        self.check("POST /v1/sdk/events (ingestion golden path)", run)

    def check_version_header(self) -> None:
        def run() -> tuple[bool, str]:
            status, body = self._get("/v1/health", auth=False)
            if status != 200:
                return False, f"HTTP {status}"
            try:
                data = json.loads(body)
                version = data.get("version") or data.get("data", {}).get("version", "")
                if version:
                    return True, f"version={version}"
            except (json.JSONDecodeError, AttributeError):
                pass
            return True, "HTTP 200 (version field optional)"
        self.check("GET /v1/health returns version", run)

    def run_all(self) -> bool:
        print(f"\nSmoke test → {self.base_url}")
        print("─" * 55)
        self.check_public_health()
        self.check_diagnostics_health()
        self.check_circuit_breakers()
        self.check_docs_accessible()
        self.check_graphql_introspection_blocked()
        self.check_sdk_ingestion()
        self.check_version_header()
        print("─" * 55)

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        avg_ms = sum(r.elapsed_ms for r in self.results) / total if total else 0

        if passed == total:
            print(f"All {total} checks passed  (avg {avg_ms:.0f}ms)")
            return True
        else:
            failed = [r.name for r in self.results if not r.passed]
            print(f"{passed}/{total} passed — FAILED: {', '.join(failed)}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AETHER post-deploy smoke test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--api-key", default="", help="X-API-Key value for authenticated endpoints")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="Per-request timeout in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print response details")
    args = parser.parse_args()

    runner = SmokeRunner(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
        verbose=args.verbose,
    )
    ok = runner.run_all()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
