---
source_files:
  - packages/shared/contracts/event-registry.json
  - packages/shared/agent-deployment.ts
  - packages/shared/ai-execution.ts
  - packages/shared/payment-rails.ts
  - packages/shared/targeting-intelligence.ts
  - Backend Architecture/aether-backend/config/settings.py
last_synced_commit: HEAD
---

# First-Release Intelligence, Telemetry, Payments, AI Economics, and Kyber Operations — Source of Truth

## Overview

Master source-of-truth document for the coordinated 8.12.0 first-release
implementation spanning five scopes:

1. **External Agent Telemetry Plane V1** (detail: `EXTERNAL_AGENT_TELEMETRY_PLANE.md`)
2. **Payment Rail Observability V1** (detail: `PAYMENT_RAIL_OBSERVABILITY.md`)
3. **AI Outcome Efficiency / AI Economics** (detail: `AI_OUTCOME_EFFICIENCY.md`)
4. **Cluster Targeting Intelligence** (detail: `CLUSTER_TARGETING_INTELLIGENCE.md`)
5. **Aether/Kyber One-Person Operations** (detail: `KYBER_ONE_PERSON_OPERATIONS.md`)

**Readiness target:** release-grade, tenant-scoped, evidence-backed, auditable,
durable in hosted modes, governed, safe by default. All new surfaces are
feature-flagged and default OFF.

## Product boundaries (non-negotiable)

- **Aether observes, attributes, and recommends.** It must not execute
  campaigns, buy ads, bid, target inside external platforms, execute or
  settle payments, custody funds, sign transactions, trade, change
  production models, rewrite production prompts, reroute live traffic,
  reduce quality thresholds, disable tools, change agent permissions,
  silently mutate canonical graph state, or initiate external spending.
- **Kyber operates.** Internal operator console; must not leak tenant-private
  raw data across tenants. Cross-tenant aggregates only where raw
  tenant-private data and tenant existence are not exposed.
- **No marketplace.** The External Agent Telemetry Plane observes tenant-owned
  agents on external surfaces. `custom_marketplace` is an external-platform
  enum value for tenant/third-party marketplaces only. The future flags
  `AETHER_PARTNER_ECOSYSTEM_ENABLED`, `AETHER_MARKETPLACE_ENABLED`,
  `AETHER_DEVELOPER_PLATFORM_ENABLED`, and `KYBER_PARTNER_ECOSYSTEM_ENABLED`
  are untouched and gate nothing in this release.
- **No generic payment webhook fallback.** Named providers only: Privy,
  Stripe crypto onramp, Coinbase, MoonPay, Bridge.
- **Staged mutation review.** Agents/workers/automation stage and recommend;
  canonical graph mutations pass through staged mutation review with human
  approval where risk or canonical truth is affected.

## Current-state audit (pre-implementation, at 8.11.0)

| Area | Status at audit | Canonical location |
|---|---|---|
| Canonical ingestion `/v1/batch`, bronze/silver, idempotency | Exists (mature) | `services/ingestion/batch.py`, `repositories/lake.py`, `services/silver/` |
| Canonical event registry (generated) | Exists — 267 events, 21 families | `packages/shared/contracts/event-registry.json` → `generate_contracts.py` |
| Agentic observability pipeline | Exists | `services/agentic_observability/` |
| Agent deployment registry | **Missing** (in-memory registration dict only) | `services/agent/routes.py` |
| Payment provider adapters (Privy/Stripe onramp/Coinbase/MoonPay/Bridge) | **Missing** (Stripe = own billing only; x402 rail exists) | `services/billing/`, `services/x402/` |
| AI execution facts | Partial — SDK cost passthrough only | `services/silver/projectors/agent_execution_projector.py` |
| AI pricing registry / price cards / workflow economics | **Missing** | — |
| Noesis LLM instrumentation | Partial — token counts only | `services/noesis/provider.py` |
| Cluster targeting intelligence (intents/eligibility/leakage/holdouts) | **Missing** (Cluster360 read surface exists) | `services/cluster/` |
| OODA suggestions / recommendation families | Exists (mature) | `services/suggestions/`, `services/intelligence/` |
| Agent runtime control plane (objectives/runs/review/kill switch) | Exists (durable) | `services/agent/runtime_repository.py` |
| Backend→worker dispatch bridge + worker callbacks | **Missing/partial** | `services/agent/routes.py`, `Agent Layer/queue/` |
| Approval-to-commit graph mutation execution | Partial (review exists; commit execution missing) | `services/agent/runtime_repository.py` |
| Durable briefings / alert compression / ops readiness | **Missing/partial** (in-memory BriefingStore) | `Agent Layer/agent_controller/runtime/briefing.py` |
| Identity resolution (conservative, consent-gated) | Exists (mature) | `services/identity/` |
| Graph write validation + staged mutations + CIS quarantine | Exists | `shared/graph/`, `shared/cis/` |
| Profile360 / Campaign360 / Cluster360 / Path Intelligence / Outcome Ledger | Exists | `services/profile/`, `services/campaign/`, `services/cluster/`, `services/operational_intelligence/`, `services/intelligence/outcome_ledger.py` |

## Canonical contracts (added in this release)

- `packages/shared/agent-deployment.ts` — `ExternalPlatform`,
  `AgentDeploymentContext`, `AgentDeployment`, lifecycle/consent enums,
  audit record. SDKs must never emit `canonical_entity_id`;
  `deployment_id`/`agent_id` are never merge-eligible identity signals.
- `packages/shared/ai-execution.ts` — `AIInvocationObserved` (canonical
  `ai_invocation_observed` payload), `AIExecutionFact`, `CostBasis`,
  `AIPriceCard`, `AIWorkflowEconomics`, detector/family constants. No raw
  prompt/completion content fields exist on these contracts.
- `packages/shared/payment-rails.ts` — `FundingSession`,
  `PaymentProviderAccount`, `DepositAddress`, `VirtualAccount`,
  `PaymentRailStatusMap`, `ReconciliationRecord`, `PaymentRailHealth`.
- `packages/shared/targeting-intelligence.ts` — targeting intent/eligibility/
  observation/outcome/leakage/holdout/journey-delta/impact/export contracts
  with evidence refs throughout.

All are exported through `packages/shared/index.ts` and mirrored by backend
Pydantic models in their owning service packages.

## Canonical events

One new canonical event is registered in this release:

| Event | Family | Purposes | Privacy | Retention | Silver projection | Graph projection |
|---|---|---|---|---|---|---|
| `ai_invocation_observed` | agent | agent | behavioral | standard_90d | `ai_execution_facts` | `USED_MODEL` |

Payment rails reuse the existing canonical `payment_initiated`,
`payment_completed`, and `payment_failed` events with rail/provider/session
properties. Deployment lifecycle is API-driven with audit records. Targeting
objects are computed read models over existing facts.

## Feature flags

All default OFF. Backend settings sections in
`Backend Architecture/aether-backend/config/settings.py`:

| Settings section | Flags |
|---|---|
| `external_agent_telemetry` | `AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED`, `KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED`, `AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED`, `AETHER_AGENT_TELEMETRY_SDK_ENABLED`, `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED`, `AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED` |
| `payment_rails` | `AETHER_PAYMENT_RAILS_ENABLED`, `AETHER_PROVIDER_PRIVY_ENABLED`, `AETHER_PROVIDER_STRIPE_ENABLED`, `AETHER_PROVIDER_COINBASE_ENABLED`, `AETHER_PROVIDER_MOONPAY_ENABLED`, `AETHER_PROVIDER_BRIDGE_ENABLED`, `KYBER_PAYMENT_RAILS_ENABLED` |
| `ai_economics` | `AETHER_AI_OUTCOME_EFFICIENCY_ENABLED`, `AETHER_AI_EXECUTION_FACTS_ENABLED`, `AETHER_AI_ECONOMICS_ENABLED`, `AETHER_AI_EFFICIENCY_RECOMMENDATIONS_ENABLED`, `KYBER_AI_EFFICIENCY_HEALTH_ENABLED` |
| `targeting_intelligence` | `AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED`, `AETHER_TARGETING_EXPORTS_ENABLED`, `AETHER_TARGETING_OODA_SUGGESTIONS_ENABLED`, `KYBER_TARGETING_INTELLIGENCE_ENABLED` |
| `one_person_ops` | `AETHER_AGENT_RUNTIME_DURABLE_ENABLED`, `AETHER_AGENT_WORKER_BRIDGE_ENABLED`, `AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED`, `AETHER_CATALYST_CYCLE_AUTOMATION_ENABLED`, `KYBER_AGENT_COMMAND_CENTER_ENABLED`, `KYBER_ONE_PERSON_OPS_ENABLED` |

All are documented in `.env.example`. The exact mandate flag names are used
verbatim — no mapping layer was needed.

## Security and privacy invariants

- Tenant isolation on every record, route, cache key, queue message, and UI
  response; cross-tenant access returns not-found/forbidden without leaking
  existence.
- Never persisted: raw prompt/completion text, chain of thought, API keys,
  authorization headers, tool credentials, retrieved document content, KYC
  documents, card numbers, bank/routing numbers, raw identity documents,
  provider secrets.
- Currency safety: mixed currencies are never summed into a scalar without
  explicit conversion metadata; unknown cost stays unknown (never zero).
- Identity: deployment/agent/platform signals are never merge-eligible;
  merges require strong evidence (authenticated IDs, verified hashes,
  wallet signature proofs, validated tenant-owned external IDs).
- Hosted durability: staging/production fail closed when required durable
  stores, queues, or migrations are missing.

## Rollout stages

1. **Dark (default)** — all flags OFF; no route mounts, no projections.
2. **Internal validation** — Kyber-side flags ON in staging; operator
   surfaces validated against deterministic fixtures and live stores.
3. **Tenant preview** — per-scope Aether flags ON for selected tenants;
   provider adapters configured via tenant-scoped BYOK secrets.
4. **General availability** — flags ON by environment default only after
   release gates (`make release-gate`) pass with the new checks.

## Release gates

- `make repo-doctor` / `make ci-check` green (contracts, parity, SDK
  alignment, docs drift, generated files, tests).
- `python scripts/bump_version.py --check` — 8.12.0 aligned everywhere.
- Domain tests per scope (see per-scope docs).
- `make release-gate` — production status strict checks.

## Known limitations / explicit non-goals

- No marketplace, app store, listing/search/discovery, submission/review,
  or revenue-share features.
- No generic webhook receiver; unsupported providers return 404.
- No autonomous execution of campaigns, payments, trades, model changes,
  or graph mutations.
- Provider adapters ship with deterministic test doubles; live credentials
  are tenant-supplied post-release.

## Implementation log

- **Slice 1 (this document's introduction):** version 8.12.0;
  `ai_invocation_observed` registered (268 events); four shared contract
  files added and exported; five backend settings sections added (28 flags,
  default OFF); `.env.example` documented.
- **Slice 2 (merged, PR #411):** External Agent Telemetry Plane — durable
  AgentDeployment registry + lifecycle routes, /v1/batch deployment-context
  validation + canonical_entity_id stripping, identity non-merge denylist,
  Profile360 subresource, server/python telemetry SDKs, Aether/Kyber UI.
  See `EXTERNAL_AGENT_TELEMETRY_PLANE.md`.
- **Slice 3 (merged, PR #412):** Payment Rail Observability — five named
  adapters (Privy/Stripe onramp/Coinbase/MoonPay/Bridge), FundingSession
  with final-state non-regression, reconciliation, public HMAC webhooks,
  Kyber fleet health, Profile360 rollup. Includes the get_settings() app
  startup fix. See `PAYMENT_RAIL_OBSERVABILITY.md`.
- **Slice 4 (merged, PR #413):** AI Outcome Efficiency — ai_execution_facts
  projector, effective-dated price cards with Noesis seeds, cost hierarchy
  (unknown never zero), workflow economics, five efficiency detectors as
  recommendation family + suggestion adapter, Noesis instrumentation,
  Aether/Kyber dashboards. See `AI_OUTCOME_EFFICIENCY.md`.
- **Slice 5 (merged, PR #414):** Cluster Targeting Intelligence — 15-module
  targeting package (policy precedence, snapshots, leakage, exports,
  suggestion/noesis adapters, recompute, readiness), Campaign360/Cluster360
  tabs, suggestion targeting cards, Kyber targeting console.
  See `CLUSTER_TARGETING_INTELLIGENCE.md`.
- **Slice 6:** One-Person Operations — worker execution bridge with hosted
  fail-closed dispatch, service-credentialed run callbacks, stuck-run
  detection/replay, approval-to-commit staged mutation pipeline with CIS
  quarantine, durable briefings, compressed ops alerts, Kyber command
  center live wiring, `make ops-readiness` release gate.
  See `KYBER_ONE_PERSON_OPERATIONS.md`.
