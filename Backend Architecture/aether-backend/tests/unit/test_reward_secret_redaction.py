"""Reward rail API secret redaction — write-only interim invariant.

Rail configs may carry secret material (``config.signing_secret``) until the
credential-authority migration completes. The API surface must already be
write-only: no rail route response and no audit before/after state may return
the secret — only presence markers and a short non-reversible fingerprint.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from services.rewards.routes import _RAIL_SECRET_KEYS, _redact_rail_config


def test_redacts_every_secret_key_and_adds_markers():
    record = {
        "id": "rc-1",
        "rail": "tenant_webhook",
        "config": {
            "webhook_url": "https://tenant.example.com/hook",
            "signing_secret": "super-secret-value",
            "api_key": "sk_live_123",
        },
    }
    redacted = _redact_rail_config(record)
    assert redacted["config"]["signing_secret"] == "<redacted>"
    assert redacted["config"]["api_key"] == "<redacted>"
    assert redacted["config"]["has_signing_secret"] is True
    assert redacted["config"]["has_api_key"] is True
    # fingerprint present, short, and not the secret
    fp = redacted["config"]["signing_secret_fingerprint"]
    assert len(fp) == 12 and fp != "super-secret-value"
    # non-secret fields untouched
    assert redacted["config"]["webhook_url"] == "https://tenant.example.com/hook"


def test_original_record_is_never_mutated():
    record = {"config": {"signing_secret": "keep-me"}}
    _redact_rail_config(record)
    assert record["config"]["signing_secret"] == "keep-me"


def test_handles_none_and_secretless_records():
    assert _redact_rail_config(None) is None
    assert _redact_rail_config({"rail": "manual_export"}) == {"rail": "manual_export"}
    plain = {"config": {"webhook_url": "https://x.example.com"}}
    assert _redact_rail_config(plain) == plain


def test_no_secret_value_survives_anywhere_in_output():
    secrets = {key: f"value-of-{key}" for key in _RAIL_SECRET_KEYS}
    record = {"config": {**secrets, "note": "public"}}
    redacted = _redact_rail_config(record)
    import json

    flat = json.dumps(redacted)
    for value in secrets.values():
        assert value not in flat


@pytest.mark.asyncio
async def test_configure_and_get_rail_routes_return_redacted_config():
    """End-to-end through the real routes (local env, in-memory repos)."""
    from starlette.requests import Request as StarletteRequest

    from services.rewards.routes import (
        RailConfigCreate,
        configure_rail,
        get_rail,
        list_rails,
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = StarletteRequest(
        {"type": "http", "method": "POST", "path": "/", "headers": []}, receive
    )
    body = RailConfigCreate(
        rail="tenant_webhook",
        enabled=False,
        config={"signing_secret": "raw-webhook-secret-value"},
        secret_ref="credref://rewards/tenant_webhook/sandbox/webhook_signing_secret",
        webhook_url="https://tenant.example.com/hook",
    )
    created = await configure_rail(request, body)
    created_data = created["data"] if isinstance(created, dict) and "data" in created else created
    # tenant_webhook dual-writes the secret into the credential authority and
    # replaces it with a secret_ref — the plaintext key is GONE entirely, not
    # merely redacted, and a resolvable secret_ref is persisted instead.
    assert "signing_secret" not in created_data["config"]
    assert created_data["config"]["secret_ref"].startswith(
        "credref://rewards/tenant_webhook/"
    )

    listed = await list_rails(request)
    listed_data = listed["data"] if isinstance(listed, dict) and "data" in listed else listed
    for rec in listed_data:
        # never any plaintext secret in a list response
        assert rec.get("config", {}).get("signing_secret") in (None, "<redacted>")

    got = await get_rail(request, created_data["id"])
    got_data = got["data"] if isinstance(got, dict) and "data" in got else got
    assert "signing_secret" not in got_data["config"]
    assert got_data["config"]["secret_ref"].startswith("credref://rewards/")


@pytest.mark.asyncio
async def test_update_rail_route_dual_writes_secret_and_never_persists_plaintext():
    """PATCH /v1/rewards/rails/{rail_id} must apply the SAME store_secret /
    secret_ref dual-write that configure_rail (CREATE) applies, BEFORE the
    repository update — a rotated config.signing_secret must never land in
    tenant_reward_rail_configs as plaintext, matching create's behavior."""
    from starlette.requests import Request as StarletteRequest

    from services.rewards.routes import (
        RailConfigCreate,
        RailConfigUpdate,
        configure_rail,
        get_rail,
        update_rail,
    )
    from services.rewards.repositories import RewardRailConfigRepository

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = StarletteRequest(
        {"type": "http", "method": "POST", "path": "/", "headers": []}, receive
    )

    created = await configure_rail(
        request,
        RailConfigCreate(
            rail="tenant_webhook",
            enabled=False,
            config={"signing_secret": "original-webhook-secret"},
            secret_ref="credref://rewards/tenant_webhook/sandbox/webhook_signing_secret",
            webhook_url="https://tenant.example.com/hook",
        ),
    )
    created_data = created["data"] if isinstance(created, dict) and "data" in created else created
    rail_id = created_data["id"]
    original_secret_ref = created_data["config"]["secret_ref"]

    # Rotate the signing secret via PATCH, exactly as a tenant would.
    patched = await update_rail(
        request,
        rail_id,
        RailConfigUpdate(config={"signing_secret": "rotated-webhook-secret"}),
    )
    patched_data = patched["data"] if isinstance(patched, dict) and "data" in patched else patched

    # API response: no plaintext, only a (rotated) secret_ref.
    assert "signing_secret" not in patched_data["config"]
    new_secret_ref = patched_data["config"]["secret_ref"]
    assert new_secret_ref.startswith("credref://rewards/tenant_webhook/")
    assert new_secret_ref == original_secret_ref  # rotation reuses the same ref

    # The persisted row itself — not just the redacted API response — must
    # never contain the plaintext secret. This is the actual bug: P3's
    # redaction only masked the response, while the row kept plaintext.
    raw = await RewardRailConfigRepository().get(rail_id, created_data["tenant_id"])
    assert "signing_secret" not in raw["config"]
    assert raw["config"]["secret_ref"] == new_secret_ref
    import json

    assert "rotated-webhook-secret" not in json.dumps(raw)
    assert "original-webhook-secret" not in json.dumps(raw)

    # get_rail confirms the same through the normal read path too.
    got = await get_rail(request, rail_id)
    got_data = got["data"] if isinstance(got, dict) and "data" in got else got
    assert "signing_secret" not in got_data["config"]
    assert got_data["config"]["secret_ref"] == new_secret_ref


@pytest.mark.asyncio
async def test_non_webhook_rail_config_still_redacted_defensively():
    """A non-tenant_webhook rail carrying an inline secret is redacted (the
    dual-write path is tenant_webhook-specific; other rails must still never
    echo secret material)."""
    from starlette.requests import Request as StarletteRequest

    from services.rewards.routes import RailConfigCreate, configure_rail

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = StarletteRequest(
        {"type": "http", "method": "POST", "path": "/", "headers": []}, receive
    )
    body = RailConfigCreate(
        rail="manual_export",
        enabled=False,
        config={"api_key": "sk_should_be_redacted"},
    )
    created = await configure_rail(request, body)
    data = created["data"] if isinstance(created, dict) and "data" in created else created
    assert data["config"]["api_key"] == "<redacted>"
    assert data["config"]["has_api_key"] is True
