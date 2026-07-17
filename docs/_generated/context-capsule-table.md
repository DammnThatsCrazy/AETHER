<!-- DO NOT EDIT — generated from packages/shared/contracts/context-capsule-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Context Capsule Registry

Contract version: `1.0.0`

## Location sources

`server_network_ip`, `device_coarse`, `device_precise`, `verified_venue`, `tenant_supplied_venue`, `qr_or_checkin`, `shipping_address`, `billing_address`, `payment_instrument_country`, `provider_reported`, `organization_registered`, `agent_execution_region`, `server_execution_region`, `imported_historical`

## Location semantics

`network_egress`, `likely_physical_presence`, `verified_physical_presence`, `declared_address`, `commercial_destination`, `billing_jurisdiction`, `organization_location`, `execution_region`, `venue_association`, `unknown`

## Precision classes

`country`, `region`, `city`, `coarse_cell`, `precise`

## Conflict states

`none`, `explainable`, `unresolved`, `contradictory`

## Context states

`normal_primary`, `normal_secondary`, `expected_recurring`, `temporary_travel`, `transient`, `new_context`, `returning_to_baseline`, `commute_pattern`, `network_egress_only`, `possible_vpn`, `possible_datacenter`, `location_uncertain`, `location_conflict`, `improbable_transition`, `not_applicable`, `suppressed`, `insufficient_evidence`

## Retention classes

| Class | Constraint |
|---|---|
| `coarse_location_observation` | maxDays=30 |
| `context_capsule` | inheritsStrictest=True |
| `derived_baseline` | aggregateOnly=True |
| `ephemeral_network_token` | maxHours=24 |
| `precise_location_observation` | tenantPolicy=True |
| `raw_ip` | maxHours=0 |

## Capsule transition types

`session_start`, `device_change`, `network_change`, `location_cluster_change`, `campaign_change`, `consent_change`, `identity_resolved`, `actor_change`, `journey_handoff`, `runtime_change`, `precision_upgrade`
