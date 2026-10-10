---
title: "Derivatives Intelligence — Domain Decisions"
slug: productization/economic-interoperability-intelligence/adr-derivatives-decisions
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/value/derivatives/state_machines.py
  - services/api/value/derivatives/streams.py
  - services/api/value/derivatives/runtime_reconciliation.py
canonical_owner: platform@aether
source_hashes:
  "services/api/value/derivatives/runtime_reconciliation.py": "sha256:2a6d91a88ff5b9da68a891ec5ca5725c9e896e6a2dab3971f0c851520c9d38d0"
  "services/api/value/derivatives/state_machines.py": "sha256:d8fc78fa1063fd5d96a3ee23f311fb3d1b3160dd832aea7966452dd19b17e2ff"
  "services/api/value/derivatives/streams.py": "sha256:fa5c9b90ff3f32c0e99b6563c4306610e57a1b84e525293ca10cc069ccafa411"
---

# Derivatives Intelligence — Domain Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Orders/fills/positions are silver facts, never graph vertices | Cardinality: accounts trade thousands of times; the graph carries venues/accounts/strategies |
| D2 | Explicit `LEGAL_TRANSITIONS` maps + monotonic ranks for Order/Position FSMs | Venue feeds arrive out of order; legality is data, not scattered ifs |
| D3 | Out-of-order lower-rank evidence attaches without regression | Late fills/acks are normal; losing them or regressing status both corrupt history |
| D4 | Corrections are new rows | Venue restatements happen; mutation would destroy the audit trail |
| D5 | Simulator is the reference adapter (`MOCKED_LOCAL`) | Deterministic seeded scenarios make the whole runtime testable in CI |
| D6 | Conformance suite gates adapter registration | Checkpoint monotonicity, idempotent replay, Decimal-only, FSM-legal ordering, no-execution — enforced, not reviewed |
| D7 | Bounded stream buffer + gap threshold + recovery-past-revealing-sequence | Unbounded buffers are a memory DoS; naive recovery fired on the first message after a gap (bug found by tests) |
| D8 | Snapshot-vs-projection reconciliation only | Re-deriving fills during reconciliation double counts; snapshots diff safely |
| D9 | P&L labels its method (average_entry vs venue_reported) | The two legitimately disagree; hiding which one you're reading is how money gets misreported |
| D10 | Kafka deferred; local asyncio transport in-repo | Topic provisioning is infra work; the sequence-tracking contract is transport-independent |
