---
title: "Aether Connectors"
slug: connectors/overview
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Aether Connectors

Connectors are Aether-managed integrations to external provider systems.

Connector capabilities acquire data from external providers, manage credentials and account scope, and may support polling, webhooks, reports, or streams. AETHER has several connector execution paths: native Universal Provider Runtime plugins, legacy integration connectors, measurement and communications connectors, and specialized payment or import systems. They share contracts where appropriate, but they do not all use one scheduler or write directly to graph projections.

## Key Distinction

| Concept | Meaning |
|---|---|
| Provider | External system that owns source data |
| Connector | Aether-managed integration to a provider |
| Normalizer | Translates provider payloads into canonical Aether contracts |
| SDK | Captures first-party app/site observations |

The Universal Provider Runtime (UPR) is the shared execution path for its registered provider plugins. UPR stores provider raw records, normalizes them to `AetherEvent`, and writes consent-admitted events to typed Bronze and the durable outbox. Provider-origin consumers are currently deferred from the SDK-only Silver and identity projection paths; provider-aware authority and graph projectors are still being built. Legacy and specialized connectors retain their existing data and control authorities during migration.

## Available Connectors

See individual connector docs for status and capabilities.

## Further Reading

- `docs/connectors/provider-vs-connector.md`
- `docs/connectors/connector-lifecycle.md`
- `docs/source-of-truth/connector-truth.md`
