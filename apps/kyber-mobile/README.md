# Kyber Mobile

The Kyber **operator companion** app (Expo + React Native). It consumes
[`@aether/mobile-core`](../../packages/mobile-core) and is bound to the `kyber`
product plane with the **workforce auth audience** — a distinct bundle id
(`com.aether.kyber`), audience, and secure store from Aether Mobile. **No Aether
tenant code ships in this binary**, and an Aether token cannot call Kyber.

## Honest build status (M4a)

This session lands the **read-only operator-companion screens** (M4a) on top of the
compiling app shell: seven typed-navigator tabs — Pulse / Exceptions / Incidents /
Runs / Reviews / Briefings / Account — backed by a GET-only typed client
(`src/kyberOps.ts`) over the EXISTING agent + Kyber operator-plane routes. Identity,
continuity, and sync remain wired via the SDK (`src/client.ts`).

**Read-only by construction**: M4a issues GETs only and renders bounded, redacted
display fields (severity / kind / title / status / ids / timestamps / counts). The
governed Tier-0–3 actions (challenge / step-up / device-sign, plus approve /
suspend / revoke / acknowledge / resolve / suppress) are **M5/M6, not this
session**.

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
