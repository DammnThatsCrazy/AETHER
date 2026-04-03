"""
Dedicated unit tests for v8.7.0 services:
  - Web3 Coverage (registries, classification, models)
  - Cross-Domain TradFi/Web2 (registries, models)
  - Privacy Control Plane (classification, access control, retention, consent)
  - Profile Resolver tenant isolation
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

os.environ["AETHER_ENV"] = "local"

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for prefix in ("config", "services", "shared", "repositories", "middleware", "dependencies"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ("config", "services", "shared", "repositories", "middleware", "dependencies"):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


# ═══════════════════════════════════════════════════════════════════════════
# WEB3 COVERAGE — MODELS & CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

class TestWeb3Models:
    def test_completeness_status_values(self):
        with backend_path():
            from services.web3.models import CompletenessStatus
            assert CompletenessStatus.RAW_OBSERVED == "raw_observed"
            assert CompletenessStatus.HIGH_CONFIDENCE == "high_confidence"

    def test_canonical_action_families(self):
        with backend_path():
            from services.web3.models import CanonicalAction
            actions = {a.value for a in CanonicalAction}
            for required in ["transfer", "swap", "lend", "borrow", "stake", "bridge", "vote"]:
                assert required in actions, f"Missing: {required}"

    def test_provenance_model(self):
        with backend_path():
            from services.web3.models import Provenance
            p = Provenance(source="dune", chain="ethereum")
            assert p.source == "dune"
            assert 0.0 <= p.classification_confidence <= 1.0

    def test_chain_create(self):
        with backend_path():
            from services.web3.models import ChainCreate, VMFamily
            c = ChainCreate(chain_id="ethereum", canonical_name="Ethereum", vm_family=VMFamily.EVM, evm_chain_id=1)
            assert c.chain_id == "ethereum"


class TestWeb3Classifier:
    def test_known_selectors(self):
        with backend_path():
            from services.web3.classifier import classify_method_selector
            assert classify_method_selector("0xa9059cbb") == "transfer"
            assert classify_method_selector("0x38ed1739") == "swap"
            assert classify_method_selector("0xe8eda9df") == "lend"

    def test_unknown_selector(self):
        with backend_path():
            from services.web3.classifier import classify_method_selector
            assert classify_method_selector("0xdeadbeef") == "unknown"


class TestWeb3Seed:
    def test_chain_seed_count(self):
        with backend_path():
            from services.web3.seed import CHAIN_SEED
            assert len(CHAIN_SEED) >= 30

    def test_protocol_seed_unique_ids(self):
        with backend_path():
            from services.web3.seed import PROTOCOL_SEED
            ids = [p["protocol_id"] for p in PROTOCOL_SEED]
            assert len(ids) == len(set(ids)), "Duplicate protocol_id"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-DOMAIN — MODELS
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossDomainModels:
    def test_entity_types(self):
        with backend_path():
            from services.crossdomain.models import EntityType
            assert EntityType.PERSON == "person"
            assert EntityType.INSTITUTION == "institution"

    def test_ownership_roles(self):
        with backend_path():
            from services.crossdomain.models import OwnershipRole
            assert OwnershipRole.LEGAL_OWNER == "legal_owner"
            assert OwnershipRole.BENEFICIAL_OWNER == "beneficial_owner"

    def test_order_lifecycle(self):
        with backend_path():
            from services.crossdomain.models import OrderStatus
            statuses = {s.value for s in OrderStatus}
            for required in ["pending", "submitted", "filled", "cancelled", "rejected"]:
                assert required in statuses


# ═══════════════════════════════════════════════════════════════════════════
# PRIVACY — CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestDataClassification:
    def test_classification_tiers(self):
        with backend_path():
            from shared.privacy.classification import DataClassification
            assert len(DataClassification) == 7

    def test_field_classifications(self):
        with backend_path():
            from shared.privacy.classification import DataClassification, classify_field
            assert classify_field("email") == DataClassification.SENSITIVE_PII
            assert classify_field("ssn") == DataClassification.HIGHLY_SENSITIVE
            assert classify_field("balance") == DataClassification.FINANCIAL
            assert classify_field("kyc_status") == DataClassification.REGULATED
            assert classify_field("unknown_field") == DataClassification.INTERNAL

    def test_sensitive_pii_rules(self):
        with backend_path():
            from shared.privacy.classification import DataClassification, get_rules
            rules = get_rules(DataClassification.SENSITIVE_PII)
            assert rules.requires_consent is True
            assert rules.log_redaction_required is True

    def test_highly_sensitive_rules(self):
        with backend_path():
            from shared.privacy.classification import DataClassification, get_rules
            rules = get_rules(DataClassification.HIGHLY_SENSITIVE)
            assert rules.exportable is False
            assert rules.graph_traversal_allowed is False


# ═══════════════════════════════════════════════════════════════════════════
# PRIVACY — ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════════

class TestAccessControl:
    def test_role_hierarchy(self):
        with backend_path():
            from shared.privacy.access_control import ROLE_HIERARCHY
            assert ROLE_HIERARCHY["viewer"] < ROLE_HIERARCHY["admin"]

    def test_viewer_denied_regulated(self):
        with backend_path():
            from shared.privacy.access_control import AccessLevel, get_field_access_level
            access = get_field_access_level("kyc_status", role="viewer")
            assert access == AccessLevel.DENIED

    def test_compliance_sees_regulated(self):
        with backend_path():
            from shared.privacy.access_control import AccessLevel, get_field_access_level
            access = get_field_access_level("kyc_status", role="compliance", purpose="compliance")
            assert access == AccessLevel.FULL

    def test_pii_denied_without_consent(self):
        with backend_path():
            from shared.privacy.access_control import AccessLevel, get_field_access_level
            access = get_field_access_level("email", role="editor", consent_granted=False)
            assert access == AccessLevel.DENIED

    def test_inferred_edges_never_exportable(self):
        with backend_path():
            from shared.privacy.access_control import can_traverse_edge
            assert can_traverse_edge("X", role="admin", purpose="export", is_inferred=True) is False
            assert can_traverse_edge("X", role="admin", purpose="training", is_inferred=True) is False

    def test_training_eligibility(self):
        with backend_path():
            from shared.privacy.access_control import can_use_for_training
            from shared.privacy.classification import DataClassification
            assert can_use_for_training(DataClassification.PUBLIC) is True
            assert can_use_for_training(DataClassification.REGULATED) is False

    def test_log_redaction(self):
        with backend_path():
            from shared.privacy.access_control import redact_for_logging
            data = {"email": "secret@test.com", "name": "John", "session_id": "abc"}
            redacted = redact_for_logging(data)
            assert redacted["email"] == "[REDACTED]"
            assert redacted["name"] == "[REDACTED]"


# ═══════════════════════════════════════════════════════════════════════════
# PRIVACY — RETENTION & DELETION
# ═══════════════════════════════════════════════════════════════════════════

class TestRetention:
    def test_pseudonymize_deterministic(self):
        with backend_path():
            from shared.privacy.retention import pseudonymize_value
            a = pseudonymize_value("john@test.com", salt="t1")
            b = pseudonymize_value("john@test.com", salt="t1")
            c = pseudonymize_value("john@test.com", salt="t2")
            assert a == b
            assert a != c
            assert a.startswith("PSEUDO_")

    def test_deletion_plan_standard(self):
        with backend_path():
            from shared.privacy.retention import DeletionPlan
            plan = DeletionPlan("user123", "tenant1")
            plan.build_standard_plan()
            assert len(plan.steps) > 10
            immutable = [s for s in plan.steps if s["behavior"] == "immutable"]
            assert len(immutable) >= 3

    def test_dsar_types(self):
        with backend_path():
            from shared.privacy.retention import DSARRequest
            dsr = DSARRequest("erasure", "u1", "t1")
            assert dsr.sla_days == 30
            with pytest.raises(ValueError):
                DSARRequest("invalid", "u1", "t1")


# ═══════════════════════════════════════════════════════════════════════════
# CONSENT ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════

class TestConsentEnforcement:
    def test_consent_required_purposes(self):
        with backend_path():
            from shared.privacy.consent_enforcement import is_consent_required_purpose
            assert is_consent_required_purpose("marketing") is True
            assert is_consent_required_purpose("analytics") is False


# ═══════════════════════════════════════════════════════════════════════════
# PROFILE RESOLVER — TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileResolverTenantIsolation:
    def test_resolve_rejects_empty_tenant(self):
        with backend_path():
            from services.profile.resolver import ProfileResolver
            from shared.cache.cache import CacheClient
            from shared.graph.graph import GraphClient
            resolver = ProfileResolver(GraphClient(), CacheClient())
            with pytest.raises(ValueError, match="tenant_id is required"):
                asyncio.run(
                    resolver.resolve(tenant_id="", wallet_address="0xabc")
                )

    def test_get_identifiers_rejects_empty_tenant(self):
        with backend_path():
            from services.profile.resolver import ProfileResolver
            from shared.cache.cache import CacheClient
            from shared.graph.graph import GraphClient
            resolver = ProfileResolver(GraphClient(), CacheClient())
            with pytest.raises(ValueError, match="tenant_id is required"):
                asyncio.run(
                    resolver.get_all_identifiers("user1", tenant_id="")
                )


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH — VERTEX / EDGE TYPE EXISTENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestGraphExpansion:
    def test_web3_vertices(self):
        with backend_path():
            from shared.graph.graph import VertexType
            for v in ["CHAIN", "TOKEN", "APP", "FRONTEND_DOMAIN", "UNKNOWN_CONTRACT"]:
                assert hasattr(VertexType, v), f"Missing vertex: {v}"

    def test_crossdomain_vertices(self):
        with backend_path():
            from shared.graph.graph import VertexType
            for v in ["INSTITUTION", "FINANCIAL_ACCOUNT", "INSTRUMENT", "ORDER", "EXECUTION"]:
                assert hasattr(VertexType, v), f"Missing vertex: {v}"

    def test_crossdomain_edges(self):
        with backend_path():
            from shared.graph.graph import EdgeType
            for e in ["OWNS_ACCOUNT", "HOLDS_POSITION", "PLACED_ORDER", "OVERLAPS_WITH"]:
                assert hasattr(EdgeType, e), f"Missing edge: {e}"
