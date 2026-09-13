"""Transactional email templates (plain HTML strings, no external deps)."""

from __future__ import annotations

from config.settings import settings


def _base(title: str, body: str) -> str:
    app_url = settings.email.app_url
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333">
<h2 style="color:#1a1a2e">{title}</h2>
{body}
<hr style="margin-top:40px;border:none;border-top:1px solid #eee">
<p style="font-size:12px;color:#999">
  AETHER Platform · <a href="{app_url}" style="color:#666">{app_url}</a><br>
  You're receiving this because you signed up for AETHER.
</p>
</body></html>"""


def welcome(tenant_name: str, api_key: str) -> tuple[str, str]:
    """Return (subject, body_html) for the welcome / first-key email."""
    app_url = settings.email.app_url
    subject = f"Welcome to AETHER — your API key is ready"
    body = _base("Welcome to AETHER", f"""
<p>Hi <strong>{tenant_name}</strong>,</p>
<p>Your account is set up. Here is your first API key:</p>
<pre style="background:#f4f4f4;padding:12px;border-radius:4px;font-size:14px">{api_key}</pre>
<p><strong>Store this securely — it will not be shown again.</strong></p>
<p>Get started: add the header <code>X-API-Key: &lt;key&gt;</code> to every request.</p>
<p>
  <a href="{app_url}/docs" style="background:#1a1a2e;color:#fff;padding:10px 20px;
     border-radius:4px;text-decoration:none;display:inline-block">View API Docs</a>
</p>
<p>Questions? Reply to this email — we're here to help.</p>
""")
    return subject, body


def payment_failed(tenant_name: str, amount: str, invoice_url: str) -> tuple[str, str]:
    """Return (subject, body_html) for an invoice.payment_failed event."""
    app_url = settings.email.app_url
    subject = "Action required — AETHER payment failed"
    body = _base("Payment failed", f"""
<p>Hi <strong>{tenant_name}</strong>,</p>
<p>We were unable to collect payment of <strong>{amount}</strong> for your AETHER subscription.</p>
<p>Your service will continue during Stripe's retry window, but please update your payment
method to avoid interruption.</p>
<p>
  <a href="{invoice_url or app_url + '/billing'}"
     style="background:#c0392b;color:#fff;padding:10px 20px;
     border-radius:4px;text-decoration:none;display:inline-block">
     Update Payment Method
  </a>
</p>
<p>If this was a mistake, your card issuer may have more information.</p>
""")
    return subject, body


def quota_threshold(tenant_name: str, percent: int, used: int, limit: int) -> tuple[str, str]:
    """Return (subject, body_html) for a quota threshold notification."""
    app_url = settings.email.app_url
    subject = f"AETHER: you've used {percent}% of your monthly quota"
    body = _base(f"Quota at {percent}%", f"""
<p>Hi <strong>{tenant_name}</strong>,</p>
<p>You've used <strong>{used:,}</strong> of your <strong>{limit:,}</strong>
monthly API calls ({percent}%).</p>
{"<p>Requests beyond your included quota are billed as overage per the service catalog.</p>" if percent >= 100 else ""}
<p>
  <a href="{app_url}/billing"
     style="background:#1a1a2e;color:#fff;padding:10px 20px;
     border-radius:4px;text-decoration:none;display:inline-block">
     View Usage &amp; Billing
  </a>
</p>
""")
    return subject, body
