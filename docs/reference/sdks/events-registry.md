---
title: SDK Events Registry
slug: events-registry
section: reference
visibility: P
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---

# SDK Events Registry

## Overview

The events registry is the canonical source of truth for all event
types that Aether SDKs can emit. Event types are defined in
`packages/shared/contracts/event-registry.json` and generated into
TypeScript and Python artifacts.

## Event Type Categories

| Category | Examples |
|---|---|
| Core | `page_view`, `screen_view`, `session_start`, `session_end` |
| Identity | `identify`, `alias`, `group` |
| Commerce | `payment_initiated`, `payment_completed`, `payment_failed` |
| Journey | `journey_started`, `journey_completed`, `journey_abandoned` |
| Agent | `agent_registered`, `agent_task_created`, `agent_escalated` |
| Error | `error` |
| Performance | `performance` |

## Parity

Event type parity between TypeScript and Python is enforced by the
CI contract suite (EventType parity check). Mobile event parity is
validated separately.

## Adding New Event Types

1. Add the event type to `packages/shared/contracts/event-registry.json`.
2. Run `python scripts/generate_contracts.py` to regenerate artifacts.
3. Update the consent purpose mapping if the new type requires it.
4. Run `make ci-check` to validate parity.
