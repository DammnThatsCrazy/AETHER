<!-- DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Integration Consent Registry (22 connectors/adapters, contract v8.13.0)

| Connector | Provider | Category | Risk | Status | Purposes | Default basis | Raw payload policy | Signature scheme |
|---|---|---|---|---|---|---|---|---|
| `slack` | Slack | workspace_collaboration | high | available | analytics, agent | legitimate_interest | quarantine_verified_allowlist | slack_signing_secret |
| `generic_webhook` | Generic Webhook | custom_ingest | high | available | analytics | explicit_manifest_required | quarantine_until_schema_approved | aether_hmac_sha256 |
| `shopify` | Shopify | commerce | medium | available | commerce, analytics, marketing | contract | prohibit_customer_email_addresses | shopify_hmac_sha256 |
| `stripe` | Stripe | payments | medium | available | commerce | contract | prohibit_payment_method_objects | stripe_v1 |
| `hubspot` | HubSpot | crm | high | available | analytics, marketing | contract | field_allowlist_only | hubspot_signature_v3 |
| `salesforce` | Salesforce | crm | high | available | analytics, marketing | contract | field_allowlist_only | provider_native_or_oauth_pull |
| `klaviyo` | Klaviyo | marketing | medium | available | marketing | consent | prohibit_recipient_email | klaviyo_native_or_oauth_pull |
| `sendgrid` | SendGrid | marketing | medium | available | marketing | consent | field_allowlist_only | sendgrid_ecdsa |
| `customerio` | Customer.io | marketing | medium | available | marketing | consent | field_allowlist_only | customerio_hmac_v0 |
| `mailchimp` | Mailchimp | marketing | medium | available | marketing | consent | field_allowlist_only | endpoint_secret |
| `postmark` | Postmark | marketing | medium | available | marketing | consent | field_allowlist_only | endpoint_secret |
| `segment` | Segment | event_router | high | available | analytics, marketing, personalization | classification_required | unknown_properties_quarantine | segment_signature_or_writekey |
| `posthog` | PostHog | product_analytics | high | available | analytics, personalization | legitimate_interest | quarantine_arbitrary_person_properties | posthog_webhook_signature |
| `ga4` | Google Analytics 4 | analytics | medium | available | analytics, marketing | aggregate_analytics | aggregate_preferred_user_level_gated | google_oauth_or_signed_export |
| `jira` | Jira | workspace_operations | high | available | analytics | contract | field_controls_required | jira_webhook_signature |
| `linear` | Linear | workspace_operations | high | available | analytics | contract | field_controls_required | linear_hmac_sha256 |
| `zendesk` | Zendesk | support | high | available | analytics, marketing | contract | sensitive_text_controls_required | zendesk_signature |
| `intercom` | Intercom | support | high | available | analytics, marketing | contract | sensitive_text_controls_required | intercom_signature |
| `dune` | Dune | public_reference_data | high | available | economic_observability, web3 | public_reference | no_raw_row_promotion_without_contract | dune_oauth_or_api_key_pull |
| `apple_pay` | Apple Pay | native_payment_adapter | medium | contract_only | commerce | contract | reject_pkpayment_tokens_contacts | not_applicable_typed_sdk_api |
| `google_pay` | Google Pay | native_payment_adapter | medium | contract_only | commerce | contract | reject_paymentdata_tokens_contacts | not_applicable_typed_sdk_api |
| `outbound_activation` | Outbound Providers | activation | high | contract_only | marketing, commerce, analytics | dispatch_time_decision_required | payload_allowlist_only | provider_native_dispatch_auth |
