"""Public lead capture accepts the unified-site contact topics.

apps/public-site's Contact page sends one of six topics as `lead_type`. The
endpoint previously accepted only waitlist, early-access and demo-request, so
every contact-form submission failed with 400.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "backend"

CONTACT_TOPICS = ["pilot", "product", "developer", "security", "proof", "research"]


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


@pytest.fixture()
def contact_routes(monkeypatch):
    with backend_path():
        from services.contact import routes

        store = AsyncMock()
        monkeypatch.setattr(routes, "_enterprise_inquiries", store)
        monkeypatch.setattr(routes, "_notify_lead_team", AsyncMock(return_value=True))
        yield routes, store


@pytest.mark.parametrize("lead_type", CONTACT_TOPICS + ["waitlist", "early-access", "demo-request"])
def test_accepts_contact_topics_and_existing_forms(contact_routes, lead_type):
    routes, store = contact_routes
    body = routes.LeadCaptureRequest(
        lead_type=lead_type,
        email="jordan@northwind.example",
        name="Jordan Lee",
        message="One view of trial-to-paid across web, CRM and billing.",
        source="olympus-marketing",
    )
    result = asyncio.run(routes.capture_lead(body, request=None))
    assert result["data"]["received"] is True
    saved = store.insert.await_args.args[1]
    assert saved["lead_type"] == lead_type
    assert saved["source"] == "olympus-marketing"


def test_rejects_unknown_lead_type(contact_routes):
    routes, store = contact_routes
    body = routes.LeadCaptureRequest(lead_type="contact", email="jordan@northwind.example")
    with pytest.raises(routes.BadRequestError):
        asyncio.run(routes.capture_lead(body, request=None))
    store.insert.assert_not_awaited()


def test_every_topic_has_a_notification_label(contact_routes):
    routes, _ = contact_routes
    assert set(routes._VALID_LEAD_TYPES) == set(routes._LEAD_TYPE_LABELS)
