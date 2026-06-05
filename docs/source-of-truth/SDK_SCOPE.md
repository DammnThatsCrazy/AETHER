# SDK Scope

## What the Aether SDK IS

A **thin, observation-only capture layer** that runs on the client (browser,
iOS, Android, React Native) and emits canonical events to the Aether backend
via a single HTTP batch endpoint.

The SDK is responsible for:

1. Building and maintaining **anonymous identity** + session state.
2. **Hydrating** identity when the host app knows a user / wallet / tenant.
3. Capturing **core analytics**: track, page/screen, conversion, heartbeat.
4. Capturing **wallet and transaction** events when the host app has web3
   context.
5. Capturing **deep-link / campaign / referrer** signals.
6. Capturing **push-open** events on native platforms.
7. Enforcing **consent gating** locally before transport.
8. Offering thin, typed **emitters** for commerce / agent / x402 events when
   the host app wants to report them (backend does all the orchestration).
9. **Batching, retrying, and persisting** events until they reach
   `POST /v1/batch`.
10. Fetching a **capability manifest** from `GET /v1/config`.

## What the Aether SDK IS NOT

The SDK does NOT:

- Classify wallets (hot/cold/smart/exchange).
- Compute DeFi positions, NFT holdings, portfolio value, whale thresholds.
- Score fraud, trust, or risk.
- Resolve identity clusters or link cross-device profiles.
- Run approval workflows, settle payments, or grant entitlements.
- Derive ground truth for agent decisions.
- Host ML models.
- Maintain a business graph.
- Decide what is or is not "valuable" activity.

All of that is backend responsibility. The SDK's job is to observe and
deliver observations.

## Design invariants

- **One batch endpoint**: every platform POSTs `POST /v1/batch`.
- **One event envelope**: every event conforms to `BaseEvent` in
  `packages/shared/events.ts`.
- **One consent model**: every SDK recognises the same 5 purposes.
- **No backend duplication**: workflow logic never lives in the client.
- **Optional tiers are optional**: commerce, agent, wallet, x402 surfaces
  only activate when the host app calls them.

## Journey continuity boundary

SDKs expose a consistent journey API (`startJourney`, `pauseJourney`, `resumeJourney`,
`continueJourney`, `completeJourney`, `abandonJourney`, `checkpointJourney`,
`getCurrentJourney`, and supported `onJourneyResumed` callbacks). These methods emit
canonical observations only. The backend stitches sessions, assigns/merges journey IDs,
computes handoff confidence, and decides whether a journey is linked, ambiguous, active,
abandoned, or completed.

SDKs must not make identity truth decisions. Fingerprints are collected only where
allowed by consent and are support signals, not sole proof. Cross-device linking is
always tenant-scoped and requires valid consent plus stronger identity evidence when the
link is sensitive.
