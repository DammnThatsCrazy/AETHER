// DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json
// Run: python scripts/generate_contracts.py
package com.aether.sdk

const val INTEGRATION_CONSENT_REGISTRY_VERSION: String = "8.13.0"

enum class IntegrationConnectorType(val connectorType: String) {
    SLACK("slack"),
    GENERIC_WEBHOOK("generic_webhook"),
    SHOPIFY("shopify"),
    STRIPE("stripe"),
    HUBSPOT("hubspot"),
    SALESFORCE("salesforce"),
    KLAVIYO("klaviyo"),
    SENDGRID("sendgrid"),
    CUSTOMERIO("customerio"),
    MAILCHIMP("mailchimp"),
    POSTMARK("postmark"),
    SEGMENT("segment"),
    POSTHOG("posthog"),
    GA4("ga4"),
    JIRA("jira"),
    LINEAR("linear"),
    ZENDESK("zendesk"),
    INTERCOM("intercom"),
    DUNE("dune"),
    APPLE_PAY("apple_pay"),
    GOOGLE_PAY("google_pay"),
    OUTBOUND_ACTIVATION("outbound_activation")
}

data class ProcessingDecision(
    val decisionId: String,
    val tenantId: String,
    val connectorType: String? = null,
    val sourceKind: String,
    val subjectId: String? = null,
    val anonymousId: String? = null,
    val purpose: String? = null,
    val processingBasis: String? = null,
    val allowed: Boolean,
    val reasonCode: String? = null,
    val identityLinkingAllowed: Boolean,
    val graphProjectionAllowed: Boolean,
    val modelTrainingAllowed: Boolean,
    val activationAllowed: Boolean,
    val retentionClass: String,
    val quarantineRequired: Boolean,
    val policyVersion: String,
    val consentReceiptId: String? = null,
    val evaluatedAt: String,
)
