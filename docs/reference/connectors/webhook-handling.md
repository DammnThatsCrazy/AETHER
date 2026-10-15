---
title: "Webhook Handling"
slug: connectors/webhook-handling
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Webhook Handling

## Registration

Connectors register webhooks with providers during the authorization phase.

## Delivery

Webhook payloads are received by the ingestion service, validated against the connector's expected schema, and routed to the appropriate normalizer.

## Verification

Webhook signatures are verified using provider-specific mechanisms before processing.
