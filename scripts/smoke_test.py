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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    diagnostics_api_key: str = ""
    results: list[CheckResult] = field(default_factory=list)

    @staticmethod
    def _batch_verdict(status: int, body: str, expected: int) -> tuple[bool, str]:
        """/v1/batch answers 200 with per-event verdicts; every event must be accepted."""
        try:
            result = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return False, f"HTTP {status} — batch response was not JSON"
        accepted = int(result.get("accepted", 0) or 0)
        if accepted == expected and not int(result.get("rejected", 0) or 0):
            return True, f"HTTP {status} — {accepted}/{expected} events accepted"
        reasons = sorted({e.get("reason") for e in result.get("events", []) if isinstance(e, dict) and e.get("reason")})
        return False, f"HTTP {status} — {accepted}/{expected} events accepted; rejected: {reasons}"

    def _grant_consent(self, purposes: list[str]) -> tuple[str | None, str]:
        """Record a server consent receipt for a fresh smoke subject.

        Deployed environments enforce authoritative consent: a purposed event
        without a receipt for its subject is rejected per event under HTTP 200.
        """
        subject = f"smoke-subject-{uuid.uuid4().hex}"
        status, _ = self._post("/v1/consent/records", {
            "user_id": subject, "purposes": purposes, "granted": True, "source": "smoke_test",
        })
        if status in (200, 201):
            return subject, ""
        return None, f"HTTP {status} — consent receipt could not be recorded for the smoke subject"

    @staticmethod
    def _canonical_event(event_type: str, properties: dict) -> dict:
        """Build the deployed canonical SDK batch envelope.

        The staging and production profiles enforce the envelope fields for
        release-critical event families.  Keeping this helper aligned with
        ``services.backend.services.ingestion.batch.BatchRequest`` prevents the
        smoke test from probing a retired ``/v1/sdk/events`` alias or sending
        legacy fields that the canonical ingestion route rejects.
        """
        now = datetime.now(timezone.utc).isoformat()
        session_id = f"smoke-{uuid.uuid4().hex}"
        return {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "timestamp": now,
            "sessionId": session_id,
            "anonymousId": session_id,
            "properties": properties,
            "context": {
                "schemaVersion": "1.0.0",
                "surface": "web",
                "sequence": {"number": 1},
            },
        }

    def _get(
        self,
        path: str,
        *,
        expect_status: int = 200,
        auth: bool = True,
        api_key: Optional[str] = None,
    ) -> tuple[int, bytes]:
        url = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        credential = self.api_key if api_key is None else api_key
        if auth and credential:
            headers["X-API-Key"] = credential
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
            status, body = self._get(
                "/v1/diagnostics/health", api_key=self.diagnostics_api_key
            )
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
            status, body = self._get(
                "/v1/diagnostics/circuit-breakers", api_key=self.diagnostics_api_key
            )
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
            subject, failure = self._grant_consent(["analytics"])
            if subject is None:
                return False, failure
            event = self._canonical_event(
                "page", {"source": "smoke_test", "path": "/smoke"}
            )
            event["userId"] = subject
            payload = {
                "batch": [event],
                "sentAt": event["timestamp"],
                "consents": ["analytics"],
            }
            status, body = self._post("/v1/batch", payload)
            if status in (200, 201, 202):
                return self._batch_verdict(status, body, 1)
            if status in (401, 403):
                return False, f"HTTP {status} — check API key / auth config"
            return False, f"HTTP {status} — canonical batch ingestion rejected"
        self.check("POST /v1/batch (canonical SDK ingestion)", run)

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

    def check_web2_ingestion(self) -> None:
        """Verify Web2-only events (no wallet/chain fields) are accepted without error."""
        def run() -> tuple[bool, str]:
            subject, failure = self._grant_consent(["analytics", "commerce"])
            if subject is None:
                return False, failure
            web2_events = [
                self._canonical_event(
                    "page",
                    {"path": "/products/widget-pro", "referrer": "/home"},
                ),
                self._canonical_event(
                    "checkout_started",
                    {"cart_value": 149.99, "currency": "USD", "item_count": 3},
                ),
                self._canonical_event(
                    "signup_completed", {"method": "email", "plan": "pro"}
                ),
            ]
            for web2_event in web2_events:
                web2_event["userId"] = subject
            status, body = self._post(
                "/v1/batch",
                {
                    "batch": web2_events,
                    "sentAt": datetime.now(timezone.utc).isoformat(),
                    "consents": ["analytics", "commerce"],
                },
            )
            if status in (200, 201, 202):
                return self._batch_verdict(status, body, len(web2_events))
            if status in (401, 403):
                return False, f"HTTP {status} — check API key"
            # 4xx indicates the backend rejected the canonical Web2 envelope.
            if status in (400, 422):
                try:
                    detail = json.loads(body).get("detail") or json.loads(body).get("message", "")
                    return False, f"HTTP {status} — Web2 events rejected: {detail}"
                except (json.JSONDecodeError, AttributeError):
                    return False, f"HTTP {status} — Web2 events rejected"
            return False, f"HTTP {status}"
        self.check("POST /v1/batch (Web2-only path — no wallet/chain fields)", run)

    def check_capabilities_endpoint(self) -> None:
        """Verify the capabilities discovery endpoint is available and returns expected fields."""
        def run() -> tuple[bool, str]:
            status, body = self._get("/v1/capabilities")
            if status in (401, 403):
                return False, f"HTTP {status} — check API key"
            if status == 404:
                return False, "HTTP 404 — /v1/capabilities not mounted (check AETHER_CAPABILITIES_ENABLED)"
            if status != 200:
                return False, f"HTTP {status}"
            try:
                data = json.loads(body)
                payload = data.get("data") or data
                has_sub_resources = "profile_sub_resources" in payload
                has_providers = "providers" in payload
                has_consent = "consent_purposes_granted" in payload
                if has_sub_resources and has_providers and has_consent:
                    sr_count = len(payload["profile_sub_resources"])
                    return True, f"OK — {sr_count} sub-resources available"
                missing = [k for k, v in {
                    "profile_sub_resources": has_sub_resources,
                    "providers": has_providers,
                    "consent_purposes_granted": has_consent,
                }.items() if not v]
                return False, f"Missing fields: {missing}"
            except (json.JSONDecodeError, AttributeError) as exc:
                return False, f"Invalid JSON: {exc}"
        self.check("GET /v1/capabilities (capability discovery)", run)

    def run_all(self, *, web2: bool = False) -> bool:
        print(f"\nSmoke test → {self.base_url}")
        print("─" * 55)
        self.check_public_health()
        self.check_diagnostics_health()
        self.check_circuit_breakers()
        self.check_docs_accessible()
        self.check_graphql_introspection_blocked()
        self.check_sdk_ingestion()
        self.check_version_header()
        if web2:
            self.check_web2_ingestion()
            self.check_capabilities_endpoint()
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
    parser.add_argument(
        "--admin-api-key",
        default="",
        help="Optional admin X-API-Key used only for diagnostic endpoints",
    )
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="Per-request timeout in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print response details")
    parser.add_argument(
        "--web2",
        action="store_true",
        help="Include Web2-specific checks: Web2-only event ingestion and /v1/capabilities endpoint",
    )
    args = parser.parse_args()

    runner = SmokeRunner(
        base_url=args.base_url,
        api_key=args.api_key,
        diagnostics_api_key=args.admin_api_key or args.api_key,
        timeout=args.timeout,
        verbose=args.verbose,
    )
    ok = runner.run_all(web2=args.web2)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
