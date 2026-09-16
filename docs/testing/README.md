---
title: Testing Index — Functionality Proof Spine
slug: testing/index
section: testing
visibility: I
audience: [dev-junior, dev-senior, qa, ops]
status: experimental
since_version: 0.1.0
---

# Testing Index — Functionality Proof Spine

## What is the Functionality Proof Spine?

The Aether Functionality Proof Spine (FPS) is a coordinated testing framework that validates the platform end-to-end across SDKs, connectors, the intelligence graph, and 360 surfaces. It runs against a dedicated proof tenant on staging and produces a structured report that gates release readiness.

The FPS is **not** a replacement for unit tests, contract tests, or CI lanes. It sits above those as an integration-level proof that the whole system works together for a real tenant workflow.

## Passes and Fails

Every FPS check produces one of these outcomes:

| Outcome | Meaning |
|---|---|
| `PASS` | The check ran, met its success criteria, and produced the expected evidence. |
| `FAIL` | The check ran but did not meet its success criteria. Includes a typed `reason` and a likely owning subsystem. |
| `BLOCKED` | The check could not run because a prerequisite was missing (e.g., missing credentials, tenant not reachable). |
| `NOT_APPLICABLE` | The check does not apply to the current run configuration (e.g., a connector smoke test when that connector is not configured). |

A **pass condition** is the explicit criterion a check must satisfy to report `PASS`. Each doc in this directory lists the pass condition for its scope. A check that produces output but does not meet its pass condition is a `FAIL`, not a `PASS_WITH_WARNINGS`.

## Product States

The FPS validates the platform across a defined set of observable product states. These states appear in the proof tenant, SDK health surfaces, connector status, and 360 dashboards. A test that exercises a state must verify both the state's presence and its expected behavior.

| State | Meaning | Where it appears |
|---|---|---|
| `not connected` | No connector or SDK session is established. | Connector status, SDK diagnostics |
| `connected` | A connector or SDK session is established and reachable. | Connector status, SDK health |
| `syncing` | A connector is actively pulling or receiving data. | Connector status, sync job logs |
| `healthy` | The subsystem is operating normally with no active issues. | Tenant health, SDK health, connector status |
| `delayed` | Data ingestion or sync is lagging behind the expected pace. | Tenant health, connector freshness |
| `failed` | A subsystem has encountered a terminal error. | Connector status, SDK health, tenant health |
| `needs attention` | The subsystem is operational but has a non-fatal issue requiring review. | Tenant health, 360 surfaces |
| `no data yet` | The subsystem is connected but no data has arrived. | Profile 360, Campaign 360, connector graph |
| `missing data` | Expected data is absent (e.g., a field or event type not yet synced). | 360 surfaces, fixture verification |
| `empty result` | A query or projection returned zero rows legitimately. | Graph queries, 360 reports |
| `zero value` | A metric or aggregate is zero by computation, not absent. | Campaign 360, revenue metrics |
| `partially degraded` | A subsystem is functional but some capabilities are impaired. | Tenant health, connector status |

## Documentation Map

### Testing coordination
- [SDK Testing](./sdk-testing.md) — How to test the SDKs through proof apps, contract tests, parity tests, and smoke tests.
- [Connector Testing](./connector-testing.md) — How to test connectors through fixtures, sandbox, backfill, incremental sync, webhook replay, token refresh, and disconnect/reconnect.
- [Mobile Device Testing](./mobile-device-testing.md) — Real-device and simulator checklist for iOS and Android proof apps.
- [Staging Smoke Testing](./staging-smoke-testing.md) — The `pnpm smoke:staging` command, required environment variables, expected output, common failures, and remediation ownership.
- [E2E Testing](./e2e-testing.md) — The seven end-to-end flows that compose a full proof run.
- [Release Readiness](./release-readiness.md) — Readiness gates for SDK, connector, graph, and 360, plus the go/no-go summary and report format.

### Proof system
- [Functionality Proof Spine Overview](../proof/functionality-proof-spine.md) — What the proof spine is, runtime flow, core components, and pass condition.
- [Proof Tenant Specification](../proof/proof-tenant.md) — The staging proof tenant identity, workspace, platforms, and required state fields.
- [Proof Fixtures](../proof/proof-fixtures.md) — Fixture package location, directory tree, fixture shape, and required scenarios.
- [Proof Apps](../proof/proof-apps.md) — Purpose, UI controls, visible state, and pass conditions for each proof app.
- [Proof Report Format](../proof/proof-report-format.md) — Report sections, example table, and failure output format.

### SDK verification guides
- [Web SDK — Verify Installation](../developers/sdk/web/verify-installation.md)
- [React SDK — Verify Installation](../developers/sdk/react/verify-installation.md)
- [iOS SDK — Verify Installation](../developers/sdk/ios/verify-installation.md)
- [Android SDK — Verify Installation](../developers/sdk/android/verify-installation.md)
