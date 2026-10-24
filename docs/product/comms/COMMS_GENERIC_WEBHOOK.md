---
title: Generic Signed Communications Webhook
slug: comms/comms-generic-webhook
section: operations
visibility: P
audience: [dev-senior, dev-junior]
status: experimental
since_version: 0.1.0
source_files: [services/api/journeys/comms/routes.py, services/api/journeys/comms/ingest.py, services/api/journeys/communication360/participant_writer.py, services/api/journeys/communication360/contracts.py, services/api/journeys/communication360/repository.py, services/api/connectors/integrations/connectors/routes.py, services/api/connectors/integrations/providers/payment_rails/webhook_endpoints.py, services/api/connectors/integrations/providers/payment_rails/signature_verify.py]
source_hashes:
  "services/api/connectors/integrations/connectors/routes.py": "sha256:d537cd13e0607f0d8e9c9db85797bdfcf42cb450815883dee6a44c8cca987a5e"
  "services/api/connectors/integrations/providers/payment_rails/signature_verify.py": "sha256:45848e154923bd4fa5709d52a1a6d858cdfbdfb36ece7446b61df7163eb5f7e4"
  "services/api/connectors/integrations/providers/payment_rails/webhook_endpoints.py": "sha256:050445ded102390adceb94fe01203eecd04b3602874f32f1e6e87cbc3f21e10a"
  "services/api/journeys/comms/ingest.py": "sha256:e5b199aaff506d136758b1a89c12a36c3622da3c224e5c39732cc4b428ed22a5"
  "services/api/journeys/comms/routes.py": "sha256:5bf1ea2871a2a9c12fe5cc29190b9a98d14af014c56f76b702d58485f362c4de"
  "services/api/journeys/communication360/contracts.py": "sha256:f826cef4a2425cd8b8ad5beafb914794cbb45bd6db9e1dab3bc7d19fb9befa9f"
  "services/api/journeys/communication360/participant_writer.py": "sha256:3569154a47bf54feb898d7a19e043aba100dc06998411afc1983017afb480cd3"
  "services/api/journeys/communication360/repository.py": "sha256:2b8546b419505d92d74098f6167dc6bf0d9da3cd94f7bb68278e179986beb01a"
---

# Generic Signed Communications Webhook

The fastest provider-neutral way to feed communications into Aether: any
system that can POST JSON can integrate — no dedicated connector required.

## Provider-native webhooks (server-controlled endpoints)

Branded comms providers (Klaviyo today; SendGrid, Postmark, Customer.io,
Mailchimp next) do **not** use the generic signed endpoint above. They receive
their own native webhook calls at a server-controlled, durable endpoint id:

```
POST /v1/integrations/webhooks/comms/{connector}/{endpoint_id}
```

Tenant ownership is resolved **server-side** from the durable `whe_` endpoint
registry — never from an `X-Aether-Tenant-ID` header (ADR-C11). The endpoint id
is high-entropy, non-sequential, revocable, and bound to exactly one
(tenant, connector, environment); the id alone is not authentication — the
provider signature is still verified.

Signature verification uses the connector's native scheme when its adapter
declares one, else Aether's generic timestamped HMAC (`X-Aether-Signature` +
`X-Aether-Timestamp`, ±300s replay window):

| Connector | Scheme | Verification |
|---|---|---|
| SendGrid | `sendgrid_ecdsa` | `X-Twilio-Email-Event-Webhook-Signature` is a base64 DER **ECDSA** signature over SHA-256(`timestamp` + raw body); the stored credential is the account's **public key** (the private key stays with Twilio) |
| Customer.io | `customerio_hmac_v0` | `X-CIO-Signature` is hex `HMAC-SHA256(secret, "v0:{X-CIO-Timestamp}:" + raw_body)` — the `v0:` prefix and colons are part of the signed string |
| Mailchimp | `endpoint_secret` | No cryptographic signature — auth is the `secret` query parameter in the webhook URL, which Aether covers with the durable endpoint id |
| Postmark | `endpoint_secret` | No cryptographic signature — auth is URL/Basic-Auth server credentials, covered by the durable endpoint id |

Timestamped native schemes (SendGrid, Customer.io) enforce the ±300s replay
tolerance; the no-signature providers rely on the durable endpoint id plus the
end-to-end idempotency dedupe for replay safety. Denied webhooks are
quarantined metadata-only (never the raw body) and audited.

Tenant administrators mint and manage endpoints for each comms connector:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/integrations/connectors/{connector}/webhook-endpoints` | Mint a durable endpoint |
| `GET` | `/v1/integrations/connectors/{connector}/webhook-endpoints` | List endpoints |
| `POST` | `/v1/integrations/connectors/{connector}/webhook-endpoints/rotate` | Revoke + mint |
| `POST` | `/v1/integrations/connectors/{connector}/webhook-endpoints/{endpoint_id}/revoke` | Revoke |

The legacy header-based connector webhook route
(`POST /v1/integrations/webhooks/{connector}` with `X-Aether-Tenant-ID`) is
**permanently denied for comms connectors**; it remains only for non-comms
connectors. Shopify deliveries on that route never use the tenant header: the
tenant comes from the shop domain (`X-Shopify-Shop-Domain`, else the body
`domain`; the two must agree when both are present), which must match exactly
one enabled Shopify binding whose own secret then verifies the HMAC over the
raw body. Every denial on the legacy route returns the same generic
`400`. Configure your comms provider to POST to the minted
`/comms/{connector}/{endpoint_id}` URL instead.

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
- An event may include a typed `participant_roster` assertion containing an
  opaque `conversation_id`, `provider_account_id`, explicit completeness
  state/evidence, and participant `bindings`. Each binding carries a provider
  recipient/profile ID, role, validity interval, and metadata-only evidence;
  optional principal identities and provider delegation references remain
  source claims. A complete roster must include an expected binding count,
  completeness evidence, and a validity start for every binding.
- Participant rosters are accepted only when a tenant webhook secret is
  configured and the request HMAC verifies. The server creates the authoring
  actor context; caller JSON cannot supply it. Every provider identity must
  resolve through the exact tenant/provider/account identity mapping before
  role facts are written. HMAC authenticates the submitting source; it does
  not independently verify participant identity or role. Provider conversation
  IDs are not canonical Conversation IDs, so the participant slot remains
  partial until membership and message coverage are joined.
- For connector-originated events, canonical sender/recipient identities and
  consent receipts are resolved by server-side authorities. Provider payload
  fields cannot set canonical entity IDs or consent state. Missing identity
  bindings remain unresolved; missing or non-matching consent evidence remains
  unknown and is handled by the applicable fail-closed policy.
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
