"""Slice-1 foundation contract tests for the 8.12.0 first release.

Covers:
- `ai_invocation_observed` canonical registration (Python registry, TS
  EventType, the generated web consent map, and the hand-maintained native
  SDK consent maps).
- New shared contract files exist and export their key types.
- New feature-flag settings sections exist and default OFF.
"""

from __future__ import annotations

import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _read(rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# ai_invocation_observed registration
# ---------------------------------------------------------------------------

class TestAIInvocationObservedRegistration:
    def test_python_registry_contains_event(self):
        from services.ingestion.generated_registry import (
            CANONICAL_EVENT_TYPES,
            EVENT_CONSENT_PURPOSE,
            EVENT_FAMILY,
        )

        assert "ai_invocation_observed" in CANONICAL_EVENT_TYPES
        assert EVENT_FAMILY["ai_invocation_observed"] == "agent"
        assert EVENT_CONSENT_PURPOSE["ai_invocation_observed"] == "agent"

    def test_registry_json_entry_shape(self):
        import json

        registry = json.loads(_read("packages/shared/contracts/event-registry.json"))
        entries = [e for e in registry["events"] if e["type"] == "ai_invocation_observed"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["family"] == "agent"
        assert entry["requiredPurposes"] == ["agent"]
        assert entry["privacyClass"] == "behavioral"
        assert entry["retentionClass"] == "standard_90d"
        assert entry["silverProjection"] == "ai_execution_facts"
        assert entry["graphProjection"] == "USED_MODEL"
        assert entry["status"] == "active"
        assert entry["introducedVersion"] == "8.12.0"

    def test_events_ts_contains_event_type(self):
        events_ts = _read("packages/shared/events.ts")
        event_type_block = events_ts.split("export type EventFamily")[0]
        assert "'ai_invocation_observed'" in event_type_block

    def test_sdk_consent_maps_contain_event(self):
        # The web consent map is registry-derived and lives in the generated file
        # (moved out of event-queue.ts); generated keys are JSON-quoted.
        web = _read("packages/web/src/core/generated-consent-map.ts")
        assert re.search(r'"ai_invocation_observed":\s*"agent"', web)

        android = _read("packages/android/src/main/java/com/aether/sdk/Aether.kt")
        assert '"ai_invocation_observed" to "agent"' in android

        ios = _read("packages/ios/Sources/AetherSDK/Aether.swift")
        assert "case ai_invocation_observed" in ios
        assert '.ai_invocation_observed: "agent"' in ios


# ---------------------------------------------------------------------------
# Shared contract files
# ---------------------------------------------------------------------------

class TestSharedContractFiles:
    def test_agent_deployment_contract_exports(self):
        body = _read("packages/shared/agent-deployment.ts")
        for needle in (
            "export type ExternalPlatform",
            "export interface AgentDeploymentContext",
            "export interface AgentDeployment",
            "'custom_marketplace'",
            "'mcp_server'",
        ):
            assert needle in body, needle
        # 14 external platforms per contract
        platforms = re.search(r"externalPlatforms = \[(.*?)\]", body, re.S)
        assert platforms and len(re.findall(r"'[a-z_]+'", platforms.group(1))) == 14

    def test_ai_execution_contract_exports(self):
        body = _read("packages/shared/ai-execution.ts")
        for needle in (
            "export interface AIInvocationObserved",
            "export interface AIExecutionFact",
            "export type CostBasis",
            "export interface AIWorkflowEconomics",
            "export interface AIPriceCard",
            "'ai_outcome_efficiency'",
        ):
            assert needle in body, needle
        # No raw content fields — only the boolean contains_* flags
        assert "prompt_text" not in body
        assert "completion_text" not in body

    def test_payment_rails_contract_exports(self):
        body = _read("packages/shared/payment-rails.ts")
        for needle in (
            "export interface FundingSession",
            "export interface ReconciliationRecord",
            "export interface PaymentRailHealth",
            "export interface PaymentRailStatusMap",
            "export interface VirtualAccount",
            "export interface DepositAddress",
        ):
            assert needle in body, needle
        providers = re.search(r"paymentRailProviders = \[(.*?)\]", body, re.S)
        assert providers is not None
        names = set(re.findall(r"'([a-z_]+)'", providers.group(1)))
        assert names == {"privy", "stripe", "coinbase", "moonpay", "bridge"}

    def test_targeting_intelligence_contract_exports(self):
        body = _read("packages/shared/targeting-intelligence.ts")
        for needle in (
            "export interface TargetingIntent",
            "export interface TargetingEligibilitySnapshot",
            "export interface TargetingObservation",
            "export interface ExclusionLeakageFinding",
            "export interface TargetingHoldout",
            "export interface ClusterJourneyDelta",
            "export interface TargetingOutcomeSnapshot",
            "export interface ClusterTargetingImpact",
            "export interface TargetingRecommendationExportPackage",
            "executionByAether: false",
            "externalExecutionRequired: true",
        ):
            assert needle in body, needle

    def test_contracts_exported_from_barrel(self):
        index = _read("packages/shared/index.ts")
        for module in (
            "./agent-deployment",
            "./ai-execution",
            "./payment-rails",
            "./targeting-intelligence",
        ):
            assert f"export * from '{module}';" in index, module


# ---------------------------------------------------------------------------
# Feature flags — default OFF
# ---------------------------------------------------------------------------

class TestFirstReleaseFlagsDefaultOff:
    def test_external_agent_telemetry_defaults(self):
        from config.settings import ExternalAgentTelemetryConfig

        cfg = ExternalAgentTelemetryConfig()
        assert cfg.enabled is False
        assert cfg.kyber_enabled is False
        assert cfg.registry_enabled is False
        assert cfg.sdk_enabled is False
        assert cfg.graph_enabled is False
        assert cfg.profile360_enabled is False

    def test_payment_rails_defaults(self):
        from config.settings import PaymentRailsConfig

        cfg = PaymentRailsConfig()
        assert cfg.enabled is False
        assert cfg.privy_enabled is False
        assert cfg.stripe_enabled is False
        assert cfg.coinbase_enabled is False
        assert cfg.moonpay_enabled is False
        assert cfg.bridge_enabled is False
        assert cfg.kyber_enabled is False

    def test_ai_economics_defaults(self):
        from config.settings import AIEconomicsConfig

        cfg = AIEconomicsConfig()
        assert cfg.enabled is False
        assert cfg.execution_facts_enabled is False
        assert cfg.economics_enabled is False
        assert cfg.recommendations_enabled is False
        assert cfg.kyber_enabled is False

    def test_targeting_intelligence_defaults(self):
        from config.settings import TargetingIntelligenceConfig

        cfg = TargetingIntelligenceConfig()
        assert cfg.enabled is False
        assert cfg.exports_enabled is False
        assert cfg.ooda_suggestions_enabled is False
        assert cfg.kyber_enabled is False

    def test_one_person_ops_defaults(self):
        from config.settings import OnePersonOpsConfig

        cfg = OnePersonOpsConfig()
        assert cfg.runtime_durable_enabled is False
        assert cfg.worker_bridge_enabled is False
        assert cfg.staged_mutation_review_enabled is False
        assert cfg.catalyst_cycle_enabled is False
        assert cfg.command_center_enabled is False
        assert cfg.one_person_ops_enabled is False

    def test_settings_singleton_carries_new_sections(self):
        from config.settings import settings

        assert hasattr(settings, "external_agent_telemetry")
        assert hasattr(settings, "payment_rails")
        assert hasattr(settings, "ai_economics")
        assert hasattr(settings, "targeting_intelligence")
        assert hasattr(settings, "one_person_ops")

    def test_env_example_documents_all_flags(self):
        env_example = _read(".env.example")
        for flag in (
            "AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED",
            "KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED",
            "AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED",
            "AETHER_AGENT_TELEMETRY_SDK_ENABLED",
            "AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED",
            "AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED",
            "AETHER_PAYMENT_RAILS_ENABLED",
            "AETHER_PROVIDER_PRIVY_ENABLED",
            "AETHER_PROVIDER_STRIPE_ENABLED",
            "AETHER_PROVIDER_COINBASE_ENABLED",
            "AETHER_PROVIDER_MOONPAY_ENABLED",
            "AETHER_PROVIDER_BRIDGE_ENABLED",
            "KYBER_PAYMENT_RAILS_ENABLED",
            "AETHER_AI_OUTCOME_EFFICIENCY_ENABLED",
            "AETHER_AI_EXECUTION_FACTS_ENABLED",
            "AETHER_AI_ECONOMICS_ENABLED",
            "AETHER_AI_EFFICIENCY_RECOMMENDATIONS_ENABLED",
            "KYBER_AI_EFFICIENCY_HEALTH_ENABLED",
            "AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED",
            "AETHER_TARGETING_EXPORTS_ENABLED",
            "AETHER_TARGETING_OODA_SUGGESTIONS_ENABLED",
            "KYBER_TARGETING_INTELLIGENCE_ENABLED",
            "AETHER_AGENT_RUNTIME_DURABLE_ENABLED",
            "AETHER_AGENT_WORKER_BRIDGE_ENABLED",
            "AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED",
            "AETHER_CATALYST_CYCLE_AUTOMATION_ENABLED",
            "KYBER_AGENT_COMMAND_CENTER_ENABLED",
            "KYBER_ONE_PERSON_OPS_ENABLED",
        ):
            assert re.search(rf"^{flag}=false", env_example, re.M), flag

    def test_untouched_future_marketplace_flags(self):
        """The marketplace/partner flags remain future-flagged and OFF."""
        env_example = _read(".env.example")
        for flag in (
            "AETHER_PARTNER_ECOSYSTEM_ENABLED",
            "AETHER_MARKETPLACE_ENABLED",
            "AETHER_DEVELOPER_PLATFORM_ENABLED",
            "KYBER_PARTNER_ECOSYSTEM_ENABLED",
        ):
            assert re.search(rf"^{flag}=false", env_example, re.M), flag
