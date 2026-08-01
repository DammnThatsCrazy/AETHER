---
title: "Before / After Productization Report"
slug: implementation/before-after-productization-report
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
---

# Before / After Productization Report

What the four flag-gated waves on `claude/aether-kyber-production-if4m8m`
changed, measured against the canonical 0–5 scorecard
(`scripts/production_status.py`). The honest headline is the most important line
in this document:

> **The overall readiness is ~3.77 / 5 before these waves and ~3.77 / 5 after
> them.** The waves extend surface area; they do not move the number. Where a
> target score is not reached, this report says why.

Rubric: 0 absent · 1 stub · 2 partial/pilot · 3 pre-production · 4 release-ready
(minor gaps) · 5 production + scale ready.

---

## 1. Why "after" is not higher

A score moves only on **evidence**, and the scorecard is deliberately built to
refuse structural or optimistic promotion. The four waves each fail at least one
promotion criterion by design:

- **Flag-gated OFF.** Every wave defaults OFF and is inert in a default
  deployment. Inert code carries no production traffic, so it cannot lift an area
  toward 5 (production + scale ready).
- **No live provider added.** None of the waves validates an economic provider
  against a live endpoint. The 18 first-release providers remain
  `CREDENTIAL_WAITING`, so no economic domain moves.
- **Tested against in-memory / local fallbacks.** Consistent with the scorecard's
  standing rule, code tested only against fallbacks is capped at release-ready
  (4), never production-ready (5).
- **One wave is scaffold, not a feature.** Kyber Missions is a migration plus a
  flag-gated monitoring-loop scaffold; the orchestrator/aggregate is not yet in
  the tree, so it cannot raise the Kyber area.

This is the intended outcome. Raising a score here without live/production
evidence would be exactly the "optimistic readiness" the certification plane
exists to prevent.

---

## 2. Per-wave before / after

| Wave | Before | After | Score effect | Why not more |
|------|--------|-------|--------------|--------------|
| **Tenant routing fix** | Tenant resolution had the addressed defect | Correctness fix in the routing path | No score change | A correctness fix under an existing 4-rated surface does not add live traffic or scale evidence |
| **Activation FSM** (`services/activation`, `/v1/activation/*`) | First value required operator SQL / manual key mint | Real self-serve FSM: plan → SDK → key mint (once) → test event via in-process `/v1/batch` → Bronze first-value proof → `complete` refused until `first_value_ready` | No score change (flag OFF) | New capability, but flag-gated OFF and unexercised by production traffic; reuses existing ingestion tested on fallbacks — capped below 5 until live |
| **Kyber Missions** | No mission construct | Migration `20260815_kyber_missions` + flag-gated monitoring-loop scaffold in `main.py` (default OFF) | No score change | Scaffold + migration only; the aggregate/orchestrator is **not in the tree** — nothing to score yet |
| **Dossiers** | Release-truth / readiness / acquisition dossiers absent | Eight authored, source-linked dossiers | No score change | Docs area is already 4; these are authored docs, not a validator or generated-doc improvement that would move the docs score |

---

## 3. Scorecard before / after (all 30 areas)

Every area is unchanged. The table is presented in full precisely so the "no
movement" claim is auditable, not asserted.

| Area | Before | After |
|------|:------:|:-----:|
| backend/API | 4 | 4 |
| SDKs | 4 | 4 |
| identity resolution | 4 | 4 |
| Profile 360 | 5 | 5 |
| Neptune relationships (H2H/H2A/A2H/A2A) | 4 | 4 |
| graph mutation safety | 4 | 4 |
| graph health / drift detection | 4 | 4 |
| Kyber (operator console) | 4 | 4 |
| customer frontend (tenant app) | 5 | 5 |
| connectors (BYOK / source) | 4 | 4 |
| Slack / action notifications | 4 | 4 |
| Dune / data-lake feeders | 4 | 4 |
| smart contracts / proofs / rewards | 4 | 4 |
| security / compliance | 4 | 4 |
| agentic_x402_productization | 4 | 4 |
| CI / tests | 4 | 4 |
| measurement / attribution | 4 | 4 |
| measurement integrity plane | 4 | 4 |
| tenant import engine | 4 | 4 |
| campaign intelligence | 5 | 5 |
| docs | 4 | 4 |
| deployment / cloud readiness | 3 | 3 |
| scale readiness | 3 | 3 |
| provider certification plane | 4 | 4 |
| stablecoin intelligence | 3 | 3 |
| derivatives intelligence | 3 | 3 |
| interoperability intelligence | 3 | 3 |
| payment rail observability | 3 | 3 |
| semantic intelligence | 2 | 2 |
| card-linked payment rails | 2 | 2 |
| **Overall** | **~3.77** | **~3.77** |

---

## 4. What *would* move each not-yet-5 area

So the "why not" is constructive, not just a refusal:

| Area (current) | To reach the next level, it needs |
|----------------|-----------------------------------|
| deployment / cloud readiness (3) | Provisioned infra + loaded secrets + published ML artifacts |
| scale readiness (3) | Recorded `make load-baselines`; Neptune + ClickHouse validated at scale |
| stablecoin / derivatives / interop / payment-rail (3) | A validated **live** provider per domain (off `CREDENTIAL_WAITING`) + provisioned transport (Kafka topics, ClickHouse DDL) |
| semantic intelligence (2) | A validated production model provider + durable store run in staging + live traffic |
| card-linked payment rails (2) | A validated live provider before the flag is enabled |
| activation path (surfaced by this branch) | Enable the flag in staging, exercise the FSM end to end under real ingestion, capture pilot evidence |
| Kyber Missions (scaffold) | Land the mission aggregate/orchestrator, then validate the `completed != verified` invariant under the flag |

Each of these is a P0/P1/P2 item already tracked in
`docs/acquisition/RISK_AND_READINESS_REGISTER.md` and
`docs/implementation/AETHER_KYBER_RELEASE_STATE.md`. The waves in this report
prepare the ground (self-serve activation, mission migrations + wiring) so those
score-movers become straightforward enablement-and-validate steps rather than
new construction.

---

## 5. Net statement

The four waves are an **honest surface-area expansion**: a self-serve activation
path a tenant can walk to first value, a Kyber mission scaffold staged for a
future wave, a tenant routing correctness fix, and the release-truth dossier set.
They add capability and reduce the distance to production **without inflating a
single score**. That is the correct result, and it is enforced — enabling any of
these under real backends and validating it with evidence is what will move the
number next, one area at a time, through `make production-status`.

See also: `docs/implementation/AETHER_KYBER_RELEASE_STATE.md`,
`docs/productization/aether_productization_audit.md`,
`docs/acquisition/RISK_AND_READINESS_REGISTER.md`.
