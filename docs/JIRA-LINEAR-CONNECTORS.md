---
title: Jira & Linear Connectors
slug: operations/jira-linear-connectors
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Jira & Linear Connectors

Project/issue connectors that ingest workflow events as graph signals.

## Jira

- Events: `jira.issue_created`, `jira.issue_updated`.
- Category: project · Webhook: yes · Pull: yes · Premium: no.
- Auth: Jira webhook secret / API token (vault-stored).

## Linear

- Events: `linear.issue`, `linear.comment`.
- Category: project · Webhook: yes · Pull: no · Premium: no.
- Auth: Linear webhook signing secret (vault-stored); payloads HMAC-verified.

## Enable

`PUT /v1/integrations/connectors/{jira|linear}` (`enabled: true`) → `/test`.
Provider API sync is a credential-gated TODO. Disabled by default. See
[Connectors](CONNECTORS.md) and [Webhook Ingestion](WEBHOOK-INGESTION.md).
