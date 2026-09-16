---
title: Functionality Proof Spine — Overview
slug: proof/functionality-proof-spine
section: testing
visibility: I
audience: [dev-junior, dev-senior, qa, ops, architect]
status: experimental
since_version: 0.1.0
---

# Functionality Proof Spine — Overview

## What the proof spine is

The Aether Functionality Proof Spine (FPS) is a coordinated, tenant-level proof that the platform works end-to-end for a real tenant workflow. It runs against a dedicated proof tenant on staging and exercises the SDKs, connectors, intelligence graph, and 360 surfaces in a defined order. It produces a structured report that records pass/fail evidence and feeds the release readiness decision.

The proof spine is not a test framework. It does not replace unit tests, contract tests, parity tests, or CI lanes. It sits above them as an integration-level proof that the whole system works together for a defined tenant baseline. A change that passes its package-level tests but breaks the proof spine has not been proven for a real tenant.

## Why it exists

The platform is composed of SDKs, connectors, an ingestion pipeline, an intelligence graph, and 360 surfaces. Each piece has its own tests, but those tests do not by themselves prove that a real tenant can install an SDK, connect a provider, sync data, and see that data in a 360. The proof spine exists to close that gap: to prove that the pieces work together for a tenant that is not a mock and a workflow that is not a unit test.

The proof spine is also the source of evidence for release readiness. When a release candidate is proposed, the proof spine is the integration-level proof that the release does not break a real tenant workflow. See [Release Readiness](./testing/release-readiness.md) for the readiness gates.

## Runtime flow

A proof run proceeds through these stages, in order:

1. **Tenant setup.** The proof tenant is identified and reset to a known clean state. The required environment variables are set. The staging environment is confirmed reachable. This stage is described in [Staging Smoke Testing](./testing/staging-smoke-testing.md) and [Proof Tenant Specification](./proof-tenant.md).

2. **Smoke checks.** The staging smoke command runs and confirms the staging environment and proof tenant are reachable. The downstream smoke commands run for each SDK and connector in the run. These are the gateway checks. If they fail, the deeper flows do not proceed.

3. **E2E flows.** The seven end-to-end flows run in order: tenant activation, Web SDK activation, connector activation, Profile 360, Campaign 360, Communications 360, and lens activation. Each flow builds on the state left by the previous one. The flows are described in [E2E Testing](./testing/e2e-testing.md).

4. **Mobile device confirmation.** Where the release includes mobile SDK changes, the mobile device checklist is run on simulator/emulator and physical device, and the required screenshots and logs are captured. This is described in [Mobile Device Testing](./testing/mobile-device-testing.md).

5. **Report generation.** The proof run produces a report that records the result of each check and flow, with typed FAIL reasons and likely owning subsystems where applicable. The report format is described in [Proof Report Format](./proof-report-format.md).

6. **Release readiness aggregation.** The report is aggregated into a go/no-go summary per [Release Readiness](./testing/release-readiness.md). The release captain or platform team uses the summary to decide whether the release candidate is ready to ship.

The runtime flow is sequential because each stage depends on the state left by the previous one. A proof tenant must be reset before the smoke checks. The smoke checks must pass before the E2E flows. The E2E flows must complete before the report can be generated.

## Core components

The proof spine is composed of these components:

- **Proof tenant.** A dedicated staging tenant with a known identity, used as the baseline for every proof run. See [Proof Tenant Specification](./proof-tenant.md).
- **Proof fixtures.** Stubbed and provider-shaped fixture data used to test connectors and normalizers in isolation. See [Proof Fixtures](./proof-fixtures.md).
- **Proof apps.** Minimal consumer apps that exercise each SDK through a real UI. See [Proof Apps](./proof-apps.md).
- **Smoke commands.** The `pnpm smoke:*` commands that gate the deeper flows. See [Staging Smoke Testing](./testing/staging-smoke-testing.md).
- **E2E flows.** The seven flows that compose a full proof run. See [E2E Testing](./testing/e2e-testing.md).
- **Mobile device checklist.** The simulator, emulator, and physical device steps for iOS and Android. See [Mobile Device Testing](./testing/mobile-device-testing.md).
- **Report format.** The structured report that records pass/fail evidence. See [Proof Report Format](./proof-report-format.md).

These components are backed by packages in the monorepo:

- `packages/proof-fixtures` — shared fixture stubs for FPS scaffolding.
- `packages/proof-reporting` — report generators for proof results.
- `packages/proof-runner` — the proof runner that orchestrates the run.
- `apps/proof-web`, `apps/proof-react`, `apps/proof-ios`, `apps/proof-android`, `apps/proof-connectors` — the proof apps.

## Required proof tenant spec

The proof tenant is identified by these fields:

| Field | Value |
|---|---|
| `tenant_id` | `aether-proof-tenant` |
| `workspace` | `proof-lab` |
| `environment` | `staging` |
| `platforms` | The list of platforms exercised in the run (web, react, ios, android, and the connectors in scope) |

The proof tenant spec is described in full in [Proof Tenant Specification](./proof-tenant.md). The proof tenant is the fixed point that makes proof runs reproducible. A proof run that uses a different tenant is not the same proof run.

## Pass condition

The proof spine passes when:

- The staging environment is reachable and the proof tenant is reset to a clean state.
- The staging smoke command passes with no FAIL lines.
- The downstream smoke commands for the SDKs and connectors in scope pass with no FAIL lines for those targets.
- The seven E2E flows complete with their pass conditions met.
- The mobile device checklist passes for any platform in scope, with the required screenshots and logs.
- The report is generated and records the evidence for each check and flow.
- The release readiness aggregation produces a go decision, or a documented no-go with typed failures and blockers.

A proof run that does not produce a report is not a pass. A proof run that produces a report with a FAIL in any applicable area is not a pass. A proof run that produces a report with a BLOCKED area that should have run is not a pass.

## How the proof spine relates to the rest of the platform

The proof spine is the integration-level proof layer. It sits on top of the package-level tests and below the release decision. It is the layer that proves the platform works for a real tenant workflow, and the layer that produces the evidence for release readiness.

A change to any part of the platform should be reflected in the proof spine if it affects a real tenant workflow. A new SDK capability, a new connector, a graph projection change, or a 360 surface change should add or update the relevant proof component before the change is considered proven.
