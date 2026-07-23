<!-- DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Canonical Traffic-Source Registry (contract v1.0.0)

Classification and campaign identity are independent dimensions. The
customer-facing fallback is **Direct / Unknown** — never a typed-URL claim.

## Dimensions

| Dimension | Values | Vocabulary |
|---|---|---|
| `traffic_origin` | 5 | `external`, `internal`, `app_store`, `offline`, `unknown` |
| `economic_class` | 4 | `paid`, `unpaid`, `unknown`, `nonhuman` |
| `channel_family` | 15 | `search`, `social`, `email`, `referral`, `affiliate`, `partner`, `ai`, `agent`, `push`, `sms`, `app_store`, `internal`, `direct`, `machine`, `unknown` |
| `source_class` | 19 | `paid_search`, `paid_social`, `display`, `organic_search`, `organic_social`, `owned_referral`, `external_referral`, `email`, `affiliate`, `partner`, `ai_referral`, `agent_referral`, `push`, `sms`, `app_store_referral`, `internal_navigation`, `direct_unknown`, `machine_referral`, `unknown` |
| `entry_method` | 18 | `verified_source_link`, `server_redirect`, `web_referrer`, `paid_click_id`, `utm_declaration`, `android_install_referrer`, `android_app_link`, `ios_universal_link`, `ios_custom_url`, `ios_adattributionkit`, `push_notification`, `email_link`, `qr_code`, `nfc`, `vanity_url`, `internal_navigation`, `manual_sdk_evidence`, `unknown` |
| `proof_level` | 7 | `cryptographic`, `platform_verified`, `domain_verified`, `server_observed`, `declared`, `inferred`, `none` |

## Source classes

| Source class | Channel family | Economic class | Label |
|---|---|---|---|
| `paid_search` | `search` | `paid` | Paid Search |
| `paid_social` | `social` | `paid` | Paid Social |
| `display` | `search` | `paid` | Display |
| `organic_search` | `search` | `unpaid` | Organic Search |
| `organic_social` | `social` | `unpaid` | Organic Social |
| `owned_referral` | `referral` | `unpaid` | Verified Source |
| `external_referral` | `referral` | `unknown` | Referral |
| `email` | `email` | `unpaid` | Email |
| `affiliate` | `affiliate` | `paid` | Affiliate |
| `partner` | `partner` | `unknown` | Partner |
| `ai_referral` | `ai` | `unpaid` | AI Referral |
| `agent_referral` | `agent` | `unpaid` | Agent Referral |
| `push` | `push` | `unpaid` | Push |
| `sms` | `sms` | `unpaid` | SMS |
| `app_store_referral` | `app_store` | `unknown` | App Install |
| `internal_navigation` | `internal` | `unpaid` | Internal Navigation |
| `direct_unknown` | `direct` | `unknown` | Direct / Unknown |
| `machine_referral` | `machine` | `nonhuman` | Machine Referral |
| `unknown` | `unknown` | `unknown` | Unknown |
