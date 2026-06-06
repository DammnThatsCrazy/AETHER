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
| Consent pre-send enforcement | A | ✔ | ✔ | ✔ | ✔ | Consent events are never blocked; unknown raw event types are dropped. |
| Commerce/access canonical emitters | A | ✔ | ✔ | ✔ | ✔ | `payment_*`, approvals, entitlements, access, ecommerce helpers. |
| Wallet/web3 manual emitters | A | ✔ | ✔ | ✔ | ✔ | Manual wallet, transaction, contract action; backend owns enrichment. |
| Multi-VM metadata support | B | ✔ | Partial | Partial | Partial | Native/RN expose manual typed metadata; no full automatic detection. |
| Agent canonical emitters | A | ✔ | ✔ | ✔ | ✔ | `agent_task`, `agent_decision`, `a2h_interaction`. |
| x402 payment emitter | A | ✔ | ✔ | ✔ | ✔ | Commerce consent required. |
| Health heartbeat | A | ✔ | Partial | Partial | ✔ | Native payloads include library/consent; JS health agent has fleet payload. |
| Remote manifest/config | A | ✔ | ✔ | ✔ | ✔ | Non-blocking fetch; endpoint overrides honored where implemented. |
| Retry/backoff/429 handling | A | ✔ | ✔ | ✔ | Native-owned | 4xx no-retry; 5xx/429 retry. |
| Offline persistence/durable queue | B | ✔ | Partial | Partial | Native-owned | Native queues are bounded in-memory in this pass. |
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

- Native rewards client (web only today).
- Full automatic native multi-VM wallet detection (manual emitters ship now).
- Durable native queue persistence beyond bounded in-memory retry queues.
- Native health payloads do not yet expose every Web health metric such as schema hash and endpoint latency. 
- Native plugin hooks (web only today).
