---
title: ADRs — Communications Intelligence
slug: comms/adr-communications-intelligence
section: architecture
visibility: I
audience: [dev-senior, architect]
source_files:
  - Backend Architecture/aether-backend/services/comms/contracts.py
  - Backend Architecture/aether-backend/services/comms/projector.py
  - Backend Architecture/aether-backend/services/silver/dispatcher.py
---

# Architecture Decision Records — Communications Intelligence

Status of all ADRs: **Accepted** (2026-07-03). Each ADR is enforced by the
tests listed in its *Enforcement* section.

---

## ADR-C1 — Communications product boundary

**Decision.** Aether observes, normalizes, resolves, connects, measures, and
explains communications executed through external providers. Aether does not
originate messages, operate send infrastructure, warm up domains, or replace
ESP/CRM tooling. There is no separate email product, application, registry,
resolver, journey compiler, or attribution engine — communications land in the
existing Campaign Intelligence, Profile360, Unified Journey, Attribution,
Graph, and Noesis systems.

**Consequences.** Connectors are read-only observers (`ConnectorRole.DATA_INGESTION`).
No SMTP, no bulk-send. Provider-side composition/scheduling/deliverability is
out of scope.

**Enforcement.** `tests/unit/comms/test_comms_contracts.py::TestProductBoundary`
asserts no send-capable surface exists in `services/comms/`.

---

## ADR-C2 — Canonical communication contract

**Decision.** All providers normalize into one provider-neutral taxonomy
(`services/comms/contracts.py`):

- Email lifecycle: `email_queued, email_processed, email_sent, email_delivered,
  email_deferred, email_bounced, email_dropped, email_opened, email_clicked,
  email_replied, email_spam_complaint, email_suppressed, unsubscribe_observed`.
- Channel-neutral: `message_sent_observed, message_received_observed,
  message_replied_observed, notification_delivered/opened/clicked`.
- Shared `CommunicationEventPayload` with identity, provider, campaign,
  classification, quality, governance, timing, and evidence field groups.
- Enums: `MessageCategory` (marketing/sales/transactional/security/account/
  support/operational/agent_generated), `Direction` (outbound/inbound/internal/
  system_generated), `ActorKind` (human/organization/agent/service/system),
  `JourneyRole` (context/active_step/state_only/outcome/excluded),
  `EngagementStrength` (none/weak/probable/strong/deterministic).

**Canonical source of truth** remains `packages/shared/contracts/event-registry.json`;
generated TS/Python artifacts are regenerated via `scripts/generate_contracts.py`.

**Enforcement.** `tests/unit/comms/test_comms_contracts.py` +
`scripts/generate_contracts.py --check` in CI.

---

## ADR-C3 — Multi-projector event fan-out

**Decision.** The Silver dispatcher (`services/silver/dispatcher.py`) maps
`event_type → ordered list of projectors` instead of a single projector.
Semantic order: communications lifecycle → identity evidence → campaign
touchpoint → preference/suppression → data quality → canonical activity →
graph emission. Each projector runs isolated: one failure never erases
another's successful projection. Results are reported per projector with
latency and failure metrics. Events with one projector behave exactly as
before (backward compatible).

**Enforcement.** `tests/unit/comms/test_silver_multi_projector.py` — fan-out,
deterministic ordering, partial-failure isolation, replay safety.

---

## ADR-C4 — Canonical activity ownership

**Decision.** One real-world communication event creates exactly one
`canonical_activity` row, keyed by the **source-derived** canonical key
`sha256(tenant_id + source_system + provider_account_id + provider_event_id +
semantic_event_type)` — never by a Silver row ID. For comms events the
`CommsProjector` owns activity emission; `TouchpointProjector` still writes its
analytical touchpoint row (with `communication_fact_id` lineage) but its
activity emission is suppressed by the dispatcher for comm event types.
Activity upsert is idempotent (`ON CONFLICT (tenant_id, idempotency_key)`),
survives replay, and late identity resolution relinks without duplication.

**Enforcement.** `tests/unit/comms/test_comms_projector.py::TestActivityOwnership`
— `email_clicked` → one comms fact, one touchpoint, one activity.

---

## ADR-C5 — Journey inclusion

**Decision.** Communication events carry a `journey_role`:

| Event | Role |
|---|---|
| queued / processed / deferred | `state_only` |
| sent / delivered | `context` |
| bounced / dropped | `state_only` (exception surface) |
| opened (provider-reported) | `context` |
| opened (human-qualified) | `context` (weak engagement) |
| clicked (machine/scanner) | `excluded` |
| clicked (human-qualified) | `active_step` |
| replied (non-automated) | `active_step` |
| replied (auto-response/DSN/OOO) | `excluded` |
| unsubscribe / spam complaint | `outcome` (negative) |

Journeys never surface lifecycle noise as primary steps; `state_only`
activities are collapsible detail under the nearest meaningful step.

**Enforcement.** `tests/unit/comms/test_comms_projector.py::TestJourneyRoles`.

---

## ADR-C6 — Graph cardinality

**Decision.** Three storage levels: (1) event facts stay in Postgres
(`silver_comms_facts`), never in the graph; (2) meaningful temporal activity
lives in `canonical_activity`/journey steps; (3) only durable relationships
enter the graph. Communications project as **aggregated**
`COMMUNICATES_WITH` / `CONTACTED` edges keyed by (tenant, sender-context,
recipient, channel) with counts, first/last observed, confidence, and consent
purpose — one edge updated in place, not one edge per event. The literal
`"system"` sender placeholder is banned: sender context resolves to
organization / human / agent / service / provider account. Messages/threads are
promoted to vertices only when replied, support-linked, conversion-linked,
agent-interaction, or explicitly investigated.

**Enforcement.** `tests/unit/comms/test_comms_graph.py` — aggregation
idempotency, no event-node explosion, no global system sender.

---

## ADR-C7 — Consent and suppression

**Decision.** Message categories map to consent purposes (marketing→`marketing`,
transactional/account/security→`analytics`+necessity, support→relationship).
Suppression is scope-modeled (`message, campaign, list, segment,
provider_account, marketing_channel, tenant_wide, alias_wide`) — never a single
global boolean. Uncertainty fails closed: a comms fact with unresolvable
consent snapshot is stored with `privacy_class` intact but is excluded from
marketing analytics and attribution eligibility.

**Enforcement.** `tests/unit/comms/test_comms_state.py::TestSuppressionScopes`.

---

## ADR-C8 — Attribution policy

**Decision.** Default eligibility: delivered = context only (no credit);
provider-reported open = excluded (optional low-confidence view-through when a
tenant enables it); machine open/click = always excluded; human-qualified
click = eligible; reply = eligible when tenant config permits; authenticated
post-click session = strong evidence; transactional email = excluded from
acquisition attribution; unsubscribe/complaint = negative outcomes, never
positive credit. Implemented as `CommsAttributionPolicy` consumed by the
existing attribution engine — no second engine.

**Enforcement.** `tests/unit/comms/test_comms_attribution_policy.py`.

---

## ADR-C9 — Campaign hierarchy

**Decision.** Reuse the existing campaign registry
(`services/campaign/registry.py`) — provider campaigns and automation flows
map through `campaign_external_refs` to canonical campaign UUIDs. New
dimensions: `campaign_messages` (message/sequence-step/variant) and
`campaign_links` (link) reference the canonical campaign. Cross-channel
rollups use `campaign_initiatives` + `campaign_initiative_members`. No second
registry; email campaigns are rows in the same `campaigns` table with
`channel='email'`.

**Enforcement.** `tests/unit/comms/test_comms_campaign_hierarchy.py`.

---

## ADR-C10 — Privacy and content retention

**Decision.** Raw email addresses are normalized then hashed tenant-scoped
(`services/comms/mailbox.py` reusing `services/identity/hashing.py`); only
redacted display forms (`j***@e***.com`) are stored for UI. Full message
bodies and attachments are never stored by default — only structural metadata
and evidence references (`raw_evidence_ref`). DSR deletion tombstones comms
facts by profile and removes derived classifications; aggregates survive only
where legally permitted. Click tokens carry no raw PII.

**Enforcement.** `tests/unit/comms/test_comms_mailbox.py::TestPrivacy` +
`tests/unit/comms/test_comms_projector.py::TestNoRawPII`.

---

## ADR-C11 — Modular multi-provider platform

**Decision.** Communications runs as a genuinely modular, multi-provider
platform. Each comms provider (Klaviyo, SendGrid, Postmark, Customer.io,
Mailchimp) is a plain `BaseConnector` subclass that declares `comms.*`
`manifest_data_outputs` and normalizes provider payloads to the canonical
`NormalizedEvent` contract at the adapter boundary. The connector catalog
auto-derives the `ProviderManifest` and comms membership from those
`data_outputs` (`shared/integration_contracts/catalog.py::build_connector_manifests`),
so new adapters are detected without per-adapter manifest wiring. Ordinary
downstream paths — Bronze→Silver ingest, identity bridge, suppression,
metering, cursor, sync-run ledger, campaign/projector/classification — never
branch on provider name.

Credentials for every comms provider are typed slots resolved through the
CredentialAuthority (never JSONB config, never logged, decrypted only at
adapter call sites). Webhook tenant ownership is resolved server-side through
durable endpoint identifiers, never an `X-Aether-Tenant-ID` header. Readiness
is reported honestly: code-complete without an externally verified credential
is `credential_waiting`; no higher state is claimed without external evidence.

HubSpot Marketing Hub, Iterable, and Braze are explicit, sequenced follow-ups
(see `docs/comms/COMMS_FOLLOW_UP_ROADMAP.md`), not part of the first branded
cohort.

**Enforcement.** Per-provider adapter conformance tests in
`tests/unit/comms/` (webhook signature, event map→canonical, pull/cursor,
suppression mapping); `grep` gates for `provider == "klaviyo"` /
`or "klaviyo"` / `COMMS_CONNECTOR_TYPE` outside adapter code; the webhook
route's server-side tenant-resolution test; and the generated
`docs/_generated/adapter-certification-matrix.json` listing all five comms
providers with truthful readiness.
