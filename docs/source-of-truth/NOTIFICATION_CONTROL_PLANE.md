---
title: Notification Control Plane
slug: mobile/notification-control-plane
section: mobile
visibility: I
audience: [architect, security, ops]
status: alpha
---

# Notification Control Plane

The canonical notification control plane is the existing **Notification
Intelligence** service (`services/notification_intelligence/`). This program
brands it as the single source of truth, adds the missing TypeScript contract
twins, and (in later increments) a producer-coverage registry and mobile
projection. It does **not** introduce a second inbox, delivery queue, or audit
ledger — those already exist and are reused.

## Four separated concepts

```
domain event  →  interpreted insight  →  attention decision  →  notification  →  delivery  →  user interaction
```

Not every fact becomes an insight; not every insight becomes a notification; not
every notification goes to every channel. The honest distinctions are preserved
end to end: **provider-accepted ≠ delivered ≠ opened ≠ read ≠ acknowledged ≠
resolved**, and an HTTP 200 is not proof of anything.

## Ownership map (reuse, not rebuild)

| Concern | Owner |
|---|---|
| Tenant in-app inbox | `services/notification_intelligence/inbox.py` (table `notification_inbox`) |
| Forward-only lifecycle | `services/notification_intelligence/lifecycle.py` |
| Attention / routing policy | `services/notification_intelligence/policy_engine.py` |
| Delivery (intent → job → adapter → receipt) | `services/delivery/` (leased worker, backoff, dead-letter) |
| Channel gateways (Slack/Discord/Telegram/webhook) | `services/notification_intelligence/channel_gateway.py` |
| Operator notification center (desktop) | `frontend/kyber/src/features/notifications/` |

Desktop and mobile read the **same** `notification_inbox` records — a
notification opened on mobile is opened on desktop. Client-specific copies are not
created (only delivery-attempt records are per-channel).

## Contract twins (C2)

The notification and delivery models were Python-only; C2 adds their TS twins,
drift-guarded by parity tests:

- `packages/shared/notification.ts` ↔ `services/notification_intelligence/models.py`
  — `notificationLifecycleStates`, `notificationSeverities` (`P0`..`P3`, `info`),
  `notificationClasses` (incl. `action-request`), `operatorActionTypes`, and
  `IntelligenceNotificationEvent`.
- `packages/shared/delivery-receipt.ts` ↔ `services/delivery/models.py` —
  `deliveryChannels`, `deliveryJobStates`, `deliveryAttemptOutcomes`,
  `externalOutcomeTypes`, `ProviderReceipt`, `DeliveryAttempt`.

A `ProviderReceipt` is proof of delivery only with a real `external_id`; the
backend rejects an empty or `sim-`-prefixed id, so a simulated receipt can never be
recorded as delivered.

## Lifecycle

`detected → validated → queued → operator_review → approved → propagated`, plus the
terminal off-ramps `suppressed` and `expired`. Transitions are forward-only
(`LIFECYCLE_TRANSITIONS`).

## Staged (this program, later increments)

A producer-coverage registry (never report "healthy" when required coverage is
missing), the `/v1/notifications` route-prefix collision resolution, mobile
notification projection with redacted push content, and an unsafe-routing
validator (no zero-channel/zero-recipient false success, no simulated receipts, no
provider-acceptance-as-delivery) follow within the same program. See
`reports/mobile-productization/PROGRAM_STATE.yaml`.
