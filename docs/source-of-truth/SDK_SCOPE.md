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

## Observation-Only Constraint

AETHER observes. AETHER does not execute.

The SDK never signs, sends, settles, or trades on behalf of the caller.
`execution_by_aether` must always be `false` in all observation payloads.

Any future capability that would have AETHER originate payments, send messages,
execute trades, custody funds, or sign transactions on behalf of tenants requires:
- Explicit product scope definition
- Legal review
- Compliance review
- Feature flag gating

Until that gate is cleared, no code path in AETHER may set `execution_by_aether = true`.

## Identity resolution boundary

The table below defines exactly what the SDK does vs. what the backend must do
after ingestion. This is a hard contract — the SDK side is exhaustive; anything
not listed is backend responsibility.

| Concern | SDK responsibility | Backend responsibility |
|---------|-------------------|----------------------|
| Anonymous identity | Generate and persist `anonymous_id` (UUID per install/browser) | — |
| User hydration | Emit `userId` field on events after host app login | Resolve `userId` → `canonical_entity_id` |
| Wallet signals | Emit `walletAddress` field; emit `wallet_signature_verified` when host app provides proof | Verify proof, map wallet → `canonical_entity_id` |
| Device fingerprint | Collect and emit fingerprint (consent-gated) | Use as weak support signal only; never promote to sole proof |
| `canonical_entity_id` | **Never set, never emit, never read** | Assign after Bronze ingestion via `services/identity/resolver.py` |
| Cross-device linking | Emit all available signals per event | Resolve cross-device links tenant-scoped, consent-gated |
| Conflict resolution | — | Enqueue candidates; expose operator review via `/v1/identity/conflicts` |
| Merge / split | — | Operator-initiated via `/v1/identity/merge` and `/v1/identity/split` |
| Consent enforcement | Gate signal collection and emission by local consent state | Gate resolution decisions by consent snapshot stamped on event |
| Alias revocation | — | Mark alias `revoked_at`; suppress from future resolution |

### What `canonical_entity_id` is and is not (SDK perspective)

- `canonical_entity_id` is a **backend-only construct**. It does not appear in
  any SDK public API, event schema, or client-side storage.
- SDK events carry raw signals (`userId`, `anonymousId`, `walletAddress`, etc.)
  as first-class fields. The backend maps these to `canonical_entity_id` after
  ingestion.
- If a host app needs to display or reference a canonical identity, it must
  read `canonical_entity_id` from the backend API (`GET /v1/identity/entities/{id}`)
  using server-side credentials, not from the SDK.


## Agentic server-side contract v2

Server-side agent and MCP SDKs use Agentic Observation Contract v2 for observation-only telemetry. The backend accepts `event_type` as the v2 canonical event field and keeps `event_name` as a v1 compatibility alias. The contract carries runtime, correlation, MCP, authorization, verification, and privacy context groups, and it still rejects any payload that claims `execution_by_aether=true`.
