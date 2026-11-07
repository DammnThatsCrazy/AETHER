---
title: Access Kit × 360 — W4 Limits and Metering Contract
slug: access-kit-w4-limits-contract
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Access Kit × 360 — W4 Limits and Metering Contract

This records what limits cover Access Kit reads today and what needs a decision
from the billing owner. It proposes nothing as approved. The Access Kit adapter
declares no limits of its own; the API decides on every request.

## Enforced today

| Control | Owner | Applies to Access Kit reads? | Evidence |
|---|---|---|---|
| Burst requests per minute, per tenant and plan | `shared/rate_limit/limiter.py`, called at `middleware.py` "Burst RPM" | Yes, every authenticated route, including `POST /v1/experience360/frames`. A 429 carries `Retry-After`; the adapter does not retry it. | Burst-limit block in `middleware.py`; adapter error mapping in `packages/access-kit/test/experience360.test.mjs` |
| Monthly request quota (meter only, never blocks) | `shared/rate_limit/quota.py` | Yes, counts the request. Overage is attributed only when the path resolves to a catalog service. | `test_access_kit_w4_limits_characterization.py` |
| Plan feature gate | `shared/rate_limit/feature_gate.py`, `shared/plans/service_catalog.py` | **No for 360 frames and the core reads.** Only `/v1/agent/agents/*` resolves to a service (`Autonomy`, gamma and above). | `test_access_kit_w4_limits_characterization.py` |
| Per-request input bounds | `Experience360FrameBody` | Yes: at most 64 requested slots, 16 lens IDs, bounded string lengths, `extra="forbid"`. | `test_experience360_frames_http_contract.py` |
| Non-billable interaction record | `_record_access_interaction` | Yes: audit row, `access_interaction` metering event with `billable=False`, outbox event. The usage summary read is not metered. | `test_access_kit_interaction_accounting.py` |

## Not enforced, and why it is open

1. **Plan or ACU gate for 360 frames.** Frames resolve to no catalog service, so
   every plan tier can call them. Which tiers get which surfaces, and whether a
   frame costs an ACU, is a pricing decision. It must not be set in the adapter.
2. **Per-credential and per-capability limits.** The burst limiter is keyed by
   tenant and plan. A single API key or delegated MCP token can use the whole
   tenant allowance. The existing `DistributedBudgetEngine` is the ML
   extraction-defense budget (`BudgetAxis.API_KEY`, sensitivity tiers) and is not
   a general capability limiter; reusing it would mix two contracts.
3. **Spend budget.** No Access Kit read is billable, so there is nothing to cap.
   This becomes relevant only if frames or any write become metered.
4. **Usage reconciliation.** Each interaction writes an audit row and a metering
   event that share the request ID (`source_id`). No job compares the two or
   compares them against the monthly quota counter.

## Decisions needed from the billing owner

| Decision | Options |
|---|---|
| Are 360 frame reads billable? | Stay non-billable; or meter per frame; or meter per slot returned. |
| Plan access | Add one catalog service for `/v1/experience360/*` with an explicit tier map; or leave open to all tiers. |
| Per-credential limit | A per-credential, per-minute cap under the tenant burst limit; or none. The number is a product decision. |
| Reconciliation | A scheduled audit-versus-metering count per tenant and day; or none while reads are non-billable. |

Until those are answered, the adapter keeps its current behavior: single attempt,
no retry on 429, bounded input, and no client-side limit that the server does not
also enforce.
