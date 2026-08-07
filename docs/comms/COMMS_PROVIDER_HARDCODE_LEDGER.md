---
title: Communications Provider Hardcode Ledger
slug: comms/comms-provider-hardcode-ledger
section: reference
visibility: I
audience: [dev-senior, architect]
---

# Communications Provider Hardcode Ledger

Reconnaissance record of every provider-name hardcode in the communications
surface, captured 2026-08-06 on `main` before the modular multi-provider work
(ADR-C11). Each entry records the site, what it does, and its disposition under
the ADR-C11 contract: **keep** (provider-branded adapter code, correct by
design), **generalize** (provider-agnostic path that must stop branching on
provider name), or **add** (surface that must grow to cover the new providers).

The completion gate for this cleanup is
`grep -rn 'provider == "klaviyo"\|or "klaviyo"\|COMMS_CONNECTOR_TYPE\|useState(.klaviyo.)'`
over non-adapter code → zero matches.

## Ordinary-path hardcodes (generalize / remove)

| Site | What it does | Disposition |
|---|---|---|
| `Backend Architecture/aether-backend/services/campaign/routes.py:544` | `provider = campaign.get("primary_platform") or "klaviyo"` fallback in the ordinary campaign path | **Remove** the `or "klaviyo"` fallback (commit 6) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:47` | `comms_certification_descriptor(provider="klaviyo")` default | **Generalize**: no provider default (commit 5) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:89` | `provider = "klaviyo"` in `CommsCertificationAdapter` | **Generalize**: wrap any comms connector (commit 5) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:96,201` | `normalize_klaviyo_event(payload)` direct calls | **Generalize**: dispatch through the adapter (commit 5) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:117` | `"url": "https://a.klaviyo.com/api/events/"` conformance probe | **Generalize**: provider-scoped endpoint (commit 5) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:156,185,276` | `manifest_by_family.get(getattr(adapter, "provider", "klaviyo"))` | **Generalize**: drop the klaviyo default (commit 5) |
| `Backend Architecture/aether-backend/services/comms/conformance.py:173,217,253,265` | Conformance self-test fixtures hardcoding `connector_type="klaviyo"`, `source_system="klaviyo"`, `"provider": "klaviyo"` | **Generalize**: first registered comms provider (commit 5) |
| `Backend Architecture/aether-backend/shared/certification/registry.py:267-283` | `_resolve_communications()` returns only `comms_certification_descriptor("klaviyo")` | **Generalize**: iterate all registered comms providers (commit 5) |
| `Backend Architecture/aether-backend/services/integrations/connectors/base.py:24` | `ConnectorType` literal lacks `sendgrid`/`postmark`/`customerio`/`mailchimp` | **Add** literals (commit 3) |
| `Backend Architecture/aether-backend/services/integrations/connectors/adapters.py:847` | Imports `KlaviyoConnector` for registry registration | **Add** imports per new adapter (commits 7–10) |
| `Backend Architecture/aether-backend/shared/integration_contracts/catalog.py:78-84` | `_NATIVE_WEBHOOK_SCHEMES` lacks comms providers | **Add** native signature schemes (commit 2) |
| `packages/shared/integration-consent.ts:16,515-546,575` | Consent provider union includes `'klaviyo'`; consent data model hardcodes `klaviyo_profile_id`, `"connectorType": "klaviyo"`, `"providerSignatureScheme": "klaviyo_native_or_oauth_pull"` | **Generalize**: drive from the registered connector catalog (commits 3/11) |
| `Backend Architecture/aether-backend/services/comms/ingest.py:10` | Comment references `klaviyo.campaign`, `klaviyo.flow` catalog records | **No change** (comment only; keep generic wording when touched) |

## Adapter code (keep — provider-branded by design)

| Site | What it is |
|---|---|
| `Backend Architecture/aether-backend/services/integrations/connectors/klaviyo.py` | The Klaviyo adapter itself: `_API_BASE`, `normalize_klaviyo_event`, `connector_type = "klaviyo"`, `source="klaviyo"`, `klaviyo.*` event types. Migrated onto the generalized contract in commit 6; provider branding stays inside the adapter boundary. |

## Frontend hardcodes (generalize)

| Site | What it does | Disposition |
|---|---|---|
| `frontend/aether/src/pages/onboarding/comms-connect-onboarding-step.tsx:8` | `COMMS_CONNECTOR_TYPE = 'klaviyo'` (+ 8 usages) | **Generalize**: iterate registered comms connectors (commit 11) |
| `frontend/kyber/src/pages/measurement/kyber-measurement-ops-page.tsx:335` | `useState('klaviyo')` provider default | **Generalize**: default from connector list (commit 11) |
| `frontend/aether/src/test/unit/onboarding-page.test.tsx` | Test fixtures keyed to Klaviyo | **Update** alongside commit 11 |

## Surfaces that must grow (add)

- `ConnectorType` literals for SendGrid, Postmark, Customer.io, Mailchimp —
  `Backend Architecture/aether-backend/services/integrations/connectors/base.py`.
- Native webhook signature schemes for the four new providers —
  `Backend Architecture/aether-backend/shared/integration_contracts/catalog.py`
  (`_NATIVE_WEBHOOK_SCHEMES`) and
  `Backend Architecture/aether-backend/services/integrations/providers/payment_rails/signature_verify.py`.
- Credential slots for the four new providers (api_key / webhook_signing_secret /
  server_token) declared as `required_credentials` on each comms adapter and
  resolved through the connector vault / CredentialAuthority — **not** the
  payment-rail `slot_registry.py` (see
  `Backend Architecture/aether-backend/services/integrations/connectors/base.py:332-334`,
  which records the deliberate divergence).
