---
title: "Connector Subsystem Registry"
slug: connectors/subsystem-registry
section: reference
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Subsystem Registry

Aether organizes connectors into three backend subsystems, each under
`Backend Architecture/aether-backend/services/`.

## Subsystems

### Integration Connectors

**Path:** `services/integrations/connectors/`

Email and marketing platform connectors. Each connector implements the
`ConnectorClass` taxonomy and normalizes provider payloads into canonical
Aether contracts.

Connectors: Klaviyo, SendGrid, Mailchimp, Postmark, Iterable, Braze, Customer.io

### Measurement Connectors

**Path:** `services/measurement/connectors/`

Ad platform measurement connectors for attribution and spend tracking.

Connectors: Google Ads, Meta Ads, TikTok Ads, LinkedIn Ads, X Ads, Reddit Ads, Microsoft Ads

### Derivatives Connectors

**Path:** `services/derivatives/connectors/`

Financial venue connectors for DeFi and derivative instrument data.

Connectors: Hyperliquid, Generic Import

## Provider Plugins

**Path:** `services/providers/`

Full-lifecycle provider plugins with OAuth, pull sync, webhook handling, and
normalization. Each plugin emits `AetherEvent` through the canonical
`shared/integration_contracts/normalization.py` contract layer.

Providers: Amazon, eBay, Etsy, Shopify, TikTok, Walmart, WooCommerce

## Provider Runtime

**Path:** `services/provider_runtime/`

Centralized runtime that manages provider manifests, certification, validation,
and the normalization pipeline. All provider plugins register through this runtime.

## Deprecated

**Path:** `Data Ingestion Layer/`

Legacy TypeScript ingestion tree. Deprecated — all new connector work uses the
Python backend subsystems above.

## See Also

- [Capability Coverage](./capability-coverage.md)
- [Provider vs Connector](./provider-vs-connector.md)
- [Normalization](./normalization.md)
- [Provider Manifests](./provider-manifests.md)
- [Provider Normalization](./provider-normalization.md)
