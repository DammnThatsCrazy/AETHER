import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "packages" / "shared" / "contracts" / "integration-consent-registry.json"
TS = ROOT / "packages" / "shared" / "integration-consent.ts"
PY_GEN = ROOT / "Backend Architecture" / "aether-backend" / "shared" / "privacy" / "generated_integration_consent.py"
SWIFT = ROOT / "packages" / "ios" / "Sources" / "AetherSDK" / "GeneratedIntegrationConsent.swift"
KOTLIN = ROOT / "packages" / "android" / "src" / "main" / "java" / "com" / "aether" / "sdk" / "GeneratedIntegrationConsent.kt"

EXPECTED = {
    "slack", "generic_webhook", "shopify", "stripe", "hubspot", "salesforce",
    "klaviyo", "sendgrid", "customerio", "mailchimp", "postmark",
    "segment", "posthog", "ga4", "jira", "linear", "zendesk",
    "intercom", "dune", "apple_pay", "google_pay", "outbound_activation",
}
REQUIRED_FIELDS = {
    "connectorType", "connectorClass", "provider", "category", "dataFlowDirection",
    "riskTier", "implementationStatus", "supportedCapabilities", "requiredTenantPermissions",
    "requiresProviderAdminInstall", "requiresTenantAdminApproval", "requiredSubjectPurposes",
    "supportedProcessingBases", "defaultProcessingBasis", "dataCategories", "identitySignals",
    "allowsIdentityLinking", "allowsGraphProjection", "allowsModelTraining",
    "allowsPreConsentProcessing", "complianceEvidenceEvents", "suppressionEvents",
    "retentionClass", "rawPayloadPolicy", "quarantinePolicy", "providerConsentBridge",
    "providerSignatureScheme", "supportsHistoricalBackfill", "supportsOutboundActivation",
}


def _registry():
    return json.loads(REGISTRY.read_text())


def test_every_connector_and_adapter_has_explicit_governance_policy():
    connectors = _registry()["connectors"]
    by_type = {entry["connectorType"]: entry for entry in connectors}
    assert set(by_type) == EXPECTED
    for connector_type, entry in by_type.items():
        assert REQUIRED_FIELDS <= set(entry), connector_type
        assert entry["retentionClass"], connector_type
        assert entry["rawPayloadPolicy"], connector_type
        assert entry["quarantinePolicy"], connector_type
        assert entry["defaultProcessingBasis"], connector_type
        assert isinstance(entry["allowsModelTraining"], bool), connector_type


def test_high_risk_and_webhook_entries_fail_closed():
    by_type = {entry["connectorType"]: entry for entry in _registry()["connectors"]}
    assert by_type["generic_webhook"]["quarantinePolicy"] == "unknown_schema_quarantine_only"
    assert by_type["generic_webhook"]["allowsIdentityLinking"] is False
    assert by_type["generic_webhook"]["allowsGraphProjection"] is False
    assert by_type["generic_webhook"]["allowsModelTraining"] is False
    assert by_type["shopify"]["providerSignatureScheme"] == "shopify_hmac_sha256"
    assert by_type["stripe"]["providerSignatureScheme"] == "stripe_v1"
    assert by_type["klaviyo"]["providerConsentBridge"] == "optional_provider_bridge"


def test_generated_platform_surfaces_include_decision_contract_and_flags():
    for path in (TS, PY_GEN, SWIFT, KOTLIN):
        source = path.read_text()
        assert "ProcessingDecision" in source
        assert "AETHER_CONSENT_CONTROL_PLANE" in source or path in (SWIFT, KOTLIN)
    ts_source = TS.read_text()
    for connector_type in EXPECTED:
        assert connector_type in ts_source
