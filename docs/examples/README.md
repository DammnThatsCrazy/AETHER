# Examples — SDK Sample App First-Value Harness

This directory contains seven sample apps that demonstrate the Aether SDK first-value journey across web, mobile, and server platforms. Each example exercises the canonical lifecycle: install → init → manifest fetch → heartbeat → consent → first event → identify → journey lifecycle → commerce event → flush → backend acceptance → activation milestone → Kyber/Aether visibility.

## Sample Apps

| Example | Platform | SDK | Description |
|---------|----------|-----|-------------|
| `web-next/` | Web (Vite+React) | `@aether/web` | Full first-value journey in a modern React app, adapted from `apps/proof-web/`. |
| `web-script-tag/` | Web (plain HTML) | `@aether/web` (CDN) | Standalone HTML with the one-tag snippet — no bundler, no framework. |
| `react-native/` | React Native (Expo) | `@aether/react-native` | Adapted from `apps/proof-react-native/`. |
| `ios-swift/` | iOS (Swift reference) | Native iOS SDK (via `@aether/react-native`) | Swift wrapper README pointing to `apps/proof-ios/` for native SDK usage. |
| `android-kotlin/` | Android (Kotlin reference) | Native Android SDK (via `@aether/react-native`) | Kotlin wrapper README pointing to `apps/proof-android/` for native SDK usage. |
| `server-node/` | Node.js server | `@aether/server` | Server-side first-value journey using the Aether Server SDK. |
| `ecommerce-full-journey/` | Web (Vite+React) | `@aether/web` | Complete ecommerce flow: product_viewed → cart → checkout → payment → order_completed → conversion → flush. |

Each example includes `.env.local` and `.env.staging` environment files for local and staging modes.

## First-Value Journey (canonical steps)

Every example proves the following sequence:

1. **Install** — The SDK package is linked in the project (or loaded via CDN for the script-tag example).
2. **Init** — `initSDK()` / `Aether.initialize()` connects to the Aether ingestion endpoint with a valid API key.
3. **Manifest fetch** — The SDK fetches the manifest (capabilities/features) from the backend.
4. **Heartbeat** — `emitHeartbeat()` proves the SDK is live and the backend is reachable (`accepted=1`).
5. **Consent** — `consent.grant([...])` grants the required purposes so events can be delivered.
6. **First event** — A custom event or page view is tracked (`trackEvent` / `pageView`).
7. **Identify** — `identifyUser('user_123', …)` attaches a known identity to the anonymous session.
8. **Journey lifecycle** — `journey.start()`, `journey.checkpoint()`, `journey.completed()` (or abandoned) prove the journey lifecycle.
9. **Commerce event** — `commerce.track()` or `conversion()` fires a revenue-bearing event visible in Kyber.
10. **Flush** — `flush()` drains the queue and proves backend acceptance (the batch response shows `accepted=N`).
11. **Backend acceptance** — POST /v1/batch returns 200 with counters; events are visible in the Aether dashboard and Kyber observability.
12. **Activation milestone** — The first valid event accepted activates the device/session in the Aether system.
13. **Kyber/Aether visibility** — Commerce + heartbeat events appear in the economic graph and Aether analytics.

## Local and Staging Modes

Create two env files (or copy the `.example` templates):

- **`.env.local`** — local development: uses `http://localhost:8000` as the ingestion endpoint and a placeholder API key (see `.env.local.example`).
- **`.env.staging`** — staging: uses the staging ingestion endpoint with a placeholder staging key (see `.env.staging.example`).

Switch between modes by using the appropriate env file (or by setting the corresponding environment variables in your shell/CI).

## CI Smoke Jobs

The `functionality-proof.yml` workflow includes two smoke jobs that run the first-value journey against the local ingestion endpoint:

- **`smoke-web`** — runs after the SDK tests pass (`needs: sdk`). Installs `examples/web-next`, runs its vitest smoke suite, then runs `scripts/smoke/web-sdk.ts` against `examples/web-script-tag`.
- **`smoke-server`** — runs after the SDK tests pass (`needs: sdk`). Type-checks `examples/server-node`, runs `scripts/smoke/staging.ts`, then executes `src/index.ts` to exercise the server-side first-value journey.

Both smoke jobs block merge on failure.

## Manual Device Smoke Testing (iOS / Android)

For the mobile examples (`ios-swift/`, `android-kotlin/`, `react-native/`), automated smoke tests run via `scripts/smoke/ios-sdk.ts` and `scripts/smoke/android-sdk.ts`. For manual verification on physical devices, follow the procedure below.

### iOS Manual Smoke Test

**Prerequisites:**

- A physical iOS device or iOS Simulator.
- Xcode installed.
- The `apps/proof-ios/` Expo project built and runnable.

**Procedure:**

1. Open `apps/proof-ios/` in Xcode or start the Expo dev server:
   ```
   cd apps/proof-ios
   npx expo start
   ```
2. Run the app on a physical iOS device or simulator.
3. Tap through the first-value journey tabs in order:
   - **Initialization** → tap "Initialize SDK" → verify `initialized: true`, sessionId and anonymousId are minted.
   - **Heartbeat** → tap "Emit Heartbeat" → verify `lastDeliveryStatus: delivered` and `accepted=1` in the API response.
   - **Screen Tracking** → tap "Track Screen" → verify a `screen.view` event is delivered.
   - **Identify User** → tap "Identify User" → verify `knownUserId: user-123` and the identity event is delivered.
   - **Conversion** → tap "Simulate Conversion" → verify a `conversion.completed` event with revenue is delivered.
   - **Consent State** → tap "Grant Consent" → verify `consentState: granted`.
   - **Offline/Retry** → tap "Simulate Offline" then "Flush Queue" → verify the queue drains and events are delivered.
   - **Debug Console** → verify the event log shows all delivered events with `status: delivered`.
4. Verify the final flush shows `accepted=N` from the backend.
5. Confirm events appear in the Aether dashboard and Kyber observability.

### Android Manual Smoke Test

**Prerequisites:**

- A physical Android device or Android Emulator.
- Android Studio or Expo CLI.
- The `apps/proof-android/` Expo project built and runnable.

**Procedure:**

1. Open `apps/proof-android/` in Android Studio or start the Expo dev server:
   ```
   cd apps/proof-android
   npx expo start
   ```
2. Run the app on a physical Android device or emulator.
3. Tap through the first-value journey tabs in order (same steps as iOS above):
   - **Initialization** → "Initialize SDK" → `initialized: true`, sessionId + anonymousId minted.
   - **Heartbeat** → "Emit Heartbeat" → `delivered`, `accepted=1`.
   - **Screen Tracking** → "Track Screen" → `screen.view` delivered.
   - **Identify User** → "Identify User" → `knownUserId: user-123`.
   - **Conversion** → "Simulate Conversion" → `conversion.completed` with revenue.
   - **Consent State** → "Grant Consent" → `consentState: granted`.
   - **Offline/Retry** → "Simulate Offline" then "Flush Queue" → queue drains, events delivered.
   - **Debug Console** → event log shows all delivered events.
4. Verify the final flush shows `accepted=N` from the backend.
5. Confirm events appear in the Aether dashboard and Kyber observability.

### What to check

For both platforms, confirm:

- **Install**: The SDK is linked (no runtime errors on init).
- **Init**: `initialized: true`, sessionId and anonymousId are non-empty.
- **Heartbeat**: `lastDeliveryStatus: delivered`, `accepted=1`.
- **Consent**: `consentState: granted` after granting.
- **First event**: A custom event or screen view is delivered.
- **Identify**: `knownUserId` is set after identify.
- **Journey**: Journey lifecycle events are delivered (if the SDK surfaces journey methods).
- **Commerce**: A revenue-bearing event is delivered (`conversion.completed` or `order_completed`).
- **Flush**: Queue is drained, `lastDeliveryStatus: delivered`, `accepted=N`.
- **Backend acceptance**: Events appear in the Aether dashboard.
- **Kyber/Aether visibility**: Commerce and heartbeat events are visible in Kyber observability.
- **Activation milestone**: The device/session is activated after the first valid event.

## Related

- `apps/proof-web/` — the original web proof harness.
- `apps/proof-react-native/` — the original React Native proof harness.
- `apps/proof-ios/` — the original iOS proof harness.
- `apps/proof-android/` — the original Android proof harness.
- `scripts/smoke/web-sdk.ts`, `scripts/smoke/ios-sdk.ts`, `scripts/smoke/android-sdk.ts`, `scripts/smoke/staging.ts` — automated smoke tests.
- `docs/sdks/` — SDK documentation.
