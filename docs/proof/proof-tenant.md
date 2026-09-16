---
title: Proof Tenant Specification
slug: proof/proof-tenant
section: testing
visibility: I
audience: [dev-junior, dev-senior, qa, ops]
status: experimental
since_version: 0.1.0
---

# Proof Tenant Specification

## Purpose

The proof tenant is the dedicated staging tenant that every Functionality Proof Spine run targets. It is the fixed point that makes proof runs reproducible. A proof run that uses a different tenant is not the same proof run, because the tenant's state, credentials, and workspace are part of the proof baseline.

The proof tenant is documented here so that every proof component — smoke commands, E2E flows, proof apps, and the report — targets the same tenant with the same expected fields.

## Identity

| Field | Value | Purpose |
|---|---|---|
| `tenant_id` | `aether-proof-tenant` | The tenant identifier used in API calls and SDK initialization. |
| `workspace` | `proof-lab` | The workspace that contains the proof tenant. |
| `environment` | `staging` | The environment the tenant lives in. The proof tenant is a staging tenant, not a production tenant. |

These values are the defaults for the proof run. They can be overridden by environment variables (`AETHER_PROOF_TENANT_ID`, `AETHER_PROOF_WORKSPACE`, `AETHER_STAGING_ENVIRONMENT`), but the defaults are the canonical proof tenant. A proof run that overrides them must record the override in the run metadata, because the report is tied to the tenant identity.

## Platforms

The proof tenant is exercised across the platforms that are in scope for the run. The platform list is part of the proof tenant spec because the tenant must be reachable from each platform's SDK and must reflect data from each platform's observations.

The expected platforms are:

- **Web.** The web SDK proof app targets the tenant.
- **React.** The React SDK proof app targets the tenant.
- **iOS.** The iOS SDK proof app targets the tenant.
- **Android.** The Android SDK proof app targets the tenant.
- **Connectors.** The connectors in scope target the tenant through their provider integrations.

A proof run does not have to include every platform. A release that touches only the web SDK does not need iOS or Android in the platform list. But the platform list must be recorded so the report can say which platforms were exercised and which were not.

## Required state fields

The proof tenant must have these state fields present and initialized before a proof run begins. These fields are the baseline that the E2E flows expect. If a field is missing, the tenant activation flow fails, and the failure is owned by the platform/tenant-management subsystem.

The required state fields are:

- **Tenant identity.** The tenant exists with the canonical `tenant_id`, `workspace`, and `environment`. The tenant is reachable from the staging API.
- **API key.** The proof tenant has a valid API key that the SDK proof apps can use to initialize and emit events.
- **Connector state.** If connectors are in scope, the proof tenant's connector state is reset so the connector activation flow can start from a clean baseline.
- **Graph state.** The proof tenant's graph state is reset so the E2E flows start from a baseline where the graph is empty for the proof tenant. This is what makes the `no data yet` and `empty result` states verifiable.
- **360 state.** The proof tenant's 360 surfaces are reachable and reflect the reset state. This is what makes the Profile 360, Campaign 360, and Communications 360 flows verifiable from a known baseline.
- **Lens state.** If lenses are in scope, the proof tenant's lens state is reset so the lens activation flow can start from a clean baseline.

The required state fields are not a claim that every field is fully populated. They are a claim that every field exists and is in a known state. Some fields will be `no data yet` or `empty result` after reset, and that is expected. The proof spine verifies that those states are surfaced correctly, not that they are populated.

## Pass condition

The proof tenant spec is satisfied when:

- The proof tenant exists with the canonical identity.
- The proof tenant is reachable from the staging API and from the SDK proof apps.
- The required state fields are present and initialized to a known state.
- The proof tenant can be reset to that known state before each proof run.
- The platform list for the run is recorded in the run metadata.

If the proof tenant does not meet these conditions, the tenant activation E2E flow fails, and the failure is reported with a typed reason and likely owning subsystem.

## How the proof tenant is used

Every proof component uses the proof tenant in the same way:

- The smoke commands use the proof tenant's API key to reach the staging API and confirm reachability.
- The SDK proof apps use the proof tenant's API key and tenant ID to initialize and emit events.
- The connector activation flow uses the proof tenant as the target for connector sync and projection.
- The E2E flows use the proof tenant as the tenant whose 360 surfaces and lens states are verified.
- The report uses the proof tenant's identity as the run's tenant identifier.

The proof tenant is not a generic staging tenant. It is the tenant that the proof spine has verified against. Using a different tenant for a proof run means the run is not comparable to previous runs, because the baseline is different.
