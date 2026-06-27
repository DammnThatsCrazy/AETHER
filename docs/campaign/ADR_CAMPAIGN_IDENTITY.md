---
title: "ADR: Campaign Identity — Canonical UUID Strategy"
section: campaign
last_updated: 2026-06-27
---

# ADR: Campaign Identity — Canonical UUID Strategy

## Status: Accepted

## Context

Aether ingests campaign spend data from 7 ad platforms. Each platform assigns its own numeric or alphanumeric campaign ID (e.g. Google `12345678901`, Meta `23847119283740001`). These IDs:

- Are not globally unique across platforms
- Change when a campaign is migrated or recreated
- Are not known at the time of SDK landing (the user lands before the campaign ID can be looked up)
- Cannot be used as a stable attribution key in SQL joins across years of data

Additionally, SDK acquisition evidence arrives as UTM parameters in landing URLs — there is no platform campaign ID available at event capture time.

## Decision

**Every campaign in Aether is assigned a canonical UUID at registration time, independent of any provider ID.**

The provider ID is stored separately in `campaign_external_refs.external_campaign_id`. The canonical UUID (`campaign_id`) is the only identifier written into measurement facts (`spend_records`, `silver_campaign_touchpoint_facts`, `attribution_credits`).

Resolution from external evidence to canonical UUID is handled by `CampaignResolver` using a deterministic 7-step priority order with documented confidence levels. The resolver never uses fuzzy name matching.

## Why not use provider IDs directly?

1. **No global uniqueness** — the same numeric ID appears across platforms.
2. **Instability** — platforms reassign IDs after campaign recreation.
3. **Cross-signal identity problem** — the SDK touchpoint has no platform ID; only UTM parameters.
4. **Auditability** — a UUID assigned by Aether is under our control; provider IDs are not.

## Why no fuzzy name matching?

Campaign names are not unique. "Summer Sale" is used by dozens of tenants and potentially multiple campaigns within one tenant. Fuzzy matching would silently merge unrelated campaigns, corrupting attribution. When evidence is ambiguous, the only correct behavior is to create a Mapping Review for human resolution.

## Why not campaign execution in Aether?

Aether is the intelligence and measurement layer. Budget management, audience targeting, and ad delivery are the province of the ad platform's campaign management tools. Mixing execution with measurement creates dual-ownership problems and regulatory risk in certain markets.

## Consequences

- Every connector must call `CampaignRegistryService.upsert_external_campaign()` before writing spend facts — no exceptions.
- The `campaign_id` column in any measurement fact is always a Aether UUID or NULL (unresolved). A provider text ID in this column is a data invariant violation.
- The backfill script must be run after migration to retroactively populate canonical UUIDs for pre-migration spend records.
- Mapping Reviews require operator attention on an ongoing basis until UTM tracking templates are fully deployed.
