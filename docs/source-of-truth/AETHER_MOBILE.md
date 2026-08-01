---
title: Aether Mobile — App Architecture
slug: mobile/aether-app
section: mobile
visibility: I
audience: [architect, mobile, security]
status: alpha
---

# Aether Mobile — App Architecture

Aether Mobile (`apps/aether-mobile`) is the **intelligence companion** — not a graph
on a phone. It tells the user what changed, why it matters, shows the evidence, lets
them ask a bounded question or take a safe approved action, and hands the work back to
the desktop without losing context. The desktop remains the complete workspace.

## What C4 lands (and what it does not)

C4 lands the **compiling app shell**: the shared SDK (`@aether/mobile-core`) is wired,
PKCE + Keychain-backed auth is bound, and a navigation skeleton renders. The full
feature surfaces (Today / Copilot / Explore / Profile360 / Campaign360 / Alerts /
Account) and governed mobile actions are **C5–C7, not this session**.

The native iOS-simulator / Android-emulator compile requires macOS + Xcode + the
Android SDK + the Expo toolchain, which are **not present in the Linux CI container**;
the native build is `externally_blocked` here and runs in the hosted (macOS) CI. See
`reports/mobile-productization/external-blockers.json`. The shared SDK typechecks and
tests in `make ci-check`; scaffold invariants are enforced by `make mobile-build-check`.

## Composition

| Layer | Source | Notes |
|---|---|---|
| Shared SDK | `@aether/mobile-core` | Typed API/auth/continuity/sync clients; platform-agnostic |
| Transport | device `fetch` (injected) | The SDK never bundles an HTTP library |
| Auth | PKCE (S256) + `expo-secure-store` | Token lives only in the Keychain/Keystore; never logged |
| Config | `app.json` `extra.appKind = aether` | Bound to the `aether` product plane |

## Identity & isolation invariants

- **Distinct binary.** Bundle id `com.aether.mobile`, scheme `aether`, audience the
  tenant plane. **No Kyber code ships in this binary.** An Aether token cannot call
  Kyber (a separate app with a separate audience) — enforced structurally by
  `make mobile-build-check` (distinct bundle ids + product planes).
- **Claim ≠ authorization.** A push, deep link, or continuation id is never authority;
  every action re-authorizes server-side.
- **Deep links carry only opaque ids.** Resolution (`POST /v1/mobile/deep-links/resolve`)
  is fail-closed and reuses server-side continuation records — the link never carries
  PII or a graph.

## Build (macOS / Expo environment)

```bash
npx expo prebuild        # generate ios/ + android/
npx expo run:ios         # iOS simulator
npx expo run:android     # Android emulator
```
