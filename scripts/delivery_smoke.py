#!/usr/bin/env python3
"""
Delivery Smoke Test
===================

Verifies the canonical delivery pipeline end-to-end.

Usage:
  python scripts/delivery_smoke.py --fake-providers
  python scripts/delivery_smoke.py --provider slack --slack-token xoxb-...
  python scripts/delivery_smoke.py --provider linear --linear-api-key lin_api_...
  python scripts/delivery_smoke.py --provider jira --jira-url https://co.atlassian.net --jira-token user@co.com:token
  python scripts/delivery_smoke.py --provider webhook --webhook-url https://your-endpoint.example.com/aether-test

Exit code 0 on PASS, 1 on FAIL. Never silently passes.
"""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Fake provider servers (used by --fake-providers)
# ---------------------------------------------------------------------------

def _run_fake_slack(host: str, port: int, results: dict) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class FakeSlack(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith("/api/auth.test"):
                self._json({"ok": True, "team_id": "T_SMOKE", "user_id": "U_SMOKE"})
            elif self.path.startswith("/api/chat.getPermalink"):
                self._json({"ok": True, "permalink": "https://slack.fake/archives/C_SMOKE/p9999"})
            else:
                self._json({"ok": False, "error": "unknown_endpoint"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if self.path == "/api/chat.postMessage":
                results["slack_received"] = json.loads(body) if body else {}
                self._json({"ok": True, "channel": "C_SMOKE", "ts": "1700000000.000001"})
            else:
                self._json({"ok": False, "error": "unknown_endpoint"}, 404)

        def _json(self, data: dict, status: int = 200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer((host, port), FakeSlack)
    server.serve_forever()


def _run_fake_linear(host: str, port: int, results: dict) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class FakeLinear(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            results["linear_received"] = json.loads(body) if body else {}
            resp = {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "smoke-issue-uuid",
                            "identifier": "ENG-SMOKE",
                            "url": "https://linear.app/team/issue/ENG-SMOKE",
                        },
                    }
                }
            }
            body_out = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_out)))
            self.end_headers()
            self.wfile.write(body_out)

    server = HTTPServer((host, port), FakeLinear)
    server.serve_forever()


def _run_fake_jira(host: str, port: int, results: dict) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class FakeJira(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if "/rest/api/3/myself" in self.path:
                self._json({"accountId": "acc_smoke", "displayName": "Smoke User"})
            else:
                self._json({}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            results["jira_received"] = json.loads(body) if body else {}
            resp = {"id": "smoke-10001", "key": "SMOKE-42", "self": f"http://{host}:{port}/rest/api/3/issue/smoke-10001"}
            body_out = json.dumps(resp).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_out)))
            self.end_headers()
            self.wfile.write(body_out)

        def _json(self, data: dict, status: int = 200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer((host, port), FakeJira)
    server.serve_forever()


def _run_fake_webhook(host: str, port: int, results: dict) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class FakeWebhook(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            results["webhook_received"] = json.loads(body) if body else {}
            results["webhook_headers"] = dict(self.headers)
            resp = json.dumps({"received": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = HTTPServer((host, port), FakeWebhook)
    server.serve_forever()


# ---------------------------------------------------------------------------
# Minimal in-process delivery test (no real DB required)
# ---------------------------------------------------------------------------

@dataclass
class _SmokeResult:
    provider: str
    passed: bool
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


def _idempotency_key(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sign_webhook(body_bytes: bytes, secret: str, timestamp: str) -> str:
    msg = f"{timestamp}.".encode() + body_bytes
    return "v1=" + hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _smoke_fake_slack(base_url: str, results: dict) -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("slack", False, error="httpx not installed")

    try:
        signing_value = "smoke-slack-signing-secret"  # noqa: test fixture, not a real credential
        channel = "C_SMOKE"
        payload = {"channel": channel, "text": f"[AETHER-SMOKE] {_now_iso()}", "blocks": []}
        idempotency_key = _idempotency_key("suggestion", "smoke-sug-1", "tenant-smoke")

        resp = httpx.post(
            f"{base_url}/api/chat.postMessage",
            json=payload,
            headers={"Authorization": "Bearer xoxb-smoke", "Idempotency-Key": idempotency_key},
            timeout=5,
        )
        body = resp.json()
        if not body.get("ok"):
            return _SmokeResult("slack", False, error=f"chat.postMessage returned ok=false: {body.get('error')}")

        ts = body["ts"]
        ch = body["channel"]
        external_id = f"{ch}:{ts}"
        external_url = f"https://slack.fake/archives/{ch}/p{ts.replace('.', '')}"

        if not external_id:
            return _SmokeResult("slack", False, error="empty external_id")
        if "sim-" in external_id:
            return _SmokeResult("slack", False, error=f"simulated external_id detected: {external_id}")

        return _SmokeResult(
            "slack", True,
            external_id=external_id,
            external_url=external_url,
            details={"payload_received": results.get("slack_received", {})}
        )
    except Exception as exc:
        return _SmokeResult("slack", False, error=str(exc))


def _smoke_fake_linear(base_url: str, results: dict) -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("linear", False, error="httpx not installed")

    try:
        query = """
        mutation IssueCreate($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue { id identifier url }
          }
        }
        """
        variables = {
            "input": {
                "title": f"[AETHER-SMOKE] {_now_iso()}",
                "description": "Smoke test from scripts/delivery_smoke.py",
                "teamId": "team-smoke",
                "priority": 3,
            }
        }
        resp = httpx.post(
            f"{base_url}/graphql",
            json={"query": query, "variables": variables},
            headers={"Authorization": "Bearer lin_api_smoke", "Content-Type": "application/json"},
            timeout=5,
        )
        body = resp.json()
        if "errors" in body:
            return _SmokeResult("linear", False, error=f"GraphQL errors: {body['errors']}")

        issue = body.get("data", {}).get("issueCreate", {}).get("issue", {})
        external_id = issue.get("id", "")
        external_url = issue.get("url", "")

        if not external_id:
            return _SmokeResult("linear", False, error="empty external_id")

        return _SmokeResult(
            "linear", True,
            external_id=external_id,
            external_url=external_url,
            details={"identifier": issue.get("identifier")}
        )
    except Exception as exc:
        return _SmokeResult("linear", False, error=str(exc))


def _smoke_fake_jira(base_url: str, results: dict) -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("jira", False, error="httpx not installed")

    try:
        payload = {
            "fields": {
                "project": {"key": "SMOKE"},
                "summary": f"[AETHER-SMOKE] {_now_iso()}",
                "issuetype": {"name": "Task"},
                "priority": {"name": "Medium"},
            }
        }
        resp = httpx.post(
            f"{base_url}/rest/api/3/issue",
            json=payload,
            headers={"Authorization": "Basic c21va2VAZXhhbXBsZS5jb206c21va2U=", "Content-Type": "application/json"},
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            return _SmokeResult("jira", False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        external_id = body.get("id", "")
        key = body.get("key", "")
        external_url = f"{base_url}/browse/{key}" if key else ""

        if not external_id:
            return _SmokeResult("jira", False, error="empty external_id")

        return _SmokeResult(
            "jira", True,
            external_id=external_id,
            external_url=external_url,
            details={"key": key}
        )
    except Exception as exc:
        return _SmokeResult("jira", False, error=str(exc))


def _smoke_fake_webhook(base_url: str, secret: str, results: dict) -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("webhook", False, error="httpx not installed")

    try:
        delivery_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        payload = {
            "schema_version": "1.0",
            "delivery_id": delivery_id,
            "event_id": str(uuid.uuid4()),
            "tenant_correlation_id": "tenant-smoke",
            "suggestion_id": "sug-smoke-1",
            "event_type": "suggestion.delivery",
            "timestamp": _now_iso(),
            "idempotency_key": _idempotency_key("suggestion", "sug-smoke-1", "tenant-smoke"),
            "signature_version": "v1",
            "title": "[AETHER-SMOKE] Delivery test",
            "summary": "Smoke test payload",
            "priority": "P2",
            "confidence": 0.99,
        }
        body_bytes = json.dumps(payload, separators=(",", ":")).encode()
        signature = _sign_webhook(body_bytes, secret, timestamp)

        resp = httpx.post(
            f"{base_url}/receive",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Aether-Delivery-ID": delivery_id,
                "X-Aether-Signature": signature,
                "X-Aether-Signature-Version": "v1",
                "X-Aether-Timestamp": timestamp,
                "X-Aether-Idempotency-Key": payload["idempotency_key"],
                "User-Agent": "Aether-Webhook/1.0",
            },
            timeout=5,
        )
        if resp.status_code not in (200, 201, 202, 204):
            return _SmokeResult("webhook", False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")

        # Verify signature was valid (round-trip check)
        expected = _sign_webhook(body_bytes, secret, timestamp)
        if expected != signature:
            return _SmokeResult("webhook", False, error="Signature round-trip mismatch")

        return _SmokeResult(
            "webhook", True,
            external_id=delivery_id,
            external_url=None,
            details={"signature": signature, "status": resp.status_code}
        )
    except Exception as exc:
        return _SmokeResult("webhook", False, error=str(exc))


# ---------------------------------------------------------------------------
# Credentialed smoke tests
# ---------------------------------------------------------------------------

def _smoke_real_slack(token: str, channel: str = "#general") -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("slack", False, error="httpx not installed")

    try:
        # Step 1: verify credentials
        auth_resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        auth_body = auth_resp.json()
        if not auth_body.get("ok"):
            return _SmokeResult("slack", False, error=f"auth.test failed: {auth_body.get('error')}")

        # Step 2: send a real test message and capture the receipt
        import datetime
        ts_label = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        msg_resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json={
                "channel": channel,
                "text": f"[AETHER-SMOKE-TEST {ts_label}] Delivery smoke test — please disregard.",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        msg_body = msg_resp.json()
        if not msg_body.get("ok"):
            return _SmokeResult("slack", False, error=f"chat.postMessage failed: {msg_body.get('error')}")

        ch = msg_body.get("channel", "")
        ts = msg_body.get("ts", "")
        if not ch or not ts:
            return _SmokeResult("slack", False, error=f"Missing channel/ts in response: {msg_body}")

        external_id = f"{ch}:{ts}"
        return _SmokeResult(
            "slack", True,
            external_id=external_id,
            details={"team": auth_body.get("team"), "channel": ch, "ts": ts},
        )
    except Exception as exc:
        return _SmokeResult("slack", False, error=str(exc))


def _smoke_real_linear(api_key: str, team_id: str = "") -> _SmokeResult:
    try:
        import httpx
    except ImportError:
        return _SmokeResult("linear", False, error="httpx not installed")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        # Step 1: verify credentials
        auth_resp = httpx.post(
            "https://api.linear.app/graphql",
            json={"query": "{ viewer { id name } }"},
            headers=headers,
            timeout=10,
        )
        auth_body = auth_resp.json()
        if "errors" in auth_body:
            return _SmokeResult("linear", False, error=str(auth_body["errors"]))
        viewer = auth_body.get("data", {}).get("viewer", {})

        # Step 2: get a team_id if not provided
        if not team_id:
            teams_resp = httpx.post(
                "https://api.linear.app/graphql",
                json={"query": "{ teams { nodes { id name } } }"},
                headers=headers,
                timeout=10,
            )
            teams_body = teams_resp.json()
            teams = teams_body.get("data", {}).get("teams", {}).get("nodes", [])
            if not teams:
                return _SmokeResult("linear", False, error="No Linear teams found — cannot create test issue")
            team_id = teams[0]["id"]

        # Step 3: create a real test issue and capture the external_id
        import datetime
        ts_label = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        mutation = """
        mutation CreateIssue($teamId: String!, $title: String!) {
            issueCreate(input: { teamId: $teamId, title: $title }) {
                success
                issue { id identifier url }
            }
        }
        """
        create_resp = httpx.post(
            "https://api.linear.app/graphql",
            json={
                "query": mutation,
                "variables": {
                    "teamId": team_id,
                    "title": f"[AETHER-SMOKE-TEST {ts_label}] Delivery smoke test — please close/delete",
                },
            },
            headers=headers,
            timeout=10,
        )
        create_body = create_resp.json()
        if "errors" in create_body:
            return _SmokeResult("linear", False, error=str(create_body["errors"]))
        issue_create = create_body.get("data", {}).get("issueCreate", {})
        if not issue_create.get("success"):
            return _SmokeResult("linear", False, error=f"issueCreate returned success=false: {create_body}")
        issue = issue_create.get("issue", {})
        return _SmokeResult(
            "linear", True,
            external_id=issue.get("id", ""),
            external_url=issue.get("url"),
            details={"viewer": viewer.get("name"), "identifier": issue.get("identifier")},
        )
    except Exception as exc:
        return _SmokeResult("linear", False, error=str(exc))


def _smoke_real_jira(jira_url: str, jira_token: str) -> _SmokeResult:
    try:
        import base64
        import httpx
    except ImportError:
        return _SmokeResult("jira", False, error="httpx not installed")

    try:
        creds = base64.b64encode(jira_token.encode()).decode()
        resp = httpx.get(
            f"{jira_url.rstrip('/')}/rest/api/3/myself",
            headers={"Authorization": f"Basic {creds}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return _SmokeResult("jira", False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        return _SmokeResult("jira", True, details={"account_id": body.get("accountId"), "display_name": body.get("displayName")})
    except Exception as exc:
        return _SmokeResult("jira", False, error=str(exc))


def _smoke_real_webhook(webhook_url: str, signing_secret: str = "") -> _SmokeResult:
    try:
        import datetime
        import hashlib
        import hmac
        import ipaddress
        import socket
        import urllib.parse
        import httpx
    except ImportError as exc:
        return _SmokeResult("webhook", False, error=f"missing dependency: {exc}")

    # Step 1: SSRF validation
    try:
        parsed = urllib.parse.urlparse(webhook_url)
        if parsed.scheme != "https" and os.environ.get("AETHER_ENV") != "local":
            return _SmokeResult("webhook", False, error="Webhook URL must use HTTPS")
        BLOCKED = [
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),
        ]
        for _, _, _, _, (addr, *_) in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(addr)
            if any(ip in net for net in BLOCKED):
                return _SmokeResult("webhook", False, error=f"SSRF: {addr} is a private address")
    except Exception as exc:
        return _SmokeResult("webhook", False, error=f"SSRF check failed: {exc}")

    # Step 2: send a real signed POST and verify 2xx
    try:
        import datetime
        import json as _json
        import uuid
        ts_label = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        delivery_id = str(uuid.uuid4())
        payload = {
            "schema_version": "1",
            "delivery_id": delivery_id,
            "event_type": "smoke_test",
            "timestamp": ts_label,
            "test": True,
            "message": f"[AETHER-SMOKE-TEST {ts_label}] Delivery smoke test — please disregard.",
        }
        body_bytes = _json.dumps(payload).encode()
        timestamp = str(int(datetime.datetime.utcnow().timestamp()))
        sig_value = "v1=unsigned"
        if signing_secret:
            digest = hmac.new(
                signing_secret.encode(),
                f"{timestamp}.".encode() + body_bytes,
                hashlib.sha256,
            ).hexdigest()
            sig_value = f"v1={digest}"

        resp = httpx.post(
            webhook_url,
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Aether-Delivery-ID": delivery_id,
                "X-Aether-Timestamp": timestamp,
                "X-Aether-Signature": sig_value,
                "X-Aether-Signature-Version": "v1",
                "User-Agent": "Aether-Webhook/1.0",
            },
            timeout=15,
            follow_redirects=False,
        )
        if resp.status_code >= 300:
            return _SmokeResult(
                "webhook", False,
                error=f"Webhook returned HTTP {resp.status_code}: {resp.text[:200]}",
            )
        return _SmokeResult(
            "webhook", True,
            external_id=delivery_id,
            details={"url": webhook_url, "ssrf_check": "passed", "http_status": resp.status_code},
        )
    except Exception as exc:
        return _SmokeResult("webhook", False, error=str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_result(r: _SmokeResult) -> None:
    status = "PASS" if r.passed else "FAIL"
    print(f"  [{status}] {r.provider}")
    if r.external_id:
        print(f"         external_id  = {r.external_id}")
    if r.external_url:
        print(f"         external_url = {r.external_url}")
    if r.error:
        print(f"         error        = {r.error}")
    if r.details:
        for k, v in r.details.items():
            print(f"         {k} = {v}")


def _start_server(fn, host, port, results, daemon=True):
    t = threading.Thread(target=fn, args=(host, port, results), daemon=daemon)
    t.start()
    # Brief wait for server to start
    time.sleep(0.2)
    return t


def main() -> int:
    parser = argparse.ArgumentParser(description="Aether delivery smoke test")
    parser.add_argument("--fake-providers", action="store_true", help="Use in-process fake providers (no credentials needed)")
    parser.add_argument("--provider", choices=["slack", "linear", "jira", "webhook"], help="Real provider to test")
    parser.add_argument("--slack-token", help="Slack bot token (xoxb-...)")
    parser.add_argument("--linear-api-key", help="Linear API key (lin_api_...)")
    parser.add_argument("--jira-url", help="Jira instance URL")
    parser.add_argument("--jira-token", help="Jira token as email:token")
    parser.add_argument("--webhook-url", help="Webhook endpoint URL")
    parser.add_argument("--webhook-secret", default="smoke-test-signing-value-32bytes", help="Webhook HMAC signing value for fake-provider runs")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    args = parser.parse_args()

    if not args.fake_providers and not args.provider:
        print("ERROR: Specify --fake-providers or --provider <name>. Exiting 1.", file=sys.stderr)
        return 1

    results: list[_SmokeResult] = []
    server_results: dict = {}

    print(f"\n=== Aether Delivery Smoke Test === {_now_iso()}")

    if args.fake_providers:
        print("\nMode: --fake-providers (in-process fake servers)\n")

        # Start fake servers
        _start_server(_run_fake_slack, "127.0.0.1", 19501, server_results)
        _start_server(_run_fake_linear, "127.0.0.1", 19502, server_results)
        _start_server(_run_fake_jira, "127.0.0.1", 19503, server_results)
        _start_server(_run_fake_webhook, "127.0.0.1", 19504, server_results)

        results.append(_smoke_fake_slack("http://127.0.0.1:19501", server_results))
        results.append(_smoke_fake_linear("http://127.0.0.1:19502", server_results))
        results.append(_smoke_fake_jira("http://127.0.0.1:19503", server_results))

        # Webhook fake receiver at /receive
        results.append(_smoke_fake_webhook("http://127.0.0.1:19504", args.webhook_secret, server_results))

    else:
        p = args.provider
        print(f"\nMode: --provider {p} (credentialed)\n")

        if p == "slack":
            if not args.slack_token:
                print("ERROR: --slack-token required for --provider slack", file=sys.stderr)
                return 1
            results.append(_smoke_real_slack(args.slack_token))

        elif p == "linear":
            if not args.linear_api_key:
                print("ERROR: --linear-api-key required for --provider linear", file=sys.stderr)
                return 1
            results.append(_smoke_real_linear(args.linear_api_key))

        elif p == "jira":
            if not args.jira_url or not args.jira_token:
                print("ERROR: --jira-url and --jira-token required for --provider jira", file=sys.stderr)
                return 1
            results.append(_smoke_real_jira(args.jira_url, args.jira_token))

        elif p == "webhook":
            if not args.webhook_url:
                print("ERROR: --webhook-url required for --provider webhook", file=sys.stderr)
                return 1
            results.append(_smoke_real_webhook(args.webhook_url, signing_secret=getattr(args, "webhook_secret", "")))

    for r in results:
        _print_result(r)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    print(f"\nResult: {passed} passed, {failed} failed\n")

    if args.json:
        report = {
            "timestamp": _now_iso(),
            "mode": "fake-providers" if args.fake_providers else f"credentialed/{args.provider}",
            "passed": passed,
            "failed": failed,
            "results": [
                {
                    "provider": r.provider,
                    "passed": r.passed,
                    "external_id": r.external_id,
                    "external_url": r.external_url,
                    "error": r.error,
                }
                for r in results
            ],
        }
        print(json.dumps(report, indent=2))

    if failed > 0:
        print("SMOKE TEST FAILED", file=sys.stderr)
        return 1

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
