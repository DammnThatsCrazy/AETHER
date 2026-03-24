# Profile 360 Audit — What Already Existed

## What Was Already Present (Reused, Not Rebuilt)

| Subsystem | What Exists | Reused By Profile 360 |
|-----------|-------------|----------------------|
| **Identity service** | Profile CRUD, merge, graph neighbors | Core profile data source |
| **Resolution service** | Identity clustering, probabilistic matching, admin approval | Cluster/identifier resolution |
| **Intelligence service** | Wallet risk scores, protocol analytics, entity clusters | Intelligence composer |
| **Graph (Neptune)** | 18 vertex types, 48+ edge types, 4 relationship layers | Graph context, identifier resolution |
| **Lake** | Bronze/Silver/Gold across 6 domains | Lake data composer, provenance |
| **Analytics** | Event queries, dashboard summaries, export | Timeline composer |
| **Consent** | Purpose-based consent, DSR handling | Consent status in profile |
| **Fraud** | Event-level risk scoring | Referenced by intelligence |
| **Trust Score** | Composite scorer (fraud + identity + behavioral) | Intelligence composer |
| **Rewards** | Per-wallet reward history | Available via wallet identifiers |
| **Agent** | Agent registration, lifecycle, trust scoring | Available via graph |

## What Was Missing

| Gap | Description |
|-----|------------|
| **Unified aggregator** | No service composed data from all subsystems into one view |
| **Cross-identifier resolution** | No way to look up a profile by wallet, email, device, or social handle — only by user_id |
| **Holistic API** | No single endpoint returned identity + timeline + graph + intelligence + lake + consent |
| **Provenance view** | Source attribution existed per-subsystem but no unified provenance query |
| **Profile resolver** | Graph edges existed but no service traversed them to resolve identifiers |

## What Was Intentionally NOT Rebuilt

| Component | Why Not Rebuilt |
|-----------|---------------|
| Identity CRUD | Already exists in identity service — Profile 360 calls it |
| Event storage | Already exists in analytics — Profile 360 queries it |
| Graph traversal | Already exists in GraphClient — Profile 360 uses it |
| Risk scoring | Already exists in TrustScoreComposite — Profile 360 calls it |
| Lake repositories | Already exist across 6 domains — Profile 360 queries Gold tier |
| Consent management | Already exists in consent service — Profile 360 reads status |
| Merge/unmerge | Already exists in identity service — not duplicated |
