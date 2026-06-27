---
title: Campaign Source Connectors
slug: campaign/campaign-connectors
section: reference
visibility: I
audience: [dev-senior, ops]
source_files:
  - Backend Architecture/aether-backend/services/measurement/connectors/google_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/meta_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/tiktok_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/linkedin_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/x_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/reddit_ads.py
  - Backend Architecture/aether-backend/services/measurement/connectors/microsoft_ads.py
last_synced_commit: 0d8c5ee76e27caa09d3ce2fc49131737b8c7b8d3
---

# Campaign Source Connectors

All connectors follow a shared contract: they call `CampaignMeasurementWriter.write_metrics()` which calls `CampaignRegistryService.upsert_external_campaign()` before writing spend facts. This guarantees:

- `spend_records.campaign_id` is always a canonical Aether UUID.
- `spend_records.external_campaign_id` always stores the provider's text ID.
- Provider campaign renames do not change the canonical UUID.

## Supported providers

| Provider | Platform key | Auth mechanism | Metrics available |
|---|---|---|---|
| Google Ads | `google_ads` | OAuth2 / Service Account | Impressions, clicks, spend, conversions |
| Meta (Facebook) Ads | `meta_ads` | OAuth2 | Impressions, clicks, spend, reach |
| TikTok Ads | `tiktok_ads` | OAuth2 | Impressions, clicks, spend, video views |
| LinkedIn Ads | `linkedin_ads` | OAuth2 | Impressions, clicks, spend, engagement |
| X (Twitter) Ads | `x_ads` | OAuth1a | Impressions, clicks, spend |
| Reddit Ads | `reddit_ads` | OAuth2 | Impressions, clicks, spend |
| Microsoft Advertising | `microsoft_ads` | OAuth2 | Impressions, clicks, spend, conversions |

## ExternalCampaignMetric fields

Each connector produces `ExternalCampaignMetric` rows:

```python
@dataclass
class ExternalCampaignMetric:
    platform: str
    external_account_id: str
    external_campaign_id: str       # Provider's campaign ID — NEVER written to campaign_id
    external_campaign_name: str
    period_start: datetime
    period_end: datetime
    impressions: int
    clicks: int
    spend: Decimal
    currency: str
    raw_dimensions: dict
```

## Tracking templates

For UTM-based resolution of SDK touchpoints, apply the following tracking template to your campaign creative in each platform. Replace `{lpurl}` with your landing page.

**Google Ads:** `{lpurl}?utm_source=google&utm_medium=cpc&utm_campaign={campaignid}&utm_id={creative}&gclid={gclid}`

**Meta Ads:** Use Facebook's URL parameter builder with `utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_id={{ad.id}}&fbclid={{fbclid}}`

**TikTok Ads:** `{lpurl}?utm_source=tiktok&utm_medium=paid_social&utm_campaign=__CAMPAIGN_NAME__&utm_id=__CID__&ttclid=__CLICKID__`

**LinkedIn Ads:** `{lpurl}?utm_source=linkedin&utm_medium=paid_social&utm_campaign={campaignid}&liEFatId={liEFatId}`

## Known limits

- Connector credentials must be re-authorized when platform tokens expire. Stale credentials generate a `CampaignSourceStale` alert.
- Provider APIs impose rate limits; connectors use exponential backoff and respect `Retry-After` headers.
- Historical data import is bounded by each platform's retention window (typically 36 months).
