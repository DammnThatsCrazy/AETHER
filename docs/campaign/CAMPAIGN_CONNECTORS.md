---
title: Campaign Source Connectors
slug: campaign/campaign-connectors
section: reference
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: 0.1.0
source_files: [Backend Architecture/aether-backend/services/measurement/connectors/google_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/meta_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/tiktok_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/linkedin_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/x_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/reddit_ads.py, Backend Architecture/aether-backend/services/measurement/connectors/microsoft_ads.py]
source_hashes:
  Backend Architecture/aether-backend/services/measurement/connectors/google_ads.py: sha256:0bdb5ba4ae3376e74e09695da7c5160af0d2193ef4067e1e808f59b82415d011
  Backend Architecture/aether-backend/services/measurement/connectors/linkedin_ads.py: sha256:cc1403bc26e99af200514c71800dbb83f1000fbdf09f15c5506595bb3e40b761
  Backend Architecture/aether-backend/services/measurement/connectors/meta_ads.py: sha256:c1099c3d670670554a0e7cdbab79d86d256002a519ac084cb21ddec1c4366dbb
  Backend Architecture/aether-backend/services/measurement/connectors/microsoft_ads.py: sha256:db43a96418564c16897d084bfb8aabc28f354e44c39d399eb87c2ae63f65b9c0
  Backend Architecture/aether-backend/services/measurement/connectors/reddit_ads.py: sha256:120aeb1ceac9f68f21374cef6af0caac77e67b04b56dcb690aa669c3adf0724c
  Backend Architecture/aether-backend/services/measurement/connectors/tiktok_ads.py: sha256:d50fcb577c68dd3585be8f95c744e01c61e47fd9b03f890ea8c89cee0f639f36
  Backend Architecture/aether-backend/services/measurement/connectors/x_ads.py: sha256:4ef01b6a17ed47ef7d2d54a4a3ce515fe6015a0d56543a1d920db0bfcec4c027
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
