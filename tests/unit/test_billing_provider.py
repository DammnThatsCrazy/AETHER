"""CI-gated tests for external billing provider readiness (Scope E).

Verifies the provider abstraction is safe + offline by default, that the Stripe
provider is import-safe and inert until enabled, that webhook signatures verify
with idempotency, and that no secrets leak into provider status/output.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _clear_billing_env(monkeypatch):
    for var in (
        "AETHER_EXTERNAL_BILLING_ENABLED", "AETHER_STRIPE_BILLING_ENABLED",
        "KYBER_BILLING_PROVIDER_SYNC_ENABLED", "BILLING_PROVIDER_MODE",
        "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRODUCT_MAPPING_JSON", "STRIPE_PRICE_MAPPING_JSON",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")


@pytest.fixture()
def billing(monkeypatch):
    _clear_billing_env(monkeypatch)
    with backend_module_path():
        providers = importlib.import_module("services.billing.providers")
        base = importlib.import_module("services.billing.providers.base")
        yield SimpleNamespace(providers=providers, base=base)


@pytest.fixture()
def stripe_billing(monkeypatch):
    _clear_billing_env(monkeypatch)
    monkeypatch.setenv("AETHER_EXTERNAL_BILLING_ENABLED", "true")
    monkeypatch.setenv("AETHER_STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_PROVIDER_MODE", "stripe")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    with backend_module_path():
        providers = importlib.import_module("services.billing.providers")
        base = importlib.import_module("services.billing.providers.base")
        yield SimpleNamespace(providers=providers, base=base)


# ── default (disabled) mode ───────────────────────────────────────────────────

async def test_default_provider_is_internal_only(billing):
    provider = billing.providers.get_billing_provider()
    assert provider.provider_type == "internal_only"
    assert provider.is_configured() is True
    assert await provider.sync_payment_status(tenant_id="t1") == "externally_managed"


async def test_default_status_summary_has_no_secrets(billing):
    summary = billing.providers.provider_status_summary()
    assert summary["external_billing_enabled"] is False
    assert summary["billing_provider_mode"] == "internal_only"
    blob = json.dumps(summary)
    assert "sk_" not in blob and "whsec" not in blob


async def test_unmapped_dimensions_reported_by_default(billing):
    mappings = billing.providers.load_mappings()
    summary = billing.providers.mapping_status_summary(mappings)
    # no mapping config in local dev → everything unmapped, but never an error
    assert summary["all_dimensions_mapped"] is False
    assert "ingestion_events" in summary["unmapped_usage_dimensions"]


async def test_internal_invoice_export_is_internal_preview(billing):
    provider = billing.providers.get_billing_provider()
    assert provider.invoice_export_mode() == "internal_preview"
    out = await provider.export_invoice(tenant_id="t1", invoice_preview={"x": 1})
    assert out["exported"] is True and out["artifact"] == "internal"


# ── stripe provider: import-safe + inert until configured ─────────────────────

async def test_stripe_provider_active_when_enabled(stripe_billing):
    provider = stripe_billing.providers.get_billing_provider()
    assert provider.provider_type == "stripe"
    assert provider.is_configured() is True
    assert provider.invoice_export_mode() == "provider_export"


async def test_stripe_mutations_raise_until_wired(stripe_billing):
    provider = stripe_billing.providers.get_billing_provider()
    with pytest.raises(stripe_billing.base.ProviderDisabledError):
        await provider.create_customer(tenant_id="t1")


async def test_stripe_disabled_provider_does_not_process_webhooks(billing):
    # internal-only build: a Stripe provider instance is not configured
    provider = billing.providers.StripeBillingProvider()
    assert provider.is_configured() is False
    result = await provider.handle_webhook(payload=b"{}", signature=None, timestamp=None)
    assert result.handled is False


# ── webhook signature + idempotency ────────────────────────────────────────────

def _sign(secret: str, payload: bytes, timestamp: str) -> str:
    signed = f"{timestamp}.".encode("utf-8") + payload
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


async def test_stripe_webhook_verifies_and_is_idempotent(stripe_billing):
    provider = stripe_billing.providers.get_billing_provider()
    payload = json.dumps({"id": "evt_1", "type": "invoice.paid"}).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("whsec_test", payload, ts)
    first = await provider.handle_webhook(payload=payload, signature=sig, timestamp=ts)
    assert first.handled is True and first.payment_status == "paid"
    second = await provider.handle_webhook(payload=payload, signature=sig, timestamp=ts)
    assert second.idempotent_skip is True


async def test_stripe_webhook_rejects_bad_signature(stripe_billing):
    provider = stripe_billing.providers.get_billing_provider()
    payload = json.dumps({"id": "evt_2", "type": "invoice.paid"}).encode("utf-8")
    ts = str(int(time.time()))
    result = await provider.handle_webhook(payload=payload, signature="deadbeef", timestamp=ts)
    assert result.handled is False and result.reason == "invalid signature"


# ── routes ─────────────────────────────────────────────────────────────────────

async def test_provider_status_route_requires_admin(billing):
    routes = importlib.import_module("services.billing.routes")

    class T:
        tenant_id = "ops"
        def require_permission(self, p):
            if p != "admin":
                raise PermissionError(p)

    req = SimpleNamespace(state=SimpleNamespace(tenant=T()))
    data = (await routes.kyber_billing_provider_status(req))["data"]
    assert data["billing_provider_mode"] == "internal_only"


async def test_tenant_payment_status_route(billing):
    routes = importlib.import_module("services.billing.routes")

    class T:
        tenant_id = "t1"
        user_id = "u1"
        def require_permission(self, p):
            return None

    req = SimpleNamespace(state=SimpleNamespace(tenant=T()))
    data = (await routes.get_billing_payment_status(req))["data"]
    assert data["payment_status"] == "externally_managed"
    assert data["external_billing_enabled"] is False
