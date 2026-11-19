"""Verify request evidence forwarded by a customer's server (server SDK).

Agents that never run JavaScript (fetchers, API clients, many crawlers) are
invisible to the browser SDK. The server SDK's ``captureRequestEvidence``
helper captures what the *customer's* server saw on the incoming request and
sends it as ``context.requestEvidence``. Ingestion verifies it here and then
removes the raw values, so client IPs and signature headers are never stored.

Trust: the evidence is observed by the tenant's server, not by Aether, and
travels over the tenant's authenticated write key. Results therefore carry
``observed_by: "tenant_server"`` and the classifier grades them one step below
Aether's own observations — except a Web Bot Auth signature, which is
cryptographically verifiable wherever it was observed (it binds the signer to
the customer's host and a short validity window).

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from journeys.traffic.agent_verification import server_agent_evidence
from journeys.traffic.web_bot_auth import SignedRequest, verify_web_bot_auth

OBSERVED_BY = "tenant_server"
#: Forwarded evidence older than this (relative to ingestion) is not verified:
#: a signature's own validity is checked at ``receivedAt``, and this bounds how
#: far back a tenant clock claim can move that check.
MAX_FORWARD_AGE_SECONDS = 24 * 3600
MAX_FUTURE_SKEW_SECONDS = 60
_MAX_FIELD = 4096


def _text(raw: dict[str, Any], key: str) -> Optional[str]:
    value = raw.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:_MAX_FIELD] if value else None


def _received_epoch(raw: dict[str, Any], ingest_now: float) -> Optional[float]:
    value = _text(raw, "receivedAt")
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    if ts > ingest_now + MAX_FUTURE_SKEW_SECONDS or ts < ingest_now - MAX_FORWARD_AGE_SECONDS:
        return None
    return ts


def verify_forwarded_request_evidence(
    raw: Any, ingest_now: float
) -> Optional[dict[str, Any]]:
    """Verify ``context.requestEvidence``; ``None`` when there is nothing to record.

    The returned dict contains verdicts only — no IP address, header value or
    signature.
    """
    if not isinstance(raw, dict):
        return None
    user_agent = _text(raw, "userAgent")
    client_ip = _text(raw, "clientIp")
    result: dict[str, Any] = {"observed_by": OBSERVED_BY}

    agent = server_agent_evidence(user_agent, client_ip)
    if agent is not None:
        result["agent_verification"] = {**agent, "observed_by": OBSERVED_BY}

    if _text(raw, "signatureInput") and _text(raw, "signature"):
        received = _received_epoch(raw, ingest_now)
        if received is None:
            result["web_bot_auth"] = {
                "verification": "web_bot_auth_invalid",
                "reason": "missing_or_implausible_received_at",
                "observed_by": OBSERVED_BY,
            }
        else:
            headers = {
                "Signature-Input": _text(raw, "signatureInput") or "",
                "Signature": _text(raw, "signature") or "",
            }
            if _text(raw, "signatureAgent"):
                headers["Signature-Agent"] = _text(raw, "signatureAgent") or ""
            signed = SignedRequest(
                method=_text(raw, "method") or "GET",
                authority=_text(raw, "authority") or "",
                path=_text(raw, "path") or "/",
                scheme=(_text(raw, "scheme") or "https").lower(),
                query=_text(raw, "query") or "",
                headers=headers,
            )
            verdict = verify_web_bot_auth(signed, now=received)
            if verdict is not None:
                result["web_bot_auth"] = {**verdict, "observed_by": OBSERVED_BY}

    if len(result) == 1:
        return None
    return result


__all__ = ["OBSERVED_BY", "verify_forwarded_request_evidence"]
