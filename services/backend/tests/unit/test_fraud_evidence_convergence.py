"""Fraud EvidenceRef convergence + legacy-compat loader tests (Phase 2).

The fraud package previously declared a divergent, fraud-local ``EvidenceRef``
(``ref_id``/``ref_type``/``ref_source``/``description``/``metadata``). It now
uses the canonical ``services.operational_intelligence.models.EvidenceRef``
(``id``/``type``/``source``/``observedAt``/``confidence``/``uri``). Because
``FraudDecision.evidence_refs`` is persisted JSONB, pre-convergence rows may
hold the old shape; ``services/fraud/evidence.py`` provides the one-way legacy
compat loader exercised here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.fraud import models as fraud_models  # noqa: E402
from services.fraud.evidence import (  # noqa: E402
    LEGACY_REF_TYPE_TO_EVIDENCE_TYPE,
    SIGNAL_TO_EVIDENCE_TYPE,
    normalize_persisted_evidence_refs,
)
from services.fraud.models import (  # noqa: E402
    FraudDecision,
    FraudDecisionCreateRequest,
)
from services.operational_intelligence.models import (  # noqa: E402
    EvidenceRef,
    EvidenceType,
)


def _canonical_evidence_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "ev-1",
        "type": "transaction",
        "source": "fraud_evaluator",
    }
    base.update(overrides)
    return base


def _decision_kwargs() -> dict[str, object]:
    return {
        "decision_id": "dec-1",
        "tenant_id": "tenant-a",
        "subject_type": "entity",
        "subject_id": "ent-1",
        "decision": "review",
        "risk_score": 55.0,
        "risk_tier": "high",
        "evaluated_at": "2026-01-01T00:00:00Z",
        "valid_from": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_fraud_models_now_reexport_canonical_evidence_ref():
    """No fraud-local EvidenceRef remains — the name resolves to the canonical one."""
    from services.operational_intelligence.models import EvidenceRef as Canonical

    assert fraud_models.EvidenceRef is Canonical


def test_fraud_decision_dumps_canonical_shape():
    decision = FraudDecision(
        **_decision_kwargs(),
        evidence_refs=[
            EvidenceRef(id="ev-1", type="model_output", source="fraud_evaluator"),
            EvidenceRef(
                id="ev-2",
                type="relationship",
                source="fraud_evaluator",
                uri="aether://fraud/decision/evidence",
            ),
        ],
    )
    dumped = decision.model_dump()
    refs = dumped["evidence_refs"]
    assert [r["id"] for r in refs] == ["ev-1", "ev-2"]
    for ref in refs:
        assert {"id", "type", "source"}.issubset(ref.keys())
        # Old fraud-local keys must not be written by new code.
        assert not {"ref_id", "ref_type", "ref_source", "description", "metadata"}.intersection(
            ref.keys()
        )


def test_fraud_decision_create_request_accepts_canonical_evidence_refs():
    request = FraudDecisionCreateRequest(
        tenant_id="tenant-a",
        subject_type="entity",
        subject_id="ent-1",
        decision="monitor",
        risk_score=30.0,
        risk_tier="medium",
        evidence_refs=[EvidenceRef(id="ev-9", type="transaction", source="fraud_evaluator")],
    )
    assert request.evidence_refs[0].id == "ev-9"
    assert request.evidence_refs[0].type == "transaction"


def test_legacy_old_shape_converts_to_canonical():
    legacy = [
        {
            "ref_id": "ev-old-1",
            "ref_type": "circular_transfer",
            "ref_source": "fraud_evaluator",
            "description": "non-uri description dropped",
            "metadata": {"transfer_ids": ["t1", "t2"]},
        }
    ]
    normalized = normalize_persisted_evidence_refs(legacy)
    assert normalized == [
        {"id": "ev-old-1", "type": "transaction", "source": "fraud_evaluator"}
    ]


def test_legacy_uri_description_is_preserved():
    legacy = [
        {
            "ref_id": "ev-old-2",
            "ref_type": "transfer",
            "ref_source": "fraud_evaluator",
            "description": "aether://evidence/evt-1",
            "metadata": {},
        }
    ]
    normalized = normalize_persisted_evidence_refs(legacy)
    assert normalized == [
        {
            "id": "ev-old-2",
            "type": "transaction",
            "source": "fraud_evaluator",
            "uri": "aether://evidence/evt-1",
        }
    ]


def test_legacy_detector_signal_and_other_ref_types_map():
    # The fraud evaluator persisted raw detector signal names as ref_type.
    assert LEGACY_REF_TYPE_TO_EVIDENCE_TYPE["shared_wallet"] == "relationship"
    # Legacy ref types documented on the removed class.
    assert LEGACY_REF_TYPE_TO_EVIDENCE_TYPE["session"] == "event"
    assert LEGACY_REF_TYPE_TO_EVIDENCE_TYPE["delegation"] == "relationship"
    assert LEGACY_REF_TYPE_TO_EVIDENCE_TYPE["order"] == "transaction"


def test_new_shape_round_trips_unchanged():
    canonical = [
        _canonical_evidence_dict(
            id="ev-3",
            type="transaction",
            source="fraud_evaluator",
            observedAt="2026-01-01T00:00:00Z",
            confidence=0.9,
            uri="aether://fraud/decision/evidence",
        )
    ]
    assert normalize_persisted_evidence_refs(canonical) == canonical


def test_unrepresentable_legacy_ref_type_is_dropped_not_fabricated():
    legacy = [
        {
            "ref_id": "ev-old-3",
            "ref_type": "some_unknown_thing",
            "ref_source": "fraud_evaluator",
        }
    ]
    assert normalize_persisted_evidence_refs(legacy) == []


def test_loader_tolerates_none_empty_and_single_dict():
    assert normalize_persisted_evidence_refs(None) == []
    assert normalize_persisted_evidence_refs([]) == []
    single = normalize_persisted_evidence_refs(
        {
            "ref_id": "ev-old-4",
            "ref_type": "reward_event",
            "ref_source": "fraud_evaluator",
        }
    )
    assert single == [{"id": "ev-old-4", "type": "event", "source": "fraud_evaluator"}]


def test_loader_outputs_validate_as_canonical_evidence_refs():
    legacy = [
        {
            "ref_id": "ev-old-5",
            "ref_type": "commerce_abuse",
            "ref_source": "fraud_evaluator",
        }
    ]
    for ref_dict in normalize_persisted_evidence_refs(legacy):
        ref = EvidenceRef(**ref_dict)  # must validate against EvidenceType Literal
        assert ref.type in set(get_args(EvidenceType))


def test_legacy_row_requires_loader_before_fraud_decision_parse():
    """A pre-convergence persisted row must be normalized before model parse."""
    legacy_row = {
        **_decision_kwargs(),
        "evidence_refs": [
            {
                "ref_id": "ev-old-6",
                "ref_type": "split_merge",
                "ref_source": "fraud_evaluator",
                "description": "x",
                "metadata": {"a": 1},
            }
        ],
    }
    with pytest.raises(ValidationError):
        FraudDecision(**legacy_row)

    normalized_row = {
        **legacy_row,
        "evidence_refs": normalize_persisted_evidence_refs(legacy_row["evidence_refs"]),
    }
    decision = FraudDecision(**normalized_row)
    assert decision.evidence_refs[0].id == "ev-old-6"
    assert decision.evidence_refs[0].type == "transaction"


def test_signal_to_evidence_type_only_yields_valid_types():
    from typing import get_args

    valid = set(get_args(EvidenceType))
    assert set(SIGNAL_TO_EVIDENCE_TYPE.values()).issubset(valid)
    assert set(LEGACY_REF_TYPE_TO_EVIDENCE_TYPE.values()).issubset(valid)
