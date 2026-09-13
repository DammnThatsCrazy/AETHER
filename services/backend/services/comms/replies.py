"""Reply ingestion — correlation and normalization of inbound replies
(Phase 13).

Providers deliver inbound replies through inbound-parse webhooks or mailbox
notifications. This module correlates a reply to the originating message and
thread, detects automated responses (DSN, out-of-office, loops), extracts
structural metadata only (never the full body by default), and produces a
canonical ``email_replied`` event for the standard ingest pipeline.

Correlation evidence priority: In-Reply-To / References (RFC 5322 Message-ID)
→ provider thread id → external message id → reply-to token.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from services.comms.classification import detect_automated_response
from services.comms.mailbox import build_email_alias

logger = get_logger("aether.comms.replies")

# Reply-to tokens embedded in plus-addressed reply addresses:
# replies+<token>@tenant-domain
_REPLY_TOKEN_RE = re.compile(r"\+([A-Za-z0-9_-]{8,64})@")


def _clean_message_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip("<>") or None


def extract_reply_token(to_address: str) -> Optional[str]:
    match = _REPLY_TOKEN_RE.search(to_address or "")
    return match.group(1) if match else None


def correlate_reply(
    *,
    in_reply_to: Optional[str] = None,
    references: Optional[list[str]] = None,
    provider_thread_id: Optional[str] = None,
    external_message_id: Optional[str] = None,
    reply_token: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve the strongest correlation evidence for an inbound reply.

    Returns ``{"external_message_id", "external_thread_id", "method"}`` —
    all optional; ``method`` is None when nothing correlates.
    """
    in_reply_to = _clean_message_id(in_reply_to)
    refs = [r for r in (_clean_message_id(r) for r in (references or [])) if r]

    if in_reply_to:
        return {"external_message_id": in_reply_to,
                "external_thread_id": provider_thread_id,
                "method": "in_reply_to"}
    if refs:
        return {"external_message_id": refs[-1],
                "external_thread_id": provider_thread_id,
                "method": "references"}
    if provider_thread_id:
        return {"external_message_id": external_message_id,
                "external_thread_id": provider_thread_id,
                "method": "provider_thread"}
    if external_message_id:
        return {"external_message_id": external_message_id,
                "external_thread_id": None,
                "method": "external_message_id"}
    if reply_token:
        return {"external_message_id": None,
                "external_thread_id": None,
                "reply_token": reply_token,
                "method": "reply_token"}
    return {"external_message_id": None, "external_thread_id": None, "method": None}


def normalize_inbound_reply(
    tenant_id: str,
    payload: dict[str, Any],
    *,
    provider: str = "inbound_parse",
) -> Optional[dict[str, Any]]:
    """Inbound reply payload → canonical ``email_replied`` normalized event.

    Accepted payload fields (all optional except ``from``):
      from, to, subject, message_id, in_reply_to, references[],
      provider_thread_id, external_message_id, headers{}, received_at,
      raw_evidence_ref.

    The subject is used for automated-response detection only and is not
    retained. Bodies are never accepted here — evidence stays a reference.
    """
    from_address = payload.get("from") or payload.get("from_email")
    if not from_address:
        return None
    alias = build_email_alias(str(from_address), tenant_id)
    if alias is None:
        return None

    headers = payload.get("headers") or {}
    local_part = str(from_address).split("@", 1)[0]
    automated_kind = detect_automated_response(
        subject=payload.get("subject"),
        headers=headers,
        from_address_local=local_part,
    )

    correlation = correlate_reply(
        in_reply_to=payload.get("in_reply_to") or headers.get("In-Reply-To"),
        references=payload.get("references")
        or (headers.get("References", "").split() if headers.get("References") else None),
        provider_thread_id=payload.get("provider_thread_id"),
        external_message_id=payload.get("external_message_id"),
        reply_token=extract_reply_token(str(payload.get("to") or "")),
    )
    if correlation["method"] is None:
        metrics.increment(
            "comms_reply_uncorrelated_total", labels={"tenant_id": tenant_id}
        )

    message_id = _clean_message_id(payload.get("message_id") or headers.get("Message-ID"))
    provider_event_id = message_id or hashlib.sha256(
        f"{tenant_id}:{alias.alias_hash}:{payload.get('received_at') or ''}".encode()
    ).hexdigest()

    properties: dict[str, Any] = {
        "provider": provider,
        "provider_event_id": provider_event_id,
        "channel": "email",
        "direction": "inbound",
        "message_category": payload.get("message_category") or "marketing",
        "recipient_alias_id": alias.alias_hash,     # reply sender becomes the correlated party
        "recipient_display": alias.display,
        "recipient_is_shared_mailbox": alias.is_shared_mailbox,
        "external_message_id": correlation.get("external_message_id"),
        "external_thread_id": correlation.get("external_thread_id"),
        "automated_response_kind": automated_kind,
        "reply_correlation_method": correlation["method"],
        "raw_evidence_ref": payload.get("raw_evidence_ref"),
    }
    return {
        "event_type": "email_replied",
        "source": provider,
        "external_id": provider_event_id,
        "occurred_at": payload.get("received_at") or _now(),
        "properties": {k: v for k, v in properties.items() if v is not None},
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
