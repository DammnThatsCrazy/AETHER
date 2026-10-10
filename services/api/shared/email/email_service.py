"""Aether Shared — Transactional Email

Thin adapter over SES (boto3) or SendGrid (requests). Degrades silently when
EMAIL_ENABLED=false or the provider SDK is unavailable.

Usage:
    from shared.email.email_service import send_email
    await send_email(to="user@example.com", subject="Welcome", body_html="<p>Hi</p>")
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config.settings import settings
from shared.logger.logger import get_logger

logger = get_logger("aether.email")


async def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
) -> bool:
    """Send a transactional email. Returns True on success, False on failure."""
    cfg = settings.email
    if not cfg.enabled or not to:
        logger.info(f"[email-noop] to={to} subject={subject!r}")
        return False
    try:
        if cfg.provider == "ses":
            return await _send_ses(to, subject, body_html, body_text or _html_to_text(body_html), cfg)
        if cfg.provider == "sendgrid":
            return await _send_sendgrid(to, subject, body_html, body_text or _html_to_text(body_html), cfg)
        logger.warning(f"Unknown email provider: {cfg.provider!r}")
        return False
    except Exception as e:
        logger.warning(f"Email send failed: to={to} subject={subject!r} error={e}")
        return False


def _html_to_text(html: str) -> str:
    """Naive HTML→plain-text strip for fallback body_text."""
    import re
    return re.sub(r"<[^>]+>", "", html).strip()


async def _send_ses(to: str, subject: str, body_html: str, body_text: str, cfg) -> bool:
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("boto3 not installed; cannot send email via SES")
        return False
    client = boto3.client("ses", region_name=cfg.aws_region)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: client.send_email(
        Source=f"{cfg.from_name} <{cfg.from_address}>",
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": body_text, "Charset": "UTF-8"},
                "Html": {"Data": body_html, "Charset": "UTF-8"},
            },
        },
    ))
    logger.info(f"[ses] sent to={to} subject={subject!r}")
    return True


async def _send_sendgrid(to: str, subject: str, body_html: str, body_text: str, cfg) -> bool:
    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("requests not installed; cannot send email via SendGrid")
        return False
    if not cfg.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not set")
        return False
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": cfg.from_address, "name": cfg.from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": body_text},
            {"type": "text/html", "value": body_html},
        ],
    }
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(None, lambda: requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers={"Authorization": f"Bearer {cfg.sendgrid_api_key}"},
        timeout=10,
    ))
    ok = resp.status_code in (200, 202)
    if ok:
        logger.info(f"[sendgrid] sent to={to} subject={subject!r}")
    else:
        logger.warning(f"[sendgrid] failed status={resp.status_code} to={to}")
    return ok
