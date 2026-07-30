"""PR-C — model-governance gates: consent-scoped training-data admission +
inference policy evidence. Runs in the root CI suite (make ci-check / python-tests)
so the gates are exercised end-to-end; deeper cases live in the backend tree.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.model_governance import consent_purposes  # noqa: E402
from services.model_governance.inference_gate import InferencePolicyGate  # noqa: E402
from services.model_governance.training_gate import TrainingDataGate  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# --------------------------------------------------------------- consent registry
def test_consent_registry_training_semantics():
    # analytics/marketing/agent/commerce/personalization may train.
    assert consent_purposes.model_training_allowed("analytics") is True
    assert consent_purposes.model_training_allowed("commerce") is True
    # web3/credit/location may never train.
    assert consent_purposes.model_training_allowed("web3") is False
    assert consent_purposes.model_training_allowed("credit") is False
    assert consent_purposes.model_training_allowed("location") is False
    # financial/economic/interop allow training only behind a separate opt-in.
    assert consent_purposes.requires_separate_training_opt_in("financial_activity") is True
    assert consent_purposes.requires_separate_training_opt_in("economic_observability") is True
    # Unknown purpose fails closed.
    assert consent_purposes.model_training_allowed("nope") is False
    # The purpose set mirrors the canonical registry exactly (no drift).
    import json

    registry = json.loads(
        (ROOT / "packages" / "shared" / "contracts" / "consent-registry.json")
        .read_text(encoding="utf-8")
    )
    assert consent_purposes.all_purposes() == {
        p["key"] for p in registry["purposes"]
    }


# --------------------------------------------------------------- training gate
# A model id NOT in the ML registry, so policy.allowed_training_purposes() is
# empty and these tests deterministically exercise the consent-registry rules
# regardless of whether the ML package is importable in the running suite.
UNSCOPED_MODEL = "gov_unscoped_test_model"


def test_training_gate_quarantines_non_trainable_purpose():
    gate = TrainingDataGate()
    d = gate.evaluate_record(
        {"record_ref": "r1", "source_purposes": ["web3"]},
        model_id=UNSCOPED_MODEL,
    )
    assert d.admitted is False
    assert "purpose_forbids_training:web3" in d.quarantine_reasons


def test_training_gate_requires_separate_opt_in():
    gate = TrainingDataGate()
    without = gate.evaluate_record(
        {"record_ref": "r2", "source_purposes": ["financial_activity"]},
        model_id=UNSCOPED_MODEL,
    )
    assert without.admitted is False
    assert "separate_opt_in_required:financial_activity" in without.quarantine_reasons
    assert "financial_activity" in without.missing_training_opt_in

    with_opt_in = gate.evaluate_record(
        {"record_ref": "r2", "source_purposes": ["financial_activity"]},
        model_id=UNSCOPED_MODEL,
        granted_training_opt_ins=["financial_activity"],
    )
    assert with_opt_in.admitted is True


def test_training_gate_admits_trainable_purpose_and_no_purpose_fails_closed():
    gate = TrainingDataGate()
    ok = gate.evaluate_record(
        {"record_ref": "r3", "source_purposes": ["analytics"]},
        model_id=UNSCOPED_MODEL,
    )
    assert ok.admitted is True
    assert ok.quarantine_reasons == []

    missing = gate.evaluate_record({"record_ref": "r4"}, model_id=UNSCOPED_MODEL)
    assert missing.admitted is False
    assert "no_source_purpose" in missing.quarantine_reasons


def test_training_gate_enforces_model_purpose_scope():
    # A model with an explicit allowed_training_purposes scope quarantines any
    # source purpose outside that scope (even an otherwise-trainable one).
    gate = TrainingDataGate()
    d = gate.evaluate_record(
        {"record_ref": "r6", "source_purposes": ["marketing"]},  # trainable, but out of scope
        model_id="scoped_model",
        model_allowed_purposes=["analytics"],
    )
    assert d.admitted is False
    assert "purpose_not_allowed_for_model:marketing" in d.quarantine_reasons
    # In-scope purpose is admitted.
    ok = gate.evaluate_record(
        {"record_ref": "r7", "source_purposes": ["analytics"]},
        model_id="scoped_model",
        model_allowed_purposes=["analytics"],
    )
    assert ok.admitted is True


def test_identity_derived_label_quarantine():
    gate = TrainingDataGate()
    bad = gate.evaluate_record(
        {"record_ref": "r5", "label_source": "identity_resolution",
         "source_purposes": ["credit"]},
        model_id=UNSCOPED_MODEL,
    )
    assert bad.admitted is False
    assert bad.identity_derived_label is True
    assert "identity_label_unconsented" in bad.quarantine_reasons


@pytest.mark.asyncio
async def test_training_gate_partition_persists_quarantine():
    gate = TrainingDataGate()
    result = await gate.partition(
        [
            {"record_ref": "a", "source_purposes": ["analytics"]},
            {"record_ref": "b", "source_purposes": ["web3"]},
        ],
        model_id=UNSCOPED_MODEL,
        tenant_id="t1",
    )
    assert result.admitted_count == 1
    assert result.quarantined_count == 1
    rows = await gate._repo.list_for_tenant("t1")
    assert len(rows) == 2
    # Tenant isolation.
    assert await gate._repo.list_for_tenant("t2") == []


# --------------------------------------------------------------- inference gate
@pytest.mark.asyncio
async def test_inference_gate_records_evidence_and_allows_by_default():
    gate = InferencePolicyGate()
    res = await gate.evaluate(
        tenant_id="t1",
        actor_id="svc",
        model_id="churn_prediction",
        granted_purposes=[],
        subject_ref="entity-1",
        required_purposes=["analytics"],
        enforce=False,
    )
    # Evidence recorded, not blocked (evidence-only mode).
    assert res.blocked is False
    assert res.policy_decision_id is not None
    assert res.missing_purposes == ["analytics"]


@pytest.mark.asyncio
async def test_inference_gate_blocks_when_enforced_and_consent_missing():
    gate = InferencePolicyGate()
    res = await gate.evaluate(
        tenant_id="t1",
        actor_id="svc",
        model_id="churn_prediction",
        granted_purposes=[],
        subject_ref="entity-1",
        required_purposes=["analytics"],
        enforce=True,
    )
    assert res.blocked is True
    assert res.enforced is True
    assert "analytics" in res.missing_purposes


@pytest.mark.asyncio
async def test_inference_gate_allows_when_consent_present():
    gate = InferencePolicyGate()
    res = await gate.evaluate(
        tenant_id="t1",
        actor_id="svc",
        model_id="churn_prediction",
        granted_purposes=["analytics"],
        subject_ref="entity-1",
        required_purposes=["analytics"],
        enforce=True,
    )
    assert res.allowed is True
    assert res.blocked is False
    assert res.missing_purposes == []
