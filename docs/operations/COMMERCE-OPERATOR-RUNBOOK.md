---
title: Commerce Operator Runbook
slug: operations/commerce-runbook
section: operations
visibility: I
audience: [ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/value/x402/
  - services/api/value/x402/provenance.py
  - services/api/value/x402/settlement_observer.py
  - services/api/governance/diagnostics/routes.py
  - services/api/actions/agent/user_agents.py
  - services/api/alembic/versions/20261022_execution_approval_decisions.py
  - services/api/actions/agent/deployment_routes.py
  - services/api/actions/agent_marketplace/authority.py
  - services/api/actions/agent_marketplace/graph_state_check.py
  - services/api/ingestion/silver/projectors/agent_execution_projector.py
canonical_owner: commerce@aether
estimated_read_minutes: 3
toc_depth: 3
reviewed_source_commits:
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
source_hashes:
  "services/api/actions/agent/deployment_routes.py": "sha256:1ad26d4901bbb8ccb6827cb60703052876c13f06014907e90f9d53c3a9bf7090"
  "services/api/actions/agent/user_agents.py": "sha256:6e8c6935786206280889003297253f1401cd67573ff490a78349840555b1af20"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/graph_state_check.py": "sha256:595617063afe604a7a5b1c421fa73916141a37b374a008606bb6dab460cd0983"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/governance/diagnostics/routes.py": "sha256:bb2f2366e46d79164868bb2df1315e1c41d704f48f0ed4d04f4ceb68039a02b9"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:73e568f142ad0407405cd3fff0328011d6e2a58260e48075cb5eedc5f5cd952c"
  "services/api/value/x402/": "sha256:edc02290facfce1c780393ca4ace0f5fc5b11065e683ee59a357bef448ef8c38"
  "services/api/value/x402/provenance.py": "sha256:fe227df986d4c03f770d97d6236bc4c5c5ee4410db66415dd38b7a697779d556"
  "services/api/value/x402/settlement_observer.py": "sha256:d7779f89245892329488cfc587ae4afa4988b012494e4b5acce736acec45874e"
---

# Commerce Operator Runbook

Aether is observation-only for x402 ([ADR-012](../architecture/decisions/ADR-012-observation-only-everywhere.md)).
It records x402 exchanges a tenant's server reports and verifies their
settlement on-chain. It issues no 402 challenge, approves no spend, grants no
entitlement and owns no settlement state, so there is nothing to approve,
retry, revoke or cap from Kyber. The former approval, entitlement, budget
policy, signer authority and settlement reconciliation procedures were removed
with the control plane.

The `/v1/diagnostics/commerce/*` routes used below admit only platform
operators (see [Access Control](../architecture/ACCESS-CONTROL.md#platform-operators))
and read historical and observed records only.

## 1. A reported payment stays `pending`

**Symptom:** `POST /v1/x402/capture` returns `settlement.state = "pending"`, or
`x402_settlement_observations_total{state="pending"}` climbs.

**Steps:**
1. Read `settlement.verdict`. `not_finalized` means the transaction is not yet
   final on-chain; `verification_unavailable` means the tenant's RPC could not
   be resolved or reached.
2. For `verification_unavailable`, check the tenant's `rpc_endpoint_pair`
   credential for the chain (providers `rpc_evm_base`, `rpc_svm_mainnet`, ...)
   and the RPC's health. Deployed environments never fall back to a platform
   RPC.
3. A pending verdict records nothing terminal. There is no background re-check:
   the tenant's server re-reports the same payment (same transaction hash) and
   the observer checks the chain again. Repeated reports are idempotent.

## 2. A reported payment is `failed` or `not_observable`

- `failed` is a terminal on-chain verdict: `reverted`, `payer_mismatch`,
  `amount_below_required`, `no_matching_transfer` or `malformed`. It describes
  the reported payment; Aether did not refuse anything.
  `GET /v1/diagnostics/commerce/verification-failures` lists recent ones.
- `not_observable` means the report had no payment proof, or the asset/chain
  is one Aether cannot verify. No settlement claim is made either way.

## 3. Agent-reported economic outcomes

**Symptom:** An Agent run reports a payment or settlement reference, or its
timeline shows a missing, unavailable, or unmatched economic record.

**Steps:**
1. Read the tenant-scoped run timeline at
   `GET /v1/agent/deployments/{deployment_id}/runs/{run_id}/explanation`.
   Inspect `economic_outcome.status` and the exact payment-intent or
   settlement-event references. `matched`, `unresolved`, `unavailable`, and
   `not_supplied` describe the lookup result; `not_supplied` does not prove no
   payment occurred.
2. For a `matched` result, use the authoritative tenant payment-intent and
   settlement records to confirm their current state and settlement finality.
   A source-reported Agent event or a matching reference establishes neither
   causation nor a completed payment.
3. Treat public SDK x402 observations as telemetry only. They cannot create or
   overwrite authoritative payment or settlement state. The x402 provenance
   rules determine which lifecycle records count as server-observed evidence;
   the settlement observer is the only live authoritative producer.
4. Do not replay a graph projection merely because a source claim is
   unmatched. For graph evidence, use the independent Kyber state check in the
   Operations Runbook; it reports graph drift without repairing it.

## 4. Historical control-plane records

Approval requests, decisions, authorizations, settlements and entitlements
written before ADR-012 remain in the commerce store. Agent 360, Workflow 360,
analytics and `/v1/diagnostics/commerce/{settlement-timeouts,approval-expirations,duplicate-payments,reconciliation-drift}`
read them; commerce erasure still covers them. They no longer change.
