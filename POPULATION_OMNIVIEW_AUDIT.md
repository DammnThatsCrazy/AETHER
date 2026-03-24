# Population Omniview Audit — What Already Existed

## What Was Already Present (Reused)

| System | What Exists | How Reused |
|--------|-------------|-----------|
| **Identity clustering** | Resolution service with graph-based clusters | Foundation for community detection |
| **Graph vertices** | IDENTITY_CLUSTER, MEMBER_OF_CLUSTER, SIMILAR_TO | Infrastructure for group membership |
| **Graph layers** | H2H, H2A, A2H, A2A classification | Layer-aware group analysis |
| **Profile 360** | Holistic single-entity views | Micro-level drill-down target |
| **Intelligence API** | Wallet risk, protocol analytics, clusters | Entity-level intelligence |
| **Lake Gold tier** | Per-entity metrics and features | Feature source for group summaries |
| **Analytics** | Event queries, dashboard aggregates | Timeline data for groups |
| **BaseRepository** | PostgreSQL/in-memory pattern | Foundation for population + membership repos |

## What Was Missing

| Gap | Description |
|-----|-------------|
| **Population registry** | No system to create, store, or query population groups |
| **Membership engine** | No system to track which entities belong to which groups |
| **Macro analytics** | No population-level rollups or trend views |
| **Group comparison** | No way to compare two groups |
| **Membership explanation** | No system to explain why an entity is in a group |
| **Group intelligence** | No group-level feature/behavior summaries |
| **Cohort/segment APIs** | Zero endpoints for segments, cohorts, clusters, or communities |
| **Rule-based segmentation** | No rule definition + membership evaluation system |
| **Population trends** | No time-series analysis of group creation or membership |

## What Was Intentionally NOT Rebuilt

| Component | Why Not Rebuilt |
|-----------|---------------|
| Graph store | Population uses existing GraphClient for community context |
| Lake repositories | Gold tier already stores per-entity metrics |
| Profile resolver | Already resolves identifiers — population adds group context |
| Trust scoring | Already computes risk — population aggregates it per group |
| Event analytics | Already queries events — population filters by group membership |
