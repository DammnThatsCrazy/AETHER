---
title: Profiles
slug: concepts/profiles
section: concepts
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Profiles

A **profile** is Aether's resolved view of one entity — typically a person,
but the same machinery composes profiles for agents, campaigns, and other
graph subjects. Profile 360 is what you get when every signal, identifier,
and graph relationship for that entity is composed into one queryable
object.

## Identity resolution

A visitor usually starts anonymous. As the SDK and backend learn more about
them — a `userId` from `hydrateIdentity()`, a connected wallet, an email
hash — those signals are stitched into the same underlying identity rather
than staying as disconnected anonymous sessions.

Resolution happens both client- and server-side:

- The Web SDK calls `POST /sdk/identity/resolve` with whatever it currently
  knows (device fingerprint, wallet addresses, a hashed email) and, when the
  backend recognizes a prior identity, resumes any in-flight journey under
  the resolved identity.
- Every acceptance stamps confidence signals rather than asserting a match
  as certain — a resolved identity carries `confidence` and
  `confidence_signals` so downstream consumers can see *how* two sessions
  were linked, not just that they were.

Identity resolution never runs ahead of consent: device fingerprinting is
gated on the `personalization` purpose, and it is never generated while the
browser's Do Not Track signal is honored.

## Profile 360

`GET /v1/profile/{user_id}` composes the full picture in one call, with each
section independently toggleable:

- **Timeline** — the entity's event history.
- **Graph** — relationship edges (shared devices, wallets, households,
  referral chains).
- **Intelligence** — risk scores, ML features, model outputs.
- **Lake** — aggregated Gold-tier analytical data (lifetime value, cohort
  membership, …).

Narrower endpoints expose single facets — `/timeline`, `/graph`,
`/identifiers`, `/wallets`, `/journeys`, `/rewards`, `/behavior`, and more —
for callers that only need one slice. See [Profiles API](../api/profiles.md).

## Behavioral graphs

Beyond flat attributes, a profile sits inside a graph: edges connect it to
other entities (co-purchasers, shared payment instruments, referral sources,
wallet clusters) and to the campaigns, journeys, and lenses used to view it.
Every fact in the graph carries provenance — which source, which signal,
observed when — so a profile is always explainable back to the raw events
that produced it, never an opaque score.

## Next steps

- [Journeys](journeys.md) — the step-by-step paths a profile takes through
  your product.
- [Lenses](lenses.md) — composable views over a profile (or any graph
  subject).
- [Profiles API](../api/profiles.md) — the full endpoint reference.
