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

This matrix enumerates each connector subsystem's supported capabilities.

## Subsystems

Aether has three connector subsystems, each under `Backend Architecture/aether-backend/services/`:

| Subsystem | Path | Purpose |
|---|---|---|
| Integrations | `services/integrations/connectors/` | Email and marketing platform connectors |
| Measurement | `services/measurement/connectors/` | Ad platform measurement connectors |
| Derivatives | `services/derivatives/connectors/` | Financial venue connectors |

## Integration Connectors

| Connector | Webhook | Pull Sync | Backfill | Real-time | Normalization |
|---|---|---|---|---|---|
| Klaviyo | Yes | Yes | Yes | No | Canonical contract |
| SendGrid | Yes | No | No | No | Canonical contract |
| Mailchimp | Yes | Yes | Yes | No | Canonical contract |
| Postmark | Yes | No | No | No | Canonical contract |
| Iterable | Yes | Yes | Yes | No | Canonical contract |
| Braze | Yes | Yes | No | No | Canonical contract |
| Customer.io | Yes | Yes | Yes | No | Canonical contract |

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

Provider plugins at `services/providers/` emit through `shared/integration_contracts/normalization.py`:

| Provider | Auth | Pull | Webhook | Normalizer |
|---|---|---|---|---|
| Amazon | OAuth | Yes | Yes | `AetherEvent` via canonical contract |
| eBay | OAuth | Yes | Yes | `AetherEvent` via canonical contract |
| Etsy | OAuth | Yes | No | `AetherEvent` via canonical contract |
| Shopify | OAuth | Yes | Yes | `AetherEvent` via canonical contract |
| TikTok | OAuth | Yes | Yes | `AetherEvent` via canonical contract |
| Walmart | OAuth | Yes | No | `AetherEvent` via canonical contract |
| WooCommerce | OAuth | Yes | Yes | `AetherEvent` via canonical contract |

## Validation

All connector subsystems normalize into canonical Aether contracts. The provider
runtime enforces this through `services/provider_runtime/validation.py` and
`services/provider_runtime/certification.py`.
