"""External campaign sender (packages/sdk/examples/campaign-sender-python).

The sender runs outside Aether (ADR-C1). These tests drive it against the
real Aether route handlers in-process — ``tag-links`` and the signed comms
webhook — with a fake SMTP server, so the wire contract is exercised for real.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import smtplib
import sys
from email import message_from_bytes
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

SENDER_PATH = ROOT / "packages" / "sdk" / "examples" / "campaign-sender-python" / "aether_campaign_sender.py"
TENANT = "tenant-sender"
SECRET = "whsec_test_secret"
HTML = '<p>Sale</p><a href="https://shop.test/sale?utm_source=email">Shop</a> <a href="https://partner.test/x">x</a>'
TEXT = "Sale: https://shop.test/sale?utm_source=email"


def _load_sender():
    spec = importlib.util.spec_from_file_location("aether_campaign_sender", SENDER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["aether_campaign_sender"] = module
    spec.loader.exec_module(module)
    return module


sender = _load_sender()


class InProcessAether:
    """``post_json`` that runs the real Aether route handlers."""

    def __init__(self, *, webhook_down: bool = False) -> None:
        self.webhook_down = webhook_down
        self.reported: list[dict] = []
        self.ingested: list[dict] = []

    def __call__(self, url: str, body: dict, headers: dict) -> dict:
        assert headers["Authorization"] == "Bearer test-key"
        return asyncio.run(self._dispatch(urlsplit(url).path, body, headers))

    async def _dispatch(self, path: str, body: dict, headers: dict) -> dict:
        from journeys.comms import routes

        tenant = SimpleNamespace(
            tenant_id=TENANT, webhook_secret=SECRET, require_permission=lambda _p: None,
        )
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")

        async def read_body():
            return raw

        request = SimpleNamespace(state=SimpleNamespace(tenant=tenant), headers=headers, body=read_body)
        if path == "/v1/comms/click-tokens/tag-links":
            return await routes.tag_links_route(request, routes.TagLinksBody(**body))
        if path == "/v1/comms/webhook":
            if self.webhook_down:
                import urllib.error

                raise urllib.error.URLError("connection refused")
            self.reported.append(body)
            return await routes.generic_comms_webhook(request, routes.CommsWebhookBody(**body))
        raise AssertionError(f"unexpected path {path}")


class FakeSmtp:
    def __init__(self, refuse: set[str] = frozenset()) -> None:
        self.messages: list = []
        self.refuse = set(refuse)
        self.logged_in = False

    def factory(self, host, port):
        return self

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, message):
        if message["To"] in self.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        self.messages.append(message_from_bytes(bytes(message)))

    def quit(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    from journeys.comms import ingest
    from journeys.comms.suppression_authority import SuppressionAuthorityService
    from journeys.comms.mailbox import build_email_alias

    gone = build_email_alias("gone@example.com", TENANT).alias_hash

    async def is_suppressed(self, tenant_id, *, recipient_alias_id=None, **_kw):
        return recipient_alias_id == gone

    monkeypatch.setattr(SuppressionAuthorityService, "is_suppressed", is_suppressed)
    ingested: list[dict] = []

    async def fake_ingest(tenant_id, events, **_kw):
        assert tenant_id == TENANT
        ingested.extend(events)
        return {"communications": len(events), "catalog": 0, "identities": 0, "skipped": 0}

    monkeypatch.setattr(ingest, "ingest_normalized_events", fake_ingest)
    return SimpleNamespace(tmp=tmp_path, ingested=ingested)


def _message():
    return sender.Message(
        subject="Our sale", mail_from="Shop <news@shop.test>", allowed_hosts=["shop.test"],
        html=HTML, text=TEXT, campaign_id="campaign-65",
        unsubscribe_url="https://shop.test/unsubscribe",
    )


def _run(env, smtp, aether, recipients, *, send_id="campaign-65-wave-1", report=True, transport=None):
    client = sender.AetherClient(
        "https://aether.test", "test-key", webhook_secret=SECRET, post_json=aether, sleep=lambda _s: None,
    )
    return sender.run_send(
        client=client,
        transport=transport or sender.SmtpTransport("smtp.test", username="u", password="p", smtp_factory=smtp.factory),
        ledger=sender.SendLedger(str(env.tmp / "send.ledger.jsonl")),
        send_id=send_id, message=_message(), recipients=recipients, report=report,
        log=lambda _l: None,
    )


def _token(email_message) -> str:
    for part in email_message.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode()
            href = html.split('href="')[1].split('"')[0].replace("&amp;", "&")
            return parse_qs(urlsplit(href).query)["ae"][0]
    raise AssertionError("no html part")


class TestCampaignSenderClient:
    def test_sends_tagged_copies_skips_suppressed_and_reports_by_alias(self, env):
        from journeys.comms.click_token import verify_click_token
        from journeys.comms.mailbox import build_email_alias

        smtp, aether = FakeSmtp(), InProcessAether()
        summary = _run(env, smtp, aether, ["jane@example.com", "gone@example.com", "not-an-email", "sam@example.com"])

        assert summary.counts == {"sent": 2, "suppressed": 1, "invalid": 1}
        assert smtp.logged_in
        by_to = {m["To"]: m for m in smtp.messages}
        assert set(by_to) == {"jane@example.com", "sam@example.com"}
        jane = verify_click_token(_token(by_to["jane@example.com"]), TENANT).claims
        assert jane.recipient_alias_id == build_email_alias("jane@example.com", TENANT).alias_hash
        assert jane.campaign_id == "campaign-65"
        assert by_to["jane@example.com"]["List-Unsubscribe"] == "<https://shop.test/unsubscribe>"
        assert "https://partner.test/x" in str(by_to["jane@example.com"])

        assert summary.reported == 2
        events = [e for body in aether.reported for e in body["events"]]
        assert {e["event_type"] for e in events} == {"email_sent"}
        assert "example.com" not in json.dumps(aether.reported)
        # The real signed webhook accepted them and handed them to comms ingest.
        assert {e["properties"]["external_message_id"] for e in env.ingested} == {
            jane.external_message_id, verify_click_token(_token(by_to["sam@example.com"]), TENANT).claims.external_message_id,
        }

    def test_rerunning_a_send_never_mails_twice(self, env):
        smtp = FakeSmtp()
        _run(env, smtp, InProcessAether(), ["jane@example.com"])
        again = _run(env, smtp, InProcessAether(), ["jane@example.com", "sam@example.com"])
        assert again.counts == {"duplicate": 1, "sent": 1}
        assert [m["To"] for m in smtp.messages] == ["jane@example.com", "sam@example.com"]

    def test_refused_recipient_is_reported_dropped_and_retried_later(self, env):
        aether = InProcessAether()
        first = _run(env, FakeSmtp(refuse={"jane@example.com"}), aether, ["jane@example.com"])
        assert first.counts == {"refused": 1}
        assert aether.reported[0]["events"][0]["event_type"] == "email_dropped"
        retry_smtp = FakeSmtp()
        assert _run(env, retry_smtp, InProcessAether(), ["jane@example.com"]).counts == {"sent": 1}

    def test_undeliverable_reports_are_kept_and_retried_next_run(self, env):
        down = _run(env, FakeSmtp(), InProcessAether(webhook_down=True), ["jane@example.com"])
        assert down.counts == {"sent": 1} and down.pending_reports == 1
        assert (env.tmp / "send.ledger.jsonl.pending.jsonl").exists()

        aether = InProcessAether()
        later = _run(env, FakeSmtp(), aether, ["jane@example.com"])
        assert later.counts == {"duplicate": 1} and later.reported == 1
        assert aether.reported[0]["events"][0]["event_type"] == "email_sent"
        assert not (env.tmp / "send.ledger.jsonl.pending.jsonl").exists()

    def test_preview_writes_eml_files_and_reports_nothing(self, env):
        aether, preview = InProcessAether(), sender.PreviewTransport(str(env.tmp / "preview"))
        summary = _run(env, FakeSmtp(), aether, ["jane@example.com"], report=False, transport=preview)
        assert summary.counts == {"sent": 1} and aether.reported == []
        eml = message_from_bytes((env.tmp / "preview" / "00001.eml").read_bytes())
        assert eml["To"] == "jane@example.com" and _token(eml)

    def test_webhook_signature_matches_aether_verification(self):
        from governance.security.integration_security import verify_signature

        client = sender.AetherClient("https://aether.test", "k", webhook_secret=SECRET)
        body = {"provider": "campaign_sender", "events": []}
        headers = client._headers(body, signed=True)
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        assert verify_signature(SECRET, raw, headers["X-Aether-Timestamp"], headers["X-Aether-Signature"])

    def test_cli_requires_mail_from_and_a_body(self, env, monkeypatch, capsys):
        monkeypatch.delenv("MAIL_FROM", raising=False)
        csv_path = env.tmp / "r.csv"
        csv_path.write_text("email\njane@example.com\n")
        with pytest.raises(SystemExit):
            sender.main(["--send-id", "s", "--subject", "x", "--recipients", str(csv_path), "--allowed-host", "shop.test"])
