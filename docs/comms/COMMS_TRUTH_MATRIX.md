---
title: Communications Intelligence — Repository Truth Matrix
slug: comms/comms-truth-matrix
section: architecture
visibility: I
audience: [dev-senior, architect]
source_files:
  - Backend Architecture/aether-backend/services/silver/dispatcher.py
  - Backend Architecture/aether-backend/services/silver/projectors/touchpoint_projector.py
  - Backend Architecture/aether-backend/services/measurement/silver_adapters.py
  - Backend Architecture/aether-backend/services/integrations/connectors/adapters.py
  - packages/shared/contracts/event-registry.json
---

# Communications Intelligence — Repository Truth Matrix (Phase 0)

Audit date: 2026-07-03 (HEAD `006f082`). Evidence below was verified by reading
code, migrations, generated contracts, and tests — not documentation prose.
This matrix is the execution checklist for the Communications Intelligence
vertical slice; each row's *Recommended change* maps to an implementation phase.

Legend — **State**: `IMPL` implemented · `PART` partial · `UNWIRED` declared but
unwired · `MISS` missing · `CONF` conflict with intended behavior.

## 1. Contracts and event taxonomy

| # | Requirement | State | Evidence (file) | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 1.1 | Canonical email lifecycle events | PART | `packages/shared/contracts/event-registry.json` — comms family has 15 events: `email_delivered/opened/clicked/bounced`, `message_sent/received/replied_observed`, `unsubscribe_observed`, `notification_*`, `support_case_*` | Backend, contracts, tests, docs | P0 / — | Add `email_queued`, `email_processed`, `email_sent`, `email_deferred`, `email_dropped`, `email_replied`, `email_spam_complaint`, `email_suppressed`; regenerate contracts |
| 1.2 | Provider-neutral CommunicationEventPayload | MISS | No shared payload contract exists; SDK `properties` is free-form | Backend, contracts, tests, docs | P0 / 1.1 | New `services/comms/contracts.py` + registry payload docs |
| 1.3 | `silverProjection: communication_facts` declared for comms events | UNWIRED | Registry declares it; no projector exists in `services/silver/projectors/` | Backend | P0 / 3.1 | Implement `CommsProjector`; register in dispatcher |
| 1.4 | Generated TS/Python contracts synchronized | IMPL | `scripts/generate_contracts.py --check` passes | — | — | Re-run after registry additions |
| 1.5 | Lucia Protocol naming/domains/templates | ABSENT | `grep -ri lucia` → no matches anywhere in repo | — | — | Verified absent; nothing to remove |

## 2. Silver dispatch and projection

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 2.1 | Multi-projector fan-out (event → ordered list) | CONF | `services/silver/dispatcher.py:52-55` — `_TYPE_MAP[_t] = _p` (dict; one projector per type, last registration wins) | Backend, tests | P0 / — | Rebuild `_TYPE_MAP` as `dict[str, list]` with deterministic semantic ordering, per-projector isolation, structured results, latency/failure metrics |
| 2.2 | Dispatcher wired into runtime event topology | UNWIRED | `services/ingestion/workers.py` attaches `sdk_bronze_writer`, `silver_normalizer`, `identity_signal_emitter` only; no consumer calls `SilverDispatcher.project()`; only docs reference it | Backend, tests | P0 / — | Attach `silver_fact_projector` worker to `SDK_EVENTS_VALIDATED` translating bus payload → SDK envelope |
| 2.3 | Communications projector registered | MISS | No comms projector in `services/silver/projectors/__init__.py` | Backend, migration, tests | P0 / 2.1 | New `CommsProjector` (authoritative for comms family) |
| 2.4 | Touchpoint projector for email events | PART | `touchpoint_projector.py:27-29` maps `email_delivered/opened/clicked` → `email_delivery/email_open/email_click`; no `email_reply`; no message/link/variant fields; no engagement-confidence gating | Backend, tests | P1 / 2.1 | Add `email_replied → email_reply`; carry comms lineage fields; suppress positive touchpoints for bounce/complaint/suppression |
| 2.5 | One event → one canonical activity | CONF | `projectors/base.py:43-62` — every projector auto-emits activity per row; with fan-out, comms+touchpoint would double-emit. Idempotency keys are row-derived (`sctf:{touchpoint_id}`, `comms:{fact_id}`), not source-derived | Backend, tests | P0 / 2.1 | CommsProjector owns activity for comms events (source-derived key `sha256(tenant+source+provider_account+provider_event_id+semantic_type)`); dispatcher suppresses duplicate emission for comm event types |
| 2.6 | Per-projector failure isolation / replay safety | PART | Dispatcher has a single try/except around one projector; DB layer has `ON CONFLICT DO NOTHING` idempotency | Backend, tests | P0 / 2.1 | Isolate per projector; structured `ProjectionOutcome`; replay tests |

## 3. Storage

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 3.1 | `silver_comms_facts` rich schema | PART | `alembic/versions/20260622_silver_fact_tables.py:252-266` — only `comms_type, channel, campaign_id, message_id, support_case_id, deliverability` + common cols | Migration | P0 / — | Additive migration: direction, message_category, communication_state, sender/recipient refs, provider refs, campaign/message/thread/link refs, engagement + machine-activity fields, suppression/unsubscribe scopes, resolution confidence + indexes |
| 3.2 | Communication state projection table | MISS | No table; no reducer | Migration, backend, tests | P0 / 3.1 | New `communication_state` table + rebuildable reducer |
| 3.3 | Message/link dimensions | MISS | Campaign registry has campaigns/external_refs/aliases/reviews only (`20260627_campaign_registry.py`) | Migration, backend | P1 / — | New `campaign_messages`, `campaign_links` dimensions |
| 3.4 | Cross-channel campaign initiatives | MISS | No `campaign_initiatives` table | Migration, backend | P2 / — | New `campaign_initiatives` + members |
| 3.5 | Suppression with scopes | PART | `20260619_identity_suppression.py` exists (identity-level); no per-scope comm suppression model | Migration, backend, tests | P1 / 3.1 | `communication_suppressions` table with scope enum (message/campaign/list/segment/provider_account/marketing_channel/tenant/alias) |

## 4. Canonical activity, journeys, attribution

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 4.1 | Comms adapter family/actor routing | CONF | `measurement/silver_adapters.py:255-272` — `adapt_comms` hard-codes `activity_family="web2"`, `actor_type="human"` | Backend, tests | P0 / 3.1 | Route family from `message_category` (marketing→campaign, order/invoice→commerce, account/security/support→web2, agent→agent); actor_kind from provenance |
| 4.2 | Journey-role policy (context/active/state_only/outcome/excluded) | MISS | Journey compiler (`measurement/engine/journey_compiler.py`) has no comms awareness; no journey_role concept | Backend, tests | P1 / 4.1 | Journey-role policy in `services/comms/contracts.py`; adapter emits `journey_role`; compiler collapses `state_only` |
| 4.3 | Coalesced journey rebuilds | PART | `rebuild_affected_by_touchpoint` exists; no burst coalescing for comm events | Backend | P2 / 4.2 | Debounced rebuild queue keyed by (tenant, profile) |
| 4.4 | Attribution eligibility for comms | MISS | `attribution/models.py` has click/impression eligibility; no machine-open exclusion, no delivered-no-credit, no reply configurability | Backend, tests | P1 / 5.2 | Comms eligibility policy: delivered=context, machine open/click=excluded, human click=eligible, reply=configurable, transactional=excluded |

## 5. Provider ingestion and classification

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 5.1 | Klaviyo connector lifecycle | PART | `integrations/connectors/adapters.py:365-407` — profile pull only; `ingest_event_types=("klaviyo.profile","klaviyo.metric")`; no webhook event mapping, no campaign/flow/message sync, no cursor, no backfill | Backend, tests, docs | P0 / 1.1 | Extend: webhook parse → canonical comm events; campaign/flow sync → campaign registry; incremental events pull with cursor; reconciliation |
| 5.2 | Machine engagement classification | MISS | No classifier anywhere; opens/clicks all treated equally | Backend, tests | P0 / — | Deterministic classifier (`services/comms/classification.py`): UA/IP-class/timing/scanner rules; `suspected_machine_activity`, `machine_activity_probability`, `engagement_confidence` |
| 5.3 | Generic signed comms webhook | MISS | `measurement/connectors/generic_webhook.py` is spend/campaign-oriented; integrations webhook lacks comms payload contract | Backend, tests, docs | P0 / 1.2 | `POST /v1/comms/webhook` with HMAC signature verification, replay protection, canonical payload |
| 5.4 | Reply ingestion + auto-response detection | MISS | `email_replied` absent from registry; no correlation logic | Backend, tests | P1 / 1.1 | `services/comms/replies.py`: Message-ID/In-Reply-To/thread correlation; auto-response/DSN/OOO detection |
| 5.5 | Signed post-click correlation token | MISS | Touchpoint projector reads UTM/click ids; no signed token | Backend, tests, docs | P1 / — | `services/comms/click_token.py`: HMAC token (`ae=`), key rotation, expiry, cross-tenant rejection; acquisitionEvidence integration |

## 6. Identity and campaign resolution

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 6.1 | Email alias identity evidence | PART | `identity/signals.py:174-180` normalizes email; hashing utilities in `identity/hashing.py`; no provider-profile/mailbox evidence kinds | Backend, tests | P1 / — | Comms identity evidence: email_hash, provider_profile_id, provider_recipient_id, thread participant |
| 6.2 | Shared-mailbox classification | MISS | No classification of role accounts (sales@, support@, …) | Backend, tests | P0 / — | `services/comms/mailbox.py`: role-account detection → organization-level resolution, never auto-human |
| 6.3 | Campaign registry reuse for email | IMPL | `campaign/registry.py` — provider-agnostic upsert/aliases/reviews, tenant-scoped | — | — | Reuse as-is; add channel=email refs via connectors |
| 6.4 | Campaign hierarchy (message/variant/link) | MISS | Registry stops at campaign level | Migration, backend | P1 / 3.3 | Message/link dimensions keyed to canonical campaign |

## 7. Graph

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 7.1 | Aggregated COMMUNICATES_WITH edges | CONF | `silver_graph_projector.py:155-171` — per-event `sender → CONTACTED → recipient`; `sender_id` defaults to literal `"system"` (global high-degree node); no counts/aggregation | Backend, tests | P1 / 3.1 | Aggregated relationship emission from comms facts with counts, first/last observed, confidence, consent purpose; resolve real sender context |
| 7.2 | Selective message/thread promotion | MISS | No promotion rules | Backend, tests | P2 / 7.1 | Promote only replied/support/high-value/agent threads |
| 7.3 | No event-node explosion | PART | Current emission is edge-per-event (bounded only by idempotency key) | Backend, tests | P1 / 7.1 | Aggregate edges keyed by (tenant, sender, recipient, channel) |

## 8. Profile360 / Campaign 360 backends

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 8.1 | `GET /v1/profile/{id}/communications` | CONF (fake success) | `profile/routes.py:1715-1734` calls `repo.query_silver(...)` — **method does not exist on `AnalyticsRepository`** (`repositories/repos.py:513`); AttributeError is swallowed, route always returns `[]` | Backend, tests | P0 / 3.1 | Real `CommsFactsRepository` query with filters (channel, category, direction, campaign, state, human_qualified, cursor) |
| 8.2 | Profile summary communication counts/state | MISS | `profile/aggregator.py` has no comms dimension | Backend, tests | P1 / 3.2 | Add comms counts + `communication_state.email` summary; new `/communication-state` endpoint |
| 8.3 | Campaign 360 Messages surface | MISS | `campaign/routes.py` tabs: overview/touchpoints/population/entities/clusters/journeys/conversions/graph/quality — no messages/links/funnel | Backend, frontend, tests | P1 / 3.3 | `/campaigns/{id}/messages`, `/messages/{id}`, `/links`, email funnel in overview with provider-reported vs human-qualified modes |
| 8.4 | Population comm filters | PART | `exploration.py` builds population from touchpoints/conversions/credits; no comm engagement filters | Backend | P2 / 8.3 | Extend population stages with delivered/engaged/replied |

## 9. Frontends

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 9.1 | Tenant Campaign 360 Messages tab | MISS | `frontend/aether/src/features/campaigns/` has no comms surface | Frontend, tests | P1 / 8.3 | Messages tab + funnel toggle + engagement labels |
| 9.2 | Tenant Profile360 comms card/timeline | MISS | `frontend/aether/src/features/profile360/` | Frontend, tests | P1 / 8.1-8.2 | Communication summary + state cards, timeline |
| 9.3 | Kyber comms health surfaces | MISS | `frontend/kyber/src/features/` has no comms ops | Frontend, tests | P2 / 5.x | Connector fleet + projection/resolution health panels |

## 10. Consent, privacy, observability

| # | Requirement | State | Evidence | Work | Priority / Depends on | Recommended change |
|---|---|---|---|---|---|---|
| 10.1 | Marketing consent purpose | IMPL | `consent-registry.json` — `marketing` purpose, 180d retention, DSR scopes | — | — | Reuse; map comms categories → purposes |
| 10.2 | Category-scoped suppression | MISS | Unsubscribe is a single event; no scope model | Backend, migration, tests | P1 / 3.5 | Scope enum + fail-closed evaluation |
| 10.3 | PII hashing / redacted display for aliases | PART | `identity/hashing.py` exists; comms facts must never store raw addresses | Backend, tests | P0 / — | Hash + redact in `services/comms/mailbox.py`; enforce in projector |
| 10.4 | Comms pipeline metrics | MISS | No comms metrics | Backend | P1 / all | Projection latency/failures, machine-event rate, resolution coverage, webhook latency |
| 10.5 | Feature flags for rollout | PART | `config/settings.py` has per-domain flag precedent | Backend | P0 / — | `comms_*` flags: ingestion, campaign projection, journeys, graph, profile360, campaign360, noesis |

## Golden scenario status

The end-to-end "Customer Reactivation" fixture (registry sync → send → delivery
→ machine open → human click → landing → auth merge → purchase → attribution →
graph) does **not** exist. Target: `tests/integration/test_comms_golden_scenario.py`.

## Documentation conflicts recorded

1. `docs/PROFILE-360-AGGREGATION.md:430` claims Silver fact tables "are populated
   asynchronously by the SilverDispatcher projector chain" — no runtime caller
   exists (row 2.2). Fixed by wiring the dispatcher worker; doc now accurate.
2. `docs/_generated/event-registry-table.md` lists `communication_facts` as the
   Silver projection for comms events — accurate only after row 2.3 lands.
3. `docs/KLAVIYO-CONNECTOR.md` describes profile sync; the connector now also
   covers campaign/flow sync and event webhooks (row 5.1).
