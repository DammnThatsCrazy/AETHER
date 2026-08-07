// DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json
// Run: python scripts/generate_contracts.py
import Foundation

public let integrationConsentRegistryVersion = "8.13.0"

public enum IntegrationConnectorType: String, CaseIterable {
    case slack = "slack"
    case genericwebhook = "generic_webhook"
    case shopify = "shopify"
    case stripe = "stripe"
    case hubspot = "hubspot"
    case salesforce = "salesforce"
    case klaviyo = "klaviyo"
    case sendgrid = "sendgrid"
    case customerio = "customerio"
    case mailchimp = "mailchimp"
    case postmark = "postmark"
    case iterable = "iterable"
    case segment = "segment"
    case posthog = "posthog"
    case ga4 = "ga4"
    case jira = "jira"
    case linear = "linear"
    case zendesk = "zendesk"
    case intercom = "intercom"
    case dune = "dune"
    case applepay = "apple_pay"
    case googlepay = "google_pay"
    case outboundactivation = "outbound_activation"
}

public struct ProcessingDecision: Codable, Equatable {
    public let decisionId: String
    public let tenantId: String
    public let connectorType: String?
    public let sourceKind: String
    public let subjectId: String?
    public let anonymousId: String?
    public let purpose: String?
    public let processingBasis: String?
    public let allowed: Bool
    public let reasonCode: String?
    public let identityLinkingAllowed: Bool
    public let graphProjectionAllowed: Bool
    public let modelTrainingAllowed: Bool
    public let activationAllowed: Bool
    public let retentionClass: String
    public let quarantineRequired: Bool
    public let policyVersion: String
    public let consentReceiptId: String?
    public let evaluatedAt: String
}
