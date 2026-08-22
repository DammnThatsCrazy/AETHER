---
title: "ADR-008: Multi-Model Intelligence Harness"
slug: decisions/adr-008-multi-model-intelligence-harness
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# ADR-008: Multi-Model Intelligence Harness

**Status**: Accepted (8.12.0)

## Context

Aether has a Noesis runtime that answers tenant questions from the intelligence
graph, but its intelligence today is narrow and ungrounded:

- **Noesis is deterministic classification with an LLM text-to-query fallback
  and no grounded synthesis.** The `NoesisPlanProvider` seam
  (`services/noesis/provider.py`) returns only a structured, allowlisted
  `QueryPlan` — the model may pick an intent and filters, and Aether executes
  the read against read-only repositories. There is no path for a model to
  produce a grounded answer: no retrieval-before-synthesis, no evidence
  references, no faithfulness verification. Answers that need reasoning must be
  stitched together elsewhere or not at all.
- **LLM providers bypass the provider gateway.** Noesis reads
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the process environment and
  constructs provider clients directly inside the service. There are **no
  per-tenant LLM credentials**, no key rotation, no masked metadata, no
  operator surface for LLM provider keys — a governance gap for a platform
  where every other external credential flows through the
  `CredentialBackend` abstraction (`shared/credentials/interface.py`).
- **There is no canonical model catalog or task-profile contract.** Models are
  hard-coded strings in provider classes (`claude-haiku-4-5`, `gpt-4o-mini`),
  routing is a single env var (`NOESIS_LLM_PROVIDER`), and there is no
  declarative statement of which models may serve which task, under what
  policy, with what guardrails, latency, or cost bounds.

The principal-engineer program needs a **production multi-model intelligence
harness**: OpenAI + Anthropic first, more providers via isolated adapters, all
operating as interchangeable planning / reasoning / classification / synthesis
engines inside a controlled Aether harness. Every answer must be
tenant-scoped, evidence-backed, policy-governed, observable, auditable, and
verifiable. The harness must deliver interchangeability, per-tenant
credentials, routing/policy, grounded synthesis, verification, evaluation,
observability, and operator + tenant UX — all inside the existing Aether
controls.

The extension must be **additive**. It does NOT redesign the intelligence
graph, the graph mutation gateway, the entity/identity model, Profile360, the
semantic/sentiment models, Gold projections, the SDK ingestion contract,
consent authority, the audit ledger, provider key vault/usage, Noesis
read-only intent + repository-dispatch architecture, the runtime-role model,
or frontend boundaries. No parallel graph/identity/consent/audit/
provider-credential/conversation systems. Noesis remains read-only (see the
observation-only execution invariant).

## Decision

Lay a controlled multi-model harness over the existing Aether authority,
recorded as nine numbered decisions.

### D1 — Additive extension layered on existing Aether authority

The harness is a **new runtime** (`services/model_runtime/` in the backend,
with contracts under `packages/shared/`) layered on the existing authority:
intelligence graph, identity, consent, audit ledger, credential backends, and
policy gates. It reuses — and never re-implements — those systems. The harness
extends the intelligence graph surface additively and does not modify the
graph mutation gateway. There are no parallel graph, identity, consent, audit,
provider-credential, or conversation systems. Noesis stays read-only and keeps
its read-only intent + repository-dispatch architecture; the harness may be
consumed by Noesis (or by other surfaces) without altering Noesis's authority
model.

### D2 — Provider-neutral adapter isolation

OpenAI and Anthropic are the first two providers. Every additional provider —
Kimi-family, open-weight, OpenAI-compatible endpoints, Bedrock, self-hosted
serving — is an **isolated adapter** behind a common runtime interface. A
provider adapter is responsible for translating the harness's provider-neutral
request/response contract to that provider's API; nothing else in the harness
imports a provider SDK. Noesis orchestration never imports provider SDKs. The
model registry's capability flags (`chat`, `tool_use`, `streaming`,
`structured_outputs`, `vision`, `thinking`, …) drive adapter behavior instead
of per-provider special cases.

### D3 — Canonical contracts (single source of truth)

`packages/shared/contracts/model-registry.json` (the canonical catalog of
harness LLM models: ids, aliases, providers, capability flags, cost, adapter
call behavior, lifecycle status) and `packages/shared/contracts/
task-profile-registry.json` (task profiles binding a model role, routing
policy, guardrails, output kind, and latency/cost bounds to named harness
tasks) are the **single source of truth** for models and task profiles.
`scripts/generate_platform_contracts.py` emits the TS / Python / Markdown
twins (`packages/shared/model-registry.ts`, the Python model-runtime module,
`docs/_generated/model-registry-table.md`, and their task-profile
counterparts) via the `REGISTRIES` table — new registries plug into that
table; generated artifacts are never hand-edited.

The **harness model registry is distinct from the ML `ModelEntry` registry** in
`ML Models/aether-ml/common/model_registry.py`. The ML registry describes
trainable/serving ML models (intent prediction, churn, LTV, trust score, …)
with artifacts, training entrypoints, and governance gates. The harness
registry describes hosted LLM provider models used as interchangeable
intelligence engines. The two coexist; neither is a special case of the other.

### D4 — Model routing and policy modes

Routing/policy supports four modes: `auto` (harness selects the best model for
the task from the registry), `tenant_default` (tenant-configured default
model), `explicit` (operator or tenant requests a specific model id), and
`policy_required` (a policy mandates a specific model or profile). Every route
is subject to **entitlement checks** (is this model/policy entitled for this
tenant?) and falls back to a safe path when the requested route is unavailable,
misconfigured, or over budget. The selected route and the fallback decision are
recorded for audit and observability.

### D5 — Per-tenant LLM credentials via the existing `CredentialBackend`

Per-tenant LLM credentials are stored through the existing `CredentialBackend`
abstraction (`shared/credentials/interface.py`), **not** a new credential
system. Backends remain in-memory (dev/test), local-encrypted (default
self-hosted), and AWS Secrets Manager scoped to `aether/credentials/
{tenant_id}/{ref}` for production. The harness resolves credentials through the
`credential_service` facade like every other connector (BYOK vault, connector
secrets). Only masked, secret-free `CredentialMetadata` ever leaves the
backend.

Credentials are **never** in source, frontend bundles, logs, prompts, or
persisted conversation content. The provider client is constructed at call time
from a decrypted `StructuredCredential` obtained through the trusted resolver
path and released immediately; nothing caches plaintext. Legacy env-key access
in Noesis (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) is migrated to this path as
the Noesis migration commit lands.

### D6 — Grounded synthesis: retrieval before synthesis

The harness performs **retrieval before synthesis**. Aether executes all
retrieval through its own repositories — the model never queries storage
directly. The model materially affects the answer text, but the harness
assembles the retrieval context and the model synthesizes over it. Every claim
in a synthesized answer carries **evidence references** back to the retrieved
records. When the model cannot ground a claim in the provided evidence, the
claim is marked unsupported rather than silently asserted.

### D7 — Verification and faithfulness

Before an answer surfaces, the harness runs **claim / numeric / identifier /
scope checks**: claims are matched against their evidence references; numeric
assertions are checked against the retrieved values; entity identifiers are
validated against the tenant's scope; and the answer is confirmed not to
reference out-of-tenant evidence. Answers that fail verification are blocked
(fail closed) or surfaced with an explicit unsupported disposition — they are
never presented as verified truth.

### D8 — Observability and operations

The harness ships production-grade observability and ops controls: metrics for
calls, tokens, latency, cost, provider errors, verification outcomes, and
circuit-breaker state; health/readiness endpoints for the runtime and each
provider adapter; circuit breakers per provider/tenant; canary model/providers;
and runbooks. **Staging and production fail closed on missing credentials or
missing/unsafe configuration** — a misconfigured adapter must degrade the
request, never silently bypass policy.

### D9 — Feature flags default OFF; capability-gated surfaces

All harness features ship behind **feature flags default OFF**. Tenant and
operator surfaces are gated by the existing capability framework (the same
framework used by the Kyber control plane and tenant product surfaces); no
harness surface is reachable without an explicit capability grant. A newly
added provider or task profile is invisible until an operator explicitly
enables it and a tenant is entitled.

## Security invariants (binding)

The following invariants are binding for every adapter, runtime module,
contract, and surface in this program:

- Credentials never stored in source code, frontend bundles, logs, prompts, or
  persisted conversation content.
- The model never receives direct database authority.
- The model may propose only allowlisted structured plans/tools.
- Aether executes all retrieval.
- Tenant scope is server-authoritative.
- Staging/production fail closed on missing credentials/config.
- Never log API keys, authorization headers, raw secret values, secret-manager
  payloads, or provider request bodies with restricted tenant data.
- No raw SQL/Gremlin/Cypher/GraphQL/arbitrary HTTP/tool execution.
- Cross-tenant evidence leakage forbidden.
- The model must never select/override tenant scope.

## Consequences

### Positive

- **Interchangeability.** OpenAI and Anthropic (then Kimi-family, open-weight,
  OpenAI-compatible, Bedrock, self-hosted) are drop-in engines behind one
  runtime interface. Model swaps are configuration, not code.
- **Per-tenant control.** LLM credentials move out of process env vars and into
  the governed `CredentialBackend`, with rotation, revocation, masked
  metadata, and audit — the same discipline as every other external
  credential.
- **Grounded, verifiable answers.** Retrieval-before-synthesis plus
  claim/numeric/identifier/scope verification means synthesized answers carry
  evidence and can be audited, instead of being ungrounded model text.
- **Single source of truth.** The model and task-profile registries plus the
  codegen `REGISTRIES` table keep TS/Python/docs twins in lockstep and make
  the catalog declarative and reviewable.
- **Auditability and observability.** Every call, route decision, fallback,
  credential resolution, verification outcome, and cost is recorded — the
  harness is a controlled, observable system, not an ad-hoc provider call.
- **Additive safety.** Because the harness layers on existing authority and
  ships behind flags default OFF, it does not disturb the intelligence graph,
  mutation gateway, identity, consent, audit, credential, Noesis read-only, or
  frontend boundaries it extends.

### Negative / trade-offs

- **Adapter maintenance.** Every provider adapter is a maintained component
  (SDK churn, endpoint drift, capability differences). The capability-flag
  contract bounds this but does not remove it.
- **Cost.** Multiple models per task profile, canaries, and evaluation runs
  multiply token spend. Cost bounds per task profile and circuit breakers
  mitigate but do not eliminate the exposure.
- **Latency.** Retrieval-before-synthesis, verification passes, and
  per-request credential resolution add hops and time versus a raw single
  provider call. Budgets and async verification keep this bounded.
- **Verification overhead.** Faithfulness checks add engineering surface and
  can produce false unsupported dispositions that need tuning; verification is
  deliberately strict and fail-closed, so teams must treat it as a product
  gate, not a cost to remove.

## Appendix — 16-commit delivery plan

The program lands in sixteen ordered commits, each independently CI-clean and
additively safe:

1. **ADR + contracts** — this ADR, plus the model and task-profile registry
   contracts and their generated twins (model registry, task-profile registry).
2. **Runtime models** — `services/model_runtime/` core models: provider-neutral
   request/response, routing, policy, evidence, verification record types.
3. **Noesis migration** — Noesis's LLM fallback re-points to the harness
   adapter seam; legacy env-key provider reads are retired behind the
   `CredentialBackend` path.
4. **OpenAI-compatible adapter** — the first generic adapter (covers OpenAI and
   OpenAI-compatible endpoints); verified against the registry contract.
5. **Routing / policy** — the four routing modes (auto / tenant_default /
   explicit / policy_required), entitlement checks, fallback, and route audit
   records.
6. **Credentials** — per-tenant LLM credential resolution through
   `CredentialBackend` (in-memory, local-encrypted, AWS Secrets Manager scoped
   `aether/credentials/{tenant_id}/{ref}`), masked metadata, fail-closed
   resolution.
7. **Task profiles** — task-profile execution: role binding, guardrails,
   latency/cost bounds, output kind enforcement.
8. **Context / evidence** — retrieval-context assembly and the evidence
   reference model; Aether executes all retrieval.
9. **Grounded synthesis** — retrieval-before-synthesis answering path; every
   claim carries evidence references.
10. **Verification** — claim / numeric / identifier / scope checks before
    answers surface; fail-closed unsupported disposition.
11. **Evaluation** — harness evaluation harness: ground-truth task sets,
    faithfulness scoring, per-model/provider comparisons, canary promotion.
12. **Observability** — metrics, health/readiness, circuit breakers, canaries,
    runbooks; staging/production fail-closed behavior validated.
13. **Aether UX** — tenant-facing surfaces (evidence-backed answers,
    transparent model routing) gated by the capability framework, flags OFF.
14. **Kyber control plane** — operator surfaces: model catalog lifecycle,
    routing policy, entitlements, credential refs, cost governance, canary
    management.
15. **Deployment config** — environment configuration, IAM/Secrets Manager
    wiring, fail-closed checks, release runbooks.
16. **Final integration** — end-to-end integration, `make ci-check` gate, docs
    synced, capability rollout.

## References

- `Backend Architecture/aether-backend/services/noesis/provider.py` — the
  Noesis provider seam being migrated to the harness adapter interface.
- `Backend Architecture/aether-backend/shared/credentials/interface.py` — the
  `CredentialBackend` abstraction + secret-free `CredentialMetadata`; concrete
  backends live alongside it (`in_memory.py`, `local_encrypted.py`,
  `aws_secrets_manager.py`).
- `scripts/generate_platform_contracts.py` — the `REGISTRIES` table that emits
  TS / Python / Markdown twins; the model and task-profile registries plug in
  here.
- `packages/shared/contracts/model-registry.json` — canonical harness LLM model
  catalog (D3).
- `packages/shared/contracts/task-profile-registry.json` — canonical task
  profiles and routing/guardrail vocabulary (D3, D4).
- `ML Models/aether-ml/common/model_registry.py` — the distinct ML `ModelEntry`
  registry the harness registry must not be confused with (D3).
- `docs/decisions/ADR-007-domain-canonicalization.md` — the one-source-of-truth
  precedent this ADR extends.
- `docs/decisions/ADR-007-observation-only-execution-invariant.md` — the
  Noesis read-only execution invariant the harness preserves.
