# Event Registry

Every `EventType` the SDK is permitted to emit. Defined in
`packages/shared/events.ts`. Emitting anything outside this list will be
dropped by the backend validator.

## Core analytics (family: `core`) — purpose: `analytics`

| Type | Emitted by | Purpose |
|---|---|---|
| `track` | `aether.track()` | Custom event |
| `page` | `aether.pageView()` + SPA hooks (web) | Navigation |
| `screen` | native lifecycle / `screenView()` | Navigation |
| `heartbeat` | session manager | Session liveness |
| `error` | error capture modules | Client errors |
| `performance` | perf collectors | Web Vitals, load metrics |
| `experiment` | experiment runners | Variant exposure |

## Identity (family: `identity`) — purpose: `analytics`

| Type | Emitted by |
|---|---|
| `identify` | `aether.hydrateIdentity()` |

## Consent (family: `consent`) — always allowed

| Type | Emitted by |
|---|---|
| `consent` | `aether.consent.grant/revoke` |

## Commerce / access (family: `commerce`) — purpose: `commerce` (except `conversion` → `marketing`)

| Type | Emitted by |
|---|---|
| `conversion` | `aether.conversion()` |
| `payment_initiated` | `aether.commerce.paymentInitiated()` |
| `payment_completed` | `aether.commerce.paymentCompleted()` |
| `payment_failed` | `aether.commerce.paymentFailed()` |
| `approval_requested` | `aether.commerce.approvalRequested()` |
| `approval_resolved` | `aether.commerce.approvalResolved()` |
| `entitlement_granted` | `aether.commerce.entitlementGranted()` |
| `entitlement_revoked` | `aether.commerce.entitlementRevoked()` |
| `access_granted` | `aether.commerce.accessGranted()` |
| `access_denied` | `aether.commerce.accessDenied()` |

All `payment_*` events carry a `rail` field so a single code path handles
fiat / stripe / invoice / onchain / x402 / internal_credit.

## Wallet / on-chain (family: `wallet`) — purpose: `web3`

| Type | Emitted by |
|---|---|
| `wallet` | `aether.wallet.connect/disconnect` |
| `transaction` | `aether.wallet.transaction()` |
| `contract_action` | host app via `aether.track()` wrapper (optional) |

## Agent (family: `agent`) — purpose: `agent`

| Type | Emitted by |
|---|---|
| `agent_task` | `aether.agent.task()` |
| `agent_decision` | `aether.agent.decision()` |
| `a2h_interaction` | `aether.agent.interaction()` |

## x402 (family: `x402`) — purpose: `commerce`

| Type | Emitted by |
|---|---|
| `x402_payment` | `aether.x402.payment()` |

## Consent mapping (authoritative)

Mirrored in `packages/shared/events.ts::EVENT_CONSENT_PURPOSE` and
`packages/web/src/core/event-queue.ts::CONSENT_MAP`. An event whose required
purpose is not granted is **dropped before transport** by the SDK.

## Journey lifecycle (family: `journey`) — purpose: `analytics`

| Type | Emitted by | Notes |
|---|---|---|
| `journey_started` | `startJourney()` | Explicit host-app journey start. |
| `journey_paused` | `pauseJourney()` / app background / page hidden | Client observation only; backend owns final state. |
| `journey_resumed` | `resumeJourney()` / `/sdk/identity/resolve` match | Canonical top-level type; no longer emitted as an unregistered event. |
| `journey_continued` | foreground/resume within timeout | Same-device/session continuation. |
| `journey_completed` | `completeJourney()` | Explicit host-app completion. |
| `journey_abandoned` | `abandonJourney()` / safe client timeout | Backend may derive abandonment when client inference is unsafe. |
| `journey_checkpoint` | `checkpointJourney()` / throttled SPA route checkpoint | Non-terminal step marker. |

Journey payloads may include `journeyId`, `journeyName`, `journeyType`, step IDs/names,
status/reason fields, handoff source/target session/device identifiers, latency,
confidence, confidence signals, campaign/referrer attribution, and metadata. Journey
events default to `analytics` consent unless commerce, web3, or agent-specific data is
also emitted through its canonical event family.

Legacy `track` events remain accepted when `properties.event` is one of the journey
lifecycle names above. Ingestion normalizes those records for internal journey stitching
without breaking existing `track`, `page`, or `screen` behavior.
