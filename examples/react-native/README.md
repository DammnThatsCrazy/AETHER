# React Native Example

Adapted from `apps/proof-react-native/` — demonstrates the Aether React Native SDK in an Expo app that exercises the full first-value journey: install → init → heartbeat → consent → event → identify → journey → commerce → flush.

## Structure

This example is a minimal Expo/React Native app that mirrors the proof harness in `apps/proof-react-native/`. It uses `@aether/react-native` and walks through every signal in the canonical first-value lifecycle.

## First-value journey (React Native path)

| Step | What happens | Proof |
|------|-------------|-------|
| Install | `@aether/react-native` package linked in Expo app | Native SDK available on device |
| Init | `AetherRN` initialized with tenant/workspace/config | Session + anonymousId minted, native SDK ready |
| Heartbeat | `sdk.heartbeat()` | Heartbeat event delivered to POST /v1/batch |
| Consent | `sdk.setConsent({ purposes: { analytics: true } })` | Consent granted — events will deliver |
| Event | `sdk.track('page_view', { url: '/' })` | Custom event delivered |
| Identify | `sdk.identify('user_123', { email: 'test@example.com' })` | Identity attached to session |
| Alias | `sdk.alias('old_anon', 'user_123')` | Anonymous → known identity aliasing |
| Journey | Journey lifecycle via SDK journey methods | Journey started, checkpoint, completed |
| Commerce | Commerce event (revenue-bearing) | Revenue event delivered, visible in Kyber |
| Flush | `sdk.flush()` | Queue flushed — backend acceptance proven |
| Reset | `sdk.reset()` | Session cleared, fresh first-value journey possible |
| Backend acceptance | POST /v1/batch returns 200 with counters | Events visible in Aether dashboard & Kyber |
| Activation milestone | First valid event accepted → device activated | Check activation in SDK state |
| Kyber/Aether visibility | Events appear in economic graph & Aether analytics | Verify in Kyber observability |

## Getting started

1. Install dependencies:
   ```
   cd examples/react-native
   npm install
   ```
2. Start the Expo dev server:
   ```
   npx expo start
   ```
3. Run on a device or simulator. The app exposes a debug UI that lets you tap through each step of the first-value journey and see the SDK state + event log update live.

## Environment

Create two env files (or copy the `.example` templates):

- **`.env.local`** — local development keys and endpoint.
- **`.env.staging`** — staging keys and endpoint.

- **`.env.local`** — local development keys and endpoint (see `.env.local.example`).
- **`.env.staging`** — staging keys and endpoint (see `.env.staging.example`).

## Related

- `apps/proof-react-native/` — the full proof harness this example is adapted from.
- `apps/proof-ios/` and `apps/proof-android/` — native surfaces that share the same `@aether/react-native` bridge.
- `scripts/smoke/ios-sdk.ts` and `scripts/smoke/android-sdk.ts` — automated smoke tests for the mobile SDKs.
