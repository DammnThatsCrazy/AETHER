---
title: "Pilot Evidence Guide"
slug: productization/staging-capstone/pilot-evidence-guide
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
last_synced_commit: "5a8df09"
---

# Pilot Evidence Guide

What a pilot must capture before any readiness score moves. The scorecard rubric
treats "tested against in-memory/local fallbacks" as at most release-ready (4)
and NEVER production-ready (5). A score only advances on recorded pilot evidence
against real infrastructure — this guide defines what that evidence is.

## Evidence classes (map to `ReadinessDimensions`)

1. **Replay evidence** — recorded provider fixtures + a passing conformance
   run. Supports `replay_validated`.
2. **Sandbox evidence** — a run against the provider sandbox with a captured
   `last_certified_at`. Supports `sandbox_validated`.
3. **Live evidence** — a controlled staging window against the live provider:
   one full lifecycle observed end to end (ingest → normalize → project →
   surface), with reconciliation clean. Supports `partner_live`.
4. **Load evidence** — recorded staging baselines (`make load-baselines`,
   `docs/LOAD-BASELINES.md`): RPS, p95, error rate against the declared SLAs.
   Required before any scale-readiness claim.
5. **Security evidence** — a completed security review (and external audit for
   on-chain rails). Required before any `production_ready` claim.

## What to record per pilot

- Provider + domain, window start/end, environment id.
- The credential/endpoint used (vault ref, never the secret itself).
- Lifecycle transcript: counts per stage, reconciliation result, any variance.
- Failure/recovery observations: rate-limit, timeout, reorg, disconnect, gap —
  cross-reference the credentialless coverage in `tests/chaos/` so the pilot
  only has to prove the LIVE leg.
- SLO/SLA readings (latency, freshness, lag) against
  `docs/productization/economic-interoperability-intelligence/OBSERVABILITY_AND_SLOS.md`.

## Before you move a score

1. The pilot evidence exists and is linked from the area's evidence paths in
   `scripts/production_status.py`.
2. `make production-status` still runs; the change does not overclaim
   (credential-waiting / pilot-ready ≠ production-ready).
3. `scripts/production_status.py` and
   `docs/productization/aether_productization_audit.md` are updated together and
   the audit is re-stamped (`python scripts/docs_drift.py --update`).

## Never do

- Never move a score on in-memory/local evidence alone.
- Never cite a pilot that lacks a reconciliation result.
- Never mark `production_ready` without live + security evidence.
