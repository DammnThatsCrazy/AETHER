---
title: "Acquisition Productization Dossier"
slug: acquisition/productization-dossier
section: operations
visibility: I
audience: [exec, buyer]
status: stable
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
estimated_read_minutes: 13
toc_depth: 3
last_synced_commit: "e9fc085"
---

# Acquisition Productization Dossier

For a buyer or diligence team. The single most important thing to know about
AETHER's self-presentation: **the scores are machine-checkable and the
limitations are stated as plainly as the strengths.** `make production-status`
(`scripts/production_status.py`) is the canonical, evidence-anchored readiness
scorecard; this document narrates it for a non-engineering reader without
inflating it.

**Headline posture: a real, tested, unusually well-gated pre-production platform
at ~3.77 / 5.** Not an MVP. Not yet a system that should take paying production
traffic. The gap to production is operational and go-to-market, not
architectural.

---

## 1. What AETHER is

AETHER is an **observation-only, no-custody** identity, intelligence, and
attribution platform for the human + agent economy. It ingests events from
first-party SDKs and connectors, resolves identities across wallet / anonymous /
email / user anchors, composes a canonical **Profile 360**, maintains a
relationship **graph** (human-to-human, human-to-agent, agent-to-human,
agent-to-agent), and surfaces operator intelligence through the **Kyber**
console — with consent enforcement, tenant isolation, and audit trails
throughout.

What it deliberately is **not** (non-goals, by construction — see
`docs/productization/staging-capstone/LIMITATIONS_AND_NON_GOALS.md`): it never
initiates or settles a payment, places or cancels a trade, sends a cross-chain
message, or holds funds. A request for execution or custody is a scope mismatch,
not a missing feature.

---

## 2. The core surfaces are real, not stubs

Each scores 4–5 on the canonical scorecard, backed by tests against real data
paths (in-memory/local fallbacks are dev/test only):

- **Backend / API (4):** 65+ FastAPI routers, auth/RBAC middleware,
  tenant-scoped repositories, plan-tier gating, rate limits, quotas. `/v1/batch`
  is production-hardened: per-event consent enforcement, PII scrub, Redis-backed
  idempotency, durable Bronze write before ACK.
- **Profile 360 (5):** canonical composition across identity, analytics,
  consent, graph, and Gold-tier lake; 15 intelligence sub-resources on real
  queries; credit data behind a **hard consent gate** (HTTP 403 on denial, not a
  soft empty envelope).
- **Identity resolution (4):** four-anchor resolution with confidence scoring, a
  merge endpoint with reason + audit event, and a low-confidence review queue.
- **Graph (4 across relationships / mutation safety / health):** exhaustive
  edge-type mapping that fails closed on unknown edges; agent mutations go
  through verify → stage → review → human approval → commit (never direct
  writes); rollback verifies the inverse and refuses a false clean undo.
- **Kyber operator console (4)** and **customer/tenant frontend (5):** the tenant
  app has a Playwright E2E suite CI-gated via the e2e-tenant job.
- **Campaign intelligence (5)**, **measurement / attribution (4)**, and a
  **measurement integrity plane (4)** that never emits a bare `0` on missing
  data — it carries an explicit `value_state`.

---

## 3. The self-serve activation path (this branch, flag-gated)

A self-serve **activation FSM** (`services/activation`, `/v1/activation/*`,
default OFF) lets a tenant reach first value without operator SQL: select a plan
tier, choose SDK platforms, mint API keys (raw key shown once), send a test
event through the **real** in-process ingestion path, and prove **Bronze first
value** before `complete` is permitted. It reuses the existing registration
key-mint rather than inventing a parallel path. It is flag-gated OFF and does not
depend on the open billing draft (#501); it is presented here as a
*demonstrable* capability, not a shipped-to-production one.

---

## 4. The intelligence loop

The value proposition is a closed loop: **ingest → resolve identity → compose
Profile 360 → maintain graph → score intelligence (trust / risk / health /
attribution) → surface to operator (Kyber) → govern actions.** Notifications and
actions (Slack, connectors) are the outbound edge; the loop never mutates the
graph on an agent's say-so — every mutation is staged and human-approved. Demo
seed (#494) lets a buyer see the loop populated deterministically, while
**live-empty honesty** means a fresh tenant shows genuinely empty surfaces
rather than fabricated data.

---

## 5. Kyber and governed operations

Kyber is the operator plane: an exception queue instead of dashboard-watching,
incidents those exceptions roll up into, **governed commands** that change
platform state (each authorized twice — a floor on the dependency, the real
capability/action-class in the handler, each writing its own decision row), and
containment switches. Tenant scope is proven against what the request names and
re-checked on every command transition. A **Kyber Missions** scaffold (migration
+ flag-gated monitoring loop, default OFF) is staged on this branch for a future
wave — presented honestly as scaffolding, not a landed feature.

---

## 6. Security and compliance (4/5)

- Secret-scan (`npm run security:secrets`, fail-closed) and dependency-audit
  (`npm run security:deps`, advisory) are CI-gated.
- Tenant isolation enforced at the repository level with dedicated tests.
- Consent fail-closed; DSR erase/restrict paths exist.
- 14/18 security controls implemented; the remaining four (IR/PR/PT/TM) are
  documented-only and need no code change.
- **Caveat:** smart contracts are tested but **unaudited** — an external audit is
  a hard gate before any real-funds deployment.

---

## 7. Evidence a buyer can run

Nothing here asks for trust:

- `make production-status` — the 30-area scorecard with evidence paths.
- `make ci-check` — the registry test suite (skip = FAIL) + `npm run test` + ~40
  validators.
- `make staging-preflight` — the fail-closed staging gate.
- `scripts/production_status.py --strict` — fails on live consistency-check
  drift.

The scorecard refuses to infer `production_ready` from structure; a score never
moves without live + security evidence.

---

## 8. Honest limitations

Stated first, not buried (`scripts/production_status.py` +
`docs/productization/staging-capstone/LIMITATIONS_AND_NON_GOALS.md`):

- **No live economic provider.** All 18 first-release providers are
  `CREDENTIAL_WAITING`. The economic domains sit at 2–3/5.
- **Mainnet / real-funds rails / paid production traffic: NO-GO.** Contracts
  unaudited; infra unprovisioned; agent hosted-mode needs durable storage.
- **Observability is a seam, not coverage.** W3C traceparent + correlation-id
  propagation exist (gated on `AETHER_OTEL_ENABLED`); no OTel SDK/exporter is
  integrated.
- **No recorded scale baselines.** Neptune throughput/cost and merge throughput
  are unvalidated at scale.
- **Two least-mature planes at 2/5:** semantic intelligence (real fail-closed
  pipeline, no validated model provider, no live traffic) and card-linked
  payment rails (wired, flag-off, no live provider).

---

## 9. Roadmap to production

Ordered, and each item is a score-mover with evidence:

1. Provision infra + load secrets (clears a P0; enables everything downstream).
2. External smart-contract audit (lifts the mainnet gate).
3. Provision agent hosted-mode durable storage (clears a P0).
4. Validate one live provider per economic domain (moves the certification plane
   and each domain off `CREDENTIAL_WAITING`).
5. Publish ML serving artifacts; integrate OTel SDK/exporter.
6. Record staging load baselines; validate Neptune + ClickHouse at scale.

None of the four flag-gated waves on the current branch move the ~3.77 overall —
they extend surface area (self-serve activation, mission scaffolding) without a
readiness claim.

---

## 10. Bottom line for a buyer

A credible, well-engineered, honestly-gated pre-production asset whose remaining
work is provisioning, credentials, audit, and scale validation — not a rewrite.
The most acquirable property is cultural: **the platform's own tooling refuses to
overstate its readiness**, which means diligence can be run against the codebase
rather than against a pitch.

See also: `docs/acquisition/ARCHITECTURE_AND_OPERATIONS_OVERVIEW.md`,
`docs/acquisition/DEMO_AND_VALUE_PROOF_GUIDE.md`,
`docs/acquisition/RISK_AND_READINESS_REGISTER.md`,
`docs/implementation/AETHER_KYBER_RELEASE_STATE.md`.
