---
title: Slack Connector
slug: operations/slack-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Slack Connector

Ingests Slack messages, reactions, and channel activity as graph signals
(`slack.message`, `slack.reaction`, `slack.channel`).

- **Category**: messaging · **Webhook**: yes · **Pull**: no · **Premium**: no
- **Auth**: Slack signing secret (stored in the vault; never in config or API).
- **Events API**: subscribe Slack to the webhook ingest endpoint; payloads are
  HMAC-verified (see [Webhook Ingestion](WEBHOOK-INGESTION.md)).

## Enable

1. Configure via `PUT /v1/integrations/connectors/slack` (`enabled: true`,
   non-secret config only; set the secret in the vault).
2. `POST /v1/integrations/connectors/slack/test` to verify.
3. Disabled by default; provider API calls are credential-gated TODOs.

See [Connectors](CONNECTORS.md).
