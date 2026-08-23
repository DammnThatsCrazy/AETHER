## What this is

**Credential-Turnkey — re-cut onto current main** (`claude/credential-turnkey-recut`,
base `origin/main`). The credential-turnkey program (financial / economic / commerce /
credential-dependent capabilities) carried as a **focused, merge-ready cut**: the
genuinely-unique program content, tests, boot fixes, regenerated migration,
vocabulary-adapted files, gate, reports, and runbooks — with branch-era surfaces
that main has superseded dropped or re-homed onto main's canonical equivalents.

The posture is unchanged and honest:

> **`CREDENTIAL_TURNKEY` / `CREDENTIAL_WAITING`** — code, contracts, and tests
> correct; fail-closed; durable; observability/entitlement/metering-ready —
> while **explicitly remaining `STAGING_UNVERIFIED` / `PROVIDER_LIVE_UNVERIFIED`**
> until external evidence (live credentials, staging, provider/cloud access)
> exists. The gate exits 0 on this branch.

---

## Why this matters (the problem it solves)

The platform had grown a long tail of capabilities that *looked* shipped but were
not operationally supplyable. An operator handed a new provider, tenant, or
surface could not get it to `CREDENTIAL_WAITING` with **no repository code
change** — the definition of turnkey. Gaps this program closes:

- **Fail-closed was not uniform.** Several worker/transport seams, entitlement
  checks, and credential paths could silently degrade to an "empty healthy" state
  instead of surfacing `failed`/`denied` (e.g. `shared/cis/clickhouse.py` now
  fails closed instead of silently no-oping; `pnl_calculator` now raises
  `PNLUnavailableError` instead of fabricating zero).
- **Lifecycle state was ambiguous.** The import-session FSM had a legacy
  `status` projection that could disagree with the authoritative lifecycle.
- **Money math could drift.** Economic selection/cost paths mixed Decimal and
  float without a stable wire contract (fixed — see *Boot fixes*).
- **Tenant isolation had a hole.** `CommerceService.record_payment` never
  persisted `tenant_id`, so tenant-scoped spend/report reads could observe
  another tenant's payments (fixed).
- **Metering/entitlement/observability were uneven.** Some capabilities had no
  canonical meter, no entitlement gate, or no dashboard/alerts (carried: metering
  evidence families, quota/entitlement gates, payment-rails Grafana dashboard).

The re-cut keeps the *only* remaining work external — never a surprise code
rewrite — and lands it on main's current architecture.

---

## The re-cut, explained

Main advanced while the original program branch (`4ce7e0fc`) was in flight. This
branch is **not** a cherry-pick or a merge of that branch — it is a deliberate
re-cut of the unique surface onto main's head:

| Decision | Surface |
|---|---|
| **Carried** (adapted to main) | Import-session FSM + durable session persistence, payment-rail fleet-health supervision (`kyber_aggregate` computes `outbox_lag`/cursor-age/liveness from real state), stablecoin price write path + polling + price persistence, derivatives durable cursor/sequence/guards/meter/topic-contract, interop scan/reconcile/metering, rewards SVM rail + receipt evidence + claim reconciliation, readiness graph + revalidation worker, credential operator view, commerce rail matrix/reconciliation/metering/workers, x402 signer authority + control plane, economic money-correct models/aggregation, PnL unavailable-not-zero, delivery retryable dead-letter, ClickHouse fail-closed, metering-evidence families, gate + evidence builder |
| **Re-homed onto main's canonical** | Branch-era manifest fields (`transport_protocol` / `base_url_config` / `idempotency_semantics`) → main's `ProviderManifest` (`webhooks`/`sync`/`deployment`) + integration-contract `idempotency_key`; payment-rail Postgres mirror seam (`durability.py`) → main's KV-backed receipt/reconciliation ledgers; stablecoin diagnostics router → main's single operator-gated surface; alert modules → main's `alert_eval.py` |
| **Dropped (superseded by main)** | The branch-era Postgres mirror seam, branch-era manifest/alert modules, and the tests that pinned those APIs (superseded-test drop policy — consistent with the program's established drops) |

---

## What landed, by domain

### State machines & durability
- **Import-session FSM** — [import_session.py](Backend%20Architecture/aether-backend/services/card_linked_payments/import_session.py) + [session_persistence.py](Backend%20Architecture/aether-backend/services/imports/session_persistence.py): guarded `lifecycle_state` machine (`CREATED → … → COMMITTING → COMPLETED`; `REJECTED` / `FAILED` / `DEAD_LETTERED` / `ROLLED_BACK`) with a **parity-safe legacy `status` projection**. Requeue re-stages a `FAILED` or stranded-`COMMITTING` session into `COMMITTING` and re-enqueues a durable `import.commit` under the same id — mapping, validation, `failure_reason`, and `retry_count` preserved for audit.
- **Payment rails** — fleet-health supervision on main's KV-backed ledgers: `kyber_aggregate` computes `outbox_lag` / cursor age / worker liveness from live state, with an *honest-unknown* path (`None`) rather than a fabricated zero. The branch-era Postgres mirror seam was **not carried**; main's ledgers are the canonical durability floor.
- **Stablecoins** — price write path + polling + durable price persistence; append-only reorg rollback (rows **demoted**, never destroyed; audit trail survives).
- **Derivatives / Interop / Rewards** — durable cursors + sequences, explicit topic/stream contracts, scan worker with reorg/restart handling, reconciliation + metering, on-chain reward rails with **SVM re-homed additively** onto main's `MultiChainSigner` (`SHA-256` + base58 + Anchor instruction; fail-closed chain identity), receipt evidence, and claim reconciliation.

### Commerce & x402
- **Commerce** — rail matrix, reconciliation, metering, supervised workers, and **tenant-id persisted on every `PaymentRecord`** so tenant-scoped reports/spend reads can never observe another tenant's payments.
- **x402** — signer authority + repos, control-plane settlement, money-correct commerce models (Decimal on the wire via `@field_serializer`, float at the boundary).

### Economic & PnL
- **Money-correct math** — [ai_models.py](Backend%20Architecture/aether-backend/services/economic/ai_models.py) (Decimal money fields, float-on-wire) + [ai_aggregation.py](Backend%20Architecture/aether-backend/services/economic/ai_aggregation.py) (exact Decimal arithmetic, float at the public boundary) + [gold_materializer.py](Backend%20Architecture/aether-backend/services/economic/gold_materializer.py) (canonical rewrite) + computed-results writer.
- **PnL** — [pnl_calculator.py](Backend%20Architecture/aether-backend/services/pnl/pnl_calculator.py): `PNLUnavailableError` wired into the failure paths — **unavailable is never zero**.

### Credentials, capabilities & readiness
- **Credential authority** — operator view that is **safe (no secret decryption)**, a dead-letter sweeper, and a slot registry derived from adapters' own descriptors; fail-closed guards enforce required env outside local.
- **Capabilities/readiness** — enforcement + readiness repo, tenant readiness demotion, and a readiness graph; certification registry at 29 first-release providers, all `credential_waiting` (none `SCAFFOLDED`, none `PARTNER_LIVE` — an honest pre-production posture, not a release claim).

### Observability, entitlement & metering
- Capability-metadata evidence families, metering hooks + reconciliation, storage-policy registry extended to every new table, and a payment-rails Grafana dashboard (from the deploy observability tree).

### Delivery & runtime
- [outcome_processor.py](Backend%20Architecture/aether-backend/services/delivery/outcome_processor.py): retryable dead-letter delta — a failed delivery is surfaced, replayable, never silently dropped; [worker.py](Backend%20Architecture/aether-backend/services/delivery/worker.py), `dead_letter_sweeper`, worker specs/topology, and the supervisor handle.

### Gate, evidence & docs
- **[scripts/credential_turnkey_gate.py](scripts/credential_turnkey_gate.py)** (+ `--strict`) and [scripts/build_credential_turnkey_evidence.py](scripts/build_credential_turnkey_evidence.py)
- **Reports (rewritten for the re-cut)** — [credential-turnkey-capability-matrix.md](reports/credential-turnkey-capability-matrix.md) (10 capabilities × evidence, C/M/R/⛔ carried/main/re-homed/pending-external) and [credential-turnkey-external-blockers.md](reports/credential-turnkey-external-blockers.md) (every external item, each annotated with whether a **repository coding blocker** remains)
- **Runbooks** — [billing-attachment-runbook.md](docs/billing-attachment-runbook.md) + [staging-activation-runbook.md](docs/staging-activation-runbook.md)
- **Migration** — [20260901_credential_turnkey_tables.py](Backend%20Architecture/aether-backend/alembic/versions/20260901_credential_turnkey_tables.py), regenerated onto main's migration head
- **Deploy + config** — kafka topic-provisioner (module + tests + `topics.json`), ClickHouse terraform, `DEPLOYMENT_CONTRACT.yaml`, `config/storage_policies.yaml`, `Makefile` targets (`credential-turnkey`, `-strict`, `-evidence`)
- **Frontend seams** — activation uses tenant readiness; API endpoint registration

---

## Boot fixes carried on this cut

Five fixes that make the carried surface deterministic and correct against main's
architecture (each verified by the tests it unblocks):

1. **Money-wire coercion** — [ai_costs.py](Backend%20Architecture/aether-backend/services/economic/ai_costs.py) coerces the observed Decimal costs to float at the `CostSelection` boundary (`test_costs` 9/9).
2. **Commerce tenant isolation** — [models.py](Backend%20Architecture/aether-backend/services/commerce/models.py) adds `tenant_id` to `PaymentRecord`; [service.py](Backend%20Architecture/aether-backend/services/commerce/service.py) persists it on every `record_payment` (tenant-isolation suite green).
3. **FX snapshot re-assertion** — [routes.py](Backend%20Architecture/aether-backend/services/economic/routes.py) re-registers the FX provider in `_aggregate_spend` so the USD conversion never depends on import order or a cleared provider registry.
4. **Store-reset hygiene (flake root cause)** — [conftest.py](Backend%20Architecture/aether-backend/tests/adversarial/conftest.py) now resets `shared.store`'s registry alongside `repositories.repos`/`typed_repo`, matching the repo's own documented dual-reset convention (the adversarial receipt suite was leaking `payment_provider_receipts` rows into `tests/payment_rails/test_alert_eval.py`, causing an intermittent empty-plane failure under xdist).
5. **Stale x402 store singletons (suite-order flake root cause)** — [test_commerce_domain_closure.py](Backend%20Architecture/aether-backend/tests/unit/test_commerce_domain_closure.py) now also resets the control plane + facilitator/asset registries, which capture the commerce store at construction. `reset_commerce_store()` replaces the store singleton, so leaving those singletons alive made routing read an old cleared store ("No facilitator for asset/chain/environment") whenever a prior test file constructed the control plane first. Fix verified deterministic: `unit/` and full backend suite both green single-process (`-n 0`) and under xdist.

---

## How it works

1. **Operators never hand-edit state.** Every mutation goes through the FSM / the
   app's own gates (`require_transition`, `mark_failed`, requeue, sweep).
2. **Fail-closed by construction.** No tenant may reach Kyber surfaces; required
   credentials raise, never silently degrade; absence of state is `UNKNOWN`, never
   a fabricated zero.
3. **Evidence is append-only.** Rollbacks demote; audit tables record; meters
   have canonical names.
4. **The gate is a single command.** `make credential-turnkey` (+ `--strict`)
   resolves the live capability matrix from the registry, workers, migrations,
   routes, and tests — nothing hand-written into the report.
5. **External blockers are first-class.** Each has an explicit "is this a repo
   blocker?" answer so the org can act with confidence.

## Meaning for the graph

- **Every carried capability is now a vertex that can be certified** — the
  readiness graph connects capabilities → providers (29, all `credential_waiting`)
  → credential slots → worker/transport seams → durable tables → meters →
  operator surfaces, all resolvable from real repo state.
- **Honesty is built into the graph posture:** `CREDENTIAL_WAITING` is a
  pre-production state by design; nothing on this branch claims live verification
  it cannot back with evidence.
- **The graph is re-provable on every commit** — the gate regenerates the
  capability matrix from the code itself, so drift between "what we say" and
  "what the code does" is caught by CI, not discovered by an operator in staging.

## Gate evidence (this branch, this run)

| Gate | Result |
|---|---|
| `make docs-fix` | **42/42** |
| `make ci-check` | **62/62** (canonical completion gate) |
| backend pytest (`Backend Architecture/aether-backend/tests`) | **5614 passed / 2 skipped** |
| root pytest | **5282 passed / 6 skipped** |
| `make credential-turnkey` | **38 rows — 36 pass / 0 fail / 2 advisory** |
| `make credential-turnkey-strict` | **PASS (no FAIL rows)** |

> All gates green on this branch at PR time. The two advisory rows are
> **"Documentation current"** (docs present; currency not independently
> verifiable) and **"CI green"** (the gate declares the CI chain; the live run is
> the evidence) — both non-blocking and reflected in the reports.

---

## Documentation Impact

- **Generated docs regenerated (never hand-edited):** `docs/_generated/doc-manifest.json`,
  `docs/REPO-INDEX.md`.
- **Authored docs updated:** the two new runbooks; both program reports rewritten
  for the re-cut surface.
- **Source-linked docs:** reviewed per `CLAUDE.md`; `python scripts/docs_drift.py`
  is clean on this branch (any stale stamps would have failed `make ci-check`).

## Known Risks / Intentionally-open items

- **Card-linked capability is still `PARTIAL`** for full turnkey (no entitlement
  gate / meter / observability dashboard / infra / tenant UI) — tracked in the
  capability matrix §2.5; a named gap, not a hidden one.
- **Repo-local integration-pass items** remain for a few seams — each listed as
  `PARTIAL` with its exact path in the capability matrix §3 (card-linked 2/5,
  interop entitlement absent, derivatives reconciliation not carried — superseded
  by main's runtime plane, missing dedicated Grafana dashboards).
- **External blockers** (chain RPC keys, venue keys, webhook secrets, provider
  registration, Kafka topics, Postgres provisioning, KMS, live network reach)
  are all **PENDING EXTERNAL** — with **"no repository coding blocker = true"**
  for nearly every item (see the external-blockers report).
- **Not a release claim:** `CREDENTIAL_WAITING` ≠ `PROVIDER_LIVE`; the
  production-status scorecard still reflects `STAGING_UNVERIFIED` /
  `PROVIDER_LIVE_UNVERIFIED` until live evidence lands.
