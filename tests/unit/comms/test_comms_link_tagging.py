"""Per-recipient link tagging: the one call a sending system needs."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-a"
HOSTS = frozenset({"shop.test"})


def _issuer(log: list[str]):
    def issue(link_id: str) -> str:
        log.append(link_id)
        return f"v1.payload{len(log)}.signature0123456789abcdef"
    return issue


def _ae(url: str) -> str | None:
    return (parse_qs(urlsplit(url).query).get("ae") or [None])[0]


class TestTagLinks:
    def test_tags_only_own_hosts_and_keeps_everything_else(self):
        from journeys.comms.link_tagging import link_id_for, tag_links

        html = (
            '<a href="https://shop.test/sale?utm_source=email#top">Sale</a>'
            '<a href="https://www.shop.test/p">Sub</a>'
            '<a href="https://partner.test/x">Partner</a>'
            '<a href="mailto:help@shop.test">Mail</a>'
            '<a href="#anchor">Anchor</a>'
            '<a href="https://shop.test/u?id={{ subscriber.id }}">Unsub</a>'
        )
        issued: list[str] = []
        out = tag_links(html=html, text=None, allowed_hosts=HOSTS, issue=_issuer(issued))

        assert len(issued) == 2
        assert "https://partner.test/x" in out.html
        assert 'href="mailto:help@shop.test"' in out.html
        assert 'href="#anchor"' in out.html
        assert "{{ subscriber.id }}" in out.html
        assert "utm_source=email" in out.html and "#top" in out.html
        assert link_id_for("https://shop.test/sale?utm_source=email#top") in out.links

    def test_repeated_link_gets_one_token_and_existing_token_is_replaced(self):
        from journeys.comms.link_tagging import tag_links

        old = "v1.oldpayload.oldsignature0123456789"
        html = f'<a href="https://shop.test/a?ae={old}">1</a> <a href="https://shop.test/a">2</a>'
        issued: list[str] = []
        out = tag_links(html=html, text=None, allowed_hosts=HOSTS, issue=_issuer(issued))
        assert len(issued) == 1
        assert old not in out.html
        assert out.html.count("ae=v1.payload1.") == 2

    def test_html_entities_and_plain_text_urls(self):
        from journeys.comms.link_tagging import tag_links

        out = tag_links(
            html='<a href="https://shop.test/p?a=1&amp;b=2">x</a>',
            text="Shop now: https://shop.test/p?a=1. Or https://other.test/q",
            allowed_hosts=HOSTS,
            issue=_issuer([]),
        )
        assert "a=1&amp;b=2&amp;ae=" in out.html
        assert "https://shop.test/p?a=1&ae=" in out.text and out.text.split("ae=")[1].split(".")[0] == "v1"
        assert out.text.endswith("Or https://other.test/q")
        assert ". Or" in out.text  # trailing punctuation kept outside the URL

    def test_requires_allowed_hosts(self):
        from journeys.comms.link_tagging import tag_links

        with pytest.raises(ValueError):
            tag_links(html="x", text=None, allowed_hosts=frozenset(), issue=_issuer([]))


class _Tenant:
    tenant_id = TENANT

    def require_permission(self, _permission):
        return None


def _request():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.mark.asyncio
class TestTagLinksRoute:
    async def test_each_recipient_gets_own_verified_tokens(self):
        from journeys.comms.click_token import verify_click_token
        from journeys.comms.mailbox import build_email_alias
        from journeys.comms.routes import TagLinksBody, tag_links_route

        body = TagLinksBody(
            campaign_id="camp-65",
            external_message_id="msg-65",
            allowed_hosts=["shop.test"],
            html='<a href="https://shop.test/sale">Sale</a>',
            text="https://shop.test/sale",
            recipients=[
                {"recipient_email": "Jane@Example.com"},
                {"recipient_email": "sam@example.com", "external_message_id": "msg-65-sam"},
                {},
            ],
        )
        response = await tag_links_route(_request(), body)
        data = response["data"]
        copies = data["recipients"]

        assert "example.com" not in repr(copies).lower()
        assert data["untagged_recipients"] == 1 and copies[2]["tagged"] is False

        jane = verify_click_token(_ae(copies[0]["html"].split('"')[1]), TENANT).claims
        sam = verify_click_token(_ae(copies[1]["text"]), TENANT).claims
        assert jane.recipient_alias_id == build_email_alias("jane@example.com", TENANT).alias_hash
        assert sam.recipient_alias_id == build_email_alias("sam@example.com", TENANT).alias_hash
        assert jane.campaign_id == "camp-65" and jane.external_message_id == "msg-65"
        assert sam.external_message_id == "msg-65-sam"
        assert jane.link_id == sam.link_id == data["links"][0]["link_id"]
        assert data["links"][0]["url"] == "https://shop.test/sale"

    async def test_rejects_empty_body(self):
        from shared.common.common import BadRequestError
        from journeys.comms.routes import TagLinksBody, tag_links_route

        with pytest.raises(BadRequestError):
            await tag_links_route(_request(), TagLinksBody(
                allowed_hosts=["shop.test"], recipients=[{"recipient_email": "a@b.test"}],
            ))

    async def test_suppressed_recipient_gets_no_copy_and_no_token(self, monkeypatch):
        from journeys.comms.mailbox import build_email_alias
        from journeys.comms.routes import TagLinksBody, tag_links_route
        from journeys.comms.suppression_authority import SuppressionAuthorityService

        gone = build_email_alias("gone@example.com", TENANT).alias_hash

        async def is_suppressed(self, tenant_id, *, recipient_alias_id=None, **_kw):
            return recipient_alias_id == gone

        monkeypatch.setattr(SuppressionAuthorityService, "is_suppressed", is_suppressed)
        data = (await tag_links_route(_request(), TagLinksBody(
            allowed_hosts=["shop.test"],
            html='<a href="https://shop.test/sale">Sale</a>',
            recipients=[{"recipient_email": "gone@example.com"}, {"recipient_email": "jane@example.com"}],
        )))["data"]
        gone_copy, jane_copy = data["recipients"]
        assert gone_copy == {"index": 0, "status": "suppressed", "tagged": False, "html": None, "text": None}
        assert jane_copy["status"] == "tagged" and "ae=" in jane_copy["html"]
        assert jane_copy["recipient_alias_id"] == build_email_alias("jane@example.com", TENANT).alias_hash
        assert data["suppressed_recipients"] == 1 and data["untagged_recipients"] == 0
