---
title: E2E Testing — Functionality Proof Spine
slug: testing/e2e-testing
section: concepts
visibility: I
audience: [dev-junior, dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# E2E Testing — Functionality Proof Spine

## Scope

This doc describes the seven end-to-end flows that compose a full proof run. Each flow exercises a path through the platform from the proof tenant's initial state to a verifiable outcome in the UI or the graph. The flows are designed to be run in order, because each flow depends on the state left by the previous one.

Tickets referenced: FPS-010 through FPS-015 (smoke), FPS-026 (tenant activation E2E), FPS-027 (Web SDK activation E2E), FPS-028 (connector activation E2E), FPS-029 (Profile 360 E2E), FPS-030 (Campaign 360 E2E), FPS-031 (Communications 360 E2E), FPS-032 (lens activation E2E).

## The seven flows

### 1. Tenant activation

**Purpose.** Confirm that the proof tenant can be activated on staging and reaches a state where SDKs and connectors can be attached.

**Steps.**
1. Confirm the staging environment is reachable (this is also covered by `pnpm smoke:staging`).
2. Confirm the proof tenant `aether-proof-tenant` exists in workspace `proof-lab` on staging.
3. Reset the proof tenant to a clean state per [Staging Smoke Testing](./staging-smoke-testing.md).
4. Confirm the tenant's required state fields are present and initialized. The required fields are documented in [Proof Tenant Specification](../proof/proof-tenant.md).
5. Confirm the tenant is reachable from the SDK and connector smoke commands.

**Pass condition.** The tenant is activated, reset to a clean state, and reachable. The tenant's required state fields are present and initialized.

**Failure modes.** Tenant not reachable, tenant reset failed, required state fields missing. Likely owning subsystem: Platform / tenant management.

### 2. Web SDK activation

**Purpose.** Confirm that the Web SDK can be initialized against the proof tenant and emits a heartbeat and a canonical event that arrive in staging.

**Steps.**
1. Initialize the Web SDK in `apps/proof-web` with the proof tenant credentials.
2. Emit a heartbeat from the proof web app.
3. Track a canonical event from the proof web app.
4. Verify the heartbeat and event appear in the proof tenant ingestion surface.
5. Confirm the SDK's visible state in the proof web app matches the expected state (initialized, heartbeat sent, event tracked).

**Pass condition.** The Web SDK initializes, emits a heartbeat, tracks a canonical event, and both are visible in the proof tenant.

**Failure modes.** SDK initialization failed, heartbeat not received, event not received, visible state mismatch. Likely owning subsystem: Web SDK / ingestion pipeline.

### 3. Connector activation

**Purpose.** Confirm that a connector can be authorized against a provider, perform an initial sync, and project normalized data into the proof tenant's graph.

**Steps.**
1. Authorize the connector against the provider sandbox or test instance. The connector is whichever connector is being validated in this proof run (e.g., Shopify, Stripe, Email).
2. Confirm the connector reaches a `connected` or `syncing` state.
3. Confirm the connector performs an initial sync and reaches a `healthy` state.
4. Confirm cursor state is present after the initial sync.
5. Confirm the normalized events are projected into the proof tenant's graph.
6. Confirm the connector's data is not visible to other tenants.

**Pass condition.** The connector is authorized, syncs successfully, and its data is projected into the proof tenant's graph with the correct tenant isolation.

**Failure modes.** Authorization failed, sync failed, cursor missing, projection failed, tenant isolation violated. Likely owning subsystem: Connector implementation / ingestion pipeline.

### 4. Profile 360

**Purpose.** Confirm that the Profile 360 surface reflects the data from the proof tenant, including SDK observations and connector data.

**Steps.**
1. Open the Profile 360 for the proof tenant.
2. Confirm the profile contains the identity data from the SDK identify calls.
3. Confirm the profile contains the events from the Web SDK activation.
4. If a connector was activated, confirm the profile reflects the connector's data where applicable.
5. Confirm the profile surfaces the expected product states (`no data yet`, `healthy`, `needs attention`, etc.) as appropriate for the current state.

**Pass condition.** The Profile 360 reflects the SDK and connector data for the proof tenant, and surfaces the expected states.

**Failure modes.** Profile empty when it should not be, profile missing SDK data, profile missing connector data, wrong state surfaced. Likely owning subsystem: Profile 360 / graph projection.

### 5. Campaign 360

**Purpose.** Confirm that the Campaign 360 surface reflects the campaign-relevant data from the proof tenant.

**Steps.**
1. Open the Campaign 360 for the proof tenant.
2. Confirm the campaign surfaces reflect the SDK events and connector data as applicable.
3. Confirm metrics and aggregates are computed correctly, including zero-value cases where the data legitimately produces zero.
4. Confirm the surface handles empty result cases correctly when no campaign-relevant data is present.

**Pass condition.** The Campaign 360 reflects the proof tenant's data, computes metrics correctly, and handles empty and zero cases as documented.

**Failure modes.** Campaign data missing, metrics wrong, empty/zero cases handled incorrectly. Likely owning subsystem: Campaign 360 / graph projection / metrics.

### 6. Communications 360

**Purpose.** Confirm that the Communications 360 surface reflects the communication-relevant data from the proof tenant.

**Steps.**
1. Open the Communications 360 for the proof tenant.
2. Confirm the communications surfaces reflect the SDK events and connector data as applicable.
3. Confirm the surface handles `no data yet` and `empty result` states correctly when no communication-relevant data is present.
4. Confirm any communication templates or channels associated with the proof tenant are surfaced correctly.

**Pass condition.** The Communications 360 reflects the proof tenant's data and handles empty and no-data states correctly.

**Failure modes.** Communications data missing, state handling wrong, template/channel not surfaced. Likely owning subsystem: Communications 360 / graph projection.

### 7. Lens activation

**Purpose.** Confirm that a lens can be activated for the proof tenant and surfaces the expected intelligence from the graph.

**Steps.**
1. Activate a lens for the proof tenant. The lens is a product surface that consumes graph data and presents it as a focused view.
2. Confirm the lens reaches a `healthy` or `connected` state.
3. Confirm the lens surfaces the expected data from the proof tenant's graph.
4. Confirm the lens handles `no data yet` and `empty result` states correctly when the underlying graph has no data for the lens.
5. Confirm the lens surfaces any `needs attention` or `partially degraded` states when the underlying data or projection has an issue.

**Pass condition.** The lens activates, surfaces the expected data, and handles empty, no-data, and degraded states correctly.

**Failure modes.** Lens activation failed, lens data missing, state handling wrong. Likely owning subsystem: Lens implementation / graph projection.

## Flow dependencies

The flows are ordered because they build on each other:

```
tenant activation
    → Web SDK activation
        → connector activation
            → Profile 360
                → Campaign 360
                    → Communications 360
                        → lens activation
```

Tenant activation must complete before any SDK or connector activation. SDK and connector activation must complete before the 360 flows can verify data. The 360 flows must complete before a lens can be verified against populated graph data.

## How to run the flows

The flows are orchestrated by the proof runner. The exact command is determined by the proof runner implementation, but the intent is:

1. Run `pnpm smoke:staging` to confirm the staging environment and proof tenant are reachable.
2. Run the smoke commands for the SDKs and connectors that are part of the run.
3. Run the E2E flows in order.

The E2E flows are not a single command today. They are described here so the implementation can be ordered and the pass/fail evidence can be captured consistently.

## Pass/fail evidence for each flow

Each flow must produce evidence that it passed or failed. The evidence includes:

- **The steps that were executed.** Not just the final result; the intermediate states matter.
- **The observable state at each step.** What was visible in the UI, the graph, or the connector status.
- **The product states that were verified.** Which of the defined states (`not connected`, `connected`, `syncing`, `healthy`, `delayed`, `failed`, `needs attention`, `no data yet`, `missing data`, `empty result`, `zero value`, `partially degraded`) were present and correct.
- **The screenshots or logs for the run**, where applicable.
- **The typed FAIL reason and likely owning subsystem**, if the flow failed.

A flow that passes without evidence is not a pass. A flow that fails without a typed reason and likely owning subsystem is not a reportable failure.

## Pass condition for the E2E layer

The E2E layer passes when all seven flows complete with their pass conditions met, and the evidence for each flow is captured. If any flow fails, the E2E layer fails, and the failure is reported through the proof report format in [Proof Report Format](../proof/proof-report-format.md).

## How the E2E flows relate to the other layers

The E2E flows are the top of the proof spine. They compose the results of the smoke tests and the proof apps into a tenant-level proof. A change that affects the graph, a 360 surface, or a lens should add or update an E2E flow before the change is considered proven.
