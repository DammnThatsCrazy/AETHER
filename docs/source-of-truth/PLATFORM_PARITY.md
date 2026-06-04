# Platform Parity

Parity is declared explicitly. Forced parity is not pursued; capabilities are
placed into tiers.

## Tiers

- **Tier A** — required across all four SDKs. Release blocker if missing.
- **Tier B** — required for Web + React Native; optional / best-effort on
  native iOS / Android.
- **Tier C** — web-only or platform-specific by design.

## Matrix

| Capability | Tier | Web | iOS | Android | RN |
|---|---|---|---|---|---|
| Core analytics (track/identify/conversion) | A | ✔ | ✔ | ✔ | ✔ |
| Page / screen tracking | A | ✔ (page) | ✔ (screen) | ✔ (screen) | ✔ (screen) |
| Session / heartbeat | A | ✔ | ✔ | ✔ | ✔ |
| Journey lifecycle API + canonical events | A | ✔ | ✔ | ✔ | ✔ |
| Identity hydration | A | ✔ | ✔ | ✔ | ✔ |
| Consent (5 purposes) | A | ✔ | ✔ | ✔ | ✔ |
| Campaign / deep-link / UTM | A | ✔ | ✔ | ✔ | ✔ |
| Device fingerprint | A | ✔ | ✔ | ✔ | ✔ |
| Wallet EVM connect/disconnect/tx | A | ✔ | ✔ | ✔ | ✔ |
| E-commerce events | A | ✔ | ✔ | ✔ | ✔ |
| Feature flag evaluation | A | ✔ | ✔ | ✔ | ✔ |
| Push-open tracking | B | — | ✔ | ✔ | ✔ |
| Offline persistence | B | ✔ | ✗ | ✗ | ✗ |
| Plugin hooks (`use()`) | B | ✔ | ✗ | ✗ | ✗ |
| Semantic context | B | ✔ | ✗ | ✗ | ✔ (partial) |
| Rewards claim client | B | ✔ | ✗ | ✗ | ✗ |
| Wallet multi-VM (SVM/BTC/SUI/NEAR/TRON/Cosmos) | B | ✔ | ✗ | ✗ | ✗ |
| Thin commerce emitters (payment_*/approval_*/...) | B | ✔ | ✗ | ✗ | ✗ |
| Thin agent emitters (agent_task/decision/a2h) | B | ✔ | ✗ | ✗ | ✗ |
| Thin x402 emitter | B | ✔ | ✗ | ✗ | ✗ |
| Experiments runtime | B | ✗ | ✗ | ✗ | ✔ |
| Feedback / surveys | B | ✗ | ✗ | ✗ | ✔ |
| Heatmaps | C (web) | ✔ | — | — | — |
| Funnels (client tagging) | C (web) | ✔ | — | — | — |
| Form analytics | C (web) | ✔ | — | — | — |
| Auto-discovery (click capture) | C (web) | ✔ | — | — | — |
| Uncaught-exception capture | C (android) | ✗ | ✗ | ✔ | — |

Legend: ✔ shipped, ✗ absent (Tier B = acceptable; Tier A = release blocker),
— not applicable.

## Policy

- A **Tier A gap** must block the release and is tracked as NEEDS UPDATE.
- A **Tier B gap** is acceptable. Add it when the host platform demands it.
- A **Tier C capability** is platform-idiomatic and will never be ported.

## Current Tier A gaps

None. All Tier A rows are satisfied.

## Current Tier B gaps (open follow-ups)

- Native rewards client (web only today).
- Native multi-VM wallet methods (web only today).
- Native thin commerce/agent/x402 emitters (web only today).
- Native offline queue persistence (web only today).
- Native plugin hooks (web only today).
