#!/usr/bin/env python3
"""Campaign sender for per-recipient click attribution with Aether.

Aether never sends email (ADR-C1). This sender runs on your side and uses your
own mail server:

1. renders nothing itself — you pass one finished message (HTML and/or text);
2. calls Aether ``POST /v1/comms/click-tokens/tag-links`` in batches of 500 to
   get one copy per recipient, each link to your own domains carrying that
   recipient's signed ``ae`` token. Suppressed recipients come back with no copy
   and are skipped;
3. sends every copy through SMTP (your server's credentials);
4. writes each delivered message id to a local ledger before anything else, so
   rerunning the same ``--send-id`` never mails anyone twice;
5. reports each delivery to Aether ``POST /v1/comms/webhook`` as ``email_sent``
   (or ``email_dropped`` when the server refuses it), using the tenant-scoped
   alias Aether returned — never the address. Reports that cannot be delivered
   are kept in ``<ledger>.pending.jsonl`` and retried on the next run.

Standard library only (Python 3.9+). Usage::

    export AETHER_API_URL=https://api.example.com AETHER_API_KEY=...
    export SMTP_HOST=smtp.example.com SMTP_USERNAME=... SMTP_PASSWORD=... MAIL_FROM="Shop <news@shop.test>"
    python aether_campaign_sender.py --send-id campaign-65-wave-1 --campaign-id campaign-65 \\
        --subject "Our sale" --html message.html --text message.txt \\
        --recipients recipients.csv --allowed-host shop.test \\
        --unsubscribe-url "https://shop.test/unsubscribe" --ledger campaign-65.ledger.jsonl

    # Preview: write .eml files instead of sending, report nothing.
    python aether_campaign_sender.py ... --preview-dir ./preview

``recipients.csv`` has an ``email`` column (header required).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional, Protocol

BATCH_SIZE = 500  # tag-links and webhook request limit
PROVIDER = "campaign_sender"
USER_AGENT = "aether-campaign-sender/1.0"


# ── Aether API ────────────────────────────────────────────────────────────────

PostJson = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


class AetherError(RuntimeError):
    pass


def _urllib_post(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - caller-configured URL
        return json.loads(response.read().decode("utf-8") or "{}")


class AetherClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        webhook_secret: Optional[str] = None,
        post_json: Optional[PostJson] = None,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url or not api_key:
            raise AetherError("AETHER_API_URL and AETHER_API_KEY are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self._post = post_json or _urllib_post
        self._retries = max(1, retries)
        self._sleep = sleep

    def _headers(self, body: dict[str, Any], *, signed: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if signed and self.webhook_secret:
            # Same bytes as _urllib_post sends.
            raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
            timestamp = str(int(time.time()))
            digest = hmac.new(
                self.webhook_secret.encode("utf-8"), f"{timestamp}.".encode() + raw, hashlib.sha256
            ).hexdigest()
            headers["X-Aether-Timestamp"] = timestamp
            headers["X-Aether-Signature"] = f"sha256={digest}"
        return headers

    def _call(self, path: str, body: dict[str, Any], *, signed: bool = False) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                return self._post(url, body, self._headers(body, signed=signed))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
                    raise AetherError(f"{path} returned {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            self._sleep(2 ** attempt)
        raise AetherError(f"{path} failed after {self._retries} attempts: {last}")

    def tag_links(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self._call("/v1/comms/click-tokens/tag-links", body)
        return response.get("data", response)

    def report(self, events: list[dict[str, Any]]) -> None:
        for chunk in _chunks(events, BATCH_SIZE):
            self._call("/v1/comms/webhook", {"provider": PROVIDER, "events": chunk}, signed=True)


# ── Delivery ──────────────────────────────────────────────────────────────────

class Transport(Protocol):
    def send(self, message: EmailMessage) -> None: ...
    def close(self) -> None: ...


class SmtpTransport:
    """One SMTP connection reused for a run. Raises on refusal."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        starttls: bool = True,
        use_ssl: bool = False,
        smtp_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not host:
            raise ValueError("SMTP_HOST is required (or use --preview-dir)")
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.starttls, self.use_ssl = starttls, use_ssl
        self._factory = smtp_factory
        self._conn: Any = None

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        context = ssl.create_default_context()
        if self._factory is not None:
            conn = self._factory(self.host, self.port)
        elif self.use_ssl:
            conn = smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=60)
        else:
            conn = smtplib.SMTP(self.host, self.port, timeout=60)
        if self.starttls and not self.use_ssl:
            conn.starttls(context=context)
        if self.username:
            conn.login(self.username, self.password or "")
        self._conn = conn
        return conn

    def send(self, message: EmailMessage) -> None:
        try:
            self._connect().send_message(message)
        except smtplib.SMTPServerDisconnected:
            self._conn = None
            self._connect().send_message(message)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.quit()
            except Exception:
                pass
            self._conn = None


class PreviewTransport:
    """Writes each message as an .eml file; sends nothing."""

    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def send(self, message: EmailMessage) -> None:
        self.count += 1
        (self.directory / f"{self.count:05d}.eml").write_bytes(bytes(message))

    def close(self) -> None:
        pass


# ── Send-once ledger ──────────────────────────────────────────────────────────

class SendLedger:
    """Append-only record of delivered message ids, flushed per send."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.pending_path = self.path.with_name(self.path.name + ".pending.jsonl")
        self._sent: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text("utf-8").splitlines():
                if line.strip():
                    self._sent.add(json.loads(line)["external_message_id"])

    def already_sent(self, message_id: str) -> bool:
        return message_id in self._sent

    def record_sent(self, message_id: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"external_message_id": message_id}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._sent.add(message_id)

    def take_pending(self) -> list[dict[str, Any]]:
        if not self.pending_path.exists():
            return []
        events = [json.loads(l) for l in self.pending_path.read_text("utf-8").splitlines() if l.strip()]
        self.pending_path.unlink()
        return events

    def keep_pending(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        with self.pending_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")


# ── Send run ──────────────────────────────────────────────────────────────────

@dataclass
class Message:
    subject: str
    mail_from: str
    allowed_hosts: list[str]
    html: Optional[str] = None
    text: Optional[str] = None
    campaign_id: Optional[str] = None
    sequence_step: Optional[int] = None
    message_category: str = "marketing"
    unsubscribe_url: Optional[str] = None
    reply_to: Optional[str] = None


@dataclass
class RunSummary:
    counts: dict[str, int] = field(default_factory=dict)
    reported: int = 0
    pending_reports: int = 0

    def add(self, status: str) -> None:
        self.counts[status] = self.counts.get(status, 0) + 1


def message_id_for(send_id: str, email: str) -> str:
    """Stable per-recipient message id within a send (no address inside)."""
    normalized = email.strip().lower()
    return f"{send_id}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def build_email(message: Message, to: str, html: Optional[str], text: Optional[str], message_id: str) -> EmailMessage:
    email = EmailMessage()
    email["From"] = message.mail_from
    email["To"] = to
    email["Subject"] = message.subject
    email["Message-ID"] = make_msgid(domain=message.mail_from.rsplit("@", 1)[-1].strip("> ") or None)
    email["X-Aether-Message-Id"] = message_id
    if message.reply_to:
        email["Reply-To"] = message.reply_to
    if message.unsubscribe_url:
        email["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
        email["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if text is not None:
        email.set_content(text)
        if html is not None:
            email.add_alternative(html, subtype="html")
    else:
        email.set_content(html or "", subtype="html")
    return email


def _event(event_type: str, message: Message, copy: dict[str, Any], **extra: Any) -> dict[str, Any]:
    message_id = copy["external_message_id"]
    return {
        "event_type": event_type,
        "external_id": f"{PROVIDER}:{event_type}:{message_id}",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "properties": {
            "provider": PROVIDER,
            "recipient_alias_id": copy["recipient_alias_id"],
            "campaign_id": message.campaign_id,
            "external_message_id": message_id,
            "sequence_step": message.sequence_step,
            "message_category": message.message_category,
            "channel": "email",
            "direction": "outbound",
            **extra,
        },
    }


def run_send(
    *,
    client: AetherClient,
    transport: Transport,
    ledger: SendLedger,
    send_id: str,
    message: Message,
    recipients: Iterable[str],
    report: bool = True,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
) -> RunSummary:
    summary = RunSummary()
    emails = [e.strip() for e in recipients if e and e.strip()]
    if report:
        retry = ledger.take_pending()
        if retry:
            try:
                client.report(retry)
                summary.reported += len(retry)
            except AetherError as exc:
                ledger.keep_pending(retry)
                log(f"previous reports still undeliverable: {exc}")

    try:
        for batch in _chunks(emails, BATCH_SIZE):
            ids = [message_id_for(send_id, e) for e in batch]
            tagged = client.tag_links({
                "campaign_id": message.campaign_id,
                "sequence_step": message.sequence_step,
                "allowed_hosts": message.allowed_hosts,
                "html": message.html,
                "text": message.text,
                "recipients": [
                    {"recipient_email": e, "external_message_id": mid} for e, mid in zip(batch, ids)
                ],
            })
            events: list[dict[str, Any]] = []
            for copy in tagged.get("recipients", []):
                index = int(copy["index"])
                email, message_id = batch[index], ids[index]
                copy.setdefault("external_message_id", message_id)
                status = copy.get("status") or ("tagged" if copy.get("tagged") else "untagged")
                if status == "suppressed":
                    summary.add("suppressed")
                    continue
                if status != "tagged" or not copy.get("recipient_alias_id"):
                    # No recipient on the copy: sending it would be a shared link.
                    summary.add("invalid")
                    continue
                if ledger.already_sent(message_id):
                    summary.add("duplicate")
                    continue
                try:
                    transport.send(build_email(message, email, copy.get("html"), copy.get("text"), message_id))
                except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as exc:
                    summary.add("refused")
                    events.append(_event("email_dropped", message, copy, drop_reason=type(exc).__name__))
                    continue
                ledger.record_sent(message_id)
                summary.add("sent")
                events.append(_event("email_sent", message, copy))
            if report and events:
                try:
                    client.report(events)
                    summary.reported += len(events)
                except AetherError as exc:
                    ledger.keep_pending(events)
                    summary.pending_reports += len(events)
                    log(f"report deferred ({len(events)} events): {exc}")
    finally:
        transport.close()
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def _read_recipients(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "email" not in reader.fieldnames:
            raise SystemExit(f"{path}: needs a header row with an 'email' column")
        return [row["email"] for row in reader if row.get("email")]


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--send-id", required=True, help="idempotency key for this send")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--html", help="path to the HTML body")
    parser.add_argument("--text", help="path to the plain-text body")
    parser.add_argument("--recipients", required=True, help="CSV with an 'email' column")
    parser.add_argument("--allowed-host", action="append", required=True, dest="allowed_hosts",
                        help="your own domain whose links get tagged (repeatable)")
    parser.add_argument("--campaign-id")
    parser.add_argument("--sequence-step", type=int)
    parser.add_argument("--category", default="marketing", choices=["marketing", "transactional"])
    parser.add_argument("--unsubscribe-url")
    parser.add_argument("--reply-to")
    parser.add_argument("--ledger", help="send-once ledger file (default: <send-id>.ledger.jsonl)")
    parser.add_argument("--preview-dir", help="write .eml files here instead of sending; reports nothing")
    args = parser.parse_args(argv)

    if not args.html and not args.text:
        parser.error("provide --html and/or --text")
    mail_from = os.getenv("MAIL_FROM", "")
    if not mail_from:
        parser.error("MAIL_FROM is required")

    message = Message(
        subject=args.subject,
        mail_from=mail_from,
        allowed_hosts=args.allowed_hosts,
        html=Path(args.html).read_text("utf-8") if args.html else None,
        text=Path(args.text).read_text("utf-8") if args.text else None,
        campaign_id=args.campaign_id,
        sequence_step=args.sequence_step,
        message_category=args.category,
        unsubscribe_url=args.unsubscribe_url,
        reply_to=args.reply_to,
    )
    client = AetherClient(
        os.getenv("AETHER_API_URL", ""), os.getenv("AETHER_API_KEY", ""),
        webhook_secret=os.getenv("AETHER_WEBHOOK_SECRET") or None,
    )
    preview = bool(args.preview_dir)
    if preview:
        transport: Transport = PreviewTransport(args.preview_dir)
        ledger = SendLedger(str(Path(args.preview_dir) / "preview.ledger.jsonl"))
    else:
        transport = SmtpTransport(
            os.getenv("SMTP_HOST", ""), int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USERNAME") or None,
            password=os.getenv("SMTP_PASSWORD") or None,
            starttls=_env_flag("SMTP_STARTTLS", True),
            use_ssl=_env_flag("SMTP_SSL", False),
        )
        ledger = SendLedger(args.ledger or f"{args.send_id}.ledger.jsonl")

    summary = run_send(
        client=client, transport=transport, ledger=ledger, send_id=args.send_id,
        message=message, recipients=_read_recipients(args.recipients), report=not preview,
    )
    print(json.dumps({
        "send_id": args.send_id, "preview": preview, "counts": summary.counts,
        "reported": summary.reported, "pending_reports": summary.pending_reports,
    }))
    return 1 if summary.pending_reports else 0


if __name__ == "__main__":
    raise SystemExit(main())
