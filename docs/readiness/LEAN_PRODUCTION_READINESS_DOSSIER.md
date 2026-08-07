---
title: "Lean Production Readiness Dossier"
slug: readiness/lean-production-readiness-dossier
section: operations
visibility: I
audience: [ops, architect, exec]
status: stable
source_files:
  - scripts/staging_preflight.py
canonical_owner: platform@aether
estimated_read_minutes: 11
toc_depth: 3
last_synced_commit: "e9fc085"
---

# Lean Production Readiness Dossier

What "lean production" would require — a minimal, cost-conscious production
footprint accepting real (but bounded) traffic — and an honest statement of why
AETHER is **not there yet**.

**Verdict up front: NO-GO for paid production traffic.** Four P0 release-blockers
stand. This dossier exists so that the day they clear, the path is already
written and gated, not improvised. Overall readiness today is **~3.77 / 5**
(`make production-status`).

---

## 1. Profile

- **Deployment profile:** `lean-production` (#492) — real backends, real
  secrets, production `AETHER_ENV`, no in-memory fallbacks anywhere.
- **Scope discipline:** lean means *fewer enabled subsystems*, not *weaker
  gates*. Economic domains stay OFF until a live provider per domain is
  validated. Mainnet reward proofs stay OFF until external audit.
- **No-custody / observation-only** is a construction invariant, not a config —
  it does not change between staging and production.

---

## 2. Expected services

Everything staging requires (Postgres, Redis, Neptune, Kafka, ClickHouse, S3,
backend, Kyber, tenant frontend), plus production-grade posture:

- Multi-AZ / redundancy for the durable stores per the lean-production Terraform
  profile.
- Loaded production secrets (`scripts/bootstrap_aws_secrets.py`).
- Published ML serving artifacts for any intelligence that serves models.
- Durable storage provisioned for **agent hosted-mode** (in-memory fallback is
  refused in hosted modes — this is a P0).

---

## 3. Required gates (mapped to real Makefile targets)

| Gate | Command | Role for lean production |
|------|---------|--------------------------|
| Release gate | `make release-gate` | The canonical release gate: `ci-check` (CI mode) + **strict** production status + ops readiness + founding-tenant control spine |
| Repo consistency | `make ci-check` | Registry suite (skip = FAIL) + `npm run test` + ~40 validators; no generated-doc diff |
| Staging preflight (live) | `python scripts/staging_preflight.py --base-url <prod-url>` | env/`Settings()`, DB + Alembic head + table-shape parity, Redis, **live** `/v1/health` + `/v1/ready` |
| Readiness scorecard (strict) | `make production-status` (release-gate runs it `--strict`) | 30-area scorecard + declared blockers + live consistency checks |
| Scale baselines | `make load-baselines` | Recorded RPS/latency baselines against a provisioned environment |

**Gate honesty:**

- `make release-gate` runs production status in `--strict` mode, which fails on
  live **consistency-check** failures — it does not fail merely because declared
  blockers exist (declared, tracked work must not paint the gate permanently
  red). So a green release-gate means "the repo is internally consistent and ops
  spine is present", **not** "there are zero blockers". The blockers in §4 are
  tracked, not gate failures.
- `staging_preflight.py` only runs the HTTP leg **with `--base-url`**; run it
  against the real production URL, not `--dry-run` (which only self-tests the
  gate against fixtures and never certifies a live environment).
- `/v1/ready` skips the migration check with no DB pool — the production probe
  must run with its pool.

---

## 4. Blockers — why lean production is NO-GO today

The four P0 release-blockers (`scripts/production_status.py`):

1. **Smart contracts unaudited.** No external certification. **Do not deploy to
   mainnet with real funds.** On-chain reward proofs stay gated.
2. **Production infra not provisioned; secrets not configured.** Terraform
   exists but is not stood up; production secrets are not loaded.
3. **Agent Layer hosted mode requires durable storage.** In-memory fallback is
   blocked in hosted modes; needs Redis-or-equivalent provisioned.
4. **Zero PARTNER_LIVE providers.** All 18 first-release providers resolve to
   `CREDENTIAL_WAITING` — code-complete, infra-defined, credential-gated, none
   validated against a live endpoint. Economic domains cannot carry real traffic
   without at least one validated live provider per enabled domain.

P1 pre-production items that must also close before the corresponding subsystem
serves production traffic: ML artifacts published; OTel SDK/exporter integrated
(the tracing seam is not coverage); `DUNE_BACKEND` provisioned; Kafka topics for
derivatives; Gold ClickHouse DDL executed; a live payment rail validated.

**Non-negotiable:** mainnet, real-funds rails, and paid production traffic are
**NO-GO** until the P0 set clears. No flag, config, or "just for a pilot"
carve-out overrides that.

---

## 5. Smoke tests (post-cutover, once P0 clears)

1. `make release-gate` green.
2. Live preflight against production URL green (with DB pool, real HTTP leg).
3. Ingestion round-trip to durable Bronze; identity resolve; Profile 360 read
   with consent gate honored (403 on denied `credit`).
4. One enabled subsystem's full lifecycle validated against its **live**
   provider, with pilot evidence captured.
5. Load baseline recorded and within threshold (`make load-baselines`).

---

## 6. Cost posture

Lean production optimizes for a small number of tenants at bounded volume:
right-sized single-to-dual-node durable stores with redundancy only where a
single point of failure is unacceptable; economic provider polling enabled only
for validated domains (so live-API spend tracks enabled subsystems); ML serving
scaled to actual inference volume. The two cost unknowns to have *already*
validated in staging before lean production are **Neptune** capacity/cost and
**ClickHouse** compaction/retention — discovering either in production is the
failure mode this profile is designed to avoid.

---

## 7. Rollback

- **Per-subsystem:** flag OFF returns to prior behavior; every wave is built for
  independent rollback on SLO breach.
- **Full deploy:** `docs/DEPLOYMENT-RUNBOOK.md` +
  `docs/productization/staging-capstone/DISASTER_RECOVERY_GUIDE.md`.
- **Data:** backup/restore per `docs/BACKUP-RESTORE.md`; no destructive
  migration without a tested down-path.
- A failing live preflight or release-gate **blocks the cutover** — never
  override.

---

## 8. Score before / after

| | Score | Note |
|--|-------|------|
| **Today** | ~3.77 / 5 | P0 blockers open; economic domains 2–3; no live provider |
| **After P0 clears + one domain live** | Moves *only* in the validated areas | e.g. provider certification plane and one economic domain rise as a live provider is validated; scale readiness rises as baselines are recorded. The overall average moves incrementally and honestly, area by area, via `production_status.py` |
| **Full production + scale** | 5 in an area requires production traffic **at scale** | No area reaches 5 on completeness alone — it must survive a customer pointing at the evidence under load |

---

## 9. Go / no-go

- **Lean production, economic domains, mainnet, paid traffic: NO-GO** until the
  four P0 blockers clear.
- **Lean production of the non-economic core** (ingestion, identity, Profile
  360, Kyber, campaign/measurement reads) becomes a **conditional GO** only once
  infra + secrets are provisioned (P0 #2), agent hosted-mode durability is in
  place (P0 #3), `make release-gate` is green, and a live preflight + recorded
  baseline exist — even then with economic/mainnet subsystems held OFF.

See also: `docs/readiness/STAGING_READINESS_DOSSIER.md`,
`docs/AWS-LEAN-PRODUCTION.md`,
`docs/productization/staging-capstone/LIMITATIONS_AND_NON_GOALS.md`,
`docs/implementation/AETHER_KYBER_RELEASE_STATE.md`.
