---
title: Integration Consent Registry Source of Truth
source_files:
  - packages/shared/contracts/integration-consent-registry.json
  - scripts/generate_contracts.py
  - packages/shared/integration-consent.ts
  - Backend Architecture/aether-backend/shared/privacy/generated_integration_consent.py
  - Backend Architecture/aether-backend/services/consent/control_plane.py
  - Backend Architecture/aether-backend/services/consent/integration_governance.py
  - Backend Architecture/aether-backend/services/consent/routes.py
  - Backend Architecture/aether-backend/services/integrations/connectors/service.py
  - Backend Architecture/aether-backend/services/integrations/connectors/routes.py
  - Backend Architecture/aether-backend/services/integrations/discovery.py
  - Backend Architecture/aether-backend/services/integrations/webhook_policy.py
  - Backend Architecture/aether-backend/services/integrations/webhook_quarantine.py
---

# Integration Consent Registry Source of Truth

`packages/shared/contracts/integration-consent-registry.json` is the canonical governance registry for consent-aware SDK, connector, webhook, native-payment, and outbound activation control-plane work.

The registry is intentionally explicit: every connector or adapter declares tenant-admin requirements, provider-install requirements, subject purposes, supported processing bases, identity-linking, graph-projection, model-training, pre-consent processing, compliance-evidence handling, suppression events, retention, raw-payload policy, quarantine policy, provider consent bridge, signature scheme, historical backfill, and outbound activation capability.

The generated artifacts are produced by:

```bash
python scripts/generate_contracts.py
```

Generated surfaces include:

- `packages/shared/integration-consent.ts`
- `Backend Architecture/aether-backend/shared/privacy/generated_integration_consent.py`
- `packages/ios/Sources/AetherSDK/GeneratedIntegrationConsent.swift`
- `packages/android/src/main/java/com/aether/sdk/GeneratedIntegrationConsent.kt`
- `docs/_generated/integration-consent-registry-table.md`

The feature flags defined by this registry are default-off and support a controlled canary rollout:

- `AETHER_CONSENT_CONTROL_PLANE_V2`
- `AETHER_CONNECTOR_POLICY_GATE`
- `AETHER_INTEGRATION_DISCOVERY`
- `AETHER_PREFERENCE_CENTER_V1`
- `AETHER_CHECKOUT_HARDENING_V1`
- `AETHER_CONSENT_LIFECYCLE_ENFORCEMENT`

Discovery or automatic recommendation may propose policy defaults, but it must not create affirmative consent receipts or automatically enable explicit-opt-in purposes. Unknown schemas, providers, fields, or purposes must fail closed or remain quarantine-only.

When both `AETHER_CONSENT_CONTROL_PLANE_V2` and `AETHER_INTEGRATION_DISCOVERY` are enabled, tenant connector configuration metadata can be scanned through `POST /v1/integrations/connectors/discovery/scan`. Discovery persists registry-versioned, tenant-scoped records in `detected_integrations`; it copies only connector type, provider, supported capability, enabled state, secret-presence state, and a non-secret configuration reference. It never reads or copies vault references or credentials. `GET /v1/integrations/connectors/discovery/detections` returns only the authenticated tenant's detections.

Tenant admins can create a deliberately non-authoritative draft through `POST /v1/integrations/connectors/manifests/{connector_type}/draft`. Drafts retain registry recommendations as metadata but set `tenant_admin_approved=false`, `provider_admin_installed=false`, and `approved_purposes=[]`; they do not enable a connector or create a consent receipt. Approval through `PUT /v1/integrations/connectors/manifests/{connector_type}` requires an admin permission and explicit required purposes, a registry-supported processing basis, an allowlist of fields, and any provider-admin installation required by the registry. Approved manifests remain tenant policy, not proof of subject consent. `GET /v1/integrations/connectors/manifests` is tenant-scoped.

Runtime enforcement uses the same registry. When both `AETHER_CONSENT_CONTROL_PLANE_V2` and `AETHER_CONNECTOR_POLICY_GATE` are enabled, connector enablement and sync call the integration governance authority before changing tenant connector state or pulling provider data. Decisions are persisted as generated `ProcessingDecision` records in `connector_policy_decisions`, including the physical `tenant_id` column used by repository tenancy filters. Missing tenant processing profiles, unapproved manifests, unsupported processing bases, undeclared purposes, unknown payload fields, or missing subject receipts deny and require quarantine.

Inbound connector webhooks use provider-native signature verification where an adapter declares it and the replay-protected Aether HMAC scheme for generic webhooks. With the connector policy gate active, webhook processing passes the explicitly configured purpose, processing basis, tenant-admin approval, and provider-admin installation state to the same authority; absent admin settings remain unknown so the approved manifest/profile can supply them. A missing policy runtime fails closed. Denied, invalidly signed, and invalid payload deliveries create metadata-only `webhook_quarantine` records containing a payload hash, byte length, expiry, policy-decision reference, and encrypted inbox reference rather than another raw-payload copy.

`POST /v1/consent/records` remains compatible with legacy consent submissions, but every write now normalizes to a `CanonicalConsentReceipt` envelope and stores one authoritative per-purpose row plus append-only history. SDK-supplied canonical receipts are accepted only when the tenant matches the authenticated tenant and the server recomputes the same `sha256:` integrity hash, derived `ccr_` receipt id, and `consent-receipt:` idempotency key. The hash preimage starts with `aether-consent-receipt/v1\n` and then appends the ordered canonical fields as `<name>=<utf8-byte-length>:<value>\n`; empty optional fields and empty metadata hash as an empty value. Reused idempotency keys cannot overwrite different consent evidence.

Official shared, Web, React Native, iOS, and Android SDK APIs mirror that
preimage exactly. They sort and deduplicate purposes, count UTF-8 bytes, sort
metadata keys recursively, send legacy compatibility fields together with the
canonical envelope, and use bearer authentication. SDK callers must supply the
tenant identifier resolved by their API key; SDK construction does not infer or
grant consent and the backend remains authoritative for tenant matching and
receipt verification.
