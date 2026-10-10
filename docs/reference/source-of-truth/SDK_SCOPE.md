---
title: Sdk Scope
slug: source-of-truth/sdk_scope
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
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
- **One consent model**: every SDK recognises the same registry-derived purposes
  (canonical set in `packages/shared/contracts/consent-registry.json`).
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

### SDK identify endpoint contract

`POST /sdk/identify` records the caller's `user_id` and supplied traits as
source identity evidence, then invokes the canonical resolver using the
authenticated tenant, anonymous ID, and email/phone traits. The SDK's `user_id`
is not passed as resolver proof and cannot authorize a merge. The endpoint
does not treat `consent_state` from the request as an authoritative grant; until
server-side consent is loaded and validated, sensitive email/phone linking is
resolved without a consent snapshot and must fail closed under resolver policy.

The response's `identified` flag means the identify request was accepted for
processing; `resolution_outcome` carries the identity decision. It includes
`canonical_entity_id` only for a `create`, `link`, or `merge` decision with a
non-empty canonical ID and successful source-identity/claim registration.
Candidate, blocked, rejected, pending, and failed outcomes carry no canonical
ID. `reason_codes` carries the resolver's policy reasons without exposing
candidate canonical IDs. `confidence` is the resolver's evidence-weighted
identity match score; it is not a calibrated probability.
`requires_restatement` remains false because this endpoint has no durable
acknowledgement that a projection restatement was accepted.
`resolution_event_publish_succeeded` reports only whether the producer's
publish call returned; it is not a durable delivery receipt. A publish failure
does not undo the identity decision or fail the identify request.

The endpoint emits `IDENTITY_RESOLVED` only when it has a canonical ID; other
outcomes emit `RESOLUTION_EVALUATED`. These events omit user IDs, anonymous IDs,
and email/phone traits; they refer to the SDK identity through its backend
source identity record. Direct calls to `POST /sdk/identify` require a
caller-supplied `idempotency_key`, scoped to the authenticated tenant and bound
to a fingerprint of the complete request. Identical completed retries replay
the stored outcome; concurrent retries return `in_progress`; reuse with changed
payload returns HTTP 409. Claims older than 15 minutes without an update report
`stale` and require operator reconciliation. Claims are not automatically
replayed or cleared. Resolver writes, restatement enqueue, response persistence,
and broker publication are not in one transaction/outbox, so this prevents
duplicate execution for the same key but is not an exactly-once guarantee.

The SDK Web, Server, iOS, and Android hydration methods emit an `identify` event
through `POST /v1/batch`, not the direct endpoint. The event's
`properties.idempotency_key` matches its top-level event `id`, so transport
retries and durable queue replay retain the same key; a new hydration event
gets a new key. React Native delegates to native iOS/Android. Server SDK callers
can emit the same event with `track({ type: 'identify', ... })`. This event
property does not substitute for the required request-body key on direct
`POST /sdk/identify` calls.

For V1 `/v1/batch`, the server uses tenant + top-level event ID + schema as
the idempotency key for canonical identify resolution. Redis `SET NX` bounds
that guard to 24 hours, and identify events fail closed if the claim store is
unavailable. Resolution starts only after the claim succeeds and batch publish
returns successfully. V1 has no durable resolver work receipt, so a crash after
publish but before task scheduling, or a resolver error, can leave accepted
ingestion without confirmed canonical resolution. V2 uses the durable unique
tenant/event/schema key and transactional outbox, whose delivery is at-least-once.
SDK event keys therefore preserve retries, but do not claim exactly-once
resolution or durable resolver retry.

Before canonical resolution, the direct endpoint evaluates imported identity
candidates. Candidate or blocked evidence returns that outcome without running
the resolver create path, preventing a duplicate canonical profile while the
import evidence requires safer resolution. Source identity and claim
registration remain distinct from canonical resolution.

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
| `canonical_entity_id` | **Never set, never emit, never read** | Assign after Bronze ingestion via `services/api/identity/identity/resolver.py` |
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
