---
title: Test Evidence — Unified Canonical Journey
slug: productization/unified-canonical-journey/test-evidence
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [tests/unit/test_canonical_activity.py, tests/unit/test_journey_compiler_v2.py, tests/unit/test_journey_step_repo.py, tests/unit/test_silver_adapters.py, tests/integration/test_unified_journey_e2e.py, tests/security/test_journey_tenant_isolation.py]
source_hashes:
  tests/integration/test_unified_journey_e2e.py: sha256:5dc9f74bc7beedf9d372386aa31f562b22fffbb63af7e44aedfc63f581f0b798
  tests/security/test_journey_tenant_isolation.py: sha256:daa61f41d0d08381158ecd27f5a473ee8783c97929d99198ef93d0957d9da1bc
  tests/unit/test_canonical_activity.py: sha256:ff981cb131bf57b417af4ba247e4602fc6a08124a3a874bc2904442f3601cf08
  tests/unit/test_journey_compiler_v2.py: sha256:11ed3a245b1d19206bc7ece87c8c1812150249c022f8bcd980818aecc2a440ea
  tests/unit/test_journey_step_repo.py: sha256:2fd091fc178bfaabc90e6b8ce68077f4f401bf41cc5db68d151d54d26df900f1
  tests/unit/test_silver_adapters.py: sha256:86f4b6a457a3e2eeff18c067af8abc049ac041ddc7f2c22284b5b1137bc2aab0
---

# Test Evidence — Unified Canonical Journey

## Summary

| Test file | Tests | Coverage |
|---|---|---|
| `test_canonical_activity.py` | 8 | Upsert idempotency, status lifecycle, tenant isolation, tombstone exclusion |
| `test_journey_compiler_v2.py` | 16 | Cross-rail ordering, deterministic sort, transitions, reorg, consent, typed-identity collisions, empty profile |
| `test_journey_step_repo.py` | 10 | Bulk insert, cursor pagination, family/wallet/session filters, adjacent steps, source-evidence persistence contract |
| `test_silver_adapters.py` | 14 | All 11 silver table adapters + idempotency stability + unknown table |
| `test_unified_journey_e2e.py` | 5 | Scenarios A (campaign→web2→web3→conversion), B (anonymous), F (reorg), G (multi-tenant wallet), H (late event replay) |
| `test_journey_tenant_isolation.py` | 4 | Tenant A cannot read tenant B activity, steps, or profile journeys |
| **Total** | **57** | |

## Key Test Scenarios

### Scenario A — Campaign → Web2 → Web3 → Conversion
Verifies the core cross-rail interleaving: a profile receives a paid ad touchpoint, browses the site, connects a wallet and makes a Web3 transaction, then converts. The compiled journey must include all four steps in chronological order with correct family labels and transition types.

### Scenario F — Blockchain Reorg
A confirmed Web3 transaction is later replaced by a reorg. `rebuild_affected_by_web3_status_change()` must update the `canonical_activity` status to `reorged` and recompile the profile's journey, producing a new version with the corrected step status.

### Scenario G — Multi-tenant Wallet Collision
The same wallet address appears in two different tenants. Confirms no data leakage: each tenant's activity, steps, and journey are completely isolated at the `tenant_id` predicate level.

### Scenario H — Late Event Deterministic Replay
A late-arriving Web2 event with an earlier `occurred_at` is inserted after the journey was already compiled. Recompilation must place the step at the correct chronological position, producing the same deterministic ordering as if the event had arrived on time.

### Typed identity collision and atomic publication

Profile, cluster, and anonymous identities that share the same raw identifier
remain separate journey lineages. Repository tests also verify the schema-v2
source-classification step parameters, while compiler/repository behavior keeps
version activation and step insertion in one transaction so a failed step write
cannot expose a hollow current version.

## Running Tests

```bash
# Unit tests (no DB required)
python -m pytest tests/unit/test_canonical_activity.py \
                 tests/unit/test_journey_compiler_v2.py \
                 tests/unit/test_journey_step_repo.py \
                 tests/unit/test_silver_adapters.py \
                 --override-ini="addopts=" -v

# Integration + security
python -m pytest tests/integration/test_unified_journey_e2e.py \
                 tests/security/test_journey_tenant_isolation.py \
                 --override-ini="addopts=" -v
```
