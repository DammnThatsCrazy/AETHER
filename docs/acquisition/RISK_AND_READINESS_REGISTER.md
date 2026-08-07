---
title: "Risk & Readiness Register"
slug: acquisition/risk-and-readiness-register
section: operations
visibility: I
audience: [exec, buyer, ops]
status: stable
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: "e9fc085"
---

# Risk & Readiness Register

An honest, single-source risk register for a diligence team. Every risk below is
traceable to the canonical scorecard (`scripts/production_status.py`) or to a
declared caveat in the CI / preflight gates. Nothing here is softened; the point
of this document is that the risks are **known, tracked, and bounded** — not
discovered in production.

Severity legend: **P0** release-blocker · **P1** pre-production · **P2**
scale-blocker · **P3** watch-item.

---

## 1. Register (ranked)

| # | Risk | Sev | Area / evidence | Status | Mitigation / next step |
|---|------|-----|-----------------|--------|------------------------|
| R1 | Smart contracts unaudited — no external certification | P0 | smart contracts / proofs | Open | External audit before any mainnet / real-funds deploy; proofs stay gated |
| R2 | Production infra not provisioned; secrets not loaded | P0 | deployment / cloud readiness | Open | Stand up Terraform stack; `scripts/bootstrap_aws_secrets.py` |
| R3 | Agent hosted-mode requires durable storage (in-memory refused in hosted modes) | P0 | graph mutation safety | Open | Provision Redis-or-equivalent for hosted control plane |
| R4 | Zero PARTNER_LIVE providers — all 18 resolve to CREDENTIAL_WAITING | P0 | provider certification plane | Open | Validate ≥1 live provider per enabled domain |
| R5 | ML serving artifacts not trained/published | P1 | deployment / cloud readiness | Open | Train + publish artifacts for serving |
| R6 | Distributed tracing is a seam only — no OTel SDK/exporter | P1 | observability / tracing | Open | Integrate OTel SDK/exporter; the seam is not coverage |
| R7 | Dune feeder disabled until `DUNE_BACKEND` provisioned | P1 | Dune / data-lake feeders | Open | Provision staging backend; enable scheduled polling |
| R8 | Derivatives streams on local transport — Kafka topics unprovisioned | P1 | derivatives intelligence | Open | Provision Kafka topics in staging |
| R9 | Gold ClickHouse DDL for economic domains unexecuted | P1 | interoperability intelligence | Open | Execute DDL in provisioned ClickHouse |
| R10 | Payment-rail plane has no live provider polling/validation | P1 | payment rail observability | Open | Validate one live rail in staging (flags default OFF) |
| R11 | No staging load baselines recorded | P2 | scale readiness | Open | `make load-baselines` against staging |
| R12 | Neptune capacity/cost + merge throughput unvalidated at scale | P2 | Neptune relationships | Open | Replay synthetic merge/traversal against provisioned Neptune |
| R13 | ClickHouse/medallion compaction validated locally only | P2 | Dune / data-lake feeders | Open | Staging soak of retention + compaction |
| R14 | Semantic intelligence: no validated model provider, no live traffic | P3→P1 on enable | semantic intelligence (2/5) | Pilot | Validate a production model provider + durable store in staging |
| R15 | Card-linked payment rails wired but flag-off, no live provider | P3→P1 on enable | card-linked payment rails (2/5) | Pilot | Validate a live provider before enabling |

---

## 2. CI / gate-truth risks (the #493 concern — CLOSED with four caveats)

The gate hole feared in #493 is closed on `main`: `make ci-check` runs the
registry suite (seven `skip_policy: never` CI pytest suites with
`hard_fail_skip`, so **a skip is a FAIL**) plus `npm run test` and ~40
validators, and `validate_test_suite_coverage.py` asserts declared == executed.
Four residual caveats remain **declared, not silent**:

| # | Caveat | Diligence implication |
|---|--------|-----------------------|
| C1 | Hardhat suite runs in a separate GitHub workflow, not in `repo_doctor` | Contract tests are green but outside the ci-check process — verify the workflow, not just ci-check |
| C2 | `npm --workspaces --if-present` can skip a workspace lacking a `test` script | Confirm each workspace that should be tested has a test script |
| C3 | `/v1/ready` skips the migration check with no DB pool | A poolless readiness probe cannot prove migration parity — run the live leg with a pool |
| C4 | staging-preflight HTTP SKIPs without `--base-url` | A green preflight without `--base-url` did not check `/v1/health` or `/v1/ready` |

Green ci-check means "the registry suite and validators passed", **not**
"everything possible was tested". That distinction is the honest reading.

---

## 3. Open-dependency risk (not merged)

These are open drafts; their contents are **not** shipped and must not be counted
as present in diligence:

| Draft | Scope | Risk if assumed shipped |
|-------|-------|-------------------------|
| #501 | Billing `plan_tier` + settings/sessions + SDK durability | Do not assume billing plan_tier work is live; the activation FSM does not depend on it |
| #500 | Mobile | Do not assume mobile scope is delivered |
| #502 | CI containment | Do not assume the additional CI containment is in force |

---

## 4. This branch's four waves — bounded, flag-gated, non-score-moving

Every wave on `claude/aether-kyber-production-if4m8m` defaults **OFF** and is
inert in a default deployment. **None of them move the ~3.77 overall.**

| Wave | State | Risk posture |
|------|-------|--------------|
| Tenant routing fix | Correctness fix | Low — no new default behavior |
| Activation FSM (`services/activation`, `/v1/activation/*`) | Real service + migration, flag OFF | Bounded — reuses registration key-mint + in-process `/v1/batch`; refuses `complete` until Bronze first value |
| Kyber Missions | Migration + flag-gated monitoring-loop **scaffold** (orchestrator not in tree) | Honest — present as scaffolding; do **not** count a mission aggregate as landed |
| These dossiers | Docs only | None |

---

## 5. Non-goals (deliberate — not risks, scope boundaries)

Stating these prevents a diligence team from mis-filing a scope boundary as a
gap (`docs/productization/staging-capstone/LIMITATIONS_AND_NON_GOALS.md`):

- **Execution / custody.** Observation-only, no-custody by construction — never
  initiates/settles a payment, places/cancels a trade, sends a cross-chain
  message, or holds funds.
- **Direct agent graph mutation.** Every mutation is staged → operator-approved →
  committed.
- **Optimistic readiness.** The certification plane refuses to infer
  `production_ready` from structure; scores never move without live + security
  evidence.
- **Bare-zero metrics.** The measurement integrity plane never emits a bare `0`
  on missing data — it carries an explicit `value_state`.

---

## 6. Overall readiness statement

- **Overall: ~3.77 / 5 — pre-production** (`make production-status`).
- **Mainnet / real-funds rails / paid production traffic: NO-GO** until R1–R4
  clear.
- **Staging bring-up for validation: GO** behind the staging profile's gates
  (`docs/readiness/STAGING_READINESS_DOSSIER.md`).
- **Acquisition presentation: GO**, honestly, with this register on the table.

The defining characteristic of this asset is that its own tooling enforces the
honesty of this register. A risk that stopped being true would fail a live
consistency check in `production_status.py --strict`; a risk that is newly true
would surface in the same place. The register is not a snapshot to be trusted —
it is a routine to be re-run.

See also: `docs/implementation/AETHER_KYBER_RELEASE_STATE.md`,
`docs/acquisition/PRODUCTIZATION_DOSSIER.md`,
`docs/productization/aether_productization_audit.md`.
