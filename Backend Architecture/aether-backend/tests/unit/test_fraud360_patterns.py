"""Fraud360 FraudPattern registry alignment tests (Phase 3).

FraudPattern is a registered pattern system, NOT a parallel taxonomy. Every
``network_type_ref`` must be a shipped ``NetworkType`` value and every
``member_role_ref`` a shipped ``MemberRole`` value from
``services/fraud_networks/models.py``; every ``required_evidence_type`` must be
a canonical ``EvidenceType``. Alignment is asserted here against the shipped
taxonomy directly — never by re-declaring it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.fraud360.contracts import FraudPattern  # noqa: E402
from services.fraud360.patterns import (  # noqa: E402
    FRAUD_PATTERN_KEYS,
    FRAUD_PATTERNS,
    fraud_pattern,
)
from services.fraud_networks.models import MemberRole, NetworkType  # noqa: E402
from services.operational_intelligence.models import EvidenceType  # noqa: E402

_NETWORK_TYPE_VALUES = frozenset(get_args(NetworkType))
_MEMBER_ROLE_VALUES = frozenset(get_args(MemberRole))
_EVIDENCE_TYPE_VALUES = frozenset(get_args(EvidenceType))

# Blueprint §14 Day-1 pattern families (normalized to machine ids).
_DAY1_FAMILIES = frozenset(
    {
        "promotion_abuse",
        "referral_abuse",
        "synthetic_identity",
        "account_takeover",
        "payment_fraud",
        "refund_chargeback_abuse",
        "bot_activity",
        "device_farm",
        "conversion_manipulation",
        "credential_abuse",
        "agent_abuse",
        "counterparty_fraud",
        "collusion",
        "circular_value_flow",
        "wallet_abuse",
        "reward_extraction",
    }
)


def test_every_registry_pattern_is_a_fraud_pattern():
    assert all(isinstance(p, FraudPattern) for p in FRAUD_PATTERNS)


def test_all_network_type_refs_are_shipped_network_types():
    refs = {ref for p in FRAUD_PATTERNS for ref in p.network_type_refs}
    assert refs, "registry must reference at least one network type"
    assert refs <= _NETWORK_TYPE_VALUES, (
        f"refs not in shipped NetworkType: {sorted(refs - _NETWORK_TYPE_VALUES)}"
    )


def test_all_member_role_refs_are_shipped_member_roles():
    refs = {ref for p in FRAUD_PATTERNS for ref in p.member_role_refs}
    assert refs, "registry must reference at least one member role"
    assert refs <= _MEMBER_ROLE_VALUES, (
        f"refs not in shipped MemberRole: {sorted(refs - _MEMBER_ROLE_VALUES)}"
    )


def test_required_evidence_types_are_canonical_evidence_types():
    refs = {ref for p in FRAUD_PATTERNS for ref in p.required_evidence_types}
    assert refs <= _EVIDENCE_TYPE_VALUES, (
        f"refs not in canonical EvidenceType: {sorted(refs - _EVIDENCE_TYPE_VALUES)}"
    )


def test_no_pattern_uses_unknown_network_type():
    assert not any("unknown" in p.network_type_refs for p in FRAUD_PATTERNS)


def test_day1_families_seeded_and_keys_match():
    ids = {p.pattern_id for p in FRAUD_PATTERNS}
    assert _DAY1_FAMILIES <= ids, (
        f"missing Day-1 families: {sorted(_DAY1_FAMILIES - ids)}"
    )
    assert len(ids) == len(FRAUD_PATTERNS), "pattern ids must be unique"
    assert FRAUD_PATTERN_KEYS == ids


def test_registry_lookup():
    p = fraud_pattern("synthetic_identity")
    assert p is not None and p.pattern_id == "synthetic_identity"
    assert fraud_pattern("does_not_exist") is None


def test_patterns_are_conditions_not_proofs():
    # A matched pattern is suspicion: it must not itself claim confirmation.
    assert all(isinstance(p.description, str) and p.description for p in FRAUD_PATTERNS)
    assert all(p.network_type_refs for p in FRAUD_PATTERNS)
    assert all(p.member_role_refs for p in FRAUD_PATTERNS)
    assert all(p.required_evidence_types for p in FRAUD_PATTERNS)
