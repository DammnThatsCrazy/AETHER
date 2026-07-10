---
title: Derivatives Intelligence
slug: derivatives/intelligence
section: concepts
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "8.11.0"
---

# Derivatives Intelligence

The PR3 intelligence layer turns reconstructed derivative position epochs and authority grants into projection intents for Aether's existing product surfaces.

- Graph intents include explicit edge-layer classification, evidence envelopes, confidence, valid time, recorded time, and deterministic idempotency keys.
- Profile360 summaries expose a `derivatives` dimension with complete and empty-state behavior, fixed-precision economic metrics, and freshness state.
- Campaign outcomes report trading results while avoiding unsupported causality claims.
- Noesis responses separate facts, computations, inferences, recommendations, and insufficient-evidence cases.

The layer never submits orders, signs transactions, stores credentials, mutates accounts, or treats behavioral similarity as verified identity.
