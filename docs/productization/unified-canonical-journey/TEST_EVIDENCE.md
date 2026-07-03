---
title: Test Evidence — Unified Canonical Journey
slug: productization/unified-canonical-journey/test-evidence
section: operations
visibility: I
audience: [architect, ops, exec]
since_version: "8.12.0"
status: stable
source_files:
  - tests/unit/test_canonical_activity.py
  - tests/unit/test_journey_compiler_v2.py
  - tests/unit/test_journey_step_repo.py
  - tests/unit/test_silver_adapters.py
  - tests/integration/test_unified_journey_e2e.py
  - tests/security/test_journey_tenant_isolation.py
last_synced_commit: 4d76caf
---

# Test Evidence — Unified Canonical Journey

## Summary

| Test file | Tests | Coverage |
|---|---|---|
| `test_canonical_activity.py` | 8 | Upsert idempotency, status lifecycle, tenant isolation, tombstone exclusion |
| `test_journey_compiler_v2.py` | 12 | Cross-rail ordering, deterministic sort, transitions, reorg, consent, empty profile |
| `test_journey_step_repo.py` | 8 | Bulk insert, cursor pagination, family/wallet/session filters, adjacent steps |
| `test_silver_adapters.py` | 14 | All 11 silver table adapters + idempotency stability + unknown table |
| `test_unified_journey_e2e.py` | 5 | Scenarios A (campaign→web2→web3→conversion), B (anonymous), F (reorg), G (multi-tenant wallet), H (late event replay) |
| `test_journey_tenant_isolation.py` | 3 | Tenant A cannot read tenant B activity, steps, or profile journeys |
| **Total** | **50** | |

## Key Test Scenarios

### Scenario A — Campaign → Web2 → Web3 → Conversion
Verifies the core cross-rail interleaving: a profile receives a paid ad touchpoint, browses the site, connects a wallet and makes a Web3 transaction, then converts. The compiled journey must include all four steps in chronological order with correct family labels and transition types.

### Scenario F — Blockchain Reorg
A confirmed Web3 transaction is later replaced by a reorg. `rebuild_affected_by_web3_status_change()` must update the `canonical_activity` status to `reorged` and recompile the profile's journey, producing a new version with the corrected step status.

### Scenario G — Multi-tenant Wallet Collision
The same wallet address appears in two different tenants. Confirms no data leakage: each tenant's activity, steps, and journey are completely isolated at the `tenant_id` predicate level.

### Scenario H — Late Event Deterministic Replay
A late-arriving Web2 event with an earlier `occurred_at` is inserted after the journey was already compiled. Recompilation must place the step at the correct chronological position, producing the same deterministic ordering as if the event had arrived on time.

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
