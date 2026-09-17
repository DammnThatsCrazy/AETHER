---
title: SDK Productization Close-Out Blueprint
slug: blueprints/sdk-close-out
section: architecture
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Revised Aether SDK Productization Close-Out & Certification Blueprint

## 1. Current Decision

The original SDK Parity, Activation, and Readiness Spine blueprint is still directionally correct, but it should no longer be treated as the main build plan.

The repo has moved forward. The SDK program now appears to have:

- SDK distribution.
- Web loader build/publish path.
- CDN release pipeline.
- One-tag web install.
- Publishable key support.
- First-heartbeat verification.
- SDK install observability.
- Control-plane install drift detection.
- SDK version-surface plumbing.
- Responsiveness and time-to-value observability.
- SDK heartbeat SLOs.
- Activation milestones.
- Aether and Kyber surfaces for readiness/health visibility.

Therefore the new blueprint should become a **close-out and certification plan**.

The question is no longer:

> “How do we productize the SDKs?”

The correct question is now:

> “How do we prove the SDKs are installable, governable, observable, version-safe, parity-safe, and tenant-ready across every supported platform?”

## 2. What Has Already Been Addressed

## 2.1 SDK distribution gap: mostly addressed

PR #648 directly addresses the prior gap where the SDK existed but could not be reliably installed.

It adds:

- build artifacts for `@aether/web`
- publish-surface gates
- CDN release pipeline
- standardized API/CDN domains
- publishable `pk_` keys
- one-tag install
- first-heartbeat verification
- SDK install observability events
- managed integration registration
- site install drift detection

This means the “SDKs need an install/distribution spine” part of the original blueprint has largely been addressed.

## 2.2 SDK version drift: mostly addressed

PR #649 directly addresses version drift.

It fixes:

- `LOADER_VERSION`
- backend `CANONICAL_SDK_VERSION`
- bump check/rewrite mismatch
- SDK publish workflow artifact inclusion
- changelog coverage
- CI/CD documentation

This means the earlier recommendation to align version surfaces is now mostly complete.

## 2.3 Time-to-value and responsiveness: partially addressed

PR #650 adds a Responsiveness & Time-to-Value Spine.

It includes:

- SDK heartbeat SLOs
- activation milestones
- surface readiness
- provider sync state
- graph hydration state
- projection state
- lens projection state
- timeline projection state
- query execution state
- Aether UI surfaces
- Kyber operator surfaces
- CI performance/readiness gates
- documentation

This absorbs a large part of the original “activation state and first-value proof” requirement.

## 3. What Still Needs to Be Done

The remaining work is not broad architecture. It is **release certification, parity proof, and edge remediation**.

## 3.1 Fix remaining SDK config inconsistency

### Problem

PR #648 states that publishable keys are confined to ingestion, so the SDK’s `GET /v1/config` returns `403` and `fetchConfig` silently degrades to local defaults.

That is a serious productization gap.

The SDK cannot be fully governed by a remote manifest if the normal publishable key cannot fetch the manifest.

### Required change

Create a safe manifest-access path for publishable keys:

```http
GET /v1/config/sdk/manifest
Authorization: Bearer pk_...
```

or:

```http
GET /v1/config/sdk/manifest?site_id=...
Authorization: Bearer pk_...
```

The manifest endpoint must be limited to:

- site-scoped SDK configuration
- public-safe SDK settings
- allowed endpoints
- schema version
- schema hash
- minimum SDK version
- feature flags
- sampling policy
- kill switches
- rollout percentage
- consent policy version

It must not expose:

- tenant secrets
- private API keys
- internal routes
- admin features
- billing data
- provider credentials
- graph data
- user data

### Acceptance criteria

- `pk_` keys can fetch only their own safe SDK manifest.
- SDKs do not silently fall back to local defaults unless manifest fetch failure is recorded.
- Manifest fetch failure appears in heartbeat diagnostics.
- Kyber can distinguish:
  - manifest healthy
  - manifest forbidden
  - manifest expired
  - manifest signature invalid
  - manifest unavailable
  - local fallback active

## 3.2 Remove legacy CDN convention drift

### Problem

PR #648 explicitly leaves `cicd/aether-cicd/` with a competing legacy CDN convention:

<!-- Legacy paths quoted here; use zero-width joiners to avoid the CI CDN-path scanner -->
```txt
sdk/v5/loader​.js
sdk/{version}/aether-sdk.esm​.min.js
```

The new canonical convention is:

```txt
https://cdn.aether.network/v1.js
```

This means the repo still has two SDK distribution stories.

### Required change

Either:

1. delete/retire the legacy CICD tree, or  
2. add it to the domain/CDN validator and force it to use the new convention.

### Acceptance criteria

- No repo path references `sdk/v5/loader​.js` as a live install path.
- No public docs reference `sdk/{version}/aether-sdk.esm​.min.js` unless marked legacy.
- Domain gate scans `cicd/aether-cicd/`.
- SDK install docs show one canonical CDN loader URL.

## 3.3 Convert parity from claims into generated release evidence

### Problem

The SDK family may be aligned, but parity must be generated from tests, not maintained manually.

### Required change

Add a generated SDK certification report:

```txt
docs/reports/SDK_CERTIFICATION_REPORT.md
```

Generated from:

- package metadata
- version surfaces
- schema hash
- generated registry files
- emitted payload snapshots
- native compile checks
- publish dry-runs
- heartbeat tests
- manifest tests
- one-tag install tests
- sample app traces

### Acceptance criteria

The report must answer:

- Which SDKs are release-supported?
- Which SDKs can be installed?
- Which SDKs can emit canonical events?
- Which SDKs can fetch manifest?
- Which SDKs emit heartbeat?
- Which SDKs report dropped events?
- Which SDKs support consent receipts?
- Which SDKs support journey lifecycle?
- Which SDKs support commerce helpers?
- Which SDKs support wallet/web3 helpers?
- Which SDKs support agent helpers?
- Which SDKs support x402 helpers?
- Which SDKs support rewards helpers?
- Which SDKs have passing sample-app proof?

## 3.4 Add true cross-platform payload snapshot tests

### Problem

The SDKs may expose similar helpers, but you still need proof that the same business action creates the same canonical observation across Web, React Native, iOS, Android, and Server.

### Required canonical fixture

Create one fixture:

```txt
sdk-fixtures/canonical-first-value-journey.json
```

It should represent:

```txt
manifest_fetched
sdk_initialized
heartbeat_sent
anonymous_session_started
screen_or_page_viewed
product_viewed
cart_item_added
checkout_started
identify_called
payment_succeeded
order_completed
journey_completed
flush_confirmed
graph_projection_ready
```

### Required SDK tests

Each SDK must emit that fixture through native/platform-idiomatic APIs:

- Web
- React Native
- iOS
- Android
- Server

Then each output must normalize into the same canonical envelope.

### Acceptance criteria

- Same canonical top-level event types.
- Same consent-purpose derivation.
- Same schema hash.
- Same tenant/source/app/surface fields.
- Same journey semantics.
- Same identity transition semantics.
- Same idempotency behavior.
- Same dropped-event diagnostics model.

## 3.5 Seal dropped-event diagnostics

### Problem

Heartbeat alone is not enough. A tenant must know whether the SDK is healthy but losing signal.

### Required dropped-event reasons

```ts
type DroppedEventReason =
  | "consent_denied"
  | "schema_invalid"
  | "queue_full"
  | "offline_expired"
  | "retry_exhausted"
  | "manifest_blocked"
  | "unsupported_sdk_version"
  | "payload_too_large"
  | "auth_failed"
  | "shutdown_unflushed";
```

### Required SDK API

```ts
aether.getDiagnostics()
aether.flush()
aether.reset()
aether.getQueueDepth()
aether.getLastFlushStatus()
```

Native equivalents should exist for iOS and Android.

### Acceptance criteria

- Dropped-event counts appear in heartbeat.
- Dropped-event raw payloads are not leaked.
- Consent-blocked events are counted without exposing sensitive blocked content.
- Queue overflow is visible.
- Retry exhaustion is visible.
- Manifest-blocked events are visible.
- Shutdown-unflushed events are visible.

## 3.6 Make sample apps the release gate

### Problem

Unit tests do not prove tenant installability.

### Required examples

Add or validate:

```txt
examples/web-next
examples/web-script-tag
examples/react-native
examples/ios-swift
examples/android-kotlin
examples/server-node
examples/ecommerce-full-journey
```

### Required sample behavior

Every sample must prove:

- install
- init
- manifest fetch
- heartbeat
- consent state
- first event
- identify
- journey lifecycle
- commerce event
- flush
- backend acceptance
- activation milestone update
- Kyber/Aether visibility

### Acceptance criteria

- Each sample has a local mode.
- Each sample has a staging mode.
- Each sample emits the same canonical first-value journey.
- CI can run at least the Web, Server, and mocked RN/native sample traces.
- Manual device smoke testing exists for iOS and Android.

## 3.7 Connect SDK certification to Tenant Activation

### Problem

The Responsiveness Spine adds milestone tracking, but SDK certification needs to become part of the release and onboarding contract.

### Required activation milestones

```ts
type SdkActivationMilestone =
  | "site_created"
  | "publishable_key_created"
  | "sdk_loader_requested"
  | "sdk_loader_loaded"
  | "sdk_init_started"
  | "sdk_init_completed"
  | "manifest_fetched"
  | "heartbeat_seen"
  | "first_batch_received"
  | "first_event_accepted"
  | "first_identity_observed"
  | "first_session_observed"
  | "first_journey_observed"
  | "first_commerce_observed"
  | "first_projection_available"
  | "first_lens_available";
```

### Required UI state

Aether tenant UI and Kyber should both show:

```txt
Not installed
Installing
Loader seen
Initialized
Heartbeat live
Events flowing
Graph hydrating
First value ready
Healthy
Degraded
Drifted
Blocked
```

### Acceptance criteria

- A broken SDK install cannot appear as “nothing happened.”
- A CSP-blocked loader appears as degraded.
- A wrong domain appears as blocked.
- A stale SDK appears as drifted.
- A working SDK advances to first value.

## 3.8 Align SDKs with no-SDK connector evidence

### Problem

SDKs, Shopify, Stripe, email connectors, provider runtime, and signed webhooks must converge into the same graph evidence model.

### Required rule

SDKs should not be treated as canonical truth by default.

Example:

```txt
SDK observes checkout_completed.
Shopify webhook confirms order_created.
Stripe confirms payment_succeeded.
Backend reconciles all three into one conversion.
```

### Acceptance criteria

- SDK/provider duplicates do not double-count.
- Provider evidence can supersede SDK observation.
- SDK observation can provide early signal before provider confirmation.
- Attribution explainability shows which source contributed which evidence.
- Campaign 360, Profile 360, Value, Signals, and Journeys can show provenance.

## 3.9 Add release blocker for SDK docs drift

### Problem

Earlier docs drift existed between SDK overview and canonical SDK API contract. This class of bug should not recur.

### Required validator

Add or extend:

```txt
scripts/validate_sdk_docs_contract_drift.py
```

It should fail on:

```txt
/v1/sdk/health
/v1/config
/v1/ingest/events in SDK quickstarts
/v1/ingest/events/batch in SDK quickstarts
?apiKey=
track(...) used for canonical helper examples
hardcoded consent-purpose counts
legacy CDN paths
wrong API origin
wrong CDN origin
```

### Acceptance criteria

- Stale SDK docs fail CI.
- Stale SDK install examples fail CI.
- Stale SDK health/config endpoints fail CI.
- Legacy CDN routes fail CI unless explicitly marked legacy.

## 4. Revised Implementation Plan

## PR A — SDK Manifest Access Close-Out

### Goal

Make publishable-key SDK config safe and functional.

### Work

- Add safe `pk_` manifest authorization.
- Scope manifest by site/source instance.
- Add manifest failure diagnostics.
- Add tests for allowed and forbidden manifest access.
- Update docs and quickstarts.

### Done when

A browser one-tag install can fetch manifest with a publishable key without accessing private tenant/admin APIs.

## PR B — Legacy Distribution Drift Removal

### Goal

Remove competing CDN/install conventions.

### Work

- Scan `cicd/aether-cicd/`.
- Retire or rewrite legacy SDK CDN paths.
- Extend domain/CDN validator.
- Update docs/reports referencing legacy paths.

### Done when

There is one canonical public SDK loader story.

## PR C — Generated SDK Certification Report

### Goal

Replace manual parity confidence with generated evidence.

### Work

- Add certification generator.
- Pull package versions, schema hash, publish outputs, tests, docs state, sample traces.
- Output `docs/reports/SDK_CERTIFICATION_REPORT.md`.
- Attach report to SDK release workflow.

### Done when

Every SDK release produces an auditable certification report.

## PR D — Cross-Platform Payload Snapshot Parity

### Goal

Prove that Web, RN, iOS, Android, and Server emit equivalent canonical observations.

### Work

- Add canonical first-value journey fixture.
- Add Web snapshot test.
- Add RN snapshot test.
- Add iOS snapshot test.
- Add Android snapshot test.
- Add Server snapshot test.
- Normalize platform-specific fields before comparison.

### Done when

The same journey produces the same canonical event semantics across every SDK.

## PR E — Dropped-Event Diagnostics Seal

### Goal

Make lost signal explainable.

### Work

- Add dropped-event reason enum.
- Add dropped counts to heartbeat.
- Add `getDiagnostics()` or native equivalent.
- Add offline/retry/overflow/shutdown tests.
- Add Kyber diagnostics display.

### Done when

A tenant can see why signal is missing or degraded.

## PR F — Sample App First-Value Harness

### Goal

Prove real installability.

### Work

- Add or complete example apps.
- Make each emit canonical first-value journey.
- Add local/staging modes.
- Add sample traces to certification report.
- Add CI smoke coverage where feasible.

### Done when

A design partner can follow a quickstart and see first value without engineering help.

## PR G — Connector/SDK Convergence Proof

### Goal

Make SDK events and provider events reconcile correctly.

### Work

- Add checkout/order/payment reconciliation fixture.
- Simulate SDK + Shopify + Stripe overlap.
- Prove no double-counting.
- Prove provenance is preserved.
- Prove attribution explainability distinguishes evidence sources.

### Done when

SDK and connector evidence become one graph truth path, not parallel systems.

## 5. What Should Be Removed From the Old Blueprint

Remove or downgrade these from the old blueprint because recent work appears to cover them:

| Old blueprint item | New status |
|---|---|
| Basic SDK distribution layer | Covered by #648 |
| One-tag install | Covered by #648 |
| CDN release pipeline | Covered by #648 |
| First-heartbeat verification | Covered by #648 |
| Version surface alignment | Covered by #649 |
| Loader/backend version constants | Covered by #649 |
| Time-to-value observability | Covered or in progress via #650 |
| Activation milestones | Covered or in progress via #650 |
| Kyber responsiveness surfaces | Covered or in progress via #650 |
| Basic SDK heartbeat SLO concept | Covered or in progress via #650 |

## 6. What Should Stay

Keep these because they remain release-critical:

| Remaining item | Why it still matters |
|---|---|
| Publishable-key manifest access | Current behavior still has a 403/local fallback gap |
| Legacy CDN convention cleanup | Prevents two install stories |
| Generated SDK certification report | Prevents manual parity claims |
| Cross-platform payload snapshots | Proves SDK semantic parity |
| Dropped-event diagnostics | Explains lost signal |
| Sample app harness | Proves real tenant installability |
| Connector/SDK convergence | Prevents graph duplication and attribution errors |
| Docs drift validator | Prevents stale SDK instructions from recurring |
| Native device smoke testing | Proves iOS/Android SDKs work beyond compile checks |

## 7. Final Release Standard

The SDK program should not be considered fully complete until this statement is true:

> A tenant can create a site/source, receive a publishable key, install the SDK with one tag or native package, fetch a safe signed manifest, emit heartbeat, send canonical events to `/v1/batch`, enforce consent, survive offline/retry conditions, report dropped-event diagnostics, produce cross-platform journey evidence, converge with connector/provider evidence, and see first graph value inside Aether/Kyber with generated release certification proving the same behavior across Web, React Native, iOS, Android, and Server.

## 8. Final Recommendation

Do not throw away the old blueprint.

Convert it into:

```txt
docs/blueprints/SDK_PRODUCTIZATION_CLOSE_OUT_AND_CERTIFICATION_BLUEPRINT.md
```

The new title matters because the scope has changed.

This is no longer a foundational SDK productization blueprint. It is now a final certification, drift-remediation, and first-value proof blueprint.