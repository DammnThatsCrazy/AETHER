---
title: Derivatives Consent Model
slug: source-of-truth/derivatives-consent-model
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/consent-registry.json
  - Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---
# Derivatives Consent Model

The consent registry adds `financial_activity` for read-only derivatives trading analytics. The purpose governs account connections, orders, fills, positions, collateral, margin, funding, fees, PnL, behavioral profiling, risk profiling, agent trading activity, campaign linkage, identity linkage, graph projection, and model-training eligibility.

The purpose defaults disabled, requires explicit opt-in, permits backend enrichment and graph projection under a purpose grant, and disallows model training unless a separate governed opt-in is introduced.
