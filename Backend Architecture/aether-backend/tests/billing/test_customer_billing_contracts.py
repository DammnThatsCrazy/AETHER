from datetime import datetime, timezone

from services.billing import routes
from shared.billing import stripe_client


def test_disabled_stripe_capability_is_explicit(monkeypatch):
    cfg = type("StripeConfig", (), {"enabled": False})()
    monkeypatch.setattr(stripe_client.settings, "stripe_billing", cfg)

    assert stripe_client.capability_status() == {
        "provider": "stripe",
        "status": "not_configured",
        "enabled": False,
    }


def test_enabled_incomplete_stripe_capability_is_degraded(monkeypatch):
    cfg = type(
        "StripeConfig",
        (),
        {
            "enabled": True,
            "secret_key": "",
            "webhook_secret": "",
            "price_p1": "",
            "price_p2": "",
            "price_p3": "",
            "price_p4": "",
            "checkout_success_url": "https://app.example/success",
            "checkout_cancel_url": "https://app.example/cancel",
            "portal_return_url": "https://app.example/billing",
        },
    )()
    monkeypatch.setattr(stripe_client.settings, "stripe_billing", cfg)
    monkeypatch.setattr(stripe_client, "STRIPE_SDK_AVAILABLE", True)

    status = stripe_client.capability_status()
    assert status["status"] == "degraded"
    assert status["missing"] == [
        "secret_key", "webhook_secret", "price_p1", "price_p2", "price_p3", "price_p4"
    ]
    assert "secret" not in status


def test_invoice_serialization_is_provider_independent():
    created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = routes._serialize_invoice(
        {
            "stripe_invoice_id": "in_123",
            "tenant_id": "tenant-secret-internal",
            "status": "paid",
            "currency": "usd",
            "amount_due": 1200,
            "amount_paid": 1200,
            "amount_remaining": 0,
            "created_at": created_at,
            "hosted_invoice_url": "https://invoice.stripe.example/in_123",
            "invoice_pdf": "https://invoice.stripe.example/in_123.pdf",
        }
    )

    assert result == {
        "id": "in_123",
        "status": "paid",
        "currency": "usd",
        "amount_due": 1200,
        "amount_paid": 1200,
        "amount_remaining": 0,
        "period_start": None,
        "period_end": None,
        "created_at": "2026-07-01T00:00:00+00:00",
        "hosted_invoice_url": "https://invoice.stripe.example/in_123",
        "invoice_pdf_url": "https://invoice.stripe.example/in_123.pdf",
    }
