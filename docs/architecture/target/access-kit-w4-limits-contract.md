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

This records what limits cover Access Kit reads and the decisions taken for
W4. The defaults below are the engineering decisions made to close W4; the billing
owner can change any of them without touching the adapter, which declares no
limits of its own (the API decides on every request).

## Enforced

| Control | Owner | Applies to Access Kit reads? | Evidence |
|---|---|---|---|
| Burst requests per minute, per tenant and plan | `shared/rate_limit/limiter.py`, "Burst RPM" in `middleware.py` | Yes, every authenticated route, including `POST /v1/experience360/frames`. A 429 carries `Retry-After`; the adapter does not retry it. | Burst-limit block in `middleware.py`; adapter error mapping in `packages/access-kit/test/experience360.test.mjs` |
| **Per-credential, per-capability cap** | `shared/rate_limit/access_capability_limit.py`, hooked after the burst check | Yes, for requests with a valid Access Kit surface label on a named Access Kit route. 120 requests per minute per (credential, capability) by default; `AETHER_ACCESS_KIT_CREDENTIAL_RPM` overrides it and `0` disables it. Platform operators are exempt. A limiter error never blocks a read. A 429 is audited like any blocked Access Kit call. | `test_access_kit_credential_limit.py` |
| Monthly request quota (meter only, never blocks) | `shared/rate_limit/quota.py` | Yes, counts the request. | `test_access_kit_w4_limits_characterization.py` |
| Per-request input bounds | `Experience360FrameBody` | Yes: at most 64 requested slots, 16 lens IDs, bounded string lengths, `extra="forbid"`. | `test_experience360_frames_http_contract.py` |
| Non-billable interaction record | `_record_access_interaction` | Yes: audit row, `access_interaction` metering event with `billable=False`, outbox event. The usage summary read is not metered. | `test_access_kit_interaction_accounting.py` |
| **Audit-versus-usage reconciliation** | `billing/billing/access_reconciliation.py` | Yes. Compares `access.interaction` audit rows with `access_interaction` usage events by request ID for a window, and reports rows with no counterpart, billable events, and truncation. Read-only. | `test_access_kit_reconciliation.py` |

## Decisions

| Question | Decision | Why |
|---|---|---|
| Are 360 frame reads billable? | No. They stay non-billable and are attributed only. | The service catalog (`shared/plans/service_catalog.py`) is a priced registry of 38 services; adding a row would invent a price. |
| Plan or ACU gate for frames | None. Frames are included on every plan; the catalog gets no new service. | Same reason. Overage attribution for frames is therefore not available. The per-credential cap and the tenant burst limit are the protection. |
| Spend budget | Not applicable while every Access Kit read is non-billable. | Nothing to cap. Revisit if any Access Kit operation becomes metered. |
| Per-credential limit value | 120 per minute per (credential, capability), configurable. | A starting default under typical plan burst limits; set the env var to tune per deployment. |
| Reconciliation cadence | The function exists; it is not scheduled. | A scheduler and an owner for the report are an operations decision. |

## Still needs the billing owner

Moving any of the decisions above: making frames billable, adding a priced catalog
row with a tier map, or changing the default cap. Until then the adapter keeps its
current behavior: single attempt, no retry on 429, bounded input.
