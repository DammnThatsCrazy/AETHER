---
title: Delivery State Machine
slug: architecture/delivery-state-machine
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Delivery State Machine

## DeliveryJob States

```
                     ┌─────────┐
              create │  QUEUED │ ◄─── re-queue on lease expiry
                     └────┬────┘
                          │ DeliveryWorker.lease_next_batch()
                          ▼
                    ┌──────────┐
                    │  LEASED  │ ─── lease_expires_at exceeded ──► QUEUED
                    └────┬─────┘
                         │ mark_running()
                         ▼
                    ┌──────────┐
                    │ RUNNING  │
                    └────┬─────┘
              ┌──────────┴──────────┐
              │ success             │ failure
              ▼                     ▼
         ┌──────────┐         ┌──────────┐
         │SUCCEEDED │         │  FAILED  │ ─── attempt < max ──► QUEUED (with backoff)
         └──────────┘         └────┬─────┘
                                   │ attempt >= max_attempts
                                   ▼
                             ┌────────────┐
                             │ DEAD_LETTER│ ◄── operator replay ──► QUEUED
                             └────────────┘
```

CANCELLED is a terminal state set by operator action (e.g. suggestion suppressed before delivery completes).

## Suggestion Lifecycle (delivery-relevant transitions)

```
DRAFT ──► PENDING_REVIEW ──► APPROVED ──► DELIVERED ──► (outcome_state updated)
                                │
                                ├──► SUPPRESSED (operator/policy)
                                └──► EXPIRED (TTL)
```

| Transition | Trigger | Actor |
|-----------|---------|-------|
| → APPROVED | PolicyDecision auto-approved or OperatorApproval | PolicyEngine / Operator |
| → DELIVERED | `DeliveryWorker._advance_lifecycle_on_success()` after `ProviderReceipt` with real `external_id` | DeliveryWorker |
| outcome_state updated | `OutcomeRouter.route()` after `ExternalOutcomeEvent` routed | WebhookInboxProcessor |

## ExternalOutcomeEvent Types

| `event_type` | Description | Suggestion outcome |
|-------------|-------------|-------------------|
| `delivered` | Provider confirmed receipt | — (covered by ProviderReceipt) |
| `acknowledged` | User opened / clicked in Slack | `outcome_state = acknowledged` |
| `accepted` | User clicked Approve in Slack | `outcome_state = accepted` |
| `commented` | Comment added on Linear/Jira issue | `outcome_state = in_progress` |
| `status_changed` | Linear/Jira issue moved to in-progress | `outcome_state = in_progress` |
| `resolved` | Linear/Jira issue marked Done | `outcome_state = executed` |
| `rejected` | User clicked Suppress in Slack | `outcome_state = rejected` |
| `cancelled` | Issue deleted or closed without resolution | `outcome_state = cancelled` |
| `reopened` | Issue reopened after resolution | `outcome_state = in_progress` |

## Loop Prevention

`OutcomeRouter` guards against infinite update loops:
1. Checks `event_data.get("aether_origin")` — skips events Aether itself originated
2. Compares `new_state` with stored `ExternalResourceLink.sync_status` — skips no-op transitions
3. Uses `hmac.compare_digest` for all signature comparisons to prevent timing oracles
