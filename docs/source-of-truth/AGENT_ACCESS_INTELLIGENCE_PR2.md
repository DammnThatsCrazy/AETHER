# Agent Access Intelligence — PR 2 Capability Catalog, Authority & Governance

**Release train:** `AGENT_ACCESS_INTELLIGENCE`
**Scope:** PR 2 — capability catalog, software identity, authority/policy, and runtime
governance for observed external agent access (monoprompt §9). Branches from PR 1's merged
`main`.
**Status:** Phases A, B1, B2 and C are implemented and land as **multiple commits on one
branch**, merging once. Phase A merged in #485; B1, B2 and C are on
`claude/new-session-wqo13a`. Ledger items `AAI-2-*` — each remains
`implementation_in_progress` with an explicit exception rather than a terminal status,
because `make ci-check` green is not the same as production evidence and
`scripts/production_status.py` is the only thing that may say otherwise.

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
  B1 (authority + `capability.invoke` policy) is shipped; B2 is not.
- **Phase C — `AAI-2-SHADOW-DRIFT`, `AAI-2-BLAST-RADIUS`:** drift findings and bounded
  blast-radius (preserving `unknown`/`missing_inputs`, never reporting unknown exposure as
  zero). Shipped — see §6b.

---

## 6a. Phase B build contract — `AAI-2-AUTHORITY-POLICY`

**B1 and B2 are both shipped.** B1: `authority.py`, `authority_routes.py`,
`policy_engine.py::check_capability_invocation`. B2: `identity.py`, `declarations.py`,
`declaration_routes.py`, `scanning.py`, migration `20260806_capability_declarations`.
The B2 subsection below now describes shipped code; §6b covers Phase C.

Phase B lands as **two commits on the same branch**: **B1 authority + capability-aware policy
decisions** (§9.6/§9.7), then **B2 artifact/publisher identity + tool-schema scanning + the
declared side that §9.5 drift compares against**. The seam is deliberate: B1 needs no new table,
no migration, no storage-policy or DSR-plan change, and no new event type — it reuses machinery
that already exists. B2 introduces the *declared* record, which is genuinely net-new state.

### B1.1 — A capability authorization **is** a delegation (no sixth grant concept)

The backend already carries five independent grant concepts (`delegations`,
`commerce_entitlements`, `commerce_grants`, `consent_receipts`, break-glass). Adding a sixth
would be the wrong answer. `repositories/repos.py::DelegationRepository` already provides
exactly the required semantics — tenant-scoped, time-bound (`starts_at`/`ends_at`), revocable
(`revoke()` → `revoked_at` + `revoked_by_entity_id`), Redis-cached `active_for()` with
invalidation on grant/revoke, and a `DelegationProjector`
(`services/profile360_workers/workers.py:218`) that mirrors lifecycle to the graph off
`DELEGATION_CREATED`/`DELEGATION_REVOKED`.

**Therefore a capability authorization is stored as a row in `delegations`**, written by
`CapabilityAuthorizationRepository(DelegationRepository)`, which adds capability-typed
**top-level** (therefore `find_many`-filterable — `BaseRepository` filters `data->>'key'`, top
level only) fields and stamps `authorization_kind: "capability"` so the generic delegation
surface and the capability surface never mistake each other's rows.

Scope encoding, evaluated by the existing `services/delegation/engine.py::DelegationEngine`:

| Grant shape | `scope.actions` | `scope.resources` |
|---|---|---|
| one capability | `["invoke"]` | `["capability:{capability_id}"]` |
| every capability on one server | `["invoke"]` | `["capability-server:{server_ref}"]` |

`server_ref` = `srv_` + `sha256(f"{tenant_id}\|{server_key}")[:24]` (same style as `cap_`/`inst_`).
A digest — not the raw server name/URL — is used as the resource token so a `:` or `*` inside a
server URL can never widen a scope through `DelegationEngine._resource_matches`' glob. The
human-readable `server_name`/`server_url` are stored as separate top-level fields on the row.

The policy check tries the specific resource first, then the server-wide one. Two `evaluate`
calls, one cached `active_for` read.

**Fail-closed invariants (each has a test):**
1. `scope.resources` is **never** empty — `DelegationEngine` treats an empty `resources` list as
   *match everything* (`engine.py`: `resource_ok = not resources or any(...)`). A capability
   authorization with no resources would silently authorize every resource in the tenant, through
   the generic `/v1/delegations/validate` surface as well.
2. `*` is rejected in both `actions` and `resources`. Capability authority is never wildcard.
3. `actions` is exactly `["invoke"]`.
4. Reads/revokes compare `tenant_id` and raise `NotFoundError` on mismatch — no cross-tenant
   existence leak.
5. Granting for a `capability_id` that is not in the tenant's catalog is **allowed** but recorded
   as `capability_observed: false` — authorizing ahead of first observation is legitimate, and
   the flag is the seed of the B2 declared-vs-observed comparison. It is never silently
   upgraded to `true`.

**No approval queue is invented.** `POST /v1/capability-authorizations` is itself the
permission-gated authorizing act (`tenant.require_permission("write")`, audited). A multi-party
pending→approved workflow already exists for spend classes
(`services/x402/approvals.py`, live router in `services/x402/commerce_routes.py`); if capability
authority ever needs one it routes through that service. Phase B does **not** clone it, and does
**not** define a `pending` state that nothing produces. Authorization state is derived from the
row — `active` / `revoked` / `expired` — never stored as a field that can disagree with it.

⚠️ Do **not** add endpoints to `services/x402/approvals_routes.py`: it declares
`prefix="/v1/approvals"` but is never mounted in `main.py`. The live approvals router is the
one in `services/x402/commerce_routes.py`.

### B1.2 — Capability-aware policy decisions **extend** `PolicyEngine`

`services/security/policy_engine.py` is the engine that HTTP routes genuinely reach at request
time. Its documented extension convention is: add one `async def check_*(...) -> PolicyDecision`
method that builds decisions via `self._decision(...)` and routes them through `self._finalize(...)`,
and add the new `policy_key` to `_SENSITIVE_KEYS` when decisions must persist even when allowed.
Phase B follows exactly that — **no new engine, no new decision model, no new decision table.**

New method `check_capability_invocation(...)`, `policy_key="capability.invoke"`, added to
`_SENSITIVE_KEYS` so every decision (allow or deny) lands in `security_policy_decisions` and the
shared audit ledger. That persistence is what makes `GET /v1/capability-policy/decisions` a real
evidence surface rather than a stub.

Verdict rules — deny on any of, in order:

| Condition | `reason` | `required_action` |
|---|---|---|
| capability not in the tenant inventory | `capability not in tenant inventory` | observe or authorize it explicitly before invocation |
| no `agent_id` on the request | `invoking agent is unidentified` | attribute the invocation to an agent |
| no active authorization for (agent, capability) | `no active capability authorization` | grant one via `POST /v1/capability-authorizations` |

Otherwise allow. **`latest_risk_level` does not change the verdict.** There is no policy source
in the repo that says "block high risk", and inventing a threshold would be a fabricated control
that reads as real. The observed risk level is carried in the decision's audit metadata and in
the evaluate response as context; risk-driven findings are Phase C.

`_decision()` forces `severity='info'` on any allowed decision — that is pre-existing shared
behavior across every policy in the engine and is **not** changed here.

### B1.3 — Surface, and what stays untouched

| Route | Method | Gate |
|---|---|---|
| `/v1/capability-authorizations` | `GET` list, `POST` grant | `require_permission("read"/"write")` |
| `/v1/capability-authorizations/{authorization_id}` | `GET` | `read`, fail-closed tenant match |
| `/v1/capability-authorizations/{authorization_id}/revoke` | `POST` | `write`, fail-closed tenant match |
| `/v1/capability-policy/decisions` | `GET` | `read`, tenant-scoped `list_decisions` |
| `/v1/capability-policy/evaluate` | `POST` | `read` — evaluation is non-mutating and must not require write |

`config/route_registry.yaml` `known_prefixes` gains `/v1/capability-authorizations` and
`/v1/capability-policy` (2-segment-prefix classifier; omission fails
`tests/unit/test_route_registry_coverage.py`). Routers mount in `main.py`'s `include_router`
block beside the Phase A routers.

Lifecycle events reuse the existing `Topic.DELEGATION_CREATED` / `Topic.DELEGATION_REVOKED` —
these rows *are* delegations, the `DelegationProjector` already converges them, and reusing the
topics means **no `event-registry.json` change and no contract-generation churn**.

**Unchanged by B1:** no alembic migration, no `storage_policies.yaml` block (the `delegations`
table is pre-existing), no projector-ownership artifacts, no new event type, no second policy
engine, no edit to PR 3's provider adapters.

**Known pre-existing gap, closed here:** `shared/privacy/retention.py::DeletionPlan.build_standard_plan`
has **no step for `delegations`** — a subject's delegations survive their erasure today, and
capability authorizations would inherit that gap. B1 adds erasure steps for the table on both
`grantee_entity_id` and `grantor_entity_id` and wires the repository into `store_adapters`. This
changes DSR behavior for pre-existing delegation rows too; that is the point, and it is called
out as a deliberate behavioral change rather than buried.

### B2 — declared identity, scanning, drift inputs (second commit)

- **§9.3 artifact/publisher identity.** No publisher/provenance/SBOM concept exists in the
  backend (`services/sdk_config/service.py`'s HMAC-signed SDK manifest is for *our own* SDK, not
  third-party MCP servers). Nothing in the system can cryptographically verify a third-party
  capability's publisher, so **no `verified` state is offered** — offering one would be a
  fabricated assurance. B2 derives what is honestly derivable: a `publisher_ref` from the
  sanitized `server_url` host (falling back to `provider`), and an `artifact_digest` over the
  capability's identity tuple so a *change* in identity is detectable even when its origin is
  unverifiable. States are `observed_only` / `declared` / `drifted`.
- **§9.4 tool/schema scanning.** The ingestion scrubber (`services/ingestion/validation.py::scrub_sensitive_fields`)
  is **key-name based** and inspects no values; `services/security/contracts.py::sanitize_metadata`
  is the only value-aware redactor. Nothing scans tool names/schemas. B2 adds pure-function
  scanning over observed capability identity (credential-bearing URL, non-TLS scheme, private/
  loopback host reusing `policy_engine._is_unsafe_destination`, injection-shaped tool names
  reusing `services/noesis/models.py::INJECTION_PATTERNS`) producing findings — **no new severity
  enum**; it reuses `services/agentic_observability/models.py::RiskLevel`.
- **§9.5 declared-vs-observed drift.** B2 adds the declared side
  (`capability_declarations`); the drift **findings surface** is Phase C, §6b.

### B2 as built — three corrections worth recording

The digest and the declared row must be comparable, and two defects made them not be:

1. `_identity_tuple` originally stringified enum members naively. For
   `CapabilityKind(str, Enum)`, `str(member)` is `"CapabilityKind.MCP_TOOL"` while the
   stored row (`model_dump(mode="json")`) and every declaration hold `"mcp_tool"`. The
   digest written at upsert therefore disagreed with one recomputed from the row's own
   stored fields, and no declaration could ever match — Phase C would have reported the
   entire declared inventory as `drifted`. Enum values are unwrapped before stringifying.
2. `catalog_service._sanitize_server_url` leaked credentials for schemeless URLs.
   `urlsplit` treats everything before the first `:` as a scheme even with no `://`
   following, so `user:pass@mcp.example.com/v1` parsed as `scheme="user"` with an **empty**
   netloc: the userinfo strip found nothing and the credential was persisted verbatim into
   a durable, operator-readable catalog row. Schemeless input is now parsed under a
   synthetic authority so the same stripping and query redaction run for both shapes;
   opaque server names and `host:port` values are unchanged.
3. `INSECURE_TRANSPORT` fired on `wss://`. MCP servers are commonly reached over WebSocket
   and `wss` **is** TLS, so `_TLS_SCHEMES` is `{https, wss}`; `ws` and `http` stay out.

Identity is computed from the **merged** record (new observation falling back to the stored
row), not the incoming fact alone — otherwise a later observation that simply omits
`protocol_version` changes the digest and manufactures drift that nothing actually drifted.
The identity tuple is explicitly enumerated rather than derived from the record dict, so
adding an unrelated field (`observation_count`, `last_seen_at`) cannot invalidate every
stored digest at once.

## 6b. Phase C build record — `AAI-2-SHADOW-DRIFT`, `AAI-2-BLAST-RADIUS`

`risk_service.py` + `risk_routes.py`, prefix `/v1/capability-risk`, both routes
`require_permission("read")`. No new table, no migration, no event type — Phase C reads the
stores A/B1/B2 already own.

**`GET /findings`** merges scan findings with identity drift.
`observed_only` is deliberately **not** a finding: an undeclared capability is the normal
state in a system whose entire premise is observing things nobody declared, and reporting
it as a finding would make the surface useless on day one. It is carried in the counts.

**`GET /blast-radius`** — the honesty rule, which is the whole point of the endpoint:

| condition | response |
|---|---|
| any required input absent | **every** count `null`, `exposure_known: false`, `missing_inputs` names each absent input, `summary` states exposure is unknown |
| all inputs present | real counts, including a genuine `0` where zero was actually computed |

Partial totals are never emitted — a partial number reads as a complete one. Authorization
uses `capability_authority_service.resolve()` per (agent, capability) pair rather than
listing grants, because a list-and-match would miss server-wide `capability-server:` grants.
Past 200 pairs the split is reported as `null` with an explicit
`capability_authorizations:check_truncated` marker rather than a guessed number. A test
walks the entire response recursively and fails on any zero-valued number (bools excluded,
since `False == 0`), so a future field cannot reintroduce the lie.

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
