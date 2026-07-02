---
title: Connector Support Matrix
slug: operations/connector-support-matrix
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: production
since_version: "9.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Connector Support Matrix

This table reflects the actual implemented capabilities as of version 9.1.0. Columns marked ✓ have production-ready code paths; — means not implemented.

## Inbound Connectors (Data Ingestion)

| Connector | Pull | Webhook | Signature Verification | Cursor | WebhookInbox | Production |
|-----------|------|---------|------------------------|--------|--------------|------------|
| Slack | — | ✓ | ✓ HMAC-SHA256 v0= | — | ✓ | ✓ |
| Stripe | — | ✓ | ✓ t=,v1= format | — | ✓ | ✓ |
| Shopify | ✓ | ✓ | ✓ Base64-HMAC-SHA256 | ✓ page_info | ✓ | ✓ |
| HubSpot | ✓ | ✓ | ✓ X-HubSpot-Signature-v3 | ✓ after cursor | ✓ | ✓ |
| Salesforce | ✓ | — | — | ✓ nextRecordsUrl | — | Beta |
| Klaviyo | ✓ | ✓ | ✓ HMAC-SHA256 | ✓ cursor | ✓ | Beta |
| Segment | ✓ | ✓ | ✓ HMAC-SHA256 | — | ✓ | Beta |
| PostHog | ✓ | — | — | ✓ since_ts | — | Beta |
| GA4 | ✓ | — | — | ✓ date range | — | Beta |
| Jira | — | ✓ | ✓ X-Hub-Signature-256 | — | ✓ | ✓ |
| Linear | — | ✓ | ✓ Linear-Signature | — | ✓ | ✓ |
| Zendesk | ✓ | ✓ | ✓ HMAC-SHA256 | ✓ since | ✓ | Beta |
| Intercom | ✓ | ✓ | ✓ HMAC-SHA256 | ✓ starting_after | ✓ | Beta |
| Dune | ✓ | — | — | ✓ cursor | — | Beta |
| Generic Webhook | — | ✓ | ✓ X-Aether-Signature v1= | — | ✓ | ✓ |

## Outbound Connectors (Delivery)

| Connector | Delivery | Receipt | ExternalResourceLink | Outcome Loop | SSRF Guard | Production |
|-----------|----------|---------|----------------------|--------------|------------|------------|
| Slack | ✓ chat.postMessage | ✓ channel:ts | ✓ | ✓ interactive callbacks | N/A | ✓ |
| Linear | ✓ IssueCreate GraphQL | ✓ issue.id + identifier | ✓ | ✓ Linear webhooks | N/A | ✓ |
| Jira | ✓ POST /rest/api/3/issue | ✓ issue id + key | ✓ | ✓ Jira webhooks | N/A | ✓ |
| Webhook (generic) | ✓ signed HTTPS POST | ✓ delivery_id | ✓ | ✓ POST /webhooks/aether/callback | ✓ SSRF | ✓ |
| CRM | ✗ fail-closed† | — | — | — | — | — |
| Marketing | ✗ fail-closed† | — | — | — | — | — |
| Ticketing | ✓ delegates to Linear/Jira | ✓ | ✓ | ✓ | N/A | ✓ |
| Agent Assist | ✓ Kafka event | ✓ agent-assist:{id} | ✓ | — | N/A | Beta |

† CRM and Marketing adapters raise `InvalidPayloadError` unless `crm_provider` / `marketing_provider` is set in the payload. Concrete HubSpot/Salesforce/Mailchimp delivery is planned for a future release.

## Security Capabilities

| Capability | Status |
|-----------|--------|
| SSRF protection (outbound webhooks) | ✓ DNS-resolved, all IPs checked |
| Replay protection (5-minute timestamp window) | ✓ all inbound webhooks |
| Credential vault (never in payloads/logs/events) | ✓ |
| WebhookInbox persistence before processing | ✓ all inbound routes |
| Constant-time signature comparison | ✓ `hmac.compare_digest` |
| Header sanitization (Authorization redacted) | ✓ `sanitize_headers()` |
| Cross-tenant isolation in delivery jobs | ✓ all queries tenant-scoped |
| Simulated delivery guard (`sim-*` rejected) | ✓ model validator + repo guard |

## DeliveryJob Retry Limits by Provider

| Provider | max_attempts | Base backoff |
|----------|-------------|--------------|
| Slack | 3 | 30s × 2^n ± 20% |
| Linear | 5 | 30s × 2^n ± 20% |
| Jira | 5 | 30s × 2^n ± 20% |
| Webhook | 5 | 30s × 2^n ± 20% |
| Agent Assist | 3 | 30s × 2^n ± 20% |

Max backoff interval: 1800s (30 min). `Retry-After` header respected when present (overrides computed backoff).
