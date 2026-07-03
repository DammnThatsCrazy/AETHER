---
title: Generic Signed Communications Webhook
slug: comms/comms-generic-webhook
section: integrations
visibility: E
audience: [dev, integrator]
source_files:
  - Backend Architecture/aether-backend/services/comms/routes.py
  - Backend Architecture/aether-backend/services/comms/ingest.py
---

# Generic Signed Communications Webhook

The fastest provider-neutral way to feed communications into Aether: any
system that can POST JSON can integrate — no dedicated connector required.

## Endpoint

```
POST /v1/comms/webhook
Authorization: Bearer <tenant API key with write permission>
X-Aether-Timestamp: <unix seconds>          (required when a signing secret is configured)
X-Aether-Signature: sha256=<hmac hex>       (required when a signing secret is configured)
```

Signature: `HMAC_SHA256(secret, "<timestamp>." + raw_body)` hex digest, with
a ±300s timestamp tolerance (replay protection). Invalid signatures are
rejected and counted (`comms_webhook_signature_failures_total`).

## Body

```json
{
  "provider": "my-esp",
  "events": [
    {
      "event_type": "email_clicked",
      "external_id": "esp-event-123",
      "occurred_at": "2026-07-01T12:00:00Z",
      "properties": {
        "provider_account_id": "acct-1",
        "provider_event_id": "esp-event-123",
        "recipient_email": "person@example.com",
        "external_campaign_id": "camp-9",
        "external_message_id": "msg-5",
        "link_id": "https://example.com/promo",
        "message_category": "marketing",
        "user_agent": "Mozilla/5.0 …"
      }
    }
  ]
}
```

- `event_type` must be a canonical communication event
  (`email_queued|processed|sent|delivered|deferred|bounced|dropped|opened|
  clicked|replied|spam_complaint|suppressed`, `unsubscribe_observed`,
  `message_sent/received/replied_observed`, `notification_*`). Unknown types
  are rejected with a 400.
- `recipient_email` transits in memory only: it is hashed to a tenant-scoped
  alias before any storage (ADR-C10). Prefer sending `recipient_alias_id`
  (a hash you obtained from Aether) when possible.
- Up to 500 events per request.
- Idempotency: `provider + external_id` dedupes replays end to end.

## Reply ingestion

```
POST /v1/comms/replies
{"provider": "inbound_parse", "replies": [{
  "from": "person@example.com",
  "subject": "Re: your offer",          // used only for auto-response detection
  "message_id": "<abc@mail>",
  "in_reply_to": "<msg-5@esp>",
  "references": ["<msg-5@esp>"],
  "provider_thread_id": "th-1",
  "received_at": "2026-07-01T12:34:00Z",
  "raw_evidence_ref": "s3://…"           // reference only — bodies are never accepted
}]}
```

Correlation priority: `In-Reply-To` → `References` → provider thread →
external message id → reply-to token (`replies+<token>@…`). Automated
responses (DSN, out-of-office, mail loops) are detected and excluded from
engagement while remaining recorded as facts.

## Signed click tokens

```
POST /v1/comms/click-tokens          → issue tokens to embed as ?ae=<token>
POST /v1/comms/click-tokens/verify   → verify + correlation evidence
```

Tokens are HMAC-signed, key-versioned (`COMMS_CLICK_TOKEN_KEYS`,
`COMMS_CLICK_TOKEN_ACTIVE_VERSION`), expiring, tenant-bound, and contain no
raw PII. On landing, the SDK forwards the token as acquisition evidence;
campaign evidence priority is: signed token → provider click id → utm_id →
external campaign id → utm_campaign composite → referrer → manual review.
