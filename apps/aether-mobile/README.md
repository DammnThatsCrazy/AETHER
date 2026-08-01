# Aether Mobile

The Aether **intelligence companion** app (Expo + React Native). It consumes
[`@aether/mobile-core`](../../packages/mobile-core) and is bound to the `aether`
product plane — a distinct bundle id (`com.aether.mobile`), auth audience, and secure
store from Kyber Mobile. **No Kyber code ships in this binary.**

## Honest build status (C4)

This session lands the **compiling app shell**: the SDK is wired (`src/client.ts`),
PKCE + Keychain/Keystore auth is bound, and a navigation skeleton renders. The full
feature surfaces (Today / Copilot / Explore / Pulse / exceptions) and governed mobile
actions are **C5–C7, not this session**.

The native iOS-simulator / Android-emulator compile (`expo prebuild` → `xcodebuild` /
`gradlew`) requires **macOS + Xcode + the Android SDK + the Expo toolchain**, which are
**not present in this Linux CI container** — the native build is `externally_blocked`
here and runs in the hosted (macOS) CI. See
`reports/mobile-productization/external-blockers.json`. TypeScript type-checking of the
shared SDK (`@aether/mobile-core`) is verified in `make ci-check`.

## Run (in a macOS / Expo environment)

```bash
npm install            # from repo root, with the app added to a native-capable install
npx expo prebuild      # generate the ios/ + android/ native projects
npx expo run:ios       # iOS simulator
npx expo run:android   # Android emulator
```

Runtime configuration (`EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_ENVIRONMENT`) is
injected at build time — never committed.
