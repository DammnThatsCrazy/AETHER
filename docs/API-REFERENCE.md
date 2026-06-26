---
title: API Reference
slug: api/api-reference
section: api
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# API Reference

The backend is FastAPI; the **authoritative, always-current** API schema is served
live at `GET /openapi.json` (and interactive docs at `/docs`). This page is the
human entry point; see [Backend API](BACKEND-API.md) for the endpoint catalog.

## Snapshotting the schema

```bash
npm run api:openapi    # python scripts/export_openapi.py → docs/_generated/openapi.json
```

`scripts/export_openapi.py` imports the app with default flags (feature-flagged
routes off) and writes a stable OpenAPI snapshot for contract review. Because
several routers mount conditionally (data quality, connectors, intelligence
quality, …), the live schema in a given environment reflects the enabled flags.

## Conventions

- Versioned under `/v1`. Success envelope `{ data, meta }`; errors
  `{ error: { code, message, details, request_id } }`.
- Auth: see [API Auth](API-AUTH.md). Errors: [API Errors](API-ERRORS.md).
  Pagination/filtering: [API Pagination & Filtering](API-PAGINATION-FILTERING.md).
  Rate limits: [API Rate Limits](API-RATE-LIMITS.md).
- Contracts are checked in CI via `scripts/validate_contracts.py` and
  `tests/unit/test_api_contracts.py`.

See [Webhook Events](WEBHOOK-EVENTS.md) and [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md).

## Reward Enablement (A6)

All reward routes are under `/v1/rewards/` and require `Authorization: Bearer <api_key>`.
Full endpoint catalog: [Backend API — Rewards section](BACKEND-API.md#reward-enablement-a6).

Key shapes:

**Evaluate eligibility** (`POST /v1/rewards/evaluate`)
```json
{
  "event_type": "conversion",
  "tenant_id": "tenant_xyz",
  "user_id": "user_123",
  "wallet_address": "0xabc...",
  "idempotency_key": "evt_abc_campaign_001",
  "attribution_result_id": "attr_001",
  "fraud_decision_id": "fraud_001",
  "consent_snapshot_id": "cs_001",
  "properties": { "amount": 49.99 }
}
```

Response: `{ eligible, decision, execution_mode, rail, next_action, attribution, fraud, identity }`

Decisions: `eligible` | `ineligible` | `needs_review` | `blocked_fraud` | `blocked_consent` |
`blocked_identity` | `blocked_wallet_binding` | `blocked_cooldown` | `blocked_cap` | `blocked_budget`

**Create campaign** (`POST /v1/rewards/campaigns`)
```json
{
  "name": "Q2 Conversion Campaign",
  "attribution_model": "last_touch",
  "default_rail": "recommend_only",
  "budget_policy": { "max_total_decisions": 10000 }
}
```

**Configure rail** (`POST /v1/rewards/rails`)
```json
{
  "rail": "tenant_webhook",
  "enabled": true,
  "webhook_url": "https://your-system.example.com/rewards",
  "signing_secret_ref": "vault://rewards/webhook-secret"
}
```

**Proof verification** (`POST /v1/rewards/proofs/verify`)
```json
{ "proof_id": "proof_uuid", "signature": "0x...", "nonce": "0x...", "wallet_address": "0x..." }
```

No-custody model: Aether verifies eligibility and generates signed proofs. Tenants execute
rewards through their own configured rails (webhook, smart contract, manual export, etc.).


---

## Path Intelligence (Phase 20)

Full reference: [`docs/CANONICAL-PATH-INTELLIGENCE.md`](./CANONICAL-PATH-INTELLIGENCE.md)

**Find paths** (`POST /v1/graph/paths`)
```json
{
  "tenant_id": "t1",
  "source_id": "node-A",
  "target_id": "node-B",
  "mode": "shortest",
  "k": 3,
  "max_depth": 6,
  "min_confidence": 0.5,
  "include_explanation": true,
  "save_snapshot": true
}
```
Modes: `shortest` | `strongest` | `k_shortest` | `temporal` | `neighborhood` | `attribution` | `decision_outcome` | `evidence` | `multi_source`

**Expand node** (`POST /v1/graph/paths/expand`)
```json
{ "tenant_id": "t1", "node_id": "node-A", "direction": "both" }
```

**Explain path** (`POST /v1/graph/paths/explain`)
```json
{ "tenant_id": "t1", "path_id": "deadbeef12345678" }
```
Returns `PathExplanation` with `why_connected`, `hop_narrative[]`, `causal_language_allowed`.

**Create async job** (`POST /v1/graph/paths/jobs`)
Same body as `/paths`. Routed to async when `max_depth > 6`.

**Get job status** (`GET /v1/graph/paths/jobs/{job_id}?tenant_id=t1`)
Returns `DeepTraversalJob` with `status`, `progress_pct`, `partial_path_ids`.

**Create snapshot** (`POST /v1/graph/snapshots`)
```json
{ "tenant_id": "t1", "path_ids": ["..."], "node_ids": ["..."], "edge_ids": ["..."] }
```

**Get snapshot** (`GET /v1/graph/snapshots/{snapshot_id}?tenant_id=t1`)
Returns `TraversalSnapshot`. Tenant ownership enforced fail-closed.

**Compare snapshots** (`POST /v1/graph/snapshots/{snapshot_id}/compare`)
```json
{ "tenantId": "t1", "anchor": { "kind": "entity", "id": "e1" }, "asOf": "2026-01-01T00:00:00Z", "compareTo": "snap-id-2" }
```
Returns added/removed node and edge IDs.
