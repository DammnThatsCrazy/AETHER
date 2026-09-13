"""Unit tests: connector taxonomy enums and descriptor validation."""
from __future__ import annotations

import pytest

from services.integrations.connectors.base import (
    ConnectorClass,
    ConnectorRole,
    DataFlowDirection,
    GraphWritePolicy,
    ImplementationStatus,
    LakeWritePolicy,
    ModelTrainingEligibility,
    PriorityPhase,
    RiskTier,
)


def test_connector_class_values():
    assert ConnectorClass.OLYMPUS_PROVIDER.value == "olympus_provider"
    assert ConnectorClass.TENANT_BYOD_DATA.value == "tenant_byod_data"
    assert ConnectorClass.BYOK_GATEWAY.value == "byok_gateway"
    assert ConnectorClass.ACTION_NOTIFIER.value == "action_notifier"
    assert ConnectorClass.DUAL_ROLE.value == "dual_role"
    assert len(list(ConnectorClass)) == 5


def test_lake_write_policy_values():
    assert LakeWritePolicy.NEVER.value == "never"
    assert LakeWritePolicy.TENANT_ONLY.value == "tenant_only"
    assert LakeWritePolicy.OLYMPUS_BASELINE_ELIGIBLE.value == "olympus_baseline_eligible"
    assert LakeWritePolicy.OLYMPUS_BASELINE_ALLOWED.value == "olympus_baseline_allowed"
    assert LakeWritePolicy.QUARANTINE_ONLY.value == "quarantine_only"


def test_graph_write_policy_values():
    assert GraphWritePolicy.NONE.value == "none"
    assert GraphWritePolicy.TENANT_GRAPH_ONLY.value == "tenant_graph_only"
    assert GraphWritePolicy.OLYMPUS_GRAPH_ALLOWED.value == "olympus_graph_allowed"


def test_model_training_eligibility_values():
    assert ModelTrainingEligibility.NEVER.value == "never"
    assert ModelTrainingEligibility.COMPLIANCE_REVIEW_REQUIRED.value == "compliance_review_required"
    assert ModelTrainingEligibility.OLYMPUS_ALLOWED.value == "olympus_allowed"


def test_implementation_status_values():
    statuses = {s.value for s in ImplementationStatus}
    assert "scaffolded" in statuses
    assert "credential_gated" in statuses
    assert "disabled_compliance_review" in statuses
    assert "provider_live" in statuses
    assert "warehouse_datashare_ready" in statuses


def test_priority_phase_values():
    assert PriorityPhase.PHASE_1_FOUNDATION.value == "phase_1_foundation"
    assert PriorityPhase.PHASE_2_ENRICHMENT.value == "phase_2_enrichment"
    assert PriorityPhase.PHASE_3_DEPTH.value == "phase_3_depth"
    assert PriorityPhase.NOT_SCHEDULED.value == "not_scheduled"


def test_risk_tier_values():
    assert RiskTier.LOW.value == "low"
    assert RiskTier.MEDIUM.value == "medium"
    assert RiskTier.HIGH.value == "high"
    assert RiskTier.RESTRICTED.value == "restricted"


def test_connector_role_has_warehouse_and_query():
    roles = {r.value for r in ConnectorRole}
    assert "warehouse_datashare" in roles
    assert "query_execution" in roles
    assert "realtime_stream" in roles
    assert "batch_backfill" in roles
    assert "action_delivery" in roles


def test_data_flow_direction():
    assert DataFlowDirection.INBOUND.value == "inbound"
    assert DataFlowDirection.OUTBOUND.value == "outbound"
    assert DataFlowDirection.BIDIRECTIONAL.value == "bidirectional"
