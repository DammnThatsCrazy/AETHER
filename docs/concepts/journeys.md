---
title: Journeys
slug: concepts/journeys
section: concepts
visibility: P
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Journeys

A journey is a named, stateful path a user takes through your product —
onboarding, checkout, a claims flow, an agent-assisted task. Where a
[signal](signals.md) is a single event, a journey groups a sequence of them
under one lifecycle so you can ask "how far did users get, and where did
they drop off" instead of reconstructing that from raw events yourself.

## Lifecycle

The Web SDK exposes the full lifecycle directly:

```typescript
aether.startJourney('checkout', { journeyId: 'ord_draft_492' });

aether.checkpointJourney('shipping_address_entered');
aether.checkpointJourney('payment_method_selected');

aether.completeJourney('order_placed');
// or, if the user gives up:
aether.abandonJourney('cart_expired');
```

Every journey event (`journey_started`, `journey_checkpoint`,
`journey_paused`, `journey_resumed`, `journey_continued`,
`journey_completed`, `journey_abandoned`) carries the same identity fields —
`journeyId`, `journeyName`, `journeyType`, `journeyStatus` — so the backend
can reconstruct the full path without you re-sending journey metadata on
every checkpoint.

## Automatic pause and resume

The SDK doesn't require you to manage tab visibility yourself. When the page
is hidden, an in-flight journey is automatically paused
(`pauseJourney('page_hidden')`); when it becomes visible again, it resumes —
or, past a configurable inactivity timeout (`journeyTimeoutMs`, default 30
minutes), it's abandoned instead of silently continuing as if nothing
happened.

In a single-page app, SPA route changes are automatically checkpointed too —
each route the user lands on while a journey is active becomes a step,
without extra instrumentation.

## Cross-device continuity

Because journey identity travels alongside identity resolution, a journey
that starts on one device can resume on another. When
[identity resolution](profiles.md#identity-resolution) recognizes a returning
visitor, the SDK calls `resumeJourney('identity_resolved', …)` with the
handoff latency and confidence signals attached — so a journey that started
on mobile and finished on desktop shows up as one continuous journey, not
two unrelated fragments.

## Reading journeys back

`GET /v1/profile/{user_id}/journeys` and `/unified-journey` on the
[Profiles API](../api/profiles.md) return a profile's journey history;
`journey` is also available as an overlay [lens](lenses.md) for viewing any
graph subject through its journey structure.

## Next steps

- [Signals](signals.md) — the events a journey groups together.
- [Lenses](lenses.md) — the `journey` overlay lens and how lenses compose.
