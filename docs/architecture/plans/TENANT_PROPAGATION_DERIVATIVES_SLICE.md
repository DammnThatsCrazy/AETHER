---
title: Tenant Propagation Lens — Derivatives and Event-Contract Slice
slug: plans/tenant-propagation-derivatives-slice
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0
canonical_owner: backend@aether
---
# Tenant Propagation Lens — Derivatives and Event-Contract Slice

This plan records the first vertical slice of the **Propagation & Diffusion
Lens**: a governed, read-only computation over Relationship360 and Social360
that shows how a trading behavior moves through one tenant's own users. The
first behavior is financial: opening a perpetual position on Hyperliquid or
buying an outcome on Polymarket.

The lens is not a new 360 and not a second graph. It reads canonical
relationship facts, Silver exposure events, and derivatives fills, then derives
paths, episodes, and classifications that are recomputed on demand. Nothing it
produces is written back as canonical truth.

## Scope and tenancy

- A tenant sees only its own linked users. A venue account link belongs to one
  `(tenant_id, subject_id)` pair; nothing crosses tenant lines and no cohort
  benchmark across tenants is produced.
- Market data (prices, funding, odds, resolutions) is public context with no
  user identity. Account data (fills, positions, outcome trades) is private to
  the tenant that holds the link.
- Linking routes: wallet address with server-verified ownership proof (this
  slice), user read-only API key, OAuth delegation, and tenant push. Every link
  carries a consent receipt and can be revoked; revocation removes the account
  from all later runs.

## Definitions

| Term | Definition in this slice |
|---|---|
| Exposure | Evidence that user B could have observed user A before B acted. Four channels: social relationship facts (`FOLLOWS`, `INTERACTS_WITH`, `MUTUAL_SOCIAL_CONNECTION`, `COMMUNITY_ASSOCIATION`, ...), on-chain links (`PAYS`), tenant in-app exposure events (Silver `exposure` family carrying the exposed-to subject), and promoted Relationship360 facts (`REFERRED_BY`, `COLLABORATES_WITH`, `COMMUNICATES_WITH`, ...). Each exposure keeps its evidence refs and validity window. |
| Adoption | A user's **first** position in an instrument, on the **same side** as the seed, within the exposure window. For perps the side is long or short. For event contracts the instrument is the condition and the side is the outcome bought. Adding to a held position never counts; only the first flat-to-open epoch from the position engine counts. |
| Seed | The earliest adopter in a tenant/instrument/side group within the run window. |
| Propagation path | An ordered chain of adopters where each hop is backed by an exposure that precedes the later adoption and falls inside the window. Multi-hop composition is certified only through predicates the governed registry marks `PROPAGATION_ELIGIBLE` or `PATH_COMPOSABLE`, via `decompose_influence_propagation`. |
| Diffusion episode | All adoptions of one tenant/instrument/side group within the run window, with their paths. Episodes reference the existing `EpisodeRecord` vocabulary; no new episode store. |
| Propagation radius | The maximum certified hop depth from the seed inside an episode. Breadth, reach, velocity, and repetition are reported separately, never folded into one score. |

## Classification and claim types

Each episode is labelled `organic`, `viral`, `coordinated`, or
`insufficient_data`:

- **Baseline.** Adoption rate among exposed users is compared against the rate
  among linked users in the same tenant with no qualifying exposure, for the
  same instrument, side, and window. Lift above the configured threshold with
  enough exposed users is `viral`; otherwise `organic`.
- **Coordination.** Adoptions that land within a tight lockstep window, or
  share an on-chain funding source, mark the episode `coordinated`. This reuses
  the pattern-discovery sequence/temporal detector semantics rather than a new
  detector.
- **Insufficient data.** Too few linked users, no unexposed comparison group,
  or missing evidence never become a zero; the episode says why.

Every path and episode declares a claim type: `observed` (exposure preceded
adoption), `inferred` (the lift suggests influence). `causally_supported` is
reserved and withheld until incrementality evidence exists.

## Reused authorities

| Need | Authority reused |
|---|---|
| Relationship paths | `RepositorySocialGraphPathReader` pattern and tenant graph edge reads; governed predicate registry |
| Influence breakdown | `shared/relationship_spine/influence_propagation.py` |
| Exposure events | `ingestion/silver/projectors/exposure_projector.py` |
| Positions and first entry | `value/derivatives/position_engine.py` |
| Wallet ownership | `identity/identity/verification.py` (`WALLET_OWNERSHIP_VERIFIED` evidence) |
| Narrative grouping | `SemanticCascade` stays a narrative view and may be linked, not replaced |

## New in this slice

1. Canonical event-contract instrument under derivatives; Polymarket and
   Kalshi normalizers move into it (the prediction-markets module re-exports).
2. Polymarket read-only venue adapter (positions and trades by wallet).
3. Tenant venue account links with ownership proof, consent, and revocation.
4. Propagation contracts (JSON Schema plus Python and TypeScript mirrors).
5. Pure propagation engine plus repository sources and a flag-gated route.
6. `propagation` overlay lens in the lens registry.

## Flags and readiness

- `AETHER_PROPAGATION_LENS_ENABLED` and `AETHER_VENUE_ACCOUNT_LINKS_ENABLED`
  default off and stay off in the release manifests.
- Registry states for `social360` and `relationship360` stay `in_flight`.
  This slice adds code, fixtures, and live public-endpoint captures. It does
  not claim provider-backed, staging-proven, or production readiness.

## Not in this slice

- CEX perps, regulated futures, more on-chain perps, Kalshi account data.
- Copy-trade or vault-leader relationships (no registered predicate yet).
- Causal claims, attribution credit, cross-tenant benchmarks.
