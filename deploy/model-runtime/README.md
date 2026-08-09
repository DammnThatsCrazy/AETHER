# Aether Model Runtime — Deployment Guide

This guide documents how to deploy the **Multi-Model Intelligence Harness**
(`Backend Architecture/aether-backend/services/model_runtime`), the
provider-neutral model runtime introduced by ADR-008. It covers the runtime
model, the `MODEL_RUNTIME_*` configuration surface, fail-closed startup
behavior, credential management, observability, and the differences between
local, staging, and production.

## 1. Overview

The model runtime is Aether's provider-neutral multi-model harness. It treats
LLMs as interchangeable engines behind a single `AsyncModelProvider` contract
(`services/model_runtime/provider.py`): provider routing, task profiles,
per-tenant credentials, grounded retrieval context, verification, and
observability all live in-process and independent of any provider SDK. OpenAI
and Anthropic ship as isolated adapters; additional providers (OpenAI-compatible
endpoints, Kimi-family, Bedrock, self-hosted) plug in as adapters without
touching orchestration logic.

The harness is an **additive, read-only extension of Noesis**. Noesis's
deterministic classification and read-only intent + repository-dispatch
architecture remain authoritative; the harness layers model routing and
synthesis on top. It does not replace the intelligence graph, the graph
mutation gateway, the entity/identity model, consent authority, the audit
ledger, the credential platform, or the frontend boundaries it extends. See
`docs/decisions/ADR-008-multi-model-intelligence-harness.md`.

## 2. Runtime model

The model runtime is **one service**: the aether-backend application with the
`model_runtime` package enabled. It is **not** N separate per-provider
services.

- The deployment unit is the existing aether-backend process; `model_runtime`
  is a library package loaded by that process at startup.
- Provider adapters are **in-process** modules under
  `services/model_runtime/adapters/`. There is no per-provider container,
  sidecar, or separately deployed adapter service.
- `MODEL_RUNTIME_ADAPTERS_DIR` points at the directory whose modules are
  registered into the runtime's provider registry at startup.
- Because adapters are in-process, a misconfigured adapter degrades the request
  (fail-closed) instead of silently bypassing policy — there is no "unhealthy
  sidecar" path around it.

Run the harness service locally or in staging:

```bash
cp deploy/model-runtime/.env.example deploy/model-runtime/.env
docker compose -f deploy/model-runtime/docker-compose.model-runtime.yml up
```

The manifest builds the aether-backend image (the runtime runs inside that
single service, D5) and passes `MODEL_RUNTIME_*` through from the deploy-scoped
`.env`. Nothing is inlined in the manifest (D9), and the service fails closed
(`ConfigError`) when required configuration is missing.

## 3. Environment variables

All runtime configuration is read from the `MODEL_RUNTIME_*` environment
surface. The authoritative parse and validation live in
`services/model_runtime/config.py`. Two templates exist: the `=== Model Runtime
===` block of the repo-root `.env.example` (production annotations) and the
deploy-scoped `deploy/model-runtime/.env.example` (copied to
`deploy/model-runtime/.env` and passed to the service by the compose manifest).
Never embed the values in source.

| Variable | Default | Meaning | Production requirement |
|---|---|---|---|
| `MODEL_RUNTIME_ENABLED` | `false` | Master feature gate (ADR-008 D9: default OFF) | `true` to serve harness traffic; remains OFF until cutover |
| `MODEL_RUNTIME_ADAPTERS_DIR` | `services/model_runtime/adapters` | Directory of in-process provider adapter modules loaded into the registry | Must exist and be readable at startup |
| `MODEL_RUNTIME_DEFAULT_PROVIDER` | `deterministic` | Provider used when no routing/provider override is selected | **MUST NOT be `deterministic`** — that is the local test fallback only |
| `MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS` | `800` | Per-request token budget reserved before invocation | Positive integer; tune per task profile |
| `MODEL_RUNTIME_MAX_PROVIDERS` | `16` | Maximum providers considered per routing decision | `>= 1` |
| `MODEL_RUNTIME_CREDENTIAL_BACKEND` | `in_memory` | Credential backend: `env`, `aws_secrets`, `in_memory`, `disabled` | **REQUIRED**: must be `env` or `aws_secrets`; never `in_memory` or `disabled` |
| `MODEL_RUNTIME_CREDENTIAL_AWS_REGION` | *(none)* | AWS region addressing Secrets Manager | **REQUIRED when** `MODEL_RUNTIME_CREDENTIAL_BACKEND=aws_secrets` |
| `MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX` | `aether/credentials` | Secrets Manager prefix for provider credentials | Scoped to the runtime's credentials path |
| `MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS` | `60` | TTL for the masked credential-metadata cache | `> 0` |
| `MODEL_RUNTIME_OBSERVABILITY_ENABLED` | `false` | Enables metrics / health / circuit-breaker telemetry | `true` in staging and production |
| `MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD` | `5` | Consecutive failures before a provider circuit opens | `>= 1` |
| `MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S` | `60` | Seconds a circuit stays OPEN before a half-open probe | `>= 0` |

## 4. Fail-closed startup behavior

Staging and production **fail closed** on missing/unsafe configuration and on a
non-secure credential backend. The startup validator raises `ConfigError` and
the service refuses to start rather than falling back to an insecure default.

| Misconfiguration | Startup behavior |
|---|---|
| `MODEL_RUNTIME_ENABLED=true` with `MODEL_RUNTIME_CREDENTIAL_BACKEND=in_memory` (staging/production) | Refuse to start — `ConfigError`. `in_memory` is dev/test-only; a non-secure backend never backs a live runtime. |
| `MODEL_RUNTIME_CREDENTIAL_BACKEND=disabled` | Refuse to start — `ConfigError`. `disabled` is the dev no-op; production requires a resolvable backend. |
| `MODEL_RUNTIME_CREDENTIAL_BACKEND=aws_secrets` without `MODEL_RUNTIME_CREDENTIAL_AWS_REGION` | Refuse to start — `ConfigError`. A region is required to address Secrets Manager. |
| `MODEL_RUNTIME_DEFAULT_PROVIDER=deterministic` (staging/production) | Refuse to start — `ConfigError`. The deterministic provider is the local test fallback only. |
| `MODEL_RUNTIME_ADAPTERS_DIR` missing or unreadable | Refuse to start — `ConfigError`. The provider registry cannot be built. |
| Unparseable or out-of-range values (e.g. cache TTL `<= 0`, failure threshold `< 1`) | Refuse to start — `ConfigError`. |
| Credential backend unreachable or unhealthy at runtime | Request-time fail-closed: resolution reports `configured=False`; readiness surfaces a blocker; while the credential gate is enabled the runtime refuses to serve. |
| A provider circuit is OPEN | Fast-fail: calls to that provider/tenant are rejected immediately while OPEN; a single half-open probe is allowed after the recovery timeout. |
| `MODEL_RUNTIME_ENABLED=false` (default) | Runtime boots inert — no harness surface reachable, no startup errors. |

**Enabled default OFF (D9):** every harness feature ships behind a feature flag
default OFF. `MODEL_RUNTIME_ENABLED=false` is the safe default in every
environment; staging and production flip it on only as part of cutover, after
the credential gate is enabled.

## 5. Credential management (ADR-008 D5)

Per-tenant LLM credentials resolve through the existing
`shared.credentials.CredentialBackend` platform — never a new credential
system, and never keys hard-coded into source or the image.

- **Backends** (selected by `MODEL_RUNTIME_CREDENTIAL_BACKEND`):
  - `env` — process-env injected at deploy time (fast path).
  - `aws_secrets` — AWS Secrets Manager scoped to
    `{MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX}/{tenant_id}/llm/{provider}` in the
    region `MODEL_RUNTIME_CREDENTIAL_AWS_REGION`.
  - `in_memory` / `disabled` — dev/test only; **rejected at startup in
    staging/production**.
- **Only masked metadata surfaces.** Every read returns a secret-free
  `CredentialResolution` / `CredentialMetadata`; the raw secret payload is
  never fetched, returned, cached, or logged.
- **Cache** (`MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS`): the in-memory
  `CredentialCache` stores only masked metadata, TTL-bounded; raw keys never
  enter it.
- **Rotation and revocation:** rotation issues a new masked version and
  invalidates the cache only after a successful source rotation; revocation
  fails closed and evicts the cached entry so a revoked credential is never
  served.
- **Never log or embed keys.** No API keys, authorization headers, or raw
  secret material appear in logs, metrics, prompts, source, or this guide. The
  credential models layer rejects any value matching the redaction patterns
  before it can cross a trust boundary.

## 6. Observability (ADR-008 D8)

`MODEL_RUNTIME_OBSERVABILITY_ENABLED=true` turns on the harness telemetry
surfaces:

- **Metrics** — canonical counters emitted by the runtime recorder:
  `model_runtime_calls`, `model_runtime_tokens_input`,
  `model_runtime_tokens_output`, `model_runtime_latency_ms`,
  `model_runtime_cost_usd`, `model_runtime_provider_errors`,
  `model_runtime_verification_failures`, `model_runtime_verification_passes`,
  `model_runtime_circuit_open`, `model_runtime_circuit_closed`,
  `model_runtime_routes`, `model_runtime_budget_exceeded`,
  `model_runtime_credential_rejections`. Labels carry only
  provider/model/mode/status/error_type — never request content, tenant data,
  or credentials.
- **Health** — `ProviderHealth` / `RuntimeHealth`: configured-based liveness
  per adapter. Probes never invoke `complete` and never block on the network.
- **Readiness** — `RuntimeReadiness`: the serve-traffic gate. Configuration and
  runtime health fail closed unconditionally; missing credentials are always
  reported as a blocker and flip readiness to False while the fail-closed
  credential gate is enabled (the staging/production cutover).
- **Circuit breakers** — per provider/tenant (`CircuitRegistry`), with
  CLOSED / OPEN / HALF_OPEN states. While OPEN, calls are rejected immediately
  (fail-closed) until the recovery timeout grants a single half-open probe.
  Tuned by `MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD` and
  `MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S`.

**Consumption:** the aether-backend metrics endpoint is scraped by Prometheus
and surfaced in Grafana using the existing `deploy/observability` stack; alert
rules can key off `model_runtime_circuit_open` and
`model_runtime_credential_rejections`. See `deploy/observability/README.md`.

## 7. Local vs staging vs production

| | Local (dev) | Staging | Production |
|---|---|---|---|
| `MODEL_RUNTIME_ENABLED` | `false` (default) | `true` at cutover | `true` |
| `MODEL_RUNTIME_CREDENTIAL_BACKEND` | `in_memory` / `disabled` OK | `env` or `aws_secrets` | `env` or `aws_secrets` |
| `MODEL_RUNTIME_CREDENTIAL_AWS_REGION` | n/a | required when `aws_secrets` | required when `aws_secrets` |
| `MODEL_RUNTIME_DEFAULT_PROVIDER` | `deterministic` OK | must not be `deterministic` | must not be `deterministic` |
| `MODEL_RUNTIME_OBSERVABILITY_ENABLED` | `false` | `true` | `true` |
| Credential fail-closed gate | off | **on** | **on** |

Exact startup gates (enforced by `services/model_runtime/config.py`):

- **Every environment:** the feature flag defaults OFF, so
  `MODEL_RUNTIME_ENABLED=false` boots the runtime inert with no startup errors.
- **Staging:** `MODEL_RUNTIME_ENABLED=true` engages the fail-closed validator.
  Startup refuses (`ConfigError`) when the credential backend is not
  `env`/`aws_secrets`, when `aws_secrets` lacks a region, when the default
  provider is `deterministic`, or when any required value is missing or unsafe.
  The credential fail-closed gate is turned on so missing credentials block
  readiness. The staging environment block is provisioned by the staging
  Terraform profile
  (`AWS Deployment/aether-aws/terraform/profiles/staging.tfvars`).
- **Production:** identical validator checks, hardened by the production
  deployment profile (`config/deployment_profiles.yaml`) and the production
  Terraform profiles
  (`AWS Deployment/aether-aws/terraform/profiles/production-*.tfvars`). No
  insecure credential backend is accepted; `deterministic` is always rejected.

## 8. References

- `docs/decisions/ADR-008-multi-model-intelligence-harness.md` — the design
  decision record (D5 credentials, D8 observability, D9 flags-off).
- `Backend Architecture/aether-backend/services/model_runtime/` — the runtime
  package (service, adapters, credentials, routing, task_profiles, context,
  observability).
- `.env.example` (`=== Model Runtime ===` block) — the canonical env template.
- `deploy/observability/README.md` — Prometheus / Grafana / Loki / Alertmanager
  stack that consumes the runtime metrics.
- `config/deployment_profiles.yaml` and
  `AWS Deployment/aether-aws/terraform/profiles/` — canonical staging and
  production deployment profiles.
