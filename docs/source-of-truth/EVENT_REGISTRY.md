# Event Registry

**Canonical source of truth:** `packages/shared/contracts/event-registry.json`  
(403 event types across 25 families, contract v8.12.0, schema v2.2.0)  
**Generated artifacts:** `packages/shared/events.ts` (TypeScript — `EventType`,
`EventFamily`, `EVENT_FAMILY`, `EVENT_CONSENT_PURPOSE`, field-trust / semantic-level
maps) and
`Backend Architecture/aether-backend/services/ingestion/generated_registry.py`
(Python), plus the native iOS/Android event-type + consent-purpose regions
(`Aether.swift` / `Aether.kt`) and the web consent map.  
**Regenerate with:** `python scripts/generate_contracts.py`  
**Authoritative per-event reference:** `docs/_generated/event-registry-table.md`
— every one of the 403 types with **Family | Required Purposes | Privacy Class |
Retention Class | Description** (deprecated events are marked).

Every `EventType` the SDK is permitted to emit must appear in the JSON registry.
Emitting anything outside this list will be dropped by the backend validator.
Of the 403 types, 399 are `active` and 4 are `deprecated` (kept for backward
compatibility); 153 are client-SDK-emittable (`sdkEmitable: true`), the rest are
backend / observation-plane events (see [Families](#event-families-contract-v8120)).

## Event families (contract v8.12.0)

`Count` is registry events; `SDK` is how many of them are `sdkEmitable: true`;
`Consent` is the required purpose(s) on the family's events.

| Family | Count | SDK | Consent | Covers |
|---|---|---|---|---|
| `core` | 7 | 7 | analytics (`experiment` → marketing) | track, page, screen, heartbeat, error, performance, experiment |
| `journey` | 15 | 12 | analytics | journey lifecycle + navigation/attribution (deep link, QR/NFC, app clip, install attribution) |
| `identity` | 1 | 1 | analytics | identify |
| `consent` | 1 | 1 | — (always allowed) | consent grant/revoke |
| `commerce` | 10 | 10 | commerce (`conversion` → marketing) | payment / approval / entitlement / access |
| `wallet` | 3 | 3 | web3 | wallet, transaction, contract_action |
| `agent` | 64 | — | agent (trade/position/portfolio/fill observations also financial_activity) | lifecycle, tools, and external observation (account / MCP / brokerage / AgentMail-style) |
| `reward` | 4 | 3 | commerce | reward action, claim, proof, delivery |
| `x402` | 26 | 26 | commerce | x402 payment lifecycle + externally-observed protocol flows |
| `exposure` | 8 | 8 | analytics (3 also personalization) + marketing (`ad_exposed`) | content/recommendation/offer/ad exposure |
| `outcome` | 9 | — | analytics (2 also personalization) | outcome/goal observation, recommendation acceptance |
| `b2b` | 20 | 20 | analytics (2 also commerce) | organization / workspace / member / seat / project |
| `ecommerce` | 23 | 23 | commerce | product / cart / checkout / order / subscription / invoice |
| `friction` | 12 | 12 | analytics | dead/rage click, form, scroll depth, backtrack |
| `interaction` | 12 | 12 | analytics | surface/UI interaction, feature + action lifecycle |
| `server` | 11 | — | analytics | API / webhook / job / connector observation |
| `identity_lc` | 15 | 15 | analytics | signup / login / logout / MFA / device / account recovery |
| `web3_lc` | 8 | — | web3 | on-chain transaction lifecycle observation |
| `comms` | 23 | — | marketing (email, unsubscribe) + analytics (notification, message, support) | notification / email / message / support-case delivery |
| `credit` | 3 | — | credit (explicit opt-in) | credit signal / account / decision |
| `location` | 2 | — | location (explicit opt-in) | location / geofence |
| `derivatives` | 52 | — | financial_activity (2 also agent) | derivatives position/order/fill/risk/reconciliation observation |
| `stablecoin` | 30 | — | economic_observability | stablecoin transfer/payment/mint/burn/valuation/depeg/finality |
| `interop` | 39 | — | cross_chain_observability | interop message/asset-leg/verification/reconciliation |
| `privacy` | 5 | — | — (always allowed) | data-subject requests + erasure (DSR/compliance) |

Two of the "SDK-emittable" families are only partially client-emittable:
`journey_completed`, `app_install_attributed`, and `deferred_attribution_resolved`
are backend-derived (`sdkEmitable: false`), as is `reward_action_queued` (reward
actions are queued by the backend). The generated table is authoritative for the
full per-type metadata — required purposes, privacy class, retention class, and
status — on every one of the 403 events; do not hand-maintain that enumeration
in prose.

Privacy classes in use: `behavioral`, `identity`, `governance`, `financial`,
`sensitive`, `sensitive_financial`, `sensitive_location`. Retention classes in
use: `standard_30d`, `standard_90d`, `standard_180d`, `standard_365d`,
`financial_7y`, `credit_730d`, `location_30d`, `permanent`. Each event's class is
declared on the spine and rendered in the generated table.

---

## Journey lifecycle (family: `journey`) — analytics

The seven canonical journey markers (client-observable):

| Type | Captured when | Notes |
|---|---|---|
| `journey_started` | journey start | Explicit start. |
| `journey_paused` | pause / background / hidden | Client observation only; backend owns final state. |
| `journey_resumed` | resume / foreground | Canonical top-level type; no longer emitted as an unregistered event. |
| `journey_continued` | foreground/resume within timeout | Same-device/session continuation. |
| `journey_completed` | backend finalization | `sdkEmitable: false` — the backend closes the journey. |
| `journey_abandoned` | `abandonJourney()` / safe client timeout | Backend may derive abandonment when client inference is unsafe. |
| `journey_checkpoint` | route/section checkpoint | Non-terminal step marker. |

The family also carries navigation and acquisition events: `navigation_intent`,
`navigation_arrival`, `deep_link_opened`, `qr_code_scanned`, `nfc_tag_read`,
`app_clip_invoked` (SDK-emitted), and `app_install_attributed`,
`deferred_attribution_resolved` (backend attribution results).

Journey payloads may include `journeyId`, `journeyName`, `journeyType`, step
IDs/names, status/reason fields, handoff source/target session/device
identifiers, latency, confidence, confidence signals, campaign/referrer
attribution, and metadata. Journey events require `analytics` consent unless
commerce, web3, or agent-specific data is also emitted through its canonical
event family.

Legacy `track` events remain accepted when `properties.event` is one of the
journey lifecycle names above. Ingestion normalizes those records for internal
journey stitching without breaking existing `track`, `page`, or `screen`
behavior.

## Core / Identity / Consent / Commerce / Wallet

| Family | Types | Consent |
|---|---|---|
| `core` | `track` (`aether.track()`), `page` (+SPA hooks), `screen`, `heartbeat`, `error`, `performance` → `analytics`; `experiment` → `marketing` | analytics / marketing |
| `identity` | `identify` (`aether.hydrateIdentity()`) | analytics |
| `consent` | `consent` (`aether.consent.grant/revoke`) | always allowed |
| `commerce` | `conversion`, `payment_initiated/completed/failed`, `approval_requested/resolved`, `entitlement_granted/revoked`, `access_granted/denied` | commerce |
| `wallet` | `wallet`, `transaction`, `contract_action` | web3 |

All `payment_*` events carry a `rail` field so a single code path handles fiat /
stripe / invoice / onchain / x402 / internal_credit. `conversion` is gated on
`marketing`, not `commerce` — a click is a marketing observation, never a
commerce fact on its own.

## Agent (family: `agent`) — agent / financial_activity

All 64 `agent` events are **backend / observation-plane** (`sdkEmitable:
false`): the agent lifecycle and tools are recorded by the Aether agent runtime,
and external observation arrives through provider webhooks / the MCP bridge /
parsers — never by the client SDK. Payload contracts:
`packages/shared/agent.ts` (`AgentRegisteredPayload`, …).

Three legacy events are `deprecated` but kept for backward compatibility:
`agent_task`, `agent_decision`, `a2h_interaction`.

### Lifecycle events (granular — preferred)

`agent_registered`, `agent_updated`, `agent_authorized`, `agent_deauthorized`,
`agent_capability_granted`, `agent_capability_revoked`, `agent_task_created` /
`decomposed` / `started` / `completed` / `failed`, `agent_tool_called`,
`agent_resource_requested`, `agent_delegated_task`, `agent_subagent_spawned`,
`agent_policy_evaluated`, `agent_handoff`, `agent_escalated_to_human`,
`agent_outcome_recorded`.

### Externally-observed agent activity (family `agent`)

These observe an external agent's account/activity — recorded from the outside;
Aether does not execute them. (The observability *service* lives under
`services/agentic_observability/`; the event *family* is `agent`.)

| Group | Types |
|---|---|
| Account / MCP observation | `agentic_account_observed`, `agentic_account_connected_observed`, `agentic_account_disconnected_observed`, `agent_budget_observed`, `agent_budget_changed_observed`, `agent_permission_observed`, `agent_mcp_connection_observed`, `agent_tool_observed`, `agent_tool_invocation_observed`, `agent_activity_observed`, `agent_risk_signal_observed`, `agent_notification_observed` |
| Trading (brokerage) observation | `agent_strategy_observed`, `agent_trade_intent_observed`, `agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_trade_rejection_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`, `agent_disconnect_observed` (the trade/position/portfolio/fill observations also require `financial_activity`) |
| Communication (AgentMail-style) observation | `agent_inbox_observed`, `agent_email_address_observed`, `agent_thread_observed`, `agent_message_received_observed`, `agent_message_sent_observed`, `agent_reply_observed`, `agent_attachment_observed`, `agent_attachment_parsed_observed`, `agent_otp_detected_observed`, `agent_invoice_detected_observed`, `agent_receipt_detected_observed`, `agent_calendar_intent_observed`, `agent_support_route_observed`, `agent_semantic_search_observed`, `agent_data_extraction_observed` |
| Runtime / oversight observation | `agent_evaluation_observed`, `agent_cost_observed`, `ai_invocation_observed`, `agent_grounding_observed`, `agent_guardrail_observed`, `agent_human_override_observed` |

## x402 (family: `x402`) — commerce

All 26 `x402` events are SDK-emittable and require `commerce` consent
(`privacyClass: financial`, `retentionClass: financial_7y`). Payload contracts:
`packages/shared/x402-lifecycle.ts` (`X402PaymentIntentCreatedPayload`, …).

### Legacy event

`x402_payment` is **deprecated** (kept for backward compatibility); the backend
lifecycle mapper normalizes it to `x402_payment_settled`.

### Lifecycle events (granular — preferred)

`x402_resource_requested`, `x402_payment_required`, `x402_quote_received`,
`x402_authorization_requested`, `x402_authorization_resolved`,
`x402_payment_intent_created`, `x402_payment_submitted`, `x402_payment_settled`,
`x402_payment_failed`, `x402_payment_timeout`, `x402_receipt_verified`,
`x402_access_granted`, `x402_access_denied`, `x402_refund_or_reversal`.

State machine:

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

### Externally-observed x402 flows (family `x402`)

The `*_observed` types record what Aether sees in an x402 flow it did not drive —
an external party requesting, authorizing, or settling a payment:

`x402_resource_request_observed`, `x402_challenge_observed`,
`x402_payment_requirement_observed`, `x402_signature_observed`,
`x402_verification_observed`, `x402_settlement_observed`,
`x402_resource_access_observed`, `x402_resource_access_denied_observed`,
`x402_failure_observed`, `x402_replay_risk_observed`, `x402_provider_observed`.

## Consent mapping (authoritative)

Generated from the registry: `packages/shared/events.ts::EVENT_CONSENT_PURPOSE`,
`packages/web/src/core/generated-consent-map.ts::EVENT_CONSENT_PURPOSE`, and the
native iOS/Android consent-purpose regions. The generated map holds each type's
primary (first) required purpose; events with no required purposes — `consent`
itself and the `privacy` DSR family — are always allowed at the consent gate and
default to `analytics` in the generated purpose map. An event whose required
purpose is not granted is **dropped before transport** by the SDK. Hand-edited
consent maps are not permitted — `generate_contracts.py --check` and
`validate_mobile_event_parity.py` enforce registry parity.

## Remaining families (dedicated sources of truth)

The families above and in the overview table have richer authored sources of
truth — see `STABLECOIN_EVENT_REGISTRY.md` (stablecoin), `COMMS_TRUTH_MATRIX.md`
(comms), `REWARD_ENABLEMENT.md` (reward), `AGENT_ACCESS_INTELLIGENCE_*.md` and
`AGENTIC_OBSERVABILITY_AUDIT.md` (agent observation), and
`docs/runbooks/INTEROP_OBSERVER_RUNBOOK.md` (interop). `privacy` (DSR) events are
added by the contract spine for compliance request/erasure tracking.
