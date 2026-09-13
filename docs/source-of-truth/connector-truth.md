---
title: Connector truth
slug: source-of-truth/connector-truth
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Connector Truth

Providers are external systems.

Connectors are Aether-managed integrations to those external systems.

## Provider

A provider owns external data.

Examples:

- Shopify
- Stripe
- Mailchimp
- HubSpot
- Google Analytics
- Salesforce
- Custom tenant systems

## Connector

A connector handles:

- Provider registration
- OAuth or credential setup
- Webhook registration
- Sync lifecycle
- Cursor state
- Retry behavior
- Provider payload validation
- Normalization into canonical contracts
- Projection into graph-ready events

## Connector Does Not

- Replace the SDK.
- Own graph semantics.
- Bypass canonical contracts.
- Write unvalidated payloads directly into the graph.
