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

### Legacy events (kept for backward compatibility)

| Type | Emitted by |
|---|---|
| `agent_task` | `aether.agent.task()` |
| `agent_decision` | `aether.agent.decision()` |
| `a2h_interaction` | `aether.agent.interaction()` |

### Lifecycle events (granular — preferred)

| Type | Emitted by |
|---|---|
| `agent_registered` | `aether.agent.registered()` |
| `agent_updated` | `aether.agent.updated()` |
| `agent_authorized` | `aether.agent.authorized()` |
| `agent_deauthorized` | `aether.agent.deauthorized()` |
| `agent_capability_granted` | `aether.agent.capabilityGranted()` |
| `agent_capability_revoked` | `aether.agent.capabilityRevoked()` |
| `agent_task_created` | `aether.agent.taskCreated()` |
| `agent_task_decomposed` | `aether.agent.taskDecomposed()` |
| `agent_task_started` | `aether.agent.taskStarted()` |
| `agent_task_completed` | `aether.agent.taskCompleted()` |
| `agent_task_failed` | `aether.agent.taskFailed()` |
| `agent_tool_called` | `aether.agent.toolCalled()` |
| `agent_resource_requested` | `aether.agent.resourceRequested()` |
| `agent_delegated_task` | `aether.agent.delegatedTask()` |
| `agent_subagent_spawned` | `aether.agent.subagentSpawned()` |
| `agent_policy_evaluated` | `aether.agent.policyEvaluated()` |
| `agent_handoff` | `aether.agent.handoff()` |
| `agent_escalated_to_human` | `aether.agent.escalatedToHuman()` |
| `agent_outcome_recorded` | `aether.agent.outcomeRecorded()` |

Payload contracts: `packages/shared/agent.ts` (`AgentRegisteredPayload`, etc.)

## x402 (family: `x402`) — purpose: `commerce`

### Legacy event (kept for backward compatibility)

| Type | Emitted by |
|---|---|
| `x402_payment` | `aether.x402.payment()` |

Legacy `x402_payment` normalizes to `x402_payment_settled` in the backend lifecycle mapper.

### Lifecycle events (granular — preferred)

| Type | Emitted by |
|---|---|
| `x402_resource_requested` | `aether.x402.resourceRequested()` |
| `x402_payment_required` | `aether.x402.paymentRequired()` |
| `x402_quote_received` | `aether.x402.quoteReceived()` |
| `x402_authorization_requested` | `aether.x402.authorizationRequested()` |
| `x402_authorization_resolved` | `aether.x402.authorizationResolved()` |
| `x402_payment_intent_created` | `aether.x402.paymentIntentCreated()` |
| `x402_payment_submitted` | `aether.x402.paymentSubmitted()` |
| `x402_payment_settled` | `aether.x402.paymentSettled()` |
| `x402_payment_failed` | `aether.x402.paymentFailed()` |
| `x402_payment_timeout` | `aether.x402.paymentTimeout()` |
| `x402_receipt_verified` | `aether.x402.receiptVerified()` |
| `x402_access_granted` | `aether.x402.accessGranted()` |
| `x402_access_denied` | `aether.x402.accessDenied()` |
| `x402_refund_or_reversal` | `aether.x402.refundOrReversal()` |

Payload contracts: `packages/shared/x402-lifecycle.ts` (`X402PaymentIntentCreatedPayload`, etc.)

### Consent rules

All x402 lifecycle events require `commerce` consent. If `agent` consent is
also granted, agent-specific detail fields are included in the payload.
Wallet/onchain fields require `web3` consent.

### State machine

```
x402_resource_requested
  → x402_payment_required
  → x402_quote_received
  → x402_authorization_requested
  → x402_authorization_resolved
  → x402_payment_intent_created
  → x402_payment_submitted
  → x402_payment_settled [terminal] | x402_payment_failed [terminal] | x402_payment_timeout [terminal]
  → x402_receipt_verified
  → x402_access_granted | x402_access_denied
  → x402_refund_or_reversal [optional terminal]
```

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

## Agentic account / MCP observation (family: `agentic_observability`) — purpose: `agent`

| Type | Observed from | Notes |
|---|---|---|
| `agentic_account_observed` | External provider webhook | New external agentic account observed |
| `agentic_account_connected_observed` | External provider webhook | Account connected to agent |
| `agentic_account_disconnected_observed` | External provider webhook | Account disconnected |
| `agent_budget_observed` | External provider webhook | Agent budget state observed |
| `agent_budget_changed_observed` | External provider webhook | Agent budget changed |
| `agent_permission_observed` | External provider webhook | Agent permissions observed |
| `agent_mcp_connection_observed` | MCP server / webhook | MCP connection observed |
| `agent_tool_observed` | MCP server | Tool available on MCP server observed |
| `agent_tool_invocation_observed` | MCP server | Tool invocation observed |
| `agent_activity_observed` | External provider | General agent activity observed |
| `agent_risk_signal_observed` | AETHER risk engine | Risk signal produced from observed activity |
| `agent_notification_observed` | External provider webhook | Agent notification observed |

## Robinhood-style trading observation (family: `agentic_observability`) — purpose: `agent`

| Type | Observed from | Notes |
|---|---|---|
| `agent_strategy_observed` | External brokerage webhook | Trading strategy observed |
| `agent_trade_intent_observed` | External brokerage webhook | Trade intent observed (not executed by AETHER) |
| `agent_trade_order_observed` | External brokerage webhook | Trade order observed (executed externally) |
| `agent_trade_fill_observed` | External brokerage webhook | Trade fill observed (executed externally) |
| `agent_trade_rejection_observed` | External brokerage webhook | Trade rejection observed |
| `agent_position_observed` | External brokerage webhook | Position snapshot observed |
| `agent_portfolio_snapshot_observed` | External brokerage webhook | Portfolio snapshot observed |
| `agent_performance_snapshot_observed` | External brokerage webhook | Performance metrics observed |
| `agent_disconnect_observed` | External brokerage webhook | External account disconnect observed |

## AgentMail-style communication observation (family: `agentic_observability`) — purpose: `agent`

| Type | Observed from | Notes |
|---|---|---|
| `agent_inbox_observed` | AgentMail-style webhook | Agent inbox state observed |
| `agent_email_address_observed` | AgentMail-style webhook | Agent email address observed |
| `agent_thread_observed` | AgentMail-style webhook | Message thread observed |
| `agent_message_received_observed` | AgentMail-style webhook | Inbound message observed |
| `agent_message_sent_observed` | AgentMail-style webhook | Outbound message observed (sent externally) |
| `agent_reply_observed` | AgentMail-style webhook | Reply observed |
| `agent_attachment_observed` | AgentMail-style webhook | Attachment observed |
| `agent_attachment_parsed_observed` | AETHER parser | Attachment parsing result observed |
| `agent_otp_detected_observed` | AETHER extractor | OTP detected in message |
| `agent_invoice_detected_observed` | AETHER extractor | Invoice detected in message |
| `agent_receipt_detected_observed` | AETHER extractor | Receipt detected in message |
| `agent_calendar_intent_observed` | AETHER extractor | Calendar intent detected |
| `agent_support_route_observed` | AETHER classifier | Support routing decision observed |
| `agent_semantic_search_observed` | AgentMail-style webhook | Semantic search performed on inbox |
| `agent_data_extraction_observed` | AgentMail-style webhook | Data extraction performed on message |

## x402 protocol observation (family: `x402_observability`) — purpose: `agent`

These events are observed FROM THE OUTSIDE — AETHER records what it sees in an x402 flow, not what it does.

| Type | Observed from | Notes |
|---|---|---|
| `x402_resource_request_observed` | Agent/client activity | Agent requested a paid resource |
| `x402_challenge_observed` | HTTP 402 response | 402 challenge received by agent |
| `x402_payment_requirement_observed` | PAYMENT-REQUIRED header | Payment requirement metadata observed |
| `x402_signature_observed` | X-PAYMENT header | Payment signature submitted by external party |
| `x402_verification_observed` | Facilitator response | Verification result observed |
| `x402_settlement_observed` | External settlement event | Settlement observed (executed externally, not by AETHER) |
| `x402_resource_access_observed` | Server response | Resource access outcome observed |
| `x402_resource_access_denied_observed` | Server response | Access denied outcome observed |
| `x402_failure_observed` | Any stage | Protocol failure observed |
| `x402_replay_risk_observed` | AETHER risk engine | Replay attack risk detected |
| `x402_provider_observed` | Protocol metadata | x402 provider observed |

### Deprecated x402 event names (imply AETHER executes — use observation equivalents)

| Deprecated | Replace with |
|---|---|
| `x402_payment_submitted` | `x402_signature_observed` (the external party submitted, not AETHER) |
| `x402_payment_settled` | `x402_settlement_observed` |
| `x402_payment_created` | `x402_payment_requirement_observed` |
