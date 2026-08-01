---
title: "Demo & Value-Proof Guide"
slug: acquisition/demo-and-value-proof-guide
section: operations
visibility: I
audience: [exec, buyer]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 9
toc_depth: 2
---

# Demo & Value-Proof Guide

How to show AETHER's value honestly — a script for a buyer-facing walkthrough
that demonstrates the real intelligence loop without staging a single claim the
codebase would not back up. The governing principle: **every screen shown is
either deterministically seeded (and labeled as such) or genuinely live-empty.**
Nothing is faked.

Companion docs: `docs/acquisition/PRODUCTIZATION_DOSSIER.md` (what it is),
`docs/acquisition/ARCHITECTURE_AND_OPERATIONS_OVERVIEW.md` (how it works).

---

## 1. Two honest demo modes

- **Seeded mode (demo-seed, #494):** a deterministic dataset populates the
  surfaces so a buyer sees the full loop — profiles, graph, intelligence scores,
  operator exceptions — with reproducible content. Always introduced as *seeded
  demonstration data*, never as production activity.
- **Live-empty mode:** a fresh tenant shows genuinely empty surfaces. This is a
  feature, not a failure — it proves the platform does not fabricate data to look
  populated. Use it to demonstrate the **activation path** filling those surfaces
  in real time.

Switching between the two, and saying which is which out loud, is the most
persuasive thing in the demo: it shows the product tells the truth about its own
state.

---

## 2. The value-proof walkthrough

A 20-minute arc that follows the intelligence loop end to end.

1. **Activation (live-empty → first value).** With `AETHER_ACTIVATION_ENABLED`,
   walk the self-serve FSM: select a plan tier, choose SDK platforms, mint an API
   key (shown once), send a **test event through the real ingestion path**, and
   watch **Bronze first value** register. Point out that `complete` is *refused*
   until `first_value_ready` — the product will not claim activation it cannot
   prove.
2. **Ingest → identity.** Send a small event batch; show identity resolution
   picking the right anchor with a confidence score, and a low-confidence case
   landing in the review queue rather than auto-merging.
3. **Profile 360.** Open a composed profile: identity + analytics + consent +
   graph + Gold intelligence. Then attempt a **credit** read without consent and
   show the hard **403** — the consent gate is real, not a soft empty envelope.
4. **Graph + intelligence.** Traverse the relationship graph (H2H/H2A/A2H/A2A);
   show trust / risk / health / attribution scores computed from real quality
   metrics, not placeholders.
5. **Kyber operator loop.** Show the exception queue, an incident rollup, and a
   **governed command** — highlighting that it authorizes twice and writes a
   decision row, and that an agent can never mutate the graph directly (every
   mutation is staged and human-approved).
6. **Close the loop.** Trigger a notification/action as the outbound edge; note
   that reward delivery (where enabled) runs on a durable outbox with a
   "never delivered without a receipt" invariant.

---

## 3. What NOT to demo as production

Say these plainly if asked — the honesty is the sales asset:

- **No live economic provider.** All 18 first-release providers are
  `CREDENTIAL_WAITING`. Economic domains (stablecoin, derivatives, interop,
  payment rails, card-linked) can be *shown as wired and tested* but **not** as
  carrying live data. Demo them in seeded/flag-off form only.
- **No mainnet / real funds.** On-chain reward proofs stay gated pending external
  audit. Do not demonstrate a real-funds settlement — the platform is
  observation-only and no-custody by construction and never will.
- **Tracing is a seam.** If asked about observability, show the correlation-id /
  traceparent propagation but state that full OpenTelemetry coverage is not yet
  integrated.
- **Kyber Missions is scaffolding.** If it comes up, describe the migration +
  flag-gated monitoring-loop scaffold honestly; do not demo a mission aggregate
  that is not yet in the tree.

---

## 4. Proof a technical buyer can run themselves

Hand the diligence team the repo and four commands:

- `make production-status` — the 30-area readiness scorecard (~3.77/5) with
  evidence paths.
- `make ci-check` — the registry test suite (skip = FAIL) + `npm run test` + ~40
  validators.
- `make staging-preflight` — the fail-closed staging gate.
- `pytest tests/chaos/` — the credentialless load/chaos/recovery suite.

The demo tells a story; these commands let the buyer verify it without taking
anyone's word.

---

## 5. Framing the close

The honest pitch: **this is a real, tested, well-gated pre-production platform,
and the demo you just saw is reproducible from the repo.** The remaining work is
provisioning, live credentials, external audit, and scale validation — visible,
tracked, and un-inflated. A buyer is acquiring a system whose own tooling refuses
to overstate it, which is exactly what makes diligence cheap and trust durable.

See also: `docs/acquisition/PRODUCTIZATION_DOSSIER.md`,
`docs/acquisition/RISK_AND_READINESS_REGISTER.md`,
`docs/productization/staging-capstone/PILOT_EVIDENCE_GUIDE.md`.
