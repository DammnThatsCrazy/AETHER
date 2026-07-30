---
title: Campaign Resolution Contract
slug: campaign/campaign-resolution-contract
section: reference
visibility: I
audience: [dev-senior, architect]
source_files:
  - Backend Architecture/aether-backend/services/campaign/resolver.py
  - Backend Architecture/aether-backend/services/campaign/normalization.py
last_synced_commit: "3283497"
---

# Campaign Resolution Contract

`CampaignResolver` deterministically maps acquisition evidence to a canonical campaign UUID. The resolution order is fixed and documented below. The resolver never falls through to fuzzy matching.

## Priority order

| Priority | Method | Confidence | Requirement |
|---|---|---|---|
| 1 | `canonical_id` | 1.00 | Explicit Aether UUID validated against tenant ownership |
| 2 | `external_ref` | 1.00 | Exact match on `(platform, external_account_id, external_campaign_id)` |
| 3 | `utm_id_alias` | 0.99 | Exact `utm_id` alias match |
| 4 | `composite_alias` | 0.95 | `(platform, account, source, medium, utm_campaign)` composite alias |
| 5 | `utm_campaign_alias` | 0.85 | Tenant-unique `utm_campaign` alias |
| 6 | Ambiguous | — | Multiple candidates; Mapping Review created |
| 7 | Unresolved | — | No candidates; Mapping Review created |

## ResolutionResult contract

```python
@dataclass
class ResolutionResult:
    status: Literal["resolved", "unresolved", "ambiguous", "invalid", "not_applicable"]
    campaign_id: Optional[UUID]           # None unless resolved
    method: Optional[str]                 # Priority method name
    confidence: Optional[Decimal]        # None unless resolved
    resolution_version: str              # RESOLVER_VERSION constant
    matched_external_ref_id: Optional[UUID]
    matched_alias_id: Optional[UUID]
    candidate_campaign_ids: list[UUID]   # Non-empty on ambiguous
    reason: str                          # Human-readable reason
    review_id: Optional[UUID]            # Set on unresolved/ambiguous
```

## Status meanings

- `resolved` — a single canonical UUID was found with deterministic confidence
- `unresolved` — no matching evidence; Mapping Review created
- `ambiguous` — multiple candidates, none definitively higher priority; Mapping Review created
- `invalid` — a malformed canonical UUID was presented (rejected without review)
- `not_applicable` — no evidence was provided; skipped silently

## Normalization

Before any lookup:
- `platform` → `normalize_platform()`: lowercased, alias-mapped (e.g. "Facebook Ads" → "meta_ads")
- `utm_campaign`, `utm_id` → `normalize_utm_value()`: URL-decoded, stripped, lowercased
- `evidence_hash` → SHA-256 of sorted, tenant-scoped key/value pairs for review deduplication

## What is explicitly prohibited

- Fuzzy name similarity matching
- Cross-tenant resolution
- Auto-merge on display name collision
- Production use of in-memory storage for resolver state
- Logging or surfacing credential/secret values in resolution errors
