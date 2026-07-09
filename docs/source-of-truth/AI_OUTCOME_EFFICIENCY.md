---
source_files:
  - packages/shared/ai-execution.ts
  - Backend Architecture/aether-backend/services/economic/ai_models.py
  - Backend Architecture/aether-backend/services/economic/ai_pricing.py
  - Backend Architecture/aether-backend/services/economic/ai_costs.py
  - Backend Architecture/aether-backend/services/economic/ai_aggregation.py
  - Backend Architecture/aether-backend/services/economic/ai_efficiency.py
  - Backend Architecture/aether-backend/services/economic/ai_routes.py
  - Backend Architecture/aether-backend/services/silver/projectors/ai_invocation_projector.py
last_synced_commit: HEAD
---

# AI Outcome Efficiency / AI Economics — Source of Truth

## Overview

Aether determines what AI work occurred, who/what caused it, which
provider/model/prompt/configuration was used, its fully loaded cost, whether
it technically succeeded and met quality thresholds, which qualified business
outcomes it produced, and where AI spend produced no value — then generates
**governed proposals** to reduce cost without degrading quality, reliability,
latency, safety, or outcomes.

**Governing rule:** Aether optimizes for the lowest fully loaded cost that
satisfies required quality, latency, reliability, risk, governance, and
business-outcome constraints.

**Hierarchy of value:** cost per token → cost per invocation → cost per
completed workflow → cost per qualified outcome → incremental business value
per AI dollar. Aether owns the final three levels.

**Naming:** backend domain **AI Economics** (`services/economic/ai_*.py`),
tenant surface **AI Efficiency** (`/ai-efficiency`), Kyber surface
**AI Efficiency Health**.

## Boundaries

Aether observes and recommends. It never changes production models, rewrites
production prompts, reroutes live traffic, reduces quality thresholds,
disables tools, or changes agent permissions. All recommendations are
evidence-backed proposals surfaced through the canonical recommendation/
suggestion framework.

**Privacy:** execution records carry identity, version, hash, configuration,
usage, model, provider, cost, latency, quality, and outcome correlation —
never raw prompt text, completion text, chain of thought, API keys, or
retrieved document content. Payloads carrying prompt/completion-content
fields are rejected at validation; `contains_prompt_content` /
`contains_completion_content` default false.

## Canonical event and read model

- Event: `ai_invocation_observed` (family `agent`, purposes `["agent"]`,
  privacy `behavioral`, retention `standard_90d`) — registered in the
  canonical event registry; validated per the shared contract
  (`packages/shared/ai-execution.ts`), mirrored in
  `services/economic/ai_models.py` (non-negative usage/cost/latency,
  `quality_score` 0..1, bounded free-text dimensions, prompt-content field
  rejection).
- Read model: `ai_execution_facts` — **a new canonical store, not an
  extension of `silver_agent_execution_facts`**. Inspection conclusion
  (mandate §8.3): the existing silver table is event-grained (one row per
  each of 14 `agent_*` lifecycle event types with passthrough `cost_usd`),
  while `AIExecutionFact` is invocation-grained with unique
  `(tenant_id, invocation_id)`, computed `selected_cost`, `cost_basis`,
  and `data_quality_status`; changing the existing table's grain would
  break its 14 co-writing projectors and violate the additive-only rule.
  `agent_cost_observed` → `silver_agent_execution_facts` continues
  unchanged; AI Economics reads only `ai_execution_facts`.
- Projector: `services/silver/projectors/ai_invocation_projector.py`,
  flag-gated (`AETHER_AI_EXECUTION_FACTS_ENABLED`), idempotent on
  `(tenant_id, invocation_id)` — duplicate with matching
  `provenance.raw_event_hash` reuses the record; a different hash is
  rejected and audited.

## Pricing and cost accounting

- Effective-dated **price cards** (`ai_pricing.py`, store `ai_price_cards`)
  per provider/model/region/service-tier across 10 usage dimensions (input/
  output/cached-input/reasoning/embedding tokens, image units, audio/video
  seconds, tool calls, retrievals); most-specific active card wins; platform
  seed cards ship for the Noesis models so Noesis costs compute immediately.
- **Cost selection hierarchy** (`ai_costs.py`):
  `billed_cost → actual_cost (provider_reported) → calculated (price card)
  → estimated_cost → unknown`. **Unknown cost stays unknown — it never
  silently becomes zero.** Currency safety: calculation only proceeds when
  event and card currencies agree; mismatches degrade to estimated/unknown
  with `data_quality_status="suspect"`. Aggregates report per-currency
  totals and never sum mixed currencies into one scalar.

## Workflow and outcome economics

`ai_aggregation.py` aggregates by `(tenant_id, workflow_run_id)` — workflow
IDs are never fabricated; facts without one are excluded from workflow
economics. Metrics: total AI cost (per currency), cost per invocation, cost
per completed workflow, qualified outcomes, cost per qualified outcome,
failed execution cost, retry waste cost, cache utilization rate, human
correction rate, outcome attribution coverage, quality-adjusted cost, and
cost coverage (share of facts with known cost).

## Noesis — first complete instrumented workload

`services/noesis/provider.py` (Anthropic + OpenAI plan providers) captures
split input/output tokens, latency, status, and model, and records an
`ai_invocation_observed` fact (`task_type="noesis_plan"`,
`provenance.source="noesis"`) through the projector path — fail-open so
telemetry can never break planning, flag-gated, and never carrying prompt
or completion content.

## Efficiency intelligence

`ai_efficiency.py` — five deterministic, evidence-backed detectors
(recommendation family `ai_outcome_efficiency`, surfaced through the
canonical recommendation registry and an OODA suggestion adapter):

1. **Retry waste** — retry cost concentration by workflow/model.
2. **Model overqualification** — consistently near-perfect quality on an
   expensive model where a cheaper card exists.
3. **Deterministic replacement candidate** — high-repetition identical-hash
   invocations with perfect quality.
4. **Cache opportunity** — high repeated input volume with low cached share.
5. **Failed-workflow concentration** — workflows/task types burning cost at
   high failure rates.

Candidate actions are governed proposals only.

## Routes

Tenant (`/v1/economic/ai`, flag `AETHER_AI_OUTCOME_EFFICIENCY_ENABLED`):
`GET /summary`, `GET /invocations` (filtered), `GET /workflows`,
`POST /workflows/{workflow_run_id}/recompute`, `GET /models`, `GET /waste`,
`GET /price-cards`, `POST /price-cards`, `GET /recommendations`.
Kyber (`/v1/admin/kyber/ai-efficiency`, operator-gated): `GET /health`
(cross-tenant aggregates only), `GET /{tenant_id}` (drilldown).

## Frontend

- Aether `/ai-efficiency`: per-currency total-cost cards (never merged),
  workflow economics table, model comparison, waste analysis, recommendations
  with the copy "Proposals only — Aether never changes models, prompts, or
  routing automatically." Unknown cost renders as an "unknown" badge — never
  `$0`.
- Kyber `/ai-efficiency` (flag `enableAiEfficiency`): fleet fact volume,
  cost-coverage gauge, unknown-cost share, detector counts, per-tenant
  drilldown (aggregates only).

## Feature flags (default OFF)

`AETHER_AI_OUTCOME_EFFICIENCY_ENABLED`, `AETHER_AI_EXECUTION_FACTS_ENABLED`,
`AETHER_AI_ECONOMICS_ENABLED`, `AETHER_AI_EFFICIENCY_RECOMMENDATIONS_ENABLED`,
`KYBER_AI_EFFICIENCY_HEALTH_ENABLED`.

## Storage

Migration `20260710_ai_economics.py`: store-backing tables
`ai_execution_facts`, `ai_price_cards`, `ai_workflow_economics`.

## Testing

`BE/tests/ai_economics/`: contract validation (incl. prompt-content
rejection), price-card effective dating/specificity/validity, cost hierarchy
incl. unknown-stays-unknown and currency-mismatch → suspect, projector
idempotency and flag-off no-op, workflow aggregation (no fabricated IDs,
per-currency totals), all five detectors (positive + negative fixtures),
Noesis telemetry fail-open, route flag gating, Kyber operator permission,
tenant isolation. Frontend: aether ai-efficiency tests (unknown-cost badge
asserted), kyber component tests.

## Known limitations / non-goals

- Seed price cards are platform defaults for the Noesis models; tenant- or
  provider-billed truth supersedes them through the cost hierarchy.
- Value attribution (`attributed_value`, qualified outcomes) activates as
  decision/outcome linkage data arrives; coverage metrics make gaps visible
  rather than guessing.
- No autonomous execution of any efficiency recommendation.
