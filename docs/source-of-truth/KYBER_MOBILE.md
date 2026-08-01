---
title: Kyber Mobile — App Architecture
slug: mobile/kyber-app
section: mobile
visibility: I
audience: [architect, mobile, security]
status: alpha
---

# Kyber Mobile — App Architecture

Kyber Mobile (`apps/kyber-mobile`) is the **operator companion** for the Kyber
workforce. Like Aether Mobile it is an attention + safe-action surface, not a full
operations console — the Kyber desktop remains the complete workspace.

## What C4 lands (and what it does not)

C4 lands the **compiling app shell** bound to the operator plane: identity, continuity,
and sync are wired via the shared SDK, and a navigation skeleton renders. The full
operator surfaces (Pulse / Exceptions / Incidents / Runs / Reviews) and the governed
Tier-0–3 actions (challenge / step-up / device-sign over the Kyber command plane
`services/kyber/ops/*`) are **C5–C7, not this session**.

The native compile is `externally_blocked` in the Linux CI container (needs macOS +
Xcode + Android SDK + Expo); it runs in the hosted (macOS) CI. See
`reports/mobile-productization/external-blockers.json`.

## Identity & isolation invariants

- **Distinct binary.** Bundle id `com.aether.kyber`, scheme `kyber`, **workforce** auth
  audience, and a separate secure-store namespace. **No Aether tenant code ships in
  this binary**; tenant identity and workforce identity stay separate.
- **Governed actions reuse the command plane.** Mobile never introduces a new mutation
  channel: any operator action adapts the existing Kyber command plane
  (request → dry-run → approve → execute → **verify**). HTTP 200 is never "command
  verified". Governed mobile actions are deferred to C5–C7.
- **Step-up is device-proof.** A `restricted` continuation requires a stepped-up
  session; the operator-plane step-up (Kyber device proof) is deferred, and until it
  lands, restricted continuations resolve to `requires_step_up` rather than data.

## Composition

Identical SDK wiring to Aether Mobile (`@aether/mobile-core`, PKCE + secure store),
differing only in plane binding (`extra.appKind = kyber`), audience, bundle id, and
keystore namespace — enforced by `make mobile-build-check`.
