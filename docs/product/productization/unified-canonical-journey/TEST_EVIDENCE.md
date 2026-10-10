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
  "tests/integration/test_unified_journey_e2e.py": "sha256:c1fdeed653886eb93bae110d595708fe0bbbc10c5573407ae740e5e6fa1b3ee2"
  "tests/security/test_journey_tenant_isolation.py": "sha256:7d774efcd8f50960977fccefa378f35c4b58fd9194202e3943b9587947fb2ef1"
  "tests/unit/test_canonical_activity.py": "sha256:f0958f74ab606cc90bad5d642a4faf4907b6472ae6644c1fbf68d790cbb43ec6"
  "tests/unit/test_journey_compiler_v2.py": "sha256:220802be0a4f9f3c56d81d233d215f13f59a6900fafa8129e41b16b7e6f589f6"
  "tests/unit/test_journey_step_repo.py": "sha256:598b94ad46bb90e743587dc5570b9183e19a1d068346d95c0082fea722b92819"
  "tests/unit/test_silver_adapters.py": "sha256:5a2339c14f0ece55281726801678104f3e74011ca8cd989377ca7543106bc561"
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
