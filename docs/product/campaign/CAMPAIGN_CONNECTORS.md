---
title: Campaign Source Connectors
slug: campaign/campaign-connectors
section: reference
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: 0.1.0
source_files: [services/api/journeys/measurement/connectors/google_ads.py, services/api/journeys/measurement/connectors/meta_ads.py, services/api/journeys/measurement/connectors/tiktok_ads.py, services/api/journeys/measurement/connectors/linkedin_ads.py, services/api/journeys/measurement/connectors/x_ads.py, services/api/journeys/measurement/connectors/reddit_ads.py, services/api/journeys/measurement/connectors/microsoft_ads.py]
source_hashes:
  "services/api/journeys/measurement/connectors/google_ads.py": "sha256:d8f63eff297fe16ac18433f7d6e13c3ae3b1a01ff00b32602181fe01cf413b2d"
  "services/api/journeys/measurement/connectors/linkedin_ads.py": "sha256:c13c468a6f29d450314a70dea3ffabdad47638a149742dde846c7c6f7d867706"
  "services/api/journeys/measurement/connectors/meta_ads.py": "sha256:470b73fbeea77c0e8471e7ca3919b530b5cb0c7e50d070af84b7a7f0a850e431"
  "services/api/journeys/measurement/connectors/microsoft_ads.py": "sha256:d86ce469708e5297db0cdc04272589ff234943c5795155fc89c5a1c6d8290cfc"
  "services/api/journeys/measurement/connectors/reddit_ads.py": "sha256:93e4f76b421a4041f9f4edc85e23c29990c534e2438ad6196b9c4ba38be3833b"
  "services/api/journeys/measurement/connectors/tiktok_ads.py": "sha256:4fc09c94676cf884d8414d1ab6d813fae6ebb648dc62f3828317288330489d87"
  "services/api/journeys/measurement/connectors/x_ads.py": "sha256:2838c6ca8665f97e9e0619478850bb59e3cec762d1f06f3d53ca2e98d1d01f97"
---

# Campaign Source Connectors

All connectors follow a shared contract: they call `CampaignMeasurementWriter.write_metrics()` which calls `CampaignRegistryService.upsert_external_campaign()` before writing spend facts. This guarantees:

- `spend_records.campaign_id` is always a canonical Aether UUID.
- `spend_records.external_campaign_id` always stores the provider's text ID.
- Provider campaign renames do not change the canonical UUID.

Connector execution is fail-closed in every deployment profile. Missing
credentials, an unavailable provider SDK, or a provider API failure produces an
explicit unavailable/error result; local development does not substitute mock
campaigns, spend, health, or successful synchronization.

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

- Every provider requires its real credential and account configuration before
  synchronization or credential health can succeed.
- Google Ads additionally requires the provider SDK; if it is absent, the
  connector reports the dependency as unavailable.
- Connector credentials must be re-authorized when platform tokens expire. Stale credentials generate a `CampaignSourceStale` alert.
- Provider APIs impose rate limits; connectors use exponential backoff and respect `Retry-After` headers.
- Historical data import is bounded by each platform's retention window (typically 36 months).
