"""Verify that a delegated MCP bearer request came from the hosted MCP service.

The Auth0 token remains the end-user authority. This HMAC only proves the
request crossed the private service boundary; it grants no tenant rights.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time

from fastapi import Request

_SIGNATURE_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_SKEW_SECONDS = 30


def verify_mcp_service_assertion(request: Request, token: str) -> bool:
    key = os.getenv("AETHER_MCP_SERVICE_ASSERTION_KEY", "")
    timestamp = request.headers.get("x-aether-mcp-service-timestamp", "")
    signature = request.headers.get("x-aether-mcp-service-signature", "")
    if (not token.isascii() or len(token) > 8192
            or not _SIGNATURE_RE.fullmatch(key) or not _SIGNATURE_RE.fullmatch(signature)
            or not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12):
        return False
    if abs(int(time.time()) - int(timestamp)) > _MAX_SKEW_SECONDS:
        return False
    raw_path = request.scope.get("raw_path")
    raw_query = request.scope.get("query_string", b"")
    if not isinstance(raw_path, bytes) or not isinstance(raw_query, bytes):
        return False
    try:
        target = raw_path.decode("ascii")
        if raw_query:
            target += "?" + raw_query.decode("ascii")
    except UnicodeDecodeError:
        return False
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    message = f"{request.method.upper()}\n{target}\n{token_hash}\n{timestamp}"
    expected = hmac.new(bytes.fromhex(key), message.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
