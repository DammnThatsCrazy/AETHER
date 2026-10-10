---
title: "Connector Capability Coverage"
slug: connectors/capability-coverage
section: reference
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Capability Coverage

This is an implementation inventory, not a certification report. It describes
the current connector execution surfaces, including native UPR provider
plugins; the repository also has specialized payment, import, SDK, and provider
execution paths. A registered connector or declared manifest capability does
not by itself prove sandbox operation, production availability, data authority,
or graph projection.

## Subsystems

Aether has multiple connector execution surfaces under
`services/api/services/`:

| Subsystem | Path | Purpose |
|---|---|---|
| Integrations | `services/api/connectors/integrations/connectors/` | Email and marketing platform connectors |
| Measurement | `services/api/journeys/measurement/connectors/` | Ad platform measurement connectors |
| Derivatives | `services/api/value/derivatives/connectors/` | Financial venue connectors |
| Universal Provider Runtime (UPR) | `services/api/connectors/provider_runtime/` and `services/api/connectors/providers/` | Manifest-driven provider lifecycle, stream sync, webhook, raw storage, normalization, and replay runtime |

## Integration Connectors

| Connector | Webhook | Pull Sync | Backfill | Real-time | Normalization |
|---|---|---|---|---|---|
| Klaviyo | Yes | Yes | Yes | No | Canonical contract |
| SendGrid | Yes | No | No | No | Canonical contract |
| Mailchimp | Yes | No | No | No | Canonical contract |
| Postmark | Yes | No | No | No | Canonical contract |
| Iterable | Yes | Yes | Yes | No | Canonical contract |
| Braze | Yes | Yes | Yes | No | Canonical contract |
| Customer.io | Yes | No | No | No | Canonical contract |

## Measurement Connectors

| Connector | Webhook | Pull Sync | Backfill | Real-time | Normalization |
|---|---|---|---|---|---|
| Google Ads | No | Yes | Yes | No | Canonical contract |
| Meta Ads | No | Yes | Yes | No | Canonical contract |
| TikTok Ads | No | Yes | Yes | No | Canonical contract |
| LinkedIn Ads | No | Yes | Yes | No | Canonical contract |
| X Ads | No | Yes | Yes | No | Canonical contract |
| Reddit Ads | No | Yes | Yes | No | Canonical contract |
| Microsoft Ads | No | Yes | Yes | No | Canonical contract |

## Provider Plugins

Provider plugins at `services/api/connectors/providers/` normalize through
`shared/integration_contracts/normalization.py`. The table reflects structural
plugin capability; follow the current manifest and certification evidence for
per-stream availability. Credentials vary by provider and profile.

| Provider | Credential declaration | Pull | Webhook | Normalizer |
|---|---|---|---|---|
| Amazon | Manifest-defined | Yes | No | `AetherEvent` via canonical contract |
| eBay | Manifest-defined | Yes | No | `AetherEvent` via canonical contract |
| Etsy | Manifest-defined | Yes | No | `AetherEvent` via canonical contract |
| Shopify | API-key credential profiles for REST, REST-webhook, and GraphQL modes | Yes | Mode-gated | `AetherEvent`; GraphQL emits schema-v2 revisions, REST remains v1 |
| TikTok | Manifest-defined | Yes | Yes | `AetherEvent` via canonical contract |
| Walmart | Manifest-defined | Yes | No | `AetherEvent` via canonical contract |
| WooCommerce | Manifest-defined | Yes | Yes | `AetherEvent` via canonical contract |

## Validation

UPR manifest honesty and structural certification are enforced through
`services/api/connectors/provider_runtime/validation.py` and
`services/api/connectors/provider_runtime/certification.py`. Legacy
integration, measurement, communications, import, and specialized financial
paths retain their own adapters and persistence contracts; this validator does
not certify those paths or prove a graph projector exists.
