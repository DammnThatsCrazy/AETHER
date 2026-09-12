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

They handle provider authorization, webhook ingestion, sync lifecycle, cursor state, normalization into canonical contracts, and graph projection.

## Key Distinction

| Concept | Meaning |
|---|---|
| Provider | External system that owns source data |
| Connector | Aether-managed integration to a provider |
| Normalizer | Translates provider payloads into canonical Aether contracts |
| SDK | Captures first-party app/site observations |

## Available Connectors

See individual connector docs for status and capabilities.

## Further Reading

- `docs/connectors/provider-vs-connector.md`
- `docs/connectors/connector-lifecycle.md`
- `docs/source-of-truth/connector-truth.md`
