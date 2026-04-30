"""Tests for Aether's Stripe Billing integration.

Covers:
  - Stripe Price ID <-> PlanTier mapping
  - Settings validation (non-local vs local)
  - Local-mode mocked Checkout / Portal URLs
  - Webhook signature verification + idempotency
  - Subscription lifecycle (created/updated/deleted) drives plan_tier
  - Invoice upsert from invoice.* events
  - Overage invoice endpoint disabled when STRIPE_OVERAGE_PRICE_ID absent
  - Plan sync: cached API key TenantContext picks up billing-account plan_tier
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for name in list(sys.modules):
            if name not in original_mods:
                sys.modules.pop(name, None)


def _set_env(monkeypatch, **kwargs):
    for key, val in kwargs.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(val))


def _reload_settings():
    """Force a clean reload of config.settings + downstream modules.

    Other backend modules cache `from config.settings import settings` at
    import time, so they must be dropped together with the config package
    to ensure they re-read os.environ on the next import.
    """
    prefixes = (
        "config",
        "shared.auth",
        "shared.billing",
        "shared.plans",
        "shared.cache",
        "shared.common",
        "shared.rate_limit",
        "shared.logger",
        "repositories",
        "services.admin",
        "dependencies",
    )
    for name in list(sys.modules):
        if name in prefixes or any(name.startswith(p + ".") for p in prefixes):
            sys.modules.pop(name, None)
    return importlib.import_module("config.settings")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestStripeSettings:
    def test_local_allows_missing_stripe_config(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="local",
            JWT_SECRET="x",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_PRICE_P1="", STRIPE_PRICE_P2="",
            STRIPE_PRICE_P3="", STRIPE_PRICE_P4="",
        )
        with backend_path():
            mod = _reload_settings()
            s = mod.settings
            assert s.stripe_billing.enabled is True
            assert s.stripe_billing.secret_key == ""

    def test_non_local_requires_stripe_vars_when_enabled(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="staging",
            JWT_SECRET="set",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_PRICE_P1="", STRIPE_PRICE_P2="",
            STRIPE_PRICE_P3="", STRIPE_PRICE_P4="",
        )
        with backend_path():
            with pytest.raises(RuntimeError) as exc:
                _reload_settings()
            assert "STRIPE_SECRET_KEY" in str(exc.value)
            assert "STRIPE_PRICE_P1" in str(exc.value)

    def test_non_local_passes_when_all_stripe_vars_set(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="staging",
            JWT_SECRET="set",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
            STRIPE_PRICE_P1="price_p1",
            STRIPE_PRICE_P2="price_p2",
            STRIPE_PRICE_P3="price_p3",
            STRIPE_PRICE_P4="price_p4",
        )
        with backend_path():
            mod = _reload_settings()
            assert mod.settings.stripe_billing.price_p3 == "price_p3"
            assert mod.settings.stripe_billing.overage_invoicing_enabled is False


# ---------------------------------------------------------------------------
# Plan <-> Price ID mapping
# ---------------------------------------------------------------------------


class TestPriceIdMapping:
    def test_price_id_round_trip(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="local", JWT_SECRET="x",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
            STRIPE_PRICE_P1="price_p1",
            STRIPE_PRICE_P2="price_p2",
            STRIPE_PRICE_P3="price_p3",
            STRIPE_PRICE_P4="price_p4",
        )
        with backend_path():
            _reload_settings()
            client = importlib.import_module("shared.billing.stripe_client")
            from shared.auth.auth import PlanTier

            assert client.get_stripe_price_id(PlanTier.P1_HOBBYIST) == "price_p1"
            assert client.get_stripe_price_id(PlanTier.P2_PROFESSIONAL) == "price_p2"
            assert client.get_stripe_price_id(PlanTier.P3_GROWTH_INTELLIGENCE) == "price_p3"
            assert client.get_stripe_price_id(PlanTier.P4_PROTOCOL_MASTER) == "price_p4"

            assert client.get_plan_for_price_id("price_p1") == PlanTier.P1_HOBBYIST
            assert client.get_plan_for_price_id("price_p3") == PlanTier.P3_GROWTH_INTELLIGENCE
            assert client.get_plan_for_price_id("price_unknown") is None
            assert client.get_plan_for_price_id("") is None


# ---------------------------------------------------------------------------
# Local-mode mocked URLs
# ---------------------------------------------------------------------------


class TestLocalMockedFlows:
    def test_checkout_returns_mocked_url_in_local_when_unconfigured(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="local", JWT_SECRET="x",
            STRIPE_BILLING_ENABLED="true",
        )
        # Clear price ids so config is "incomplete" for mocked-mode trigger
        for k in ("STRIPE_PRICE_P1", "STRIPE_PRICE_P2", "STRIPE_PRICE_P3", "STRIPE_PRICE_P4",
                  "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
            monkeypatch.delenv(k, raising=False)
        with backend_path():
            _reload_settings()
            client = importlib.import_module("shared.billing.stripe_client")
            from shared.auth.auth import PlanTier

            session = asyncio.run(
                client.create_checkout_session(
                    tenant_id="t-1",
                    plan_tier=PlanTier.P3_GROWTH_INTELLIGENCE,
                    contact_email="dev@example.com",
                )
            )
            assert session.mocked is True
            assert session.session_id == "cs_mock_t-1_P3"
            assert "tenant_id=t-1" in session.url
            assert "plan_tier=P3" in session.url

    def test_portal_returns_mocked_url_in_local_when_unconfigured(self, monkeypatch):
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            client = importlib.import_module("shared.billing.stripe_client")

            portal = asyncio.run(client.create_portal_session(tenant_id="t-7"))
            assert portal.mocked is True
            assert "tenant_id=t-7" in portal.url


# ---------------------------------------------------------------------------
# Webhook signature verification + idempotency
# ---------------------------------------------------------------------------


class TestWebhookHandling:
    def _setup(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="local", JWT_SECRET="x",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
            STRIPE_PRICE_P1="price_p1",
            STRIPE_PRICE_P2="price_p2",
            STRIPE_PRICE_P3="price_p3",
            STRIPE_PRICE_P4="price_p4",
        )

    def test_webhook_rejects_missing_signature(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            client = importlib.import_module("shared.billing.stripe_client")
            from shared.common.common import BadRequestError, ServiceUnavailableError

            err: Exception | None = None
            try:
                client.construct_webhook_event(b"{}", "")
            except (BadRequestError, ServiceUnavailableError) as e:
                err = e
            assert err is not None

    def test_subscription_updated_active_sets_plan_tier(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository

            stripe_repository._reset_in_memory_for_tests()
            routes = importlib.import_module("services.admin.routes")

            sub_obj = {
                "id": "sub_1",
                "customer": "cus_1",
                "status": "active",
                "current_period_end": 1_900_000_000,
                "metadata": {"tenant_id": "t-1"},
                "items": {"data": [{"price": {"id": "price_p3"}}]},
            }
            asyncio.run(routes._handle_subscription_event(sub_obj, deleted=False))

            acct = asyncio.run(stripe_repository.get_billing_account("t-1"))
            assert acct["plan_tier"] == "P3"
            assert acct["subscription_status"] == "active"
            assert acct["stripe_price_id"] == "price_p3"
            assert acct["stripe_subscription_id"] == "sub_1"

    def test_subscription_deleted_downgrades_to_p1(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            asyncio.run(stripe_repository.update_plan_tier("t-2", "P3"))

            routes = importlib.import_module("services.admin.routes")
            sub_obj = {
                "id": "sub_2", "customer": "cus_2", "status": "canceled",
                "metadata": {"tenant_id": "t-2"},
                "items": {"data": [{"price": {"id": "price_p3"}}]},
            }
            asyncio.run(routes._handle_subscription_event(sub_obj, deleted=True))
            acct = asyncio.run(stripe_repository.get_billing_account("t-2"))
            assert acct["plan_tier"] == "P1"
            assert acct["subscription_status"] == "canceled"

    def test_checkout_session_completed_does_not_change_plan_tier(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            asyncio.run(stripe_repository.update_plan_tier("t-3", "P1"))

            routes = importlib.import_module("services.admin.routes")
            session_obj = {
                "id": "cs_1", "customer": "cus_3", "subscription": "sub_3",
                "client_reference_id": "t-3",
                "metadata": {"tenant_id": "t-3", "requested_plan_tier": "P3"},
            }
            asyncio.run(routes._handle_checkout_session_completed(session_obj))
            acct = asyncio.run(stripe_repository.get_billing_account("t-3"))
            # plan_tier must remain unchanged at this stage
            assert acct["plan_tier"] == "P1"
            assert acct["stripe_customer_id"] == "cus_3"
            assert acct["stripe_subscription_id"] == "sub_3"

    def test_invoice_paid_upserts_paid_invoice(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            routes = importlib.import_module("services.admin.routes")
            inv = {
                "id": "in_1", "customer": "cus_4", "subscription": "sub_4",
                "status": "paid", "currency": "usd",
                "amount_due": 9900, "amount_paid": 9900, "amount_remaining": 0,
                "hosted_invoice_url": "https://stripe/h", "invoice_pdf": "https://stripe/p",
                "created": 1_700_000_000, "period_start": 1_700_000_000,
                "period_end": 1_702_000_000,
                "metadata": {"tenant_id": "t-4"},
            }
            asyncio.run(routes._handle_invoice_event("invoice.paid", inv))
            invoices = asyncio.run(stripe_repository.list_invoices("t-4"))
            assert len(invoices) == 1
            assert invoices[0]["stripe_invoice_id"] == "in_1"
            assert invoices[0]["status"] == "paid"

    def test_invoice_payment_failed_does_not_downgrade(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            asyncio.run(stripe_repository.update_plan_tier("t-5", "P3"))
            routes = importlib.import_module("services.admin.routes")
            inv = {
                "id": "in_5", "customer": "cus_5", "subscription": "sub_5",
                "status": "open", "currency": "usd",
                "amount_due": 9900, "amount_paid": 0, "amount_remaining": 9900,
                "metadata": {"tenant_id": "t-5"},
            }
            asyncio.run(routes._handle_invoice_event("invoice.payment_failed", inv))
            acct = asyncio.run(stripe_repository.get_billing_account("t-5"))
            assert acct["plan_tier"] == "P3"  # not downgraded by invoice event alone
            invs = asyncio.run(stripe_repository.list_invoices("t-5"))
            assert invs[0]["status"] == "open"

    def test_record_webhook_event_once_idempotent(self, monkeypatch):
        self._setup(monkeypatch)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            first = asyncio.run(
                stripe_repository.record_webhook_event_once("evt_1", "checkout.session.completed")
            )
            second = asyncio.run(
                stripe_repository.record_webhook_event_once("evt_1", "checkout.session.completed")
            )
            assert first is True
            assert second is False


# ---------------------------------------------------------------------------
# Plan-sync: API key validator picks up billing-account plan_tier
# ---------------------------------------------------------------------------


class TestPlanSync:
    def test_billing_account_plan_tier_overrides_cached_key(self, monkeypatch):
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            asyncio.run(stripe_repository.update_plan_tier("tenant_001", "P3"))

            from shared.auth.auth import APIKeyValidator, PlanTier
            v = APIKeyValidator()
            ctx = asyncio.run(v.validate_async("ak_test_123"))
            assert ctx.tenant_id == "tenant_001"
            assert ctx.plan_tier == PlanTier.P3_GROWTH_INTELLIGENCE


# ---------------------------------------------------------------------------
# Overage invoice endpoint
# ---------------------------------------------------------------------------


class TestOverageInvoice:
    def test_overage_invoice_blocked_without_price_id(self, monkeypatch):
        _set_env(
            monkeypatch,
            AETHER_ENV="local", JWT_SECRET="x",
            STRIPE_BILLING_ENABLED="true",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
            STRIPE_PRICE_P1="p1", STRIPE_PRICE_P2="p2",
            STRIPE_PRICE_P3="p3", STRIPE_PRICE_P4="p4",
        )
        monkeypatch.delenv("STRIPE_OVERAGE_PRICE_ID", raising=False)
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_client
            from shared.common.common import BadRequestError

            with pytest.raises(BadRequestError) as exc:
                asyncio.run(
                    stripe_client.create_overage_invoice_item(
                        tenant_id="t-1",
                        customer_id="cus_1",
                        billing_period="2026-04",
                        overage_requests=1000,
                        amount_cents=5000,
                    )
                )
            assert "overage" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Regression: webhook idempotency claim is released on handler failure
# ---------------------------------------------------------------------------


class TestWebhookIdempotencyOnFailure:
    def test_delete_webhook_event_releases_claim(self, monkeypatch):
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            assert asyncio.run(
                stripe_repository.record_webhook_event_once("evt_x", "x")
            ) is True
            # Releasing the claim allows the same event_id to be re-processed.
            asyncio.run(stripe_repository.delete_webhook_event("evt_x"))
            assert asyncio.run(
                stripe_repository.record_webhook_event_once("evt_x", "x")
            ) is True

    def test_record_event_raises_on_db_error(self, monkeypatch):
        """A DB failure inside record_webhook_event_once must raise so the
        webhook route can return 5xx and Stripe will retry, instead of
        ack-ing as a duplicate.
        """
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository

            class _FailingPool:
                async def execute(self, *args, **kwargs):
                    raise RuntimeError("simulated DB outage")

            async def _get_failing_pool():
                return _FailingPool()

            monkeypatch.setattr(stripe_repository, "get_pool", _get_failing_pool)
            with pytest.raises(RuntimeError):
                asyncio.run(
                    stripe_repository.record_webhook_event_once("evt_db", "x")
                )


# ---------------------------------------------------------------------------
# Regression: cross-tenant overage uses the BILLED tenant's plan_tier
# ---------------------------------------------------------------------------


class TestOveragePlanTierResolution:
    def test_resolve_plan_tier_for_other_tenant_uses_billing_account(
        self, monkeypatch,
    ):
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()
            # Billed tenant is on P4.
            asyncio.run(stripe_repository.update_plan_tier("billed-tenant", "P4"))

            from shared.auth.auth import (
                APIKeyTier, PlanTier, Role, TenantContext,
            )
            routes = importlib.import_module("services.admin.routes")

            class _Req:
                pass

            req = _Req()
            req.state = type("S", (), {})()
            req.state.tenant = TenantContext(
                tenant_id="admin-tenant",
                role=Role.ADMIN,
                api_key_tier=APIKeyTier.PRO,
                plan_tier=PlanTier.P2_PROFESSIONAL,  # caller's plan
                permissions=["billing", "admin"],
            )
            plan = asyncio.run(
                routes._resolve_plan_tier_for_tenant(req, "billed-tenant")
            )
            # Must NOT inherit the caller's P2 plan; must read billed P4.
            assert plan == PlanTier.P4_PROTOCOL_MASTER

    def test_resolve_plan_tier_for_self_uses_request_context(self, monkeypatch):
        _set_env(monkeypatch, AETHER_ENV="local", JWT_SECRET="x")
        with backend_path():
            _reload_settings()
            from shared.billing import stripe_repository
            stripe_repository._reset_in_memory_for_tests()

            from shared.auth.auth import (
                APIKeyTier, PlanTier, Role, TenantContext,
            )
            routes = importlib.import_module("services.admin.routes")

            class _Req:
                pass

            req = _Req()
            req.state = type("S", (), {})()
            req.state.tenant = TenantContext(
                tenant_id="self-tenant",
                role=Role.EDITOR,
                api_key_tier=APIKeyTier.PRO,
                plan_tier=PlanTier.P3_GROWTH_INTELLIGENCE,
                permissions=["billing"],
            )
            plan = asyncio.run(
                routes._resolve_plan_tier_for_tenant(req, "self-tenant")
            )
            assert plan == PlanTier.P3_GROWTH_INTELLIGENCE
