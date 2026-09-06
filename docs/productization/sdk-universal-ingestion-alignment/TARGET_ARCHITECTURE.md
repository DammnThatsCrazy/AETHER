---
title: Target Architecture — SDK + Universal Ingestion Alignment
slug: productization/sdk-universal-ingestion-alignment/target-architecture
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Target Architecture

## Scope & role of this document

This is the canonical, governed home for the **SDK + Universal Ingestion Alignment**
target architecture — a curated rendering of the 34-section alignment blueprint.
The controlling artifact is the blueprint itself, now committed in-repo at
`docs/blueprints/sdk-universal-ingestion-alignment.md`; this page is the
repository's working reference to it. It exists so that future work has a single
place to anchor "how the repo must be organized around ingestion" without
re-deriving the boundary each time.

This page references — it does **not** recreate — the two decisions that already
encode parts of the boundary:

- **ADR-007 (domain canonicalization)** — `docs/decisions/ADR-007-domain-canonicalization.md`;
- **ADR-011 (observation-only execution invariant)** — `docs/decisions/ADR-011-observation-only-execution-invariant.md`.

Phase 0 makes these authoritative *and* enforced. See
[`EXECUTION_STATE.md`](./EXECUTION_STATE.md) for the phase ledger and
[`REPO_TRUTH_AND_GAP_MATRIX.md`](./REPO_TRUTH_AND_GAP_MATRIX.md) for the
read-only gap assessment each blueprint section maps to.

## Architecture dictum

The architecture dictum is five clauses, each mapped to the concrete layer that
owns it:

| Clause | Meaning | Owning layer |
|---|---|---|
| **Sources observe** | SDKs and ingress adapters may observe, timestamp, identify the local source, preserve source-native references and correlation IDs, capture consent, queue, and retry — nothing more. | SDK surfaces (`packages/*`) + ingress adapters |
| **Ingestion preserves** | The gateway accepts, validates, deduplicates, orders, and makes durable exactly what sources observed — without interpreting it. | `services/ingestion` (batch/bronze/outbox) |
| **Aether interprets** | Normalization, identity resolution, temporal/correlation/relationship/evidence resolution happen server-side, behind a governed envelope. | lake → silver (normalizers, projectors, resolvers) |
| **The graph establishes governed state** | Canonical entities, relationships, journeys, episodes, and outcomes are written only through governed, auditable graph mutations. | graph gateway + mutation governance |
| **Intelligence derives meaning** | Metrics, attribution, findings, and 360 projections derive from canonical backend state; nothing source-specific may leak into them. | metrics / attribution / findings / projections / Kyber |

The dictum is load-bearing for the thinness boundary (clause 1 vs 3) and for the
observation-only invariant (`execution_by_aether = false`) that ADR-011 fixes.

## Canonical vs legacy trees

| Tree | Role | Evidence |
|---|---|---|
| `Backend Architecture/aether-backend/` | **CANONICAL deployed backend** — the only tree Docker/ECR build and reference | root `docker-compose.yml` (builds this service only), `.github/workflows/deploy.yml` (ECR), `AWS Deployment/main.tf` (+ `AWS Deployment/aether-aws/terraform/…`), `config/runtime_deployment.yaml` |
| `packages/*` (`web`, `server`, `react-native`, `mobile-core`, `mobile-ui`, `android`, `ios`, `python`) + `packages/shared` | **CANONICAL SDK surface** — thin, observation-only clients over `api.aether.io` / `ingest.aether.so` | SDK endpoints never target port `3001`; `packages/web/src/index.ts` default endpoint `https://api.aether.io`; SDK dependency graph imports only `@aether/shared` + sibling SDKs |
| `packages/shared/contracts/event-registry.json` | **CANONICAL event registry** (Contract Spine source) | generated TS/Python twins + gated docs declare this one JSON as source |
| `Data Ingestion Layer/` | **LEGACY / UN-DEPLOYED duplicate** — TypeScript; `package.json` `name` is literally `"aether-backend"`; port `:3001`; kept alive only by version-sync/fallback/test-suite config | `Data Ingestion Layer/README.md` (versioned H1, no deprecation marker pre-Phase-0) |
| `Data Lake Architecture/` | **LEGACY / UN-DEPLOYED duplicate lake** — TypeScript Bronze/Silver/Gold with its own `/v1/batch` | `Data Lake Architecture/README.md` |
| `Agent Layer/` | **registered-not-deployable** — live, broker-coupled Celery workers; never canonical, never deprecated | `Agent Layer/` |
| `Backend Architecture/` root modules (besides `aether-backend/`) | **ORPHANED dead legacy** | `auth.py cache.py common.py events.py graph.py limiter.py logger.py repos.py routes.py settings.py migrations/ mnt/ services/{delegation,journey-service,web3}` |

Phase 0 adds a single-owner registration and deprecation banners to the two
legacy trees; it does **not** delete them (see
[`REPO_TRUTH_AND_GAP_MATRIX.md`](./REPO_TRUTH_AND_GAP_MATRIX.md#deferred-constraints)).

## Two-envelope model

- **Envelope A — Source/Wire Envelope.** Optimized for the producer. For SDKs
  this is `BaseEvent` (`packages/shared/events.ts`): source id/type/timestamp,
  session/anonymous/user identity fields, `properties`, and source context.
- **Envelope B — Universal Observation Envelope.** Created **inside Aether**:
  `observation` (id, type, family, occurred/received/ingested times, schema
  version), `tenancy`, `source`, `subjects[]` (identifier + `trust_class`),
  `temporal`, `correlation`, `acquisition`, `application`, `surface`, `device`,
  `privacy/consent`, `evidence/lineage`, and provenance.

Every downstream predicate in the blueprint (observation boundary, identity
subject-hints, field trust, event semantics) hangs off Envelope B.

**Live status: Envelope B model shipped (WS-A5); the WS-B adapter-convergence
workstream (B1..B5) has shipped flag-gated default-OFF on the feat branch.** The
canonical field registry (`packages/shared/contracts/observation-envelope-registry.json`),
the pydantic runtime model (`Backend Architecture/aether-backend/shared/observation/envelope.py`)
and the passive TS twin (`packages/shared/observation-envelope.ts`) now exist and are held in
lock-step by a parity test; `/v1/batch` can build the envelope per accepted SDK event behind a
default-OFF flag (`AETHER_OBSERVATION_ENVELOPE_ENABLED`, additive
`normalized["observation_envelope"]`, degrade-safe). WS-B ships the ingest-side convergence
machinery, each behind its own default-OFF flag: the universal ingress adapter registry + one
validated gateway (B1), deprecated-alias convergence onto the `/v1/batch` core (B2),
server-authoritative consent/minimization on every non-batch ingress seam (B3), ingestion-level
replay with original-time preservation (B4), and the single consumption normalization spine that
retires heterogeneous-envelope branching in downstream consumers (B5). `BaseEvent` (Envelope A)
remains the public/client envelope; the flat dict stays the default consumption surface until the
WS-B gateway/envelope/spine flags turn on. See the ledger rows for Blueprint §3/§4/§9/§12/§15 and
the gap matrix in [`REPO_TRUTH_AND_GAP_MATRIX.md`](./REPO_TRUTH_AND_GAP_MATRIX.md).

## Field-trust taxonomy

Every Contract Spine field carries a trust/authority classification; validators
enforce which trust classes may originate from which ingress path:

```text
OBSERVED
SOURCE_ASSERTED
SOURCE_REFERENCE
CLIENT_HINT
SERVER_STAMPED
RESOLVED
DERIVED
INFERRED
PREDICTED
OPERATOR_ASSERTED
```

Example (from the blueprint): a browser SDK sending `userId = "34922"` may assert
a `SOURCE_ASSERTED` identifier hint but must **not** assert
`canonicalEntityId`/`identityConfidence`; a Stripe webhook referencing
`customer = cus_123` means "Stripe observed/refers to `cus_123`", not "`cus_123`
is definitely canonical Entity E5".

**Live status: field-trust + semantic-level metadata is real on the spine
(WS-A2/A3).** `event-registry.json` carries per-field `fieldTrust` metadata and
`semanticLevel`/`sdkEmitable`/`sdkBoundary` release semantics; the generator emits
`EVENT_FIELD_TRUST` / `TRUST_CLASS_ORDER` / `EVENT_SEMANTIC_LEVEL` to the Python twin and
the field-trust map to TS, drift-gated. Minimum-trust-per-field enforcement at the boundary
and per-path trust evaluation (the WS-A3 boundary gate holds `sdkEmitable`/level; runtime
per-field enforcement) remain ledger rows Blueprint §3 / §10 / §11 / WS-B.

## Contract spine

- Canonical SDK ingress = **`POST /v1/batch`**, implemented by
  `Backend Architecture/aether-backend/services/ingestion/batch.py`.
- SDK endpoints target `https://api.aether.io` / `https://ingest.aether.so` —
  never the legacy port `3001`.
- Consent/privacy/scrub/minimization is server-authoritative on `/v1/batch`
  (acquisition-privacy referrer/token digesting, sensitive-key scrub,
  fingerprint-policy gating, GPC/DNT parse, server-authoritative consent, and
  `strip_canonical_entity_id`) and, since WS-B3 (flag-gated default-OFF), runs
  the **same facade on every non-batch ingress seam** — API feeds, connector-comms
  ingest, payment-rails webhooks, provider-runtime events, and tenant import
  commits. The mandatory minimization layer (scrub of sensitive values, strip of
  client-asserted canonical entity ids, T-class tenant data-policy) is
  **unconditional on every path** (never behind the per-path flags); only the
  per-subject (S) server-receipt rejection is a per-path toggle, and an OFF state
  denies rather than silently skipping (imports raise `ConflictError`) — ledger
  rows Blueprint §9/§10.
- Deprecated aliases `POST /v1/ingest/events[/batch]` stay mounted (so gateway
  discovery sees them) but, since WS-B2 (flag-gated default-OFF), route through
  the same `/v1/batch` core — validation / consent / scrub / Bronze-durable /
  idempotency / publish — instead of publishing un-validated events onto the
  validated topic; `AETHER_KILL_DEPRECATED_INGEST_ALIASES` retires both with
  HTTP 410 — ledger row Blueprint §4.

## Ingress adapters & credential classes

Registry-bound credential authority. The blueprint's seven ingress credential
classes are declared on the Envelope-B spine
(`observation-envelope-registry.json` → `shared/observation/envelope.py`
`CREDENTIAL_CLASSES`, parity-tested):

```text
PUBLIC_CLIENT
TRUSTED_CLIENT
TENANT_SERVER
VERIFIED_WEBHOOK
MANAGED_CONNECTOR
AETHER_INTERNAL
OPERATOR_REPLAY
```

**WS-B1 (flag-gated, default OFF): universal ingress adapter registry + one
validated gateway.** The adapter registry ships in
`Backend Architecture/aether-backend/services/ingestion/adapters/`: all seven
families (SDK / webhook / connector / API-feed / import / harness / replay)
declared with their Envelope-B `source_type`, blueprint adapter name, and
allowed credential classes; the SDK family is the first converged adapter
(`SdkIngressAdapter`, `PUBLIC_CLIENT`).
`services/ingestion/gateway.py` is the gateway core that validates + stamps the
Envelope-B observations adapters build (schema/type/family/tenant checks,
credential + source-trust provenance). A public SDK credential must be scoped
to `observation:write` + `config:read` only (never `graph:read`,
`identity:merge`, `export`, `admin`, …). The rest of the WS-B workstream has
shipped flag-gated default-OFF on the feat branch: the feed/provider-runtime/
payment-rails/import seams run the same validated facade with **unconditional**
scrub + strip + T-class data-policy minimization (WS-B3); deprecated aliases
converge onto the `/v1/batch` core with a kill-flag → HTTP 410 (WS-B2); an
ingestion-level replay adapter + Kyber-operator route deliver durable Bronze
re-drive with original-time preservation (WS-B4); and downstream consumers read
through one normalization spine instead of branching on heterogeneous envelopes
(WS-B5). Universal enforcement on every family is still behind the default-OFF
flags (gateway/envelope/spine/replay kill-switch) — ledger rows Blueprint §4,
§9, §12, §15.

`execution_by_aether = false` applies at every layer per **ADR-011**: DB CHECK
constraints, `Literal[False]` model fields, `check_no_execution` on write routes,
read-only adapter credentials, and conformance assertions.

## SDK thinness boundary

The thinness rule (Blueprint §28): **an SDK feature is permitted only when the
information is uniquely observable at the source, required to preserve
correlation/provenance/privacy, or required for reliable delivery.** Any
capability involving interpretation, resolution, aggregation, classification, or
decision must live in the backend, behind Envelope B + a trust class + a registry
+ evidence lineage.

- SDKs may touch `packages/shared` and sibling SDK packages; they never import
  backend internals (`Backend Architecture/**`, `Data Ingestion Layer/**`,
  `Data Lake Architecture/**`).
- `docs/source-of-truth/SDK_SCOPE.md` conventions forbid `canonical_entity_id`
  in the SDK; `validation.py` strips client/library fields server-side.
- **Live gap:** no CI gate enforces thinness, and interpretation modules
  (`packages/shared/commerce-bridge.ts`, `packages/shared/economic-metrics.ts`)
  ship inside the SDK graph. Phase 0 adds the first import-boundary gate
  (`scripts/validate_sdk_import_boundary.py`) — ledger row Blueprint §28.

## Interpretation spine

lake → silver → graph → intelligence:

```text
Bronze (raw, hash-chained) ──► Normalizers/projectors/resolvers (Silver)
        ──► governed graph mutations ──► metrics / attribution / findings / 360s
```

**Live gap:** three heterogeneous envelopes share the single "validated" topic
(SDK-normalized dict, comms-normalized dict, provider_runtime `AetherEvent`), so
Silver workers branch on `source_service`/payload keys; five+ Bronze/Silver
pipelines exist instead of one normalization spine; graph/ledger governance is
off by default (`mutation_gateway_mode='off'`). WS-B5 ships the consumption-side
spine (`services/ingestion/spine.py::to_observation_view`, flag-gated default-OFF):
the additive Envelope-B `observation_envelope` key wins when present, otherwise the
legacy flat SDK/comms dict or the provider_runtime `AetherEvent` dump is mapped —
so the ingestion worker + semantic-intelligence + resolution consumers can read
through one normalization view instead of branching on envelope shape. Ledger rows
Blueprint §1, §15, §20–§26.

## Architecture invariants — checklist

The blueprint's 18 mandatory architecture invariants (Blueprint §29), transcribed
**verbatim** as an auditable checklist. Phase 0 does not claim these are met — it
fixes the governance that lets new work steer toward them. The read-only
assessment of each invariant against the live tree is in
[`REPO_TRUTH_AND_GAP_MATRIX.md`](./REPO_TRUTH_AND_GAP_MATRIX.md) (invariant
matrix under the Blueprint §29 ledger row).

> The implementation is not considered complete unless all of the following are true.

1. **One observation model after adapters.**
2. **One Contract Spine governs ingestion vocabulary.**
3. **No SDK owns backend intelligence.**
4. **No public source may assert canonical identity truth.**
5. **Every accepted observation is durable before acknowledgment.**
6. **Every observation has tenant provenance.**
7. **Every provider record preserves source provenance.**
8. **Every ingestion path implements idempotency.**
9. **Consent and privacy policy apply to every path.**
10. **Raw/source data and normalized graph truth remain distinguishable.**
11. **Temporal source information is never discarded.**
12. **Correlation IDs survive normalization.**
13. **Missing/empty/zero/degraded states remain distinct.**
14. **Derived claims retain evidence and model/policy lineage.**
15. **Replays never masquerade as new occurrence time.**
16. **SDK schemas are generated rather than manually drifting.**
17. **Kyber can trace observations end-to-end.**
18. **Backend intelligence changes do not require SDK releases unless source-observable information must change.**

## ADR pointers

- **ADR-007 — Domain Canonicalization** (`docs/decisions/ADR-007-domain-canonicalization.md`):
  the one-source-of-truth decision that underpins the Contract Spine.
- **ADR-011 — Observation-Only Execution Invariant** (`docs/decisions/ADR-011-observation-only-execution-invariant.md`):
  `execution_by_aether = false`, the "observation ends and interpretation begins"
  boundary this program hardens. (Phase 0 renumbers this ADR out of the ADR-007
  collision; see the ADR collision record in
  [`REPO_TRUTH_AND_GAP_MATRIX.md`](./REPO_TRUTH_AND_GAP_MATRIX.md).)
- **ADR-012 is reserved** for a future genuine decision (for example,
  converge-on-one-`observe` + the Envelope A→B contract). It is explicitly **not**
  created in Phase 0; no new ADR is added by this program slice.

## Phase workstreams

The program runs as phased workstreams. See
[`EXECUTION_STATE.md`](./EXECUTION_STATE.md) for the live phase ledger and
definitions of done. The roadmap is: **Phase 0 (convergence bedrock — this
slice)** then the blueprint's own **Workstreams A–E** (contract foundation /
adapter convergence / SDK hardening / backend interpretation / operations).

## Change ownership

- This is an **authored** document (no `source_files`, no `last_synced_commit`)
  — it is drift-exempt by design.
- **Owner:** `platform@aether`.
- **Update procedure:** edit this page when a program decision changes the target
  architecture; do not restamp `since_version` on content edits (it marks the
  platform version the page first applied to, currently `"8.12.0"`). Coordinate
  any change that alters a governance gate or ADR with the owning ticket.
