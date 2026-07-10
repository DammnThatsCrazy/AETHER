---
title: Olympus Intelligence Surfaces
slug: productization/economic-interoperability-intelligence/olympus-intelligence-surfaces
section: operations
visibility: I
audience: [architect, ops, exec]
status: beta
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/noesis/capability_registry.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Olympus Intelligence Surfaces

Olympus consumes the same evidence-backed read surfaces as Noesis — no
Olympus-specific code paths were added for these domains. Available
building blocks:

- Noesis intents (`stablecoin_flow_lookup`, `derivatives_exposure_lookup`,
  `derivatives_reconciliation_lookup`, `interop_message_trace`,
  `interop_path_reliability`) return `EvidenceEnvelope` responses suitable
  for cross-tenant operator reasoning on the Kyber surface.
- Gold tables (`gold_stablecoin_flows`, `gold_derivatives_exposure`,
  `gold_interop_paths`) are the aggregate query surface; every row is
  `model_training_eligible = 0`.
- Alert topics (depeg, variance, stalled gap, stuck message, policy
  change) feed the shared notification-intelligence pipeline Olympus
  already observes.

Any deeper Olympus workflow (cross-tenant benchmarks, fleet-level
reliability scoring) is future work and intentionally out of scope for
8.12.0 — nothing here fakes it.
