"""Enterprise inquiry endpoint: durable persistence + real email, no PII in logs.

Drives the handler directly (stub tenant), patching the email service so the
tests are deterministic regardless of EMAIL_ENABLED / provider SDK presence.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.contact.routes as contact_routes
from repositories.repos import EnterpriseInquiryRepository, reset_in_memory_stores
from services.contact.routes import EnterpriseContactRequest, contact_enterprise
from shared.common.common import BadRequestError, ServiceUnavailableError
from shared.email import email_service


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


def _body(**overrides) -> EnterpriseContactRequest:
    payload = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "company_name": "Analytical Engines",
        "company_type": "enterprise",
        "message": "We need a dedicated data plane for our analytics workloads.",
    }
    payload.update(overrides)
    return EnterpriseContactRequest(**payload)


async def _sent_email(**kwargs):
    return True


async def _failed_email(**kwargs):
    return False


async def test_valid_inquiry_persists_and_notifies(monkeypatch, capsys):
    monkeypatch.setattr(email_service, "send_email", _sent_email)
    out = await contact_enterprise(_body(), _req())
    assert out["data"]["received"] is True
    inquiry_id = out["data"]["inquiry_id"]
    assert inquiry_id

    row = await EnterpriseInquiryRepository().find_by_id(inquiry_id)
    assert row is not None
    assert row["tenant_id"] == "tenant-a"
    assert row["status"] == "notified"
    assert row["name"] == "Ada Lovelace"

    # The inquiry PII must never reach application logs.
    captured = capsys.readouterr().out
    assert "Ada Lovelace" not in captured
    assert "ada@example.com" not in captured
    assert "Analytical Engines" not in captured
    assert "dedicated data plane" not in captured


async def test_email_failure_is_nonfatal_and_inquiry_retained(monkeypatch):
    monkeypatch.setattr(email_service, "send_email", _failed_email)
    out = await contact_enterprise(_body(), _req())
    assert out["data"]["received"] is True
    inquiry_id = out["data"]["inquiry_id"]

    row = await EnterpriseInquiryRepository().find_by_id(inquiry_id)
    assert row is not None
    assert row["status"] == "email_failed"


async def test_invalid_company_type_rejected():
    with pytest.raises(BadRequestError):
        await contact_enterprise(_body(company_type="conglomerate"), _req())


async def test_email_body_escapes_user_controlled_html(monkeypatch):
    """Email XSS: tenant-supplied fields are HTML-escaped in the rendered body."""
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(email_service, "send_email", _capture)
    await contact_enterprise(_body(
        message="<script>alert(1)</script>",
        name="<b>Ada</b>",
        company_name="<img src=x onerror=alert(1)>",
    ), _req())

    body_html = captured["body_html"]
    # Raw markup from the user must never survive into the mail client.
    assert "<script>" not in body_html
    assert "<b>" not in body_html
    assert "<img" not in body_html
    # ... and the escaped forms are present.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body_html
    assert "&lt;b&gt;Ada&lt;/b&gt;" in body_html
    assert "&lt;img src=x onerror=alert(1)&gt;" in body_html


async def test_email_subject_newline_stripped(monkeypatch):
    """Header-injection defense: newlines in the company name cannot reach the subject."""
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(email_service, "send_email", _capture)
    await contact_enterprise(_body(company_name="Acme\r\nBcc: evil@example.com"), _req())

    subject = captured["subject"]
    assert "\r" not in subject
    assert "\n" not in subject


async def test_persistence_failure_is_not_fake_success(monkeypatch):
    async def _boom(self, record_id, data):
        raise RuntimeError("disk full")

    monkeypatch.setattr(contact_routes._enterprise_inquiries, "insert", _boom)
    with pytest.raises(ServiceUnavailableError):
        await contact_enterprise(_body(), _req())
