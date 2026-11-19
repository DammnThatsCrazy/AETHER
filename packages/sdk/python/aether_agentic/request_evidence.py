"""Capture evidence about an incoming request for Aether agent detection.

Build ``context["requestEvidence"]`` for an event so Aether can tell whether an
AI agent or crawler sent the request — including agents that never run
JavaScript. Aether verifies it at ingestion (provider-published IP ranges, Web
Bot Auth / RFC 9421 signatures) and then discards the raw values; the client IP
and signature headers are never stored.

Only request metadata is read: user-agent, client IP, method, host, path, query
and the three HTTP Message Signature headers. Never bodies, cookies or
authorization headers.

Mirrors ``captureRequestEvidence`` in the Node server SDK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

_MAX_FIELD = 4096


def _clip(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_FIELD] if text else None


def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    lower = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower:
            if isinstance(value, (list, tuple)):
                return _clip(", ".join(str(v) for v in value))
            return _clip(value)
    return None


def capture_request_evidence(
    *,
    method: str,
    url: str,
    headers: Mapping[str, Any],
    client_ip: Optional[str] = None,
    trust_forwarded_for: bool = False,
    received_at: Optional[datetime] = None,
) -> dict[str, str]:
    """Return ``requestEvidence`` for one request. Never raises.

    ``url`` may be absolute (``https://shop.example/p?x=1``) or a path
    (``/p?x=1``; the host is then read from the ``Host`` header).
    ``client_ip`` should be the address your framework already resolved. Set
    ``trust_forwarded_for`` only behind a proxy you control: otherwise any client
    can choose the IP Aether checks.
    """
    received = (received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence: dict[str, str] = {"receivedAt": received.isoformat().replace("+00:00", "Z")}
    try:
        parts = urlsplit(url or "/")
        authority = _header(headers, "host") or (parts.netloc or None)
        scheme = parts.scheme or "https"
        ip = _clip(client_ip)
        if trust_forwarded_for:
            forwarded = _header(headers, "x-forwarded-for")
            if not ip and forwarded:
                ip = forwarded.split(",")[0].strip() or None
            proto = _header(headers, "x-forwarded-proto")
            if proto:
                scheme = proto.split(",")[0].strip()
        if ip and ip.startswith("::ffff:"):
            ip = ip[7:]
        fields = {
            "userAgent": _header(headers, "user-agent"),
            "clientIp": ip,
            "method": _clip(method.upper() if method else None),
            "authority": _clip(authority),
            "path": _clip(parts.path or "/"),
            "query": _clip(parts.query),
            "scheme": _clip(scheme),
            "signature": _header(headers, "signature"),
            "signatureInput": _header(headers, "signature-input"),
            "signatureAgent": _header(headers, "signature-agent"),
        }
        evidence.update({k: v for k, v in fields.items() if v is not None})
    except Exception:  # noqa: BLE001 - evidence capture must never break the host app
        pass
    return evidence


def capture_request_evidence_from_wsgi(
    environ: Mapping[str, Any], *, trust_forwarded_for: bool = False
) -> dict[str, str]:
    """``capture_request_evidence`` for a WSGI ``environ`` (Flask, Django, ...)."""
    headers = {
        key[5:].replace("_", "-").lower(): value
        for key, value in environ.items()
        if isinstance(key, str) and key.startswith("HTTP_")
    }
    path = str(environ.get("PATH_INFO") or "/")
    query = str(environ.get("QUERY_STRING") or "")
    scheme = str(environ.get("wsgi.url_scheme") or "https")
    host = headers.get("host") or environ.get("SERVER_NAME") or ""
    url = f"{scheme}://{host}{path}" + (f"?{query}" if query else "")
    return capture_request_evidence(
        method=str(environ.get("REQUEST_METHOD") or "GET"),
        url=url,
        headers=headers,
        client_ip=environ.get("REMOTE_ADDR"),
        trust_forwarded_for=trust_forwarded_for,
    )


__all__ = ["capture_request_evidence", "capture_request_evidence_from_wsgi"]
