"""Braze `rest_api_base` SSRF hardening tests (WS8) — Team F.

The Braze adapter previously interpolated the tenant-supplied ``rest_api_base``
into REST URLs with zero validation, and ``_get`` used plain httpx (accepting
``http://``) — a live SSRF (e.g. ``rest_api_base="http://169.254.169.254/latest"``
hits the EC2 metadata service). The base URL is now validated against the
``braze.com`` allowlist suffix via ``validated_https_host`` BEFORE any URL is
built:

* (a) a denied base NEVER reaches ``_get``: ``test_connection`` returns the
  existing error shape and ``pull`` raises the typed
  ``ConnectorPullDeniedError`` (F-4 — a denied host is a failed sync run,
  never a silent empty that reads as "provider returned none");
* (b) a valid allowlisted base still works (``https://rest.iad-01.braze.com``,
  the bare form, and the ``_API_BASE`` default) and reaches ``_get`` with a
  URL whose host equals the allowlisted host.

Error text is ``safe_message`` only — the raw ``rest_api_base`` value is never
echoed back.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest

import services.integrations.connectors.braze as braze_mod
from services.integrations.connectors.braze import BrazeConnector
from services.integrations.connectors.base import ConnectorConfig

BRAZE_VALID_HOST = "rest.iad-01.braze.com"


def _cfg(rest_api_base: str | None = None) -> ConnectorConfig:
    config: dict[str, Any] = {}
    if rest_api_base is not None:
        config["rest_api_base"] = rest_api_base
    return ConnectorConfig(
        tenant_id="t1",
        connector_type="braze",  # type: ignore[arg-type]
        enabled=True,
        secret_configured=True,
        config=config,
    )


def _host_of(url: str) -> str:
    return urlparse(url).hostname or ""


BRAZE_MALICIOUS_BASE = [
    "http://169.254.169.254/latest",   # EC2 metadata service (the proven hit)
    "http://127.0.0.1",
    "http://rest.iad-01.braze.com",    # wrong scheme (http)
    "https://braze.com.evil.com",      # trailing labels not on the allowlist
    "https://attacker.com",
    "2130706433",                      # decimal IP literal (127.0.0.1)
    "0x7f000001",                      # hex IP literal (127.0.0.1)
    "127.1",                           # shorthand IPv4 (127.0.0.1)
    "https://10.0.0.1",
    "http://10.0.0.1",
    "https://[::1]",
    "169.254.169.254",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("base", BRAZE_MALICIOUS_BASE)
async def test_braze_test_connection_rejects_malicious_base(monkeypatch, base: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    result = await conn.test_connection(_cfg(base), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "braze" in result.detail
    assert "invalid rest_api_base URL" in result.detail
    assert base not in result.detail  # safe_message only, never the raw value
    assert get.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("base", BRAZE_MALICIOUS_BASE)
async def test_braze_pull_rejects_malicious_base(monkeypatch, base: str) -> None:
    from services.integrations.connectors.adapters import ConnectorPullDeniedError

    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    # F-4: a denied base in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg(base), secret="secret")
    assert base not in excinfo.value.safe_message  # safe_message only, never the raw value
    assert get.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["https://rest.iad-01.braze.com", "rest.iad-01.braze.com"])
async def test_braze_test_connection_accepts_valid_base(monkeypatch, base: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    result = await conn.test_connection(_cfg(base), secret="secret")
    assert result.ok, result.detail
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == BRAZE_VALID_HOST


@pytest.mark.asyncio
async def test_braze_test_connection_default_base_is_validated(monkeypatch) -> None:
    """No ``rest_api_base`` key → falls back to ``_API_BASE``, which is an
    allowlisted subdomain and must still pass the gate."""
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    result = await conn.test_connection(_cfg(), secret="secret")
    assert result.ok, result.detail
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == BRAZE_VALID_HOST


def _dispatch_get(url: str, secret: str) -> tuple[int, dict]:
    """Realistic 200 responses per Braze endpoint."""
    if "hard_bounces" in url:
        return (200, {"emails": [{"email": "a@b.com", "hard_bounced_at": "2024-01-01T00:00:00Z"}]})
    if "unsubscribes" in url:
        return (200, {"emails": [{"email": "b@c.com", "unsubscribed_at": "2024-01-01T00:00:00Z"}]})
    if "campaigns" in url:
        return (200, {"campaigns": [{"id": "c1", "name": "Welcome", "is_api_campaign": True}]})
    if "canvas" in url:
        return (200, {"canvases": [{"id": "v1", "name": "Onboarding"}]})
    return (200, {})


@pytest.mark.asyncio
async def test_braze_pull_default_path_emits_campaign_and_canvas_events(monkeypatch) -> None:
    """Default-base pull flows through email lists + campaign/canvas catalog with
    every `_get` URL pinned to the allowlisted host."""
    get = AsyncMock(side_effect=_dispatch_get)
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    events = await conn.pull(_cfg(), secret="secret")
    event_types = {e.event_type for e in events}
    assert "email_bounced" in event_types
    assert "unsubscribe_observed" in event_types
    assert "braze.campaign" in event_types
    assert "braze.canvas" in event_types
    assert get.await_count >= 4  # hard_bounces, unsubscribes, campaigns, canvases
    for call in get.await_args_list:
        assert _host_of(call.args[0]) == BRAZE_VALID_HOST, call.args[0]


@pytest.mark.asyncio
async def test_braze_pull_valid_custom_base_emits_events(monkeypatch) -> None:
    get = AsyncMock(side_effect=_dispatch_get)
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    events = await conn.pull(_cfg("https://rest.eu-01.braze.com"), secret="secret")
    assert len(events) >= 4
    for call in get.await_args_list:
        assert _host_of(call.args[0]) == "rest.eu-01.braze.com", call.args[0]
