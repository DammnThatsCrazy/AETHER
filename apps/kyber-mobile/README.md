# Kyber Mobile

The Kyber **operator companion** app (Expo + React Native). It consumes
[`@aether/mobile-core`](../../packages/mobile-core) and is bound to the `kyber`
product plane with the **workforce auth audience** — a distinct bundle id
(`com.aether.kyber`), audience, and secure store from Aether Mobile. **No Aether
tenant code ships in this binary**, and an Aether token cannot call Kyber.

## Honest build status (C4)

This session lands the **compiling app shell** bound to the operator plane: identity,
continuity, and sync are wired via the SDK; a navigation skeleton renders. The full
operator surfaces (Pulse / Exceptions / Incidents / Runs / Reviews) and the governed
Tier-0–3 actions (challenge / step-up / device-sign over the Kyber command plane) are
**C5–C7, not this session**.

The native iOS-simulator / Android-emulator compile requires **macOS + Xcode + the
Android SDK + the Expo toolchain**, which are **not present in this Linux CI
container** — the native build is `externally_blocked` here and runs in the hosted
(macOS) CI. See `reports/mobile-productization/external-blockers.json`.

## Run (in a macOS / Expo environment)

```bash
npx expo prebuild
npx expo run:ios
npx expo run:android
```
