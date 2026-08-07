---
title: Communications Multi-Provider Follow-Up Roadmap
slug: comms/comms-follow-up-roadmap
section: reference
visibility: I
audience: [architect, dev-senior, ops]
---

# Communications Multi-Provider Follow-Up Roadmap

Sequenced plan for the three branded communications providers that are **not**
part of the ADR-C11 first cohort (Klaviyo, SendGrid, Postmark, Customer.io,
Mailchimp). This document records, per provider, the exact missing work, the
dependencies, and the acceptance criteria. It exists so the follow-up work is
bounded and reviewable without re-deriving scope.

The first cohort establishes the platform this roadmap assumes:
server-controlled webhook endpoints (no tenant header), a generic comms adapter
contract on `BaseConnector`, typed credential slots via the CredentialAuthority,
and a generic certification harness that lists every registered comms provider
honestly.

## Sequence and dependencies

1. **HubSpot Marketing Hub** — first follow-up. The HubSpot **connector already
   exists** (CRM: `hubspot.contact` / `hubspot.company` / `hubspot.deal`,
   `hubspot_signature_v3` webhook verification), so this is the cheapest step:
   it extends an existing connector rather than adding a new one. Depends on the
   generalized contract and comms credential slots (commits 3–4).
2. **Iterable** — second. Zero references today; a brand-new adapter. Requires
   at least one certified exemplar of the contract (Klaviyo migration) plus the
   generalized contract and certification harness.
3. **Braze** — third. Zero references today; brand-new adapter, pull-model-first
   (see below). Same dependencies as Iterable.

## HubSpot Marketing Hub

**Current state.** `services/integrations/connectors/adapters.py` defines a
HubSpot connector with `connector_type = "hubspot"`, CRM ingest event types
(`hubspot.contact`, `hubspot.company`, `hubspot.deal`), and native webhook
signature verification (`x-hubspot-signature-v3` / `x-hubspot-signature`,
listed in `_NATIVE_WEBHOOK_SCHEMES`). It declares **no** `comms.*`
`manifest_data_outputs`, so it is not a comms connector today.

**Missing work.**
- Add `comms.*` data outputs (e.g. `comms.email_event`) so the catalog
  auto-detects it as a comms connector and manifests/entitlements follow.
- Map HubSpot Marketing Email event webhooks → canonical `NormalizedEvent`
  (delivered, open, click, unsubscribe/bounce via marketing event webhooks).
- Suppression mapping to HubSpot contacts (unsubscribe / email bounce lists).
- Optional pull: Marketing Email campaigns / emails via the Marketing Hub API
  with a cursor, to backfill and reconcile against webhooks.
- Declare HubSpot comms credential slots (api_key / webhook signing secret) in
  the slot registry.

**Acceptance criteria.**
- HubSpot connector appears in the certification matrix under
  `communications` with truthful readiness.
- HubSpot email events project through the generic comms spine to Campaign 360 /
  Profile 360 without provider branching.
- Suppression events from HubSpot flow through `suppression_authority` with the
  provider recorded as generic metadata.
- All existing CRM behavior (contact/company/deal) remains untouched.

## Iterable

**Current state.** Zero references in backend services, shared contracts, or
frontend (verified 2026-08-06).

**Missing work.**
- New `iterable` adapter: `ConnectorType` literal, `BaseConnector` subclass with
  `comms.*` `manifest_data_outputs`.
- Webhook verification: Iterable signs webhook requests with an HMAC built from
  the webhook signing secret (shared secret in the webhook's query params) —
  implement a native scheme and register it in `_NATIVE_WEBHOOK_SCHEMES`.
- Event map → canonical: email send / delivered / open / click / subscribe /
  unsubscribe / complaint, plus identify payloads.
- Suppression: Iterable list-unsubscribe endpoint (via API key credential slot).
- Pull: Iterable REST API event export with cursor for backfill/reconciliation.
- Conformance tests mirroring `tests/unit/comms/test_klaviyo_connector.py`.

**Acceptance criteria.**
- Iterable appears in the certification matrix under `communications` with
  truthful readiness (`credential_waiting` until a real credential is verified).
- Webhook replay protection via timestamp tolerance + `silver_comms_idem`
  dedupe; quarantine on signature denial.
- No provider-name branching in downstream comms paths.

## Braze

**Current state.** Zero references in backend services, shared contracts, or
frontend (verified 2026-08-06).

**Missing work.**
- New `braze` adapter: `ConnectorType` literal, `BaseConnector` subclass with
  `comms.*` `manifest_data_outputs`.
- Webhook verification: Braze does not sign REST webhooks with an HMAC the way
  the other providers do — inbound Braze events arrive via REST push, so the
  primary ingest path is **pull-model-first**: export users' email events from
  the Braze REST API (`/users/track`, canvas/campaign steps) with a cursor.
  Implement a `pull` that advances the durable cursor only after acceptance.
  If signed webhooks are used, verify accordingly; otherwise report the honest
  scheme (generic/`hmac`) for webhooks.
- Event map → canonical: email send / delivered / open / click / bounce /
  unsubscribe from Braze REST responses.
- Suppression: Braze subscription-group unsubscribe via REST API key.
- Conformance tests mirroring `tests/unit/comms/test_klaviyo_connector.py`.

**Acceptance criteria.**
- Braze appears in the certification matrix under `communications` with truthful
  readiness; the webhook/scheme entry honestly reflects the pull-first model.
- Cursor advances only after durable acceptance; no silent data loss.
- Suppression via Braze REST flows through `suppression_authority` with provider
  recorded as generic metadata.

## Governance

- Each provider lands as its own ordered commit inside a single PR, following
  the same per-provider runbook pattern (`docs/COMMS-<PROVIDER>-CONNECTOR.md`).
- Readiness is always reported from evidence: `credential_waiting` until an
  external credential is verified; `sandbox_validated`/`partner_live` only with
  the supporting artifacts.
- The completion gate for every provider is `make ci-check` green with the
  generated `adapter-certification-matrix.json` showing the provider under
  `communications`.
