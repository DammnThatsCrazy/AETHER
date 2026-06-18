# Platform Parity

Parity is declared explicitly. Forced parity is not pursued; capabilities are
placed into tiers.

## Tiers

- **Tier A** — required across all four SDKs. Release blocker if missing.
- **Tier B** — required for Web + React Native; optional / best-effort on
  native iOS / Android.
- **Tier C** — web-only or platform-specific by design.

## Matrix

| Capability | Tier | Web | iOS | Android | RN | Notes |
|---|---|---|---|---|---|---|
| Canonical `/v1/batch` transport | A | ✔ | ✔ | ✔ | ✔ | `/v1/ingest/*` is connector/server-side only. |
| Version-synchronized runtime/package metadata | A | ✔ | ✔ | ✔ | ✔ | Validated by `scripts/validate_sdk_release_alignment.py`. |
| Core analytics (`track`, page/screen, conversion) | A | ✔ | ✔ | ✔ | ✔ | Custom app events use `track` + `properties.event`. |
| Error/performance where platform appropriate | A | ✔ | ✔ | ✔ | ✔ | Native lifecycle/error capture is platform-scoped. |
| Journey lifecycle API + canonical events | A | ✔ | ✔ | ✔ | ✔ | Start/pause/resume/continue/complete/abandon/checkpoint/current journey. |
| Identity hydration/reset/session/anonymous ID | A | ✔ | ✔ | ✔ | ✔ | Email is hashed before identity resolve where implemented. |
| Consent pre-send enforcement (opt-in and opt-out) | A | ✔ | ✔ | ✔ | ✔ | `gdprMode=false` → opt-out (all events pass). `gdprMode=true` → explicit opt-in. Consent events are never blocked. |
| Sensitive field scrubber | A | — | ✔ | ✔ | Native-owned | SENSITIVE_KEYS set (privateKey/seedPhrase/cardNumber/cvv/pan/password/paymentToken etc.) redacted before queue. Web SDK does not collect these fields. |
| Commerce/access canonical emitters | A | ✔ | ✔ | ✔ | ✔ | `payment_*`, approvals, entitlements, access, ecommerce helpers. |
| Wallet/web3 manual emitters | A | ✔ | ✔ | ✔ | ✔ | Manual wallet, transaction, contract action; backend owns enrichment. |
| EVM address normalization | B | ✔ | ✔ | ✔ | Native-owned | `walletConnected` lowercases EVM addresses before storage and transport. |
| WalletConnect v2 session tracking | B | — | ✔ | ✔ | ✔ | `trackWalletConnectSession(topic, address?, chainId?)` emits wallet event and resolves identity. |
| Apple Pay payment tracking | C | — | ✔ | — | iOS only | `trackApplePayPayment(status, amount?, currency?)` via PassKit delegate callbacks. |
| Google Pay payment tracking | C | — | — | ✔ | Android only | `trackGooglePayPayment(status, amount?, currency?)` via PaymentsClient callbacks. |
| Wallet capability API | B | — | ✔ | ✔ | ✔ | `getWalletCapabilities()` returns connected state, addresses, supportedVMs, applePay/googlePay availability. |
| Multi-VM metadata support | B | ✔ | Partial | Partial | Partial | Native/RN expose manual typed metadata; no full automatic detection. |
| Agent canonical emitters | A | ✔ | ✔ | ✔ | ✔ | `agent_task`, `agent_decision`, `a2h_interaction`. |
| x402 payment emitter | A | ✔ | ✔ | ✔ | ✔ | Commerce consent required. |
| Granular agent lifecycle emitters (19) | A | ✔ | ✔ | ✔ | ✔ | All 19 methods: registered, updated, authorized, deauthorized, capabilityGranted/Revoked, taskCreated/Decomposed/Started/Completed/Failed, toolCalled, resourceRequested, delegatedTask, subagentSpawned, policyEvaluated, handoff, escalatedToHuman, outcomeRecorded. |
| Granular x402 lifecycle emitters (14) | A | ✔ | ✔ | ✔ | ✔ | All 14 methods: resourceRequested, paymentRequired, quoteReceived, authorizationRequested/Resolved, paymentIntentCreated/Submitted/Settled/Failed/Timeout, receiptVerified, accessGranted/Denied, refundOrReversal. |
| Native rewards client | B | ✔ | ✔ | ✔ | ✔ | 4 observation emitters: actionQueued, proofGenerated, delivered, claimSubmitted. Backend owns eligibility/claim logic. |
| Full ecommerce workflow | B | ✔ | ✔ | ✔ | ✔ | removeFromCart, applyCoupon, beginCheckout added to iOS/Android/RN. Existing: trackProductView, trackAddToCart, trackPurchase. |
| Health heartbeat | A | ✔ | ✔ | ✔ | ✔ | Native fleet heartbeat + manifest fetch added; full payload matches Web health agent. |
| Remote manifest/config | A | ✔ | ✔ | ✔ | ✔ | Non-blocking fetch; endpoint overrides honored where implemented. |
| Retry/backoff/429 handling | A | ✔ | ✔ | ✔ | Native-owned | 4xx no-retry; 5xx/429 retry. |
| Offline persistence/durable queue | B | ✔ | ✔ | ✔ | Native-owned | File-based persistence in ApplicationSupport (iOS) and filesDir (Android); cap 1000 events. |
| Plugin hooks | C | ✔ | — | — | — | Web-only. |
| Heatmaps/funnels/form analytics/auto-discovery | C | ✔ | — | — | — | Web-only capabilities documented as such. |

Legend: ✔ shipped, Partial = supported with documented platform limitations, — not applicable.

## Policy

- A **Tier A gap** must block the release and is tracked as NEEDS UPDATE.
- A **Tier B gap** is acceptable. Add it when the host platform demands it.
- A **Tier C capability** is platform-idiomatic and will never be ported.

## Current Tier A gaps

None. All Tier A rows are satisfied.

## Current Tier B gaps (open follow-ups)

None. All Tier B gaps resolved in SDK 8.9.0 productionization pass.

Previously open items — now closed:
- Native rewards client → shipped (4 emitters on iOS/Android/RN/Web).
- Full automatic native multi-VM wallet detection → manual emitters ship; auto-detection remains backend-owned per architecture.
- Durable native queue persistence → shipped (file-based on iOS/Android).
- Native health payloads — schema hash + endpoint latency → shipped in AetherHealthAgent.
- Native plugin hooks → confirmed Web-only (Tier C by design; will not port).
- Web SDK sensitive field scrubber → confirmed Web does not collect these fields by design.
