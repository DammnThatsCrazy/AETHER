# Agent Access Intelligence — PR 2 Capability Catalog, Authority & Governance

**Release train:** `AGENT_ACCESS_INTELLIGENCE`
**Scope:** PR 2 — capability catalog, software identity, authority/policy, and runtime
governance for observed external agent access (monoprompt §9). Branches from PR 1's merged
`main`.
**Status:** partial / in progress. Landing incrementally as multiple commits on one branch
(the full PR merges once, at the end). Ledger items `AAI-2-*`. No completion evidence is
claimed for un-shipped phases.

This document is the source of truth for **how observed agent access is turned into a
tenant-scoped capability inventory, and how authority/policy/governance extend the existing
engines** — it does not assert any phase is production-ready beyond what
`scripts/production_status.py` supports.

---

## 1. Product boundary (monoprompt §9 "Parallel ownership")

PR 2 **owns**: the capability catalog + domain services, directory/listing/review lifecycle,
package/version/artifact identity, installations/connections, authorization grants /
delegations / approvals / revocations, **extensions** to the existing policy-decision service,
shadow-capability discovery, capability drift + blast-radius, private enterprise catalogs, and
the related backend APIs / repositories / migrations / tests / docs.

PR 2 **must not** edit the provider adapters owned by PR 3 (`services/interop/providers/*`,
`services/agentic_observability/provider_framework.py` and its packs) except shared interfaces
already established in PR 1. PR 2 consumes PR 1 contracts; it does not add net-new
provider-neutral event types (those are deferred to `AAI-3-PROVIDER-FRAMEWORK`).

---

## 2. Architectural decision — the catalog is a *maintained materialization*, not a projector

The observed capability data already lands in `silver_agent_execution_facts` (PR 1's canonical
target). Two facts, verified against the code, drive the design:

1. **A capability catalog is a table→table derivation.** Silver `BaseProjector`s are
   **Bronze-event-driven** (`project(event) -> ProjectionResult`); the dispatcher has no
   mechanism to feed a projector rows from a silver table. Forcing a dispatcher projector in
   would touch four CI-guarded artifacts (`dispatcher.py::_ALL_PROJECTORS`,
   `projector-ownership-registry.json`, generated `services/silver/generated_ownership.py`,
   `scripts/validate_projector_ownership.py`) — the #1 CI risk from PR 1 — for no benefit.
   A **plain derived read-model / repository is invisible to the projector-ownership CI** and
   is the correct fit. Precedents: `services/provider_catalog/*`, `services/comms/repository.py`,
   `services/measurement/repositories/touchpoint_repo.py`.

2. **The queryable fields live in `payload` JSONB, camelCase.** `silver_agent_execution_facts`
   has only 9 typed agent columns (`agent_id, task_id, model_id, prompt_tokens,
   completion_tokens, cost_usd, outcome, grounding_sources, human_override`). The generic writer
   (`services/silver/writer.py::SilverFactWriter._persist_generic`) **drops row keys that have
   no column**, so `tool_name/server_name/server_url/provider/protocol_version/risk_level/…` are
   **not** typed columns — they survive only inside `payload` (= the event `properties`) under
   **camelCase** keys (`toolName, serverName, serverUrl, protocolVersion, provider, riskLevel,
   agentId, …`). The generic silver *read* path (`AnalyticsRepository.query_silver`) is
   effectively a stub, so read-time aggregation over the silver table is not viable.

**Therefore:** PR 2 maintains its own persisted tables (`capability_catalog`,
`capability_installations`) and upserts them from the agent-execution fact stream via an
**out-of-band, fire-and-forget dispatcher hook that mirrors `SilverGraphProjector.maybe_emit`**
(`services/silver/dispatcher.py`). The catalog service reads a fact row's snake_case top-level
keys first and falls back to `payload` camelCase — so it is correct whether fed a live
projection row (snake_case present) or a persisted/re-queried row (payload only). The catalog is
therefore **populated when the PR 1 canonical spine is enabled** (`AGENTIC_OBS_CANONICAL_SPINE_ENABLED`),
consistent with PR 1's gating.

---

## 3. API surface & the `/v1/capabilities` collision

`GET /v1/capabilities` is **already owned** by `services/capabilities/` — a
**release/feature-surface discovery** endpoint the frontends use for nav-gating. It is
load-bearing and must not be repurposed. PR 2's capability *inventory* therefore lives under
unclaimed prefixes (a documented deviation from the monoprompt's literal path, chosen for
correctness over literalism):

| Monoprompt intent | PR 2 path | Phase |
|---|---|---|
| list capabilities | `GET /v1/capability-catalog` | A |
| capability detail (`/v1/capabilities/{id}`) | `GET /v1/capability-catalog/{capability_id}` | A |
| installations | `GET /v1/capability-installations`, `GET /v1/capability-installations/{id}` | A |
| operator catalog health / shadow | `GET /v1/kyber/capability-catalog/health` (+ `/shadow`) | A |
| authorizations + revoke | `GET /v1/capability-authorizations`, `POST /v1/capability-authorizations/{id}/revoke` | B |
| policy decisions / evaluate | `GET /v1/capability-policy/decisions`, `POST /v1/capability-policy/evaluate` | B |
| risk findings / blast radius | `GET /v1/capability-risk/findings`, `GET /v1/capability-risk/blast-radius` | C |

Route conventions (verified): tenant handlers take `request: Request`, read
`request.state.tenant` (`TenantContext`), call `tenant.require_permission("read")` and reject
`tenantId != tenant.tenant_id` with `ForbiddenError`. Kyber routes use
`Depends(require_kyber_operator)` (`services/security/request_context.py`) and filter every
cross-tenant query by explicit `tenant_id`. Responses use `APIResponse(data=…).to_dict()` /
`@api_response` (`shared/decorators.py`, `shared/common/common.py`). Routers are mounted in
`main.py`'s `include_router` block. `config/route_registry.yaml` `known_prefixes` gains
`/v1/capability-catalog` and `/v1/capability-installations` (classifier is 2-segment-prefix
based; `/v1/kyber/*` auto-classifies operator+audit+high).

---

## 4. Domain model (Phase A)

A **Capability** is a distinct observed external capability for a tenant, keyed by
`(tenant_id, provider, server_name|server_url, tool_name)`:

- identity: `capability_id` = `cap_` + `sha256(tenant|provider|server|tool)[:24]` (deterministic
  → idempotent upsert), `provider`, `server_name`, `server_url`, `tool_name`,
  `protocol_version`, `capability_kind` (`mcp_tool | provider_action | account | resource |
  unknown`, derived from the source event type — honest `unknown`, never faked).
- posture: `latest_risk_level` (observed, nullable), `discovery_state` (`observed`), and
  bounded provenance — `first_seen_at`, `last_seen_at`, `observation_count`,
  `sample_source_event_ids` (bounded most-recent display sample). `observation_count` is
  deduplicated over a **bounded** recent window of source-event ids (kept in a private field,
  separate from the display sample); a redelivery older than the window may be recounted — it
  is a bounded-window count, not exactly-once. Row identity is always exactly-once
  (deterministic id).
- `server_url` is credential-sanitized before it is persisted (userinfo stripped, sensitive
  query params redacted): the PR 1 ingestion scrubber is key-name based and does not sanitize
  secrets embedded in a URL *value*, and this store creates a durable row + tenant/operator
  read surface for the field.

A **CapabilityInstallation** is an agent↔server binding, keyed by
`(tenant_id, agent_id, server_name|server_url)`: `installation_id`, `agent_id`, `provider`,
`server_name`, `server_url`, `protocol_version`, `first_seen_at`, `last_seen_at`,
`observation_count`, `capability_ids` (bounded set of capabilities seen on this installation),
`status` (`active` while observed).

Money/quantity fields (Phases B/C exposure/notional) are decimal strings via
`decimal_str_from_provider`; never binary floats. Cross-currency rollups use
`services.value.safe_rollup`.

---

## 5. Persistence, DSR, and CI touchpoints

- **Service:** `Backend Architecture/aether-backend/services/agent_access_intelligence/`
  (`__init__.py`, `models.py`, `repositories.py`, `catalog_service.py`, `routes.py`).
- **Repos:** subclass `_ScopedRepo` (`services/security/repositories.py`) →
  `CapabilityCatalogRepository("capability_catalog")`,
  `CapabilityInstallationRepository("capability_installations")`. Dual Postgres/in-memory via
  `BaseRepository`/`_IN_MEMORY_STORES`; every read tenant-scoped by `filters={"tenant_id": …}`;
  single-record reads fail-closed (compare `tenant_id`, raise NotFound on mismatch — no
  cross-tenant existence leak).
- **Migration:** `alembic/versions/20260805_capability_catalog.py`,
  `revision="20260805_capability_catalog"`, `down_revision="20260804_traffic_ops"` (new sole
  head — single-head is CI-enforced by `scripts/validate_temporal_integrity.py`). `_TABLES` dict
  style (mirrors `20260722_trust_plane.py`): `id TEXT PK, tenant_id TEXT, <typed index cols>,
  data JSONB DEFAULT '{}'::jsonb, created_at, updated_at`, plus `ix_{table}_tenant` on
  `tenant_id`. Symmetric `downgrade()`.
- **storage_policies.yaml:** one `resource_type` block per table (bidirectional, fail-closed
  gate `scripts/release/check_storage_policies.py`), mirroring `economic_resources`:
  `retention_class: standard`, `delete_behavior: hard_delete`, `legal_hold_supported: true`,
  `requires_consent_invalidation: true` (subject-derived observations).
- **DSR / erasure:** map onto the existing `connector_derived_records` DSR component (no new
  `DSR_COMPONENTS` enum → no test churn); add `HARD_DELETE` steps for both tables in
  `shared/privacy/retention.py::DeletionPlan.build_standard_plan` (`entity_field="tenant_id"`)
  and wire the repos into `store_adapters`.
- **route_registry.yaml:** add `/v1/capability-catalog`, `/v1/capability-installations` to
  `known_prefixes` (satisfies `tests/unit/test_route_registry_coverage.py`).

`make ci-check` (`scripts/repo_doctor.py --ci`) must exit 0; `make repo-doctor-fix` regenerates
`docs/REPO-INDEX.md` (adds this doc) and generated docs.

---

## 6. Phasing → ledger mapping

- **Phase A — `AAI-2-CAPABILITY-CATALOG`:** the catalog + installations inventory, maintainer,
  read APIs, Kyber health, migration/storage/DSR, tests. (This document's shipped scope.)
- **Phase B — `AAI-2-AUTHORITY-POLICY`:** authorization grants / delegation / approval /
  revocation and capability-aware policy decisions, **extending** the existing engines
  (`services/security/policy_engine.py`, `services/security/access_control.py`,
  `services/policy/engine.py`, `services/consent/authority.py`) — **not** a second engine.
  §9.3 artifact/publisher identity + §9.4 tool-schema scanning + §9.5 declared-vs-observed drift.
- **Phase C — `AAI-2-SHADOW-DRIFT`, `AAI-2-BLAST-RADIUS`:** shadow detection, drift findings,
  and bounded blast-radius (preserving `unknown`/`missing_inputs`, never reporting unknown
  exposure as zero).

---

## 7. Verification

- `make ci-check` exits 0; `git status --short` clean after `make docs-fix`.
- Unit: `record_from_fact` upserts one capability + one installation; a replayed
  `source_event_id` (within the bounded dedup window) does not double-count, while a distinct
  new observation of the same capability increments `observation_count`, advances
  `last_seen_at`, and reuses the one row; camelCase-only `payload` still yields
  tool/server/provider; a credential-bearing `server_url` is sanitized before storage;
  private fields never leak to the API; cross-tenant read denied (fail-closed).
- Wiring: with `AGENTIC_OBS_CANONICAL_SPINE_ENABLED` on, an
  `agent_tool_invocation_observed` / `agent_mcp_connection_observed` observation flows through
  the spine and the dispatcher hook populates the catalog.
- Read APIs return the tenant inventory with working filters; Kyber route 403s for a
  non-operator tenant and aggregates cross-tenant with explicit tenant filtering.
- DSR: `build_standard_plan` includes both tables as `HARD_DELETE`; `delete_by_entity` erases a
  tenant's catalog + installations.
