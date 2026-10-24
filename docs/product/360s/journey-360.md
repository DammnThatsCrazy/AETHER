---
title: "Journey 360"
slug: product/360s/journey-360
section: concepts
visibility: P
audience: [buyer, dev-senior]
status: stable
since_version: "0.1.0"
---

# Journey 360

Journey 360 composes journey state, episode evidence, communications, linked
identity context, temporal context, and measured outcome evidence through the
tenant-scoped projection plane. It is a read model over canonical authorities;
it does not own journey, identity, episode, communication, or outcome truth.

## Backend subject and provider paths

The frame contract supports `entity`, `journey`, and `episode` subjects. Its
slots bind to the Journey/Episode, Temporal, Communication, Outcome, and Profile
360 providers according to the generated [surface catalog](../../_generated/360-surface-catalog.md).
The shared `POST /v1/experience360/frames` route evaluates tenant and slot
policy before reading providers, then preserves section evidence and provider
lineage in each composed slot.

For `journey` and `episode` requests, Profile 360 can provide linked user
identity context only when the canonical relation is exact and tenant scoped:
the journey must have one current profile version, or the episode must store an
exact `user` subject. The frame keeps the requested journey or episode as its
subject and labels the user profile as a related entity. Current links do not
prove historical identity, so bounded or point-in-time requests return unknown
for this context until the relationship authority supports valid-time replay.

The required `communications` slot reads Communication 360 evidence and
interactions only from tenant-scoped canonical communication facts whose typed
`journey_id` or `journey_ids` contains the exact requested journey ID. A
message endpoint, free-text mention, or association with another journey does
not qualify. This closes the explicit fact-to-journey join, while message-spine
coverage, completeness, freshness evaluation, and historical replay remain
unestablished; the slot therefore stays partial.

The required `episodes` slot reads only tenant-scoped EpisodeRecords that
explicitly persist the exact `journey_id`. The projection includes linked
episode IDs and their record/source evidence. Legacy records without that
field are not joined by profile, subject, timestamp, or matching opaque IDs;
association completeness and store freshness remain unknown, so the slot stays
partial when explicit links are present and unknown when none are observed.

Provider evidence that is missing, ambiguous, stale, truncated, or unavailable
remains explicit. In particular, an execution or journey status is not
promoted into a measured business outcome.

## Status

The product contract is reconstructed and remains pending clause-by-clause
alignment to the original 360 SSOT. Provider coverage is still in progress; a
catalog binding alone does not establish a complete surface. See
`docs/architecture/target/360-system-blueprint.md` for the current state and
remaining gaps.
