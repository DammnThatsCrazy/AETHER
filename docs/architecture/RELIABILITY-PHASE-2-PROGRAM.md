---
title: Aether Reliability Phase 2 — Architectural Programs
slug: architecture/reliability-phase-2-program
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
canonical_owner: platform@aether
estimated_read_minutes: 28
toc_depth: 4
---

# Aether Reliability Phase 2 — Architectural Programs

> **This document is the design/sequencing reference for five multi-milestone
> programs.** It was originally authored as design-only; some milestones have
> since shipped (see **Landed milestones** below). Every claim about "what
> exists today" was verified against the repository at authoring time; each
> milestone marked landed has real code + tests behind it, and every milestone
> not yet marked landed remains a proposal, not a status report.
>
> ### Landed milestones
> - **M1 — all five programs** (initial reliability remediation PR): shared
>   `hash_chain` primitive; Node `DurableEventQueue`; re-attribution on privacy
>   erasure; the production-equivalent CI lane; the FX `PriceProvider`.
> - **Program 1 (Ledger) M2** — `prev_hash`/`integrity_hash` on
>   `bronze_sdk_events`, chained inside `ingest_many` (new rows only; NULL =
>   documented pre-cutover boundary).
> - **Program 3 (Re-attribution) M3** — invalidation generalized into
>   `services/measurement/reattribution.py`, reused by privacy erasure and by a
>   new fraud-network `takedown` flow.
> - **Program 4 (Prod-equivalent CI) M2** — real-stack ingestion
>   idempotency/concurrency tests (exactly-once under genuine racing).
> - **Program 5 (Multi-currency) M2** — real FX rate + provenance recorded in
>   `conversion_repo`/`spend_repo` upserts (no more hardcoded `1.0`; unpriced is
>   flagged, never silent parity).
>
> Remaining milestones below (incl. Program 2's backend rollout M1–M3, and the
> behavior-change / infra-gated milestones) are still design-only.

## Why these five and why they are Phase 2

A reliability cleanup pass can fix a wrong default, add a missing test, close
a race in a single function, or wire an existing repository method into an
existing handler. It cannot introduce a new durability primitive, retire a
parallel code path that tenants currently depend on, or stand up new
infrastructure — those changes need their own design review, their own
migration, their own rollout plan, and usually span more than one release.
The five programs below are exactly that class of change:

1. **Truth-chain / append-only event ledger** — closes a *provability* gap:
   Aether already treats its Bronze event tier as immutable by convention,
   but nothing proves it, and the one subsystem that does prove immutability
   (the security audit ledger) only covers governance actions, not the event
   stream itself.
2. **A single `/v1/batch` ingestion owner + Node SDK durability** — closes a
   *durability* gap: two parallel ingestion code paths with two different
   idempotency models both currently answer the same endpoint, and the Node
   server SDK can silently drop already-accepted events on a process crash.
3. **Deletion / replay / re-attribution** — closes a *correctness-after-change*
   gap: deleting or invalidating data is partially wired (tombstones exist),
   but the derived analytical state built on top of deleted data — attribution
   credit specifically — is not automatically corrected, and there is no
   supported way to replay a corrected pipeline over historical data.
4. **A production-equivalent CI lane** — closes a *verification* gap: every
   current CI lane runs the backend in its in-memory fallback mode, so the
   transactional guarantees the other four programs depend on are never
   actually exercised by CI.
5. **Multi-currency** — closes a *false-precision* gap: money fields carry a
   currency and an exchange-rate column that give the *appearance* of
   multi-currency support, but every value is silently normalized to USD at
   1:1 parity regardless of actual currency.

Programs 1–3 and 5 each describe a "first increment" that is small,
additive, and safe to ship in isolation ahead of the rest of the program.
Program 4 is close to a prerequisite for trusting the others in production
and is called out as the recommended starting point in
[Cross-program sequencing](#6-cross-program-sequencing).

---

## 1. Truth-chain / append-only event ledger

### Problem statement

Aether's own architecture documentation asserts Bronze immutability as a
design rule — `docs/architecture/BACKEND_INTELLIGENCE_ARCHITECTURE.md`
lists "Preserve bronze immutability" as a preservation rule for the data
lake — but nothing enforces or proves that rule at the data layer. A row in
`bronze_sdk_events` (written by `services/ingestion/bronze_bulk.py`'s
`ingest_many`, or by the legacy per-event path in
`services/ingestion/batch.py`) can be edited or deleted by anyone with
database access, including an operator script, a bad migration, or a
compromised credential, and nothing downstream would detect it. Every
number Aether reports — attribution credit, spend, conversions — ultimately
traces back to that table being what it claims to be.

The repository already contains proof that this problem is solvable
cheaply: `services/security/audit_ledger.py` (`AuditLedger`, documented in
`docs/AUDIT-EVENT-LEDGER.md`) chains an `integrity_hash` per event to the
previous event **for the same tenant**, so `verify_chain()` can detect
deletion or reordering of governance/security audit events. But that
ledger's own "Planned controls" section is explicit about what is still
missing even for the one table it protects: "External WORM/append-only
sink export for long-term retention" and "Per-event signing with a
rotating service key (current hash chain is integrity, not
non-repudiation)." In other words, the one place Aether has built
tamper-evidence today (a) covers only security/governance actions, not the
canonical SDK event stream that everything else is computed from, and (b)
is still only self-consistent within the same database an attacker with
write access could also reach — it is not yet notarized externally.

The false-certainty this program closes: statements like "Bronze is
append-only" or "the event stream is the source of truth" are currently
architectural intent, not a verifiable property.

### What exists today

- `AuditLedger.compute_integrity_hash` / `AuditLedger.verify_chain` — a
  working, tested, per-tenant hash-chain implementation, scoped to
  `SecurityAuditEvent` rows only (`docs/AUDIT-EVENT-LEDGER.md`).
- `bronze_sdk_events` and `event_outbox` — the two tables the V2 ingestion
  path (`services/ingestion/bronze_bulk.py`) writes transactionally, with
  `ON CONFLICT ... DO NOTHING` idempotency, but no chaining or hash column.
- `services/silver/projectors/*` — Silver/Gold projections computed from
  Bronze with no recorded proof of which Bronze rows/hashes a projection
  run actually consumed.
- Backward-compatibility precedent: `AuditLedger`'s chain already tolerates
  a "v1 vs v2" hash shape so historical rows verify without a backfill —
  the same technique this program would reuse for a Bronze cutover.

### Proposed architecture

Generalize the proven `AuditLedger` pattern into a shared, table-agnostic
primitive rather than reimplementing hash-chaining a second time:

1. Extract `compute_integrity_hash` / `verify_chain` from
   `services/security/audit_ledger.py` into a new
   `shared/integrity/hash_chain.py` module parameterized by "canonical
   fields to hash" and "chain partition key" (tenant for audit events,
   likely `(tenant_id)` again for Bronze, since ingestion is already
   tenant-partitioned everywhere else in the pipeline).
2. Re-point `AuditLedger` at the shared primitive (pure refactor, same
   behavior, existing `AuditLedger` tests become the regression oracle).
3. Apply the primitive to `bronze_sdk_events`: two new columns
   (`prev_hash`, `integrity_hash`), chained per `tenant_id`, hashed over the
   canonical envelope fields the ingestion contract already guarantees are
   present (`event_id`, `schema_version`, `occurred_at`/`sentAt`, a content
   hash of the normalized payload) — written inside the same transaction
   `ingest_many` already uses, so no new write path is introduced.
4. Add a scheduled verifier — shaped like `outbox_relay.py`'s polling
   worker, not a new pattern — that periodically calls `verify_chain()`
   over recent Bronze partitions and raises through the existing
   security-alert path (the same one `AuditLedger` already reports into)
   on a break.
5. Extend chaining to `event_outbox` so publish order itself is provable,
   then stamp Silver/Gold projector runs with the exact chained Bronze
   range (`tenant_id`, first/last `integrity_hash`) they were computed
   from, so a projection can cite its own provenance.
6. Only after 1–5 are stable: deliver the external WORM export
   `docs/AUDIT-EVENT-LEDGER.md` already lists as "planned" — e.g. an
   object-lock (Object Lock / Glacier Vault Lock–style) bucket that
   receives periodic, signed chain-segment exports — so integrity is
   provable even against a fully compromised database, not merely
   self-consistent within it.

### Milestones (sequenced)

- **M1** — Extract the shared `hash_chain` primitive from `AuditLedger`;
  re-point `AuditLedger` at it; zero behavior change, full parity against
  existing `AuditLedger` tests.
- **M2** — Add `prev_hash`/`integrity_hash` columns to `bronze_sdk_events`
  and populate them inside `ingest_many`'s existing transaction, scoped to
  new rows only (explicitly document the pre-cutover boundary rather than
  attempting a backfill of historical rows in the same change).
- **M3** — Scheduled verifier worker + alert wiring into the existing
  security-alert path; dashboard for "tenants currently verified" /
  "verification failures."
- **M4** — Extend chaining to `event_outbox` rows.
- **M5** — Stamp Silver/Gold projector runs (`services/silver/projectors/*`)
  with the Bronze chain range they consumed.
- **M6** — External WORM export of verified chain segments on a retention
  cadence, gated on infra/security sign-off for the storage target.

### First increment

**M1 alone.** Extracting `hash_chain.py` out of `AuditLedger` with the
existing `AuditLedger` test suite as a pinned regression oracle changes zero
runtime behavior — `AuditLedger` calls the exact same logic through a new
import — and is not wired into any new table yet. It ships independently,
requires no migration, and de-risks every later milestone by proving the
extraction preserves the one hash-chain implementation Aether already
trusts.

### Dependencies

M2 depends on M1. M3 depends on M2 (needs the columns to verify). M4 is
independent of M2/M3 and could run in parallel once M1 lands. M5 depends on
M2. M6 depends on M2–M4 plus an infrastructure/security decision on the
external storage target, and is explicitly the slowest milestone since it
likely needs a compliance/security review, not just an engineering change.

### Risks

- **Write-path cost**: adding a hash computation to every Bronze row is a
  cost added to the highest-throughput write path in the system
  (`ingest_many`, the V2 core of `/v1/batch`). Must be benchmarked against
  V2's existing transactional-outbox write path before M2 ships to more
  than a canary tenant.
- **Per-tenant chain serialization**: `AuditLedger`'s chain is already
  per-tenant sequential (each new hash depends on the previous one for that
  tenant). Reusing that shape for the much higher-volume Bronze table could
  become a write bottleneck for high-volume tenants; a batched or Merkle
  variant should be evaluated before M2 ships broadly, not retrofitted
  after.
- **Backfill temptation**: hashing only new rows (M2) leaves historical
  Bronze data with no integrity proof. That gap must be stated explicitly
  in any customer- or compliance-facing claim — do not imply full-history
  tamper-evidence until a deliberate backfill milestone is scoped and
  costed separately.

---

## 2. A single `/v1/batch` ingestion owner + Node SDK durability

### Problem statement

`POST /v1/batch` is answered today by two parallel, config-selected code
paths inside `services/ingestion/batch.py`:

- **V1** — a per-event write loop using Redis `SETNX` for dedupe, a
  fire-and-forget `asyncio.create_task()` identity resolution call, and an
  in-request bus publish.
- **V2** (`_ingest_batch_v2`, PR 5/PR 6 in the code's own history) — a
  single transaction that bulk-inserts typed Bronze rows plus their
  transactional-outbox rows via `services/ingestion/bronze_bulk.py`'s
  `ingest_many`, with **database uniqueness, not Redis, as the idempotency
  source of truth**, and a separate relay worker
  (`services/ingestion/outbox_relay.py`) that is supposed to drain
  `event_outbox` to the bus.

Which path a given request actually takes is decided per-tenant by
`IngestionV2Config.enabled` / `canary_tenants` in `config/settings.py`, and
the same config module documents `outbox_relay_enabled` as "config-only
here; the relay WORKER that drains `event_outbox` to the bus is a later
PR" — i.e., even for tenants already on V2, the mechanism that actually
delivers their accepted events to the bus is not yet confirmed running by
that same settings module's own comments. There is no single answer today
to "what happens when a tenant calls `/v1/batch`" — the answer depends on
tenant, on two independent feature flags, and on whether the relay worker
described as a later deliverable has since been turned on.

Separately, on the client side, the Node server SDK's queue
(`packages/server/src/queue.ts`, `EventQueue`) is a bare in-process array:

```
private readonly queue: QueuedEvent[] = [];
```

`enqueue()` pushes into memory only. If the host process crashes or
restarts between a caller's `track()` call and a successful `/v1/batch`
transport send, every queued-but-unsent event is gone — silently, from the
caller's point of view, since `track()` already returned. This is exactly
the class of problem the backend side has already solved once (the
transactional-outbox pattern in V2) but the reference server SDK has not.

### What exists today

- Two live code paths behind `IngestionV2Config` in
  `services/ingestion/batch.py` / `config/settings.py`, selected per-tenant.
- `outbox_relay.py` — batch size, poll interval, lease seconds, and max
  attempts are already configurable (`OUTBOX_RELAY_*` env vars), i.e. the
  relay's operational shape is designed, but its `enabled` default is
  `False`.
- `packages/server/src/queue.ts` — bounded (`maxSize`, default 1000),
  exponential-backoff retry with jitter, but entirely in-process memory;
  `packages/server/src/transport.ts` already parses structured
  accepted/duplicate/rejected counters from the V1/V2-compatible
  `BatchResponse`, so the transport layer already expects the durable
  backend contract — only the client-side queue is the gap.

### Proposed architecture

**Backend**: make V2 the only code path, by finishing the rollout the
code's own comments already describe as pending, not by inventing a new
mechanism:

1. Turn on `outbox_relay_enabled` for tenants already in `canary_tenants`
   and observe relay lag / dead-letter rate in production.
2. Expand `canary_tenants` to 100% using the existing per-tenant flag — a
   pure rollout step, no code change.
3. Delete the V1 code path and the `IngestionV2Config` flag surface. After
   this, `services/ingestion/batch.py`'s V2 function plus
   `outbox_relay.py` **are** the ingestion owner — one function, one
   idempotency model, no runtime branch.

**Node SDK**: add an opt-in durable spool behind the same `EventQueue`
contract (`QueuedEvent`, `enqueue`/`dequeueReady`/`requeue`) so swapping
implementations requires no change to `client.ts` or `transport.ts`:

4. Implement `DurableEventQueue` backed by an append-only local file (or an
   embedded store where the runtime supports it), satisfying the same
   interface `EventQueue` exposes today.
5. On process start, replay any un-flushed spool entries through the
   existing transport/retry logic before accepting new `track()` calls.

### Milestones (sequenced)

- **M1** — Turn on `outbox_relay_enabled` for the existing `canary_tenants`
  set; add relay-lag and dead-letter-rate dashboards.
- **M2** — Expand `canary_tenants` to 100% of tenants once M1 is stable.
- **M3** — Delete the V1 ingestion path and the `IngestionV2Config` flag
  surface entirely.
- **M4** — Implement `DurableEventQueue` in `packages/server`, matching the
  existing `EventQueue` interface.
- **M5** — Ship `DurableEventQueue` as opt-in, then default, in the Node
  SDK client, with startup replay and a documented disk-space bound.

### First increment

**M1 alone.** Turning on the outbox relay worker only affects tenants
already opted into the V2 canary path — it is fully config-gated behind
`OUTBOX_RELAY_ENABLED`, requires no schema change, and is exactly the "PR
6" work the code's own comments already anticipate as the next step. It
ships without touching V1 tenants at all and produces the first real
production signal (relay lag, dead-letter rate) needed to justify M2.

### Dependencies

M2 depends on M1 proving stable relay lag in production. M3 must trail M2
by a full observation window — the canary flag is the rollback mechanism
for M2, so V1 code cannot be deleted until that safety net is no longer
needed. M4 is independent of the backend milestones and can ship on its
own schedule. M5 depends on M4 plus the Node SDK's existing version/
changelog process (`packages/server/package.json`).

### Risks

- **Simultaneous idempotency-model switch**: M2 changes the idempotency
  source of truth (Redis → DB uniqueness) for every remaining tenant at
  once. A rollback plan must exist and be exercised before M3 removes the
  only fallback.
- **Deleting V1 too early**: if M3 lands before M2's observation window
  closes, there is no way to roll a misbehaving tenant back to the
  previously-trusted path.
- **New local-disk write path in customer processes**: `DurableEventQueue`
  (M4) introduces disk I/O into a library that runs inside customer server
  processes, some of which may be in constrained containers (read-only
  filesystems, limited ephemeral storage). It must be strictly opt-in with
  a documented, bounded disk footprint, or it becomes a new reliability
  problem instead of solving one.

---

## 3. Deletion / replay / re-attribution

### Problem statement

Privacy erasure already reaches the measurement layer:
`MeasurementPrivacyHandler.handle_erasure`
(`services/measurement/privacy.py`), invoked durably by the
`consent.erasure` job (`services/consent/erasure_jobs.py`), tombstones a
profile's touchpoints and conversions
(`TouchpointRepository.tombstone_for_profile`,
`ConversionRepository.tombstone_for_profile`) and triggers
`JourneyCompiler.rebuild_affected_by_consent_change` for that profile.

What it does **not** do: call into `AttributionRunRepository`
(`services/measurement/repositories/attribution_run_repo.py`), which
already exposes exactly the operation this needs —
`create_run` + `deactivate_prior_runs` — and is already used in production
by `services/measurement/engine/subscription_ltv.py` and
`services/measurement/engine/attribution_engine.py`. The result: a
conversion whose winning touchpoint was just erased keeps its **stale**
`attribution_run` and credits until some unrelated process happens to
recompute it. Attribution numbers built on deleted data are not
automatically corrected — they are just as confidently wrong as they were
before the deletion, and nothing in the erasure evidence trail records
that the attribution result is now stale.

Separately, `services/dsr_propagation` is explicit that it is *not* the
thing that performs erasure — its own module docstring states it "does NOT
execute erasure/access itself" — it is only the propagation-record and
impact-index layer. So even once re-attribution is wired up, there is no
single place today that both performs an invalidation (privacy erasure,
fraud takedown, or a bad-data correction) *and* records citable evidence of
exactly what changed and why.

Finally, there is no general "replay a corrected pipeline over historical
data" capability. `docs/BACKFILL-JOBS.md` documents a generic,
tenant-scoped, idempotent backfill *pattern*, but nothing today applies
that pattern specifically to re-draining a Bronze range through
`journey_compiler` and the attribution engine after a bug fix, a fraud
network takedown (`services/fraud_networks`), or an attribution-model
change — that is handled ad hoc today, not as a supported operation.

### What exists today

- Tombstone status values already standardized across repositories:
  `touchpoint_repo.py` / `conversion_repo.py` use `'privacy_tombstoned'`;
  `activity_repo.py` uses `'tombstoned'`; `journey_compiler.py` already
  excludes rows in `('tombstoned', 'deleted', 'consent_restricted')` from
  journey construction.
- `AttributionRunRepository.create_run` / `deactivate_prior_runs` /
  `get_active_run` — a working "supersede the active run for a conversion"
  primitive, exercised today by subscription LTV and the core attribution
  engine, but never called from the erasure path.
- `services/dsr_propagation` — a real evidence/impact-index layer with
  named components (e.g. `attribution_records`, `continuation_records`,
  `mobile_installations`, `client_sync_records` — see
  `services/consent/erasure_jobs.py`), ready to record a new kind of step
  once one exists to record.
- `docs/BACKFILL-JOBS.md` — the generic backfill pattern (scope,
  idempotency by `(tenant_id, resource_id)`, throttle, observe, verify)
  that a replay job type would extend rather than replace.
- `services/jobs` (documented in `docs/source-of-truth/JOBS_PLATFORM.md`)
  — the durable jobs platform (`FOR UPDATE SKIP LOCKED` leasing, retries,
  dead-letter, `HANDLER_REGISTRY`/`register_handler`) that already hosts
  `consent.erasure` and is the natural home for a new `replay.*` job type.
- `services/fraud_networks` — cluster detection and investigation linking
  that identifies groups of entities that may need bulk invalidation, but
  has no wired path to actually invalidate touchpoints/conversions today.

### Proposed architecture

1. **Close the re-attribution gap first.** Extend
   `MeasurementPrivacyHandler.handle_erasure` to call
   `AttributionRunRepository.deactivate_prior_runs` plus a new attribution
   run for every conversion whose touchpoint set just changed, reusing
   `attribution_engine.py`'s existing run-creation path (the same one
   `subscription_ltv.py` already calls in production).
2. **Make the result citable.** Record the re-attribution as a DSR
   propagation step, extending the existing `attribution_records`
   component's evidence (previous run id deactivated, new run id active,
   which touchpoint/conversion triggered it) rather than inventing a new
   component name.
3. **Generalize invalidation beyond privacy.** Factor the
   tombstone-then-rebuild-then-reattribute sequence into a named,
   independently callable operation so a fraud-network takedown
   (`services/fraud_networks`) or a data-quality correction can trigger the
   same correctness path privacy erasure uses today, instead of each
   caller reinventing it.
4. **Build replay as a typed backfill job**, registered on the existing
   jobs platform (`services/jobs`, `register_handler`), that re-drains a
   bounded, verified Bronze range through the same Silver/Gold projectors
   and `journey_compiler` — idempotent by `(tenant_id, resource_id)` like
   every other backfill in `docs/BACKFILL-JOBS.md`.
5. **Verify what's being replayed.** Once Program 1's hash-chain exists,
   require replay to verify the Bronze range's chain before re-processing
   it, so replay cannot silently reprocess a range that was itself
   tampered with.

### Milestones (sequenced)

- **M1** — Wire `deactivate_prior_runs` + new-run creation into
  `MeasurementPrivacyHandler.handle_erasure` for the privacy-erasure path
  only.
- **M2** — Record the re-attribution as DSR propagation evidence on the
  existing `attribution_records` component.
- **M3** — Generalize invalidation into a callable service usable by
  `services/fraud_networks` takedown flows, not just privacy erasure.
- **M4** — Define `replay.bronze_range` (or similarly named) as a typed job
  on `services/jobs`, re-running Bronze → Silver → journey → attribution
  for a bounded range.
- **M5** — Wire replay's range verification to Program 1's hash-chain
  primitive once it ships.

### First increment

**M1 alone.** Calling the already-production-tested
`AttributionRunRepository` methods from the already-existing
`handle_erasure` handler is a small, additive change confined to one
method, using repository methods `subscription_ltv.py` already exercises
in production today. It ships independently of every other program in this
document and closes the single most concrete correctness gap described
here: attribution credits that silently outlive a legally-mandated
deletion of the data they were computed from.

### Dependencies

M2 depends on M1. M3 depends on M1 (reuses the same invalidation
primitive) and on `services/fraud_networks`' existing takedown flow. M4
depends on the `docs/BACKFILL-JOBS.md` pattern and, for full range
verification, on Program 1 (M5 here depends on Program 1's M2/M3).

### Risks

- **Amplification**: automatic re-attribution triggered by every erasure
  could itself become a load spike if many erasures land at once (a bulk
  DSR request, or a large fraud-network takedown). Needs the same
  throttle/off-peak guidance `docs/BACKFILL-JOBS.md` already states for
  backfills, applied to the re-attribution trigger itself.
- **Retroactive number changes**: replaying a corrected pipeline over a
  historical range (M4) can change previously-reported totals. This must
  ship with an explicit before/after reconciliation delta surfaced to the
  affected tenant, not just an internal ops runbook — silently changing
  historical numbers is its own false-certainty problem.
- **Evidence completeness**: M2's propagation record is only as trustworthy
  as the re-attribution call it wraps; if M1 has a partial failure (one
  conversion re-attributed, another silently skipped), the evidence must
  reflect that explicitly rather than reporting a blanket success, matching
  the `partial_failure` pattern `handle_erasure` already uses for its
  existing tombstone steps.

---

## 4. A production-equivalent CI lane

### Problem statement

Every backend test workflow in `.github/workflows/` (`repo-health.yml`,
and by extension anything invoked through `make ci-check`) runs with
`AETHER_ENV=local`. Under that setting, every pooled dependency in the
ingestion and measurement code takes its in-memory fallback branch —
`services/ingestion/bronze_bulk.py`'s own module docstring documents this
explicitly: "Local / test mode: when `get_pool()` returns `None`
(`AETHER_ENV=local`, no asyncpg), an in-memory fallback dedupes ... against
the shared `_IN_MEMORY_STORES` dicts." The same pattern repeats in
`spend_repo.py`, `conversion_repo.py`, `attribution_run_repo.py`, and the
outbox/relay code. A repository-wide check confirms no workflow file starts
a Postgres, Redis, Kafka, or ClickHouse service container — every
`postgres`/`redis`/`kafka`/`clickhouse` grep across `.github/workflows/*.yml`
returns nothing.

That means the specific guarantees Program 1 and Program 2 depend on —
single-transaction Bronze+outbox atomicity, `ON CONFLICT ... DO NOTHING`
database-uniqueness idempotency, `FOR UPDATE SKIP LOCKED` lease claiming in
`outbox_relay.py` and the jobs platform — are never exercised by CI. An
in-memory Python dict has different concurrency semantics than a real
Postgres transaction under real connection pooling and real lock
contention. A broken index, an actual deadlock, or a lease-expiry race can
pass every existing CI gate and only surface in staging or production,
which is precisely the "false certainty" this document is named for:
`make ci-check` passing is not evidence that the transactional code paths
those other four programs rely on actually work under real infrastructure.

`docker-compose.yml` at the repo root already defines the exact
production-shaped topology — `postgres`, `redis`, `kafka`/`zookeeper`,
`clickhouse`, `backend`, `outbox-relay`, `stream-worker`, and the rest —
that nothing in CI stands up today.

### What exists today

- `docker-compose.yml` — full local topology, already used for manual
  local development, not wired into any GitHub Actions workflow.
- `AETHER_ENV=local` in-memory fallbacks throughout the ingestion and
  measurement repositories, explicitly documented in code as the
  local/test path, distinct from the production DB-backed path.
- `.github/workflows/repo-health.yml` — runs `pytest tests/ -n auto` and
  similar, always under `AETHER_ENV=local`.
- `.github/workflows/hardening-release-gate.yml` — runs `make ci-check`
  and `make release-gate`, but through the same in-memory-mode test
  invocations as every other lane; it adds release-readiness *scorecard*
  checks, not a real-infrastructure test run.
- No workflow currently defines a Postgres/Redis/Kafka/ClickHouse service
  container or runs `docker compose up` as part of CI.

### Proposed architecture

A **new, separate** CI lane — additive to, not a replacement for, the
existing fast local-mode lane, which stays as the quick-feedback default
for every PR:

1. Stand up a bounded subset of `docker-compose.yml`'s services as GitHub
   Actions service containers (or via `docker compose up -d` in a CI job) —
   starting with `postgres` + `redis` only.
2. Point the backend test run at that real stack (`DATABASE_URL` set, so
   `get_pool()` returns a real pool and every in-memory-fallback branch is
   no longer taken) instead of `AETHER_ENV=local`.
3. Start with the ingestion and measurement test suites specifically,
   since those are the modules whose own docstrings already call out the
   in-memory-vs-real distinction.
4. Add `kafka` + `outbox-relay` to the compose subset for relay-specific
   tests (lease expiry, claim races, dead-letter transitions) that need
   real row locking, not an in-memory dict, to be meaningful.
5. Once flake rate and wall-clock time are proven acceptable, promote the
   lane to a required check — on `hardening-release-gate.yml` or a
   dedicated new gate — without folding it into `make ci-check`'s fast
   path.

### Milestones (sequenced)

- **M1** — New, non-blocking workflow: boot `postgres` + `redis` via a
  compose subset; run one existing, already-passing smoke test against the
  real stack to prove the harness works.
- **M2** — Migrate the ingestion test suite (`tests/` under
  `services/ingestion`) to run against the real stack; fix whatever
  concurrency assumptions the in-memory-only tests were implicitly making.
- **M3** — Add `kafka` + `outbox-relay` to the compose subset; add
  relay-specific tests (lease expiry, claim races, dead-letter) that
  exercise real Postgres locking.
- **M4** — Extend the lane to measurement/attribution suites (`spend_repo`,
  `conversion_repo`, `attribution_run_repo`), which share the same
  in-memory-fallback branch pattern.
- **M5** — Promote the lane to a required check once M1–M4 have run clean
  for a stabilization period.

### First increment

**M1 alone.** A new, additive, non-blocking workflow that boots
`postgres` + `redis` and runs a single already-passing ingestion smoke test
against them, proving the harness itself works before any existing suite
is migrated. It cannot regress the existing fast lane or `make ci-check`
because it is a separate job with no required-check status yet.

### Dependencies

M2–M4 depend on M1's harness existing. M5 (making the lane required)
depends on M1–M4 running clean for a stabilization period. This program has
no dependency on Programs 1, 2, 3, or 5 — it can start immediately and, if
anything, should run first, since it is what makes the other programs'
claims of correctness independently checkable rather than asserted.

### Risks

- **Cost and wall-clock time**: real service containers materially lengthen
  CI runtime and infrastructure spend compared to in-memory dicts. This
  must stay a parallel, non-blocking lane rather than gating every PR from
  day one.
- **New flakiness class**: container startup and real network behavior
  introduce flakiness that deterministic in-memory fallbacks do not have.
  Needs its own retry/quarantine policy before promotion to required, or
  engineers will learn to ignore its failures — which defeats the purpose.
- **Do not delete the in-memory paths**: this program adds a second,
  higher-fidelity lane; it must not be used as a reason to remove the
  in-memory fallback code paths, which remain the right choice for fast PR
  feedback and for contributors without Docker available.

---

## 5. Multi-currency

### Problem statement

Measurement's money-bearing tables already have the *shape* of
multi-currency support: `conversion_repo.py` carries both `currency` and
`normalized_currency`; `spend_repo.py` carries `billing_currency`,
`normalized_currency`, **and** `exchange_rate`. But every one of those
repositories defaults `currency`/`normalized_currency` to `"USD"` and
`exchange_rate` to the string `"1.0"` on write
(`row.setdefault("currency", "USD")`,
`row.setdefault("normalized_currency", "USD")`,
`row.setdefault("exchange_rate", "1.0")`), and nothing in the measurement
ingestion path ever overrides those defaults with a real observed rate. A
conversion or spend record ingested with `currency="EUR"` is stored and
rolled up today as if it were USD at 1:1 parity — silently. `ROAS`,
`campaign_credit_summary`, and `referral_performance` rollups in
`attribution_run_repo.py` are Decimal-typed over NUMERIC columns, which
*looks* precise, while potentially mixing currencies at parity underneath.

The repository already has a real answer for exactly this class of problem
sitting unused one layer over: `services/value/price_sources.py` is a
pluggable USD-pricing subsystem with an explicit, already-enforced
invariant — "a source being unavailable yields **unpriced** (`usd_value`
`None`), never 0" — that resolves valuations across FX/fiat, token market
price, and peg-aware stablecoin sources (`_FX_FIAT_SYMBOLS` already lists
ten fiat currencies: EUR, GBP, JPY, CAD, AUD, CHF, CNY, INR, BRL, MXN), with
every valuation recording `conversion_rate` + `conversion_source` +
`method`. Measurement's repositories simply never call it.

### What exists today

- `currency` / `normalized_currency` / `billing_currency` / `exchange_rate`
  columns already present across `conversion_repo.py`, `spend_repo.py`,
  `adjustment_repo.py`, `attribution_run_repo.py`, and
  `services/measurement/contracts.py`'s Pydantic models — the schema
  surface for multi-currency is largely already there.
- `services/value/price_sources.py` — a working, provider-registerable USD
  valuation subsystem (`register_price_provider`, `PriceProvider`,
  `PriceObservation`) with a documented, tested "unpriced, never silently
  zero" invariant, peg-aware stablecoin classification
  (`services/stablecoin/valuation.classify_peg`), and an explicit
  `_FX_FIAT_SYMBOLS` set already naming the ten fiat currencies it's aware
  of — currently used for Web3/value valuation, not wired to measurement.
- Every measurement repository's `setdefault("currency", "USD")` /
  `setdefault("exchange_rate", "1.0")` pattern, applied unconditionally
  regardless of the record's actual reported currency.

### Proposed architecture

1. Wire `services/value/price_sources.py`'s existing provider registry into
   the measurement write path: when a `conversion_repo.upsert` or
   `spend_repo.upsert` call carries a `currency` different from
   `normalized_currency`, resolve a real `PriceObservation` and record its
   `conversion_rate` + `conversion_source` instead of writing the hardcoded
   `"1.0"` default.
2. Where no provider can price a currency, follow `price_sources.py`'s own
   invariant: mark the record explicitly unpriced/excluded from
   USD-denominated rollups rather than silently defaulting to 1:1 parity —
   the same "never fabricate a value" discipline the pricing subsystem
   already enforces for Web3 valuations.
3. Extend the FX provider set beyond the ten fiat currencies
   `_FX_FIAT_SYMBOLS` already lists, as tenant demand requires, backed by a
   real rate source with a documented refresh cadence.
4. Surface currency-mix and conversion provenance explicitly in rollups —
   Campaign 360 (`docs/architecture/CAMPAIGN_360_ARCHITECTURE.md`) and
   `attribution_run_repo.py`'s summary responses — so an operator sees
   "this total mixes N currencies converted at rates observed on date D"
   instead of an unlabeled single number.
5. Evaluate whether commerce/x402/stablecoin flows, which already have
   peg-aware valuation via `price_sources.py`, need the same end-to-end
   treatment inside measurement rollups specifically, once the fiat path is
   proven.

### Milestones (sequenced)

- **M1** — Register a real FX provider matching `price_sources.py`'s
  `PriceProvider` signature for the fiat symbols already listed in
  `_FX_FIAT_SYMBOLS`, backed by a documented rate source and refresh
  cadence.
- **M2** — Call `price_sources.py` from `conversion_repo.upsert` /
  `spend_repo.upsert` when `currency != normalized_currency`, replacing the
  hardcoded `"1.0"` default with a real `conversion_rate` +
  `conversion_source` recorded per row.
- **M3** — Change the unpriced case to exclude the record from
  USD-denominated rollups (or flag it) instead of silently defaulting to
  parity — a behavior change that needs its own migration/communication
  plan, since it can change how historical-looking totals read.
- **M4** — Surface currency-mix / conversion provenance in Campaign 360 and
  `attribution_run_repo.py`'s rollup responses.
- **M5** — Evaluate extending the same treatment to commerce/x402/
  stablecoin flows inside measurement rollups.

### First increment

**M1 alone.** Registering one real FX provider against the existing
`register_price_provider` extension point in `price_sources.py` ships with
zero behavior change to measurement — nothing calls it yet — and is pure
additive infrastructure that can be independently verified against known
historical rates before anything downstream depends on it.

### Dependencies

M2 depends on M1. M3 (changing the default-to-parity behavior) depends on
M2 being stable in production and is the highest-risk milestone in this
program — it should ship behind a per-tenant flag, not as a global
cutover. M4 depends on M2/M3. M5 is independent and can start any time
after M1.

### Risks

- **Retroactive readability change**: M3's behavior change (stop silently
  defaulting unpriced currency to USD parity) can change how a tenant's
  *existing* historical rollups read, not just new ingest, if applied
  without care. This needs the same reconciliation-delta treatment called
  out in Program 3 — show the before/after, do not silently reclassify
  history.
- **New external dependency on the ingestion-adjacent path**: FX rate
  sourcing is a new external dependency (provider uptime, cost, rate
  limits). It must be asynchronous and cached, never a synchronous call
  blocking `/v1/batch` or the measurement write path — the pricing
  subsystem's existing "unpriced, never a fabricated 0" invariant already
  points toward this: an unavailable provider should degrade to "unpriced"
  for that record, not stall ingestion.
- **Currency-mix visibility lag**: shipping M1–M3 without M4 leaves
  operators unable to see *why* a rollup total changed once real FX rates
  start applying — M4 should not trail M3 by long in production, or the
  program trades one false-certainty problem (silent USD parity) for
  another (unexplained number movement).

---

## 6. Cross-program sequencing

None of these five programs blocks another at the milestone-1 level, but
their value compounds in a specific order:

- **Start with Program 4 (CI lane).** It has no dependency on the other
  four programs, and it is what turns every other program's "this is
  correct" claim into something CI can actually verify rather than
  something a PR description asserts. Shipping Programs 1–3 without it
  means their transactional guarantees are still only checked manually or
  in production.
- **Programs 1 and 2 can run in parallel** once Program 4's M1 harness
  exists to validate them under real infrastructure. Program 1's hash-chain
  should reach at least its M2 (chained Bronze rows) before Program 2's M3
  (deleting the V1 ingestion path) — having provable Bronze integrity
  first makes it safer to retire the older path that currently offers a
  fallback.
- **Program 3's M1 (re-attribution wiring) is independent and cheap** — it
  reuses existing repository methods and could ship as soon as it is
  reviewed, regardless of where the other programs stand. Program 3's
  later milestones (generalized invalidation, replay) benefit from
  Program 1's chain (for verified replay ranges) and from Program 4 (to
  test replay against real infrastructure, not an in-memory dict).
- **Program 5 is fully independent** of Programs 1–4 and can start at any
  time; its own internal risk (M3, the behavior-change milestone) is the
  gating factor, not any other program.

## 7. Non-goals and explicit disclaimers

- This document authorizes no database migration. The repository's current
  single Alembic head is unaffected; any future migration implementing a
  milestone above must chain from whatever the head is at the time it is
  written, reviewed on its own.
- No code in this repository was changed to produce this document.
- Every "first increment" above is a description of a safe starting slice,
  not a claim that it has been built, scheduled, or estimated in story
  points.
- This document does not update, supersede, or claim consistency with
  `scripts/production_status.py`'s readiness scorecard. No production-
  readiness claim should be drawn from this document; it is a forward
  design reference only, consistent with the `status: experimental`
  marking in its own frontmatter.
- Nothing here proposes weakening an existing validator, skipping an
  existing check, or bypassing the ownership map in
  `docs/source-of-truth/repo_consistency_ownership.json`. Every milestone
  that touches source code, contracts, or generated docs would need to
  satisfy the same gates (`make ci-check`, `docs_drift.py`,
  `validate_contracts.py`, etc.) as any other change when it is actually
  implemented.
