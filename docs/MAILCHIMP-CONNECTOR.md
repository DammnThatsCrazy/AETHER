---
title: Mailchimp Connector
slug: operations/mailchimp-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/mailchimp.py
---

# Mailchimp Connector

Observes the Mailchimp audience lifecycle for Communications Intelligence.
Aether never sends through this connector (ADR-C1) — Mailchimp keeps
composition, scheduling, sending, and suppression execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: no ·
  **Historical backfill**: no · **Premium**: no
- **Auth**: endpoint-secret. Mailchimp sends no body signature, so the
  server-controlled durable endpoint id (`POST /comms/mailchimp/{endpoint_id}`)
  is the credential (verified by possession). No vault secret is required.
  Mailchimp sends a GET validation probe on setup, answered by the GET
  validation handler. Ready once the connector is enabled.

## What it ingests

| Mailchimp event | Canonical event |
|---|---|
| `unsubscribe` | `unsubscribe_observed` (scope=list) |
| `cleaned` | `email_suppressed` (reason: hard bounce / abuse complaint) |

Subscribe, profile-update, email-change, and campaign events are dropped:
campaign rows register in the canonical campaign registry as identity
evidence, never as communication facts. Form-encoded bodies are parsed
content-type-aware (`application/x-www-form-urlencoded`).

Mailchimp sends no timestamp — the normalizer emits the empty "unknown"
occurrence sentinel and receive time is stamped at ingest, so replays stay
idempotent.

## Enable

`PUT /v1/integrations/connectors/mailchimp` (`enabled: true`) → point the
provider's webhook at the server-controlled endpoint
(`POST /comms/mailchimp/{endpoint_id}`). No vault secret is needed. Webhooks
land on the connector webhook route and flow through the durable Bronze →
Silver pipeline. See [Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
