---
title: Model Runtime Deployment
slug: operations/model-runtime-deployment
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: beta
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/model_runtime/config.py
  - Backend Architecture/aether-backend/services/model_runtime/service.py
  - Backend Architecture/aether-backend/services/model_runtime/routing/engine.py
  - Backend Architecture/aether-backend/services/model_runtime/credentials/interface.py
  - Backend Architecture/aether-backend/services/model_runtime/context/evidence.py
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Model Runtime Deployment

Deployment contract for the Aether **model runtime** — the provider-neutral
multi-model intelligence harness (ADR-008). This doc is the runtime's
fail-closed deployment surface: the `MODEL_RUNTIME_*` environment contract,
the security invariants a deploy must honor, and the runbook pointers that
describe how to operate it once it is running.

## 1. Overview

The model runtime (`Backend Architecture/aether-backend/services/model_runtime/`)
is a **new, additive runtime** layered on the existing Aether authority. It is
**additive to Noesis** — Noesis keeps its read-only intent +
repository-dispatch architecture, and the harness may be consumed by Noesis or
by other surfaces without altering Noesis's authority model. The harness is
**read-only**: it executes retrieval through Aether's own repositories, proposes
only allowlisted structured plans, and never writes to the intelligence graph,
mutation gateway, identity, consent, or audit systems it extends.

The runtime is gated behind a feature flag that is **OFF by default**
(ADR-008 D9). Nothing is reachable until an operator explicitly enables the
runtime and a tenant is entitled. Deploying the flag `false` is a valid,
supported production state.

## 2. Architecture summary

The runtime is composed of small, single-purpose modules behind one
orchestration seam (`service.py`). A request flows: routing/policy → entitlement
→ credential resolution → provider invocation → grounded-synthesis context →
verification. Every hop is observable and audited.

| Concern | Module | Behavior |
|---|---|---|
| Orchestration | `service.py` | Provider registry, per-tenant token budget, invoke/reconcile path. Never imports a provider SDK, credentials backend, or noesis package. |
| Routing / policy | `routing/engine.py` | Four routing modes, entitlement checks, fallback chain, `RouteAuditEntry` recording. Deterministic — no randomness, no wall-clock-dependent choice. |
| Credentials | `credentials/interface.py` | Per-tenant LLM credential resolution through the existing `CredentialBackend` (D5). Secret-free masked metadata only. |
| Grounded context | `context/evidence.py` | Retrieval-before-synthesis evidence models (D6). Secret-free, frozen, `extra="forbid"`. |
| Config | `config.py` | Authoritative parse of the `MODEL_RUNTIME_*` env surface; fail-closed on missing/unsafe configuration. |
| Registry | `shared/model_governance/generated_model_registry.py` | Canonical harness model catalog (generated, never hand-edited). |

### Routing modes (ADR-008 D4)

`routing/engine.py` selects a model according to one of four modes:

- `auto` — the harness picks the best model for the task from the registry
  (preferring `recommended`, then `stable`), filtered by the request's
  entitlement allowlist when present.
- `tenant_default` — the tenant-configured default model.
- `explicit` — the operator/tenant requests a specific model id.
- `policy_required` — a policy mandates a specific model; **strict**. A denied
  or unmandated policy route raises rather than silently routing elsewhere.

### Fail-closed entitlements

Every route is subject to **entitlement checks** (is this model/policy
entitled for this tenant?). When a requested route is unavailable,
misconfigured, not entitled, or over budget, the router engages a fallback
chain and records the decision. `policy_required` is strict and never falls
back silently. The selected route and every fallback decision are recorded
for audit and observability.

### Task profiles

Task profiles bind a model role, routing policy, guardrails, output kind, and
latency/cost bounds to named harness tasks (canonical task profile registry, a
generated artifact). A newly added provider or task profile is invisible until
an operator enables it and a tenant is entitled.

### Credentials

Per-tenant LLM credentials live in the existing `CredentialBackend`
(`shared/credentials/interface.py`), **not** a new credential system and not
process env vars. Backends: `in_memory` (dev/test only), `env` (deploy-time
injected), AWS Secrets Manager scoped `aether/credentials/{tenant_id}/{ref}`
(production), or `disabled`. Staging/production fail closed to `env` or
`aws_secrets` — never `in_memory`/`disabled` (ADR-008 D5). Only masked,
secret-free `CredentialMetadata` ever leaves the backend; the provider client
is built at call time and released immediately.

### Observability

Metrics (calls, tokens, latency, cost, provider errors, verification outcomes,
circuit-breaker state), health/readiness endpoints for the runtime and each
provider adapter, circuit breakers per provider/tenant, canary
model/providers, and runbooks. **Staging and production fail closed on missing
credentials or missing/unsafe configuration** — a misconfigured adapter must
degrade the request, never silently bypass policy.

### Grounded context

`context/evidence.py` implements retrieval-before-synthesis (D6): Aether
retrieves a tenant-scoped, freshness-bounded evidence set; the model
synthesizes **only** from that evidence. Every claim carries evidence
references; claims the model cannot ground are marked unsupported. Evidence
fields reject credential-shaped content (provider API-key prefixes, AWS access
keys, auth tokens, PEM blocks, auth headers) at the field layer via
`EvidenceUnsafe`.

## 3. Deployment requirements

The runtime reads the `MODEL_RUNTIME_*` variables below; the authoritative
parse lives in `config.py`. Staging/production **fail closed**: missing
required configuration, or an unresolvable credential backend, causes the
runtime to refuse to serve and to log an explicit startup error rather than
falling back to an insecure default.

| Variable | Default | Required | Fail-closed behavior |
|---|---|---|---|
| `MODEL_RUNTIME_ENABLED` | `false` | Production: set `true` to expose (D9 feature gate) | `false` keeps the runtime inert and unreachable; safe default |
| `MODEL_RUNTIME_DEFAULT_PROVIDER` | `deterministic` | Production: set a real provider — production MUST NOT be `deterministic` | `deterministic` yields fixed responses; unacceptable in production |
| `MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS` | `800` | Optional (per-request token budget for routing) | Excess budget raises `ModelBudgetExceeded`; fails the call, never overdraws |
| `MODEL_RUNTIME_MAX_PROVIDERS` | `16` | Optional (max providers considered per routing decision) | Bounds routing fan-out |
| `MODEL_RUNTIME_CREDENTIAL_BACKEND` | `in_memory` | **REQUIRED IN PRODUCTION** — must be `env` or `aws_secrets` | `in_memory` in staging/production is a startup error; runtime refuses to serve |
| `MODEL_RUNTIME_CREDENTIAL_AWS_REGION` | — | **REQUIRED IN PRODUCTION** when backend is `aws_secrets` | Missing region with `aws_secrets` is a startup error |
| `MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX` | `aether/credentials` | Production: pin to the managed prefix | Secrets must stay under the governed prefix, never a custom hole |
| `MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS` | `60` | Optional (credential resolution cache TTL) | Cache stores secret-free `CredentialMetadata` only |
| `MODEL_RUNTIME_OBSERVABILITY_ENABLED` | `false` | Production: set `true` (metrics/circuit telemetry) | `false` disables telemetry; keep OFF locally |
| `MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD` | `5` | Optional (consecutive failures before a provider trips) | Tripped provider degrades the request; never silently bypasses policy |
| `MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S` | `60` | Optional (seconds before a tripped provider retries) | Recovery is time-boxed and re-trips on repeat failure |
| `MODEL_RUNTIME_ADAPTERS_DIR` | `services/model_runtime/adapters` | Optional (provider adapter registry directory) | Only providers in this directory are loadable |

Secrets are **never** declared in `.env` files — the `MODEL_RUNTIME_COMPAT_*`
and `MODEL_RUNTIME_DETERMINISTIC_*` provider-level overrides are the only
credential-bearing surface, and they are deploy-time injected (env or AWS
Secrets Manager), never committed. Key rotation is handled entirely by the
secret backend.

## 4. Security model

The following are **binding** for every deployment, adapter, and surface:

- **Credentials never in code, logs, prompts, or frontends.** No API key,
  authorization header, raw secret value, secret-manager payload, or provider
  request body with restricted tenant data is ever logged. Only masked,
  secret-free `CredentialMetadata` leaves the backend.
- **The model never receives database authority.** The model may propose only
  allowlisted structured plans/tools; Aether executes all retrieval through its
  own repositories. No raw SQL/Gremlin/Cypher/GraphQL/arbitrary HTTP/tool
  execution by the model.
- **Tenant scope is server-authoritative.** The model must never select or
  override tenant scope; cross-tenant evidence leakage is forbidden. A routing
  decision can never widen tenant scope.
- **Staging/production fail closed** on missing credentials or missing/unsafe
  configuration. A misconfigured adapter degrades the request — it never
  silently bypasses policy.
- **Feature flags default OFF** (D9). No harness surface is reachable without
  an explicit capability grant; newly added providers/task profiles are
  invisible until an operator enables them and a tenant is entitled.

## 5. Operational runbooks

The runtime's operational surface (deploy, health/readiness, circuit-breaker
response, credential rotation, canaries, incident response) is covered by the
deployment and observability runbooks:

- Deployment guide: [`../../deploy/model-runtime/README.md`](../../deploy/model-runtime/README.md)
- Observability runbooks: [`../../deploy/observability/`](../../deploy/observability/)

For the design and security rationale, see
[ADR-008 — Multi-Model Intelligence Harness](../decisions/ADR-008-multi-model-intelligence-harness.md).

## References

- `Backend Architecture/aether-backend/services/model_runtime/config.py` —
  authoritative `MODEL_RUNTIME_*` env parse.
- `Backend Architecture/aether-backend/services/model_runtime/service.py` —
  runtime orchestration seam.
- `Backend Architecture/aether-backend/services/model_runtime/routing/engine.py` —
  routing modes, entitlements, fallback.
- `Backend Architecture/aether-backend/services/model_runtime/credentials/interface.py` —
  per-tenant credential resolution seam.
- `Backend Architecture/aether-backend/services/model_runtime/context/evidence.py` —
  grounded-synthesis evidence models.
- `docs/decisions/ADR-008-multi-model-intelligence-harness.md` — decisions D1–D9.
