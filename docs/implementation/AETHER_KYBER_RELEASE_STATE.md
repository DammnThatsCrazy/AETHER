---
title: "AETHER × Kyber Release State"
slug: implementation/aether-kyber-release-state
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
estimated_read_minutes: 14
toc_depth: 3
---

# AETHER × Kyber Release State

Single-page truth for where the platform stands at the head of
`claude/aether-kyber-production-if4m8m`. This document narrates; the machine
truth is `make production-status` (`scripts/production_status.py`). If the two
disagree, re-run the routine and correct this page — the script wins.

The one-line posture: **pre-production, release-shaped, gated by a short list of
known blockers.** Overall readiness is **~3.77 / 5**. Nothing on this branch
changes that number, by design (see §5).

---

## 1. Base and foundation

**Base SHA:** `a588563` — the merge point this branch was cut from. The merged
foundation underneath it:

| PR | What it landed |
|----|----------------|
| #420 | Durable jobs + scheduler, RFC 9457 problem-details, correlation-id propagation |
| #491 | Kyber workforce / graph / mirror / governed commands |
| #492 | Deployment profiles (staging / lean-production) |
| #494 | Data-truth + demo-seed (deterministic seed, live-empty honesty) |
| #499 | Communications Intelligence (credential-turnkey Klaviyo) |

This branch's own scaffold commit (`b858a66`) adds flag-gated wiring and two
Alembic migrations for tenant activation and Kyber missions — nothing that runs
by default (see §4).

---

## 2. CI / gate-truth — the #493 concern is CLOSED (with four honest caveats)

The historical worry (#493) was that the CI gate could pass while silently
skipping suites. On `main` that hole is closed:

- `make ci-check` runs `repo_doctor --ci`, which executes the **registry suite**
  from `config/test_suites.yaml`: seven CI pytest suites carrying
  `skip_policy: never`, run with `hard_fail_skip` so a **skip is a FAIL**, not a
  pass.
- `validate_test_suite_coverage.py` asserts **declared == executed** — a suite
  cannot be dropped from execution without failing the coverage check.
- Alongside: `npm run test` and ~40 validators (contracts, SDK alignment,
  frontmatter, source-linked drift, version alignment, generated-doc diff).

This is a real gate, not a rubber stamp. It is also not omnipotent. Four caveats
are stated openly so nobody mistakes green CI for total coverage:

1. **Hardhat suite runs in a separate GitHub workflow**, not inside
   `repo_doctor`. Its green is real but lives outside the ci-check process.
2. **`npm --workspaces --if-present`** can skip a workspace that lacks a `test`
   script — absence of a script reads as absence of failure.
3. **`/v1/ready` skips the migration check when there is no DB pool** — a
   poolless readiness probe cannot prove migration parity.
4. **staging-preflight HTTP checks SKIP without `--base-url`** — the gate is
   fail-closed on what it runs, but it does not run the live HTTP leg unless
   pointed at a deployment.

None of these are silent: each is a declared, tracked caveat. Treat green
ci-check as "the registry suite and validators passed", not "everything that
could ever be tested passed".

---

## 3. Open dependencies (NOT merged — state them as drafts)

These are open drafts. Do not describe their contents as shipped:

| Draft | Scope | Status |
|-------|-------|--------|
| #501 | Billing `plan_tier` + settings/sessions + SDK durability | Open draft |
| #500 | Mobile | Open draft |
| #502 | CI containment | Open draft |

The activation FSM on this branch reuses the existing registration key-mint and
in-process batch path; it does **not** depend on #501's billing work landing.
Where a dossier references plan tiers it references today's plan-tier gating in
the backend, not #501.

---

## 4. What this branch adds — four waves, all flag-gated OFF

Every item below defaults OFF and is inert in a default deployment. They are
staged so each can be enabled, validated once end-to-end, and rolled back
independently.

1. **Tenant routing fix.** Correctness fix to tenant resolution; behind the same
   routing path, no new default behavior.
2. **Self-serve activation FSM** (`services/activation`, `/v1/activation/*`,
   flag `AETHER_ACTIVATION_ENABLED`). A real service — `models.py`,
   `repository.py`, `routes.py`, `service.py` plus migration
   `20260814_activation_state.py`. The FSM reuses the registration key-mint,
   drives an event through the **in-process** `/v1/batch` ingestion path, and
   proves Bronze first-value before `POST /v1/activation/complete` is allowed
   (`complete` is refused until `first_value_ready`). It mints raw SDK keys once
   and never echoes them again.
3. **Kyber Mission aggregate** (`/v1/kyber/missions`, flags
   `KYBER_MISSIONS_ENABLED` and `KYBER_MISSION_MONITORING_ENABLED`, both OFF by
   default). Landed as real modules under `services/kyber/ops/`:
   `mission_contracts.py`, `mission_repository.py`, `missions.py`,
   `monitoring_service.py`, and `mission_routes.py`, plus migration
   `20260815_kyber_missions.py`. It is a thin-root Mission aggregate with
   read-time composition over the existing
   Objective/Plan/WorkerRun/Evidence/Verification/Job/Command planes, a
   first-class `MonitoringCondition`, a structural `completed != verified` gate,
   and workforce-identity-scoped routes (capability `kyber.incident.read`, never
   tenant auth). Flag-gated OFF and tested against in-memory/local fallbacks — so
   it is release-shaped, not production-proven, and does not move the Kyber score.
4. **These dossiers** (docs only).

---

## 5. Measured productization scorecard (0–5)

Rubric: 0 absent · 1 stub · 2 partial/pilot · 3 pre-production · 4 release-ready
(minor gaps) · 5 production + scale ready. Canonical source:
`scripts/production_status.py` — run `make production-status` for the live table
with evidence paths.

| Area | Score |
|------|-------|
| backend/API | 4 |
| SDKs | 4 |
| identity resolution | 4 |
| Profile 360 | 5 |
| Neptune relationships (H2H/H2A/A2H/A2A) | 4 |
| graph mutation safety | 4 |
| graph health / drift detection | 4 |
| Kyber (operator console) | 4 |
| customer frontend (tenant app) | 5 |
| connectors (BYOK / source) | 4 |
| Slack / action notifications | 4 |
| Dune / data-lake feeders | 4 |
| smart contracts / proofs / rewards | 4 |
| security / compliance | 4 |
| agentic_x402_productization | 4 |
| CI / tests | 4 |
| measurement / attribution | 4 |
| measurement integrity plane | 4 |
| tenant import engine | 4 |
| campaign intelligence | 5 |
| docs | 4 |
| deployment / cloud readiness | 3 |
| scale readiness | 3 |
| provider certification plane | 4 |
| stablecoin intelligence | 3 |
| derivatives intelligence | 3 |
| interoperability intelligence | 3 |
| payment rail observability | 3 |
| semantic intelligence | 2 |
| card-linked payment rails | 2 |

**Overall: ~3.77 / 5 — pre-production.** Three areas sit at 5 (Profile 360,
customer frontend, campaign intelligence). Most core surfaces are 4
(release-ready with minor gaps, tested against in-memory/local fallbacks). The
economic domains (stablecoin/derivatives/interop/payment-rail) sit at 3, and the
two least-mature planes (semantic intelligence, card-linked rails) at 2. The
four waves above do **not** move this number: they are flag-gated OFF, add no
live provider, and carry no production traffic.

---

## 6. Prioritized blocker table

Severities mirror the blockers emitted by `scripts/production_status.py`.

| Pri | Blocker | Area | Class | Next step |
|-----|---------|------|-------|-----------|
| P0 | Smart contracts unaudited | smart contracts / proofs / rewards | release-blocker | External certification before any mainnet / real-funds deploy |
| P0 | Production infra not provisioned; secrets not configured | deployment / cloud readiness | release-blocker | Stand up Terraform stack; `scripts/bootstrap_aws_secrets.py` |
| P0 | Agent Layer hosted mode needs durable storage | graph mutation safety | release-blocker | Provision Redis-or-equivalent for hosted control plane |
| P0 | Zero PARTNER_LIVE providers — all 18 CREDENTIAL_WAITING | provider certification plane | release-blocker | Validate at least one live provider per enabled domain |
| P1 | ML artifacts not trained/published | deployment / cloud readiness | pre-production | Train + publish serving artifacts |
| P1 | Distributed tracing is a seam only (no OTel SDK/exporter) | observability / tracing | pre-production | Integrate OTel SDK/exporter; the seam is not coverage |
| P1 | Dune feeder disabled until `DUNE_BACKEND` provisioned | Dune / data-lake feeders | pre-production | Provision staging backend; enable scheduled polling |
| P1 | Derivatives streams on local transport (Kafka topics unprovisioned) | derivatives intelligence | pre-production | Provision Kafka topics in staging |
| P1 | Gold ClickHouse DDL for economic domains unexecuted | interoperability intelligence | pre-production | Execute DDL in a provisioned ClickHouse |
| P1 | Payment-rail plane has no live provider polling/validation | payment rail observability | pre-production | Validate one live rail in staging (flags default OFF) |
| P2 | No staging load baselines recorded | scale readiness | scale-blocker | `make load-baselines` against staging |
| P2 | Neptune capacity/cost + merge throughput unvalidated | Neptune relationships | scale-blocker | Replay synthetic merge/traversal against provisioned Neptune |

---

## 7. Readiness by target profile

Three distinct go/no-go questions, three distinct answers.

| Target | Score | Verdict |
|--------|-------|---------|
| **Staging bring-up** | Ready to attempt | **GO** — with the profile's gates green. The machinery exists (`make staging-preflight`, `make ci-check`); staging is where the P1/P2 items get validated. See `docs/readiness/STAGING_READINESS_DOSSIER.md`. |
| **Lean production (paid traffic)** | Not ready | **NO-GO** — P0 blockers stand: unaudited contracts, unprovisioned infra, no live provider, agent hosted-mode durability. See `docs/readiness/LEAN_PRODUCTION_READINESS_DOSSIER.md`. |
| **Acquisition / diligence** | Ready to present | **GO to present, honestly** — the platform is a credible, well-gated pre-production asset. The acquisition dossiers state limitations as plainly as strengths. See `docs/acquisition/`. |

---

## 8. Overall go / no-go

- **Mainnet / real-funds rails / paid production traffic: NO-GO.** Non-negotiable
  until the four P0 blockers clear.
- **Staging deployment for validation: GO** behind the staging profile's gates.
- **Acquisition presentation: GO** with the honesty guardrails intact.

The honest summary: a real, tested, unusually well-gated platform at ~3.77/5.
The gap to production is operational and go-to-market (provisioned infra, live
provider credentials, external audit, recorded scale baselines), not
architectural. The four flag-gated waves on this branch extend the surface
(self-serve activation, Kyber Mission aggregate — both flag-gated OFF) without inflating the score.

See also: `docs/productization/aether_productization_audit.md`,
`docs/productization/staging-capstone/LIMITATIONS_AND_NON_GOALS.md`,
`docs/implementation/BEFORE_AFTER_PRODUCTIZATION_REPORT.md`.
