---
title: "Staging Readiness Dossier"
slug: readiness/staging-readiness-dossier
section: operations
visibility: I
audience: [ops, architect, exec]
status: stable
source_files:
  - scripts/staging_preflight.py
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: "9aa8d51b"
---

# Staging Readiness Dossier

What "ready for staging" means for AETHER, and how to prove it with the gates
that already exist. Staging is not a smaller production — it is the environment
where the pre-production and scale blockers get **validated for the first time**
against real backends. This dossier sequences that; it does not replace
`docs/productization/staging-capstone/STAGING_DEPLOYMENT_GUIDE.md` or
`docs/runbooks/STAGING_PREFLIGHT.md`.

**Verdict up front: GO to attempt staging bring-up**, provided the gates in §3
are green. Staging is exactly where the open P1/P2 items are meant to be closed.

---

## 1. Profile

- **Deployment profile:** `staging` (`AETHER_ENV=staging`). Real backends are
  mandatory — in-memory fallbacks are dev/test only and are refused in hosted
  modes.
- **Flags:** every economic / agent / activation / mission rollout flag defaults
  **OFF**. Staging enables **one subsystem at a time**, validates one lifecycle
  end to end, captures pilot evidence, then moves on.
- **Data:** deterministic demo-seed (#494) for live-empty honesty; never point
  staging at production data until tenant isolation is verified.

---

## 2. Expected services

Staging requires the real stack stood up (per the Terraform deployment profile,
#492):

- **Postgres** — durable relational + Alembic head parity.
- **Redis** — idempotency, caches, and hosted-mode agent durability.
- **Neptune** — graph writes/traversal (H2H/H2A/A2H/A2A).
- **Kafka** — event bus + economic-domain streams.
- **ClickHouse** — medallion Gold + CIS health engine.
- **S3** — object storage / lake.
- Backend API (65+ routers), Kyber operator console, tenant frontend.

Absence of any of these is a preflight FAIL, not a soft-start.

---

## 3. Required gates (mapped to real Makefile targets)

Run these in order. Each maps to a real target; do not substitute a narrower
check for a broader one.

| Gate | Command | What it proves | Fail-closed? |
|------|---------|----------------|--------------|
| Repo consistency | `make ci-check` | Registry test suite (7 CI pytest suites, skip = FAIL) + `npm run test` + ~40 validators; no generated-doc diff | Yes |
| Staging preflight | `make staging-preflight` | env/`Settings()` construction under real env, DB connect + Alembic head + table-shape parity, Redis PING, contracts | Yes |
| Live HTTP leg | `python scripts/staging_preflight.py --base-url https://api.staging.aether.io` | `GET /v1/health` + `GET /v1/ready` against the live deployment | Yes (but SKIPs without `--base-url`) |
| Readiness scorecard | `make production-status` | 30-area scorecard + declared blockers + live consistency checks | Advisory |

**Preflight honesty — read this before trusting a green run:**

- `make staging-preflight` with no `--base-url` **SKIPs the HTTP leg**. A green
  preflight without `--base-url` has *not* checked `/v1/health` or `/v1/ready`.
- `--dry-run` is a **self-test of the gate itself** against committed fixtures
  (`tests/fixtures/staging_preflight/{valid,invalid}.env`). It proves the gate
  fails closed; it **never certifies a live environment**.
- `/v1/ready` **skips the migration check when there is no DB pool**. Run the
  live HTTP leg against a deployment that has its pool, or the readiness probe
  cannot prove migration parity.

---

## 4. Smoke tests

After the gates are green and before enabling any subsystem:

1. **Health/ready:** `/v1/health` 200 and `/v1/ready` 200 with a real DB pool
   (migration check must actually run).
2. **Ingestion round-trip:** one event through `/v1/batch` → durable Bronze
   write → ACK; confirm the row lands.
3. **Identity resolve:** `/sdk/identity/resolve` returns a resolution with
   confidence.
4. **Activation FSM (if `AETHER_ACTIVATION_ENABLED`):** walk
   `/v1/activation/status → select-plan → sdk-selection → create-sdk-keys →
   test-event → first-value → complete`; confirm `complete` is refused until
   `first_value_ready`.
5. **Load smoke:** `make load-smoke` (20 users, 30s) — fails closed on
   unreachable backend, zero traffic, or threshold breach.

---

## 5. Blockers to clear IN staging

Staging is the environment that closes most of these (from
`scripts/production_status.py`):

- ML serving artifacts not trained/published (P1).
- Dune feeder disabled until `DUNE_BACKEND` provisioned (P1).
- Derivatives streams on local transport — Kafka topics unprovisioned (P1).
- Gold ClickHouse DDL for economic domains unexecuted (P1).
- No recorded load baselines; Neptune throughput/cost unvalidated (P2).
- Distributed tracing is a seam only — no OTel SDK/exporter (P1).

The four P0 release-blockers (unaudited contracts, live provider credentials,
production infra + secrets, agent hosted-mode durability) are **not** staging's
to clear for a *validation* deployment — they gate lean-production, not staging
bring-up.

---

## 6. Cost posture

Staging runs the full backend set but at validation scale, not production scale:
single small nodes per service, no multi-AZ redundancy required, economic
provider polling OFF (no live-API spend), ML serving OFF until artifacts exist.
The dominant costs are Neptune and ClickHouse baseline capacity — validate their
throughput/cost here so the first large tenant does not discover it in
production.

---

## 7. Rollback

- **Subsystem rollback:** flag OFF. Every wave is designed so a single flag
  returns the platform to its prior behavior on any SLO breach.
- **Deploy rollback:** per `docs/DEPLOYMENT-RUNBOOK.md` /
  `docs/productization/staging-capstone/DISASTER_RECOVERY_GUIDE.md`.
- **A failing preflight blocks traffic.** Never override it "just to test".

---

## 8. Score before / after

| | Score | Note |
|--|-------|------|
| **Before staging** | ~3.77 / 5 (pre-production) | Tested against in-memory/local fallbacks; no live provider; no recorded baselines |
| **After a clean staging soak** | Still ~3.77 at bring-up | Bringing staging *up* does not raise scores. Scores rise only as specific P1/P2 items are validated with evidence (live provider → provider plane; recorded baselines → scale readiness; executed ClickHouse DDL → interop) |

Staging does not itself move the number; the **evidence produced in staging**
does, one area at a time, via `scripts/production_status.py`.

---

## 9. Go / no-go

- **Staging bring-up: GO** when `make ci-check` and `make staging-preflight`
  (with the live HTTP leg) are green.
- **Enable a subsystem: GO** one at a time, each with an end-to-end lifecycle
  validation and captured pilot evidence; roll back (flag off) on any SLO
  breach.
- **Promote staging → production: NO-GO** from staging alone — see
  `docs/readiness/LEAN_PRODUCTION_READINESS_DOSSIER.md`.

See also: `docs/productization/staging-capstone/STAGING_DEPLOYMENT_GUIDE.md`,
`docs/runbooks/STAGING_PREFLIGHT.md`,
`docs/implementation/AETHER_KYBER_RELEASE_STATE.md`.
