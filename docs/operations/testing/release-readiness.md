---
title: Release Readiness — Functionality Proof Spine
slug: testing/release-readiness
section: concepts
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# Release Readiness — Functionality Proof Spine

## Scope

This doc describes the release readiness gates for the Aether platform as exercised through the Functionality Proof Spine. It covers the readiness gates for SDK, connector, graph, and 360, the go/no-go summary, and the report format. Release readiness is the decision point where the proof evidence is aggregated and a release candidate is declared ready or not ready to ship.

Tickets referenced: FPS-033 (release readiness gates), FPS-034 (go/no-go summary), FPS-035 (release readiness report format), FPS-036 (SDK release readiness), FPS-037 (connector release readiness), FPS-038 (graph release readiness), FPS-039 (360 release readiness).

## What release readiness is not

Release readiness is not a substitute for CI lanes, contract tests, parity tests, or the verification disposition in `make verification-disposition`. It is the aggregation of proof evidence on top of those layers. A release candidate that has not passed its CI lanes is not release-ready, even if the proof spine has not failed. A release candidate that has passed CI lanes but has failed proof evidence is not release-ready, because the proof spine is the integration-level confirmation that the whole system works for a real tenant.

## Readiness gates

A release candidate must pass the readiness gates for every area that is part of the release. If a release includes an SDK change, the SDK gate must pass. If it includes a connector change, the connector gate must pass. If it includes a graph or 360 change, the corresponding gate must pass. A release that touches nothing in an area does not need that area's gate, but it must still pass the gates for the areas it does touch.

### SDK gate

The SDK gate confirms that the SDK layer is proven for the release candidate.

**Required evidence.**
- All contract tests for the affected SDK package pass.
- The parity validator reports no missing required capabilities for the affected SDK.
- The proof app for the affected SDK exposes the required controls and shows the required visible state.
- The staging smoke test for the affected SDK passes with no FAIL lines for that platform.
- If the release includes mobile SDK changes, the mobile device checklist for the affected platform passes, including the required screenshots and logs.
- Any SDK behavior that is platform-specific (ATT gating on iOS, durable queue on Android, background lifecycle, fingerprinting gating) is verified on the appropriate device or emulator.

**Pass condition.** The affected SDK passes all four layers described in [SDK Testing](./sdk-testing.md), and the mobile device checklist passes where applicable.

### Connector gate

The connector gate confirms that the connector layer is proven for the release candidate.

**Required evidence.**
- All fixture tests for the affected connector pass.
- The sandbox test for the affected connector passes against the provider sandbox, where available.
- The connector activation E2E flow completes with the connector in a `healthy` state and its data visible in the graph.
- Token refresh and disconnect/reconnect behave as documented, with no silent data loss.
- The connector does not produce duplicate historical data during incremental sync or reconnection.
- Any connector-specific behavior that changed is verified in the sandbox or staging as applicable.

**Pass condition.** The affected connector passes all layers described in [Connector Testing](./connector-testing.md).

### Graph gate

The graph gate confirms that the intelligence graph is behaving correctly for the proof tenant.

**Required evidence.**
- The graph projection for the proof tenant contains the expected entities and edges after SDK and connector activation.
- The graph surfaces the expected product states (`no data yet`, `healthy`, `needs attention`, etc.) as appropriate.
- Tenant isolation is preserved: the proof tenant's graph data is not visible to other tenants.
- Any graph change that affects projection, identity resolution, or entity modeling is verified in the E2E flows.

**Pass condition.** The graph reflects the proof tenant's data correctly, preserves tenant isolation, and surfaces the expected states.

### 360 gate

The 360 gate confirms that the 360 surfaces are behaving correctly for the proof tenant.

**Required evidence.**
- Profile 360 reflects the SDK and connector data for the proof tenant and surfaces the expected states.
- Campaign 360 reflects the proof tenant's data, computes metrics correctly, and handles empty and zero cases as documented.
- Communications 360 reflects the proof tenant's data and handles empty and no-data states correctly.
- Any 360 change that affects data presentation, metrics, or state handling is verified in the E2E flows.

**Pass condition.** All 360 surfaces reflect the proof tenant's data correctly and handle the expected states correctly.

## Go/no-go summary

The go/no-go summary is the aggregation of the readiness gates into a single decision. It is not a vote. It is a report on whether the proof evidence supports shipping the release candidate.

The go/no-go summary has three parts:

1. **Gate status.** For each area in the release, the gate status is `PASS`, `FAIL`, or `NOT_APPLICABLE`. A release candidate is a go only when every applicable gate is `PASS`.
2. **Failure summary.** If any gate is `FAIL`, the summary lists each failure with its typed reason and likely owning subsystem, per the report format. A failure in any applicable gate is a no-go, even if the other gates pass.
3. **Blocker list.** Any `BLOCKED` evidence that prevented a gate from running is listed as a blocker. A release candidate with unresolved blockers in an applicable area is not a go, because the area has not been proven.

The go/no-go summary is owned by the release captain or the platform team, depending on the release process. The summary is not owned by the individual gate owners. The gate owners are responsible for their gate's evidence; the release captain is responsible for the summary.

## Report format

The release readiness report is the persistent artifact of the go/no-go decision. It is written to the same output location as the proof report, so it can be attached to the release candidate and reviewed after the fact.

The report format is described in [Proof Report Format](../proof/proof-report-format.md). The release readiness report uses the same sections and failure output format as the proof report, with the addition of the go/no-go summary section.

The release readiness report includes:

- **The run metadata.** Tenant ID, workspace, environment, run timestamp, and the release candidate identifier.
- **The gate status for each area.** SDK, connector, graph, 360, with `PASS`, `FAIL`, or `NOT_APPLICABLE`.
- **The go/no-go summary.** The decision and the reasoning.
- **The failure summary.** Any FAIL or BLOCKED evidence, with typed reason and likely owning subsystem.
- **The blocker list.** Any blockers that prevented an applicable gate from running.
- **The evidence references.** The report files, screenshots, and logs that support the decision.

## How release readiness relates to the rest of the proof spine

Release readiness is the top of the proof spine. It aggregates the evidence from the smoke tests, the E2E flows, and the mobile device checklist into a decision. A release candidate that has not run the proof spine is not release-ready, because it has no proof evidence. A release candidate that has run the proof spine but has a FAIL in an applicable gate is not release-ready, because the proof evidence says the system is not working for a real tenant.

A change to the release process, the readiness gates, or the report format should be reflected in this doc first. A new gate, a new failure reason, or a new report section should be documented here before it is used in a release decision.
