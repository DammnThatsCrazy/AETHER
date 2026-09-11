---
title: "SDK Heartbeat"
slug: sdks/heartbeat
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# SDK Heartbeat

Every Aether SDK emits periodic heartbeat events to confirm liveness and session continuity.

## Purpose

- Confirm SDK initialization
- Track session duration
- Detect silent failures
- Provide ingestion pipeline health signal

## Behavior

- First heartbeat emitted on SDK initialization
- Subsequent heartbeats at configurable intervals
- Heartbeat includes session state, SDK version, and contract version
