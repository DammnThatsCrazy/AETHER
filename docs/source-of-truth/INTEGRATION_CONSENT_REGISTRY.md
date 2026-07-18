---
title: Integration Consent Registry Source of Truth
source_files:
  - packages/shared/contracts/integration-consent-registry.json
  - scripts/generate_contracts.py
  - packages/shared/integration-consent.ts
  - Backend Architecture/aether-backend/shared/privacy/generated_integration_consent.py
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
