"""Program 3 M2: re-attribution recorded as DSR propagation evidence.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §3 ("Deletion / replay /
re-attribution"). M1 wired re-attribution into privacy erasure; M3 generalized
it into ``services/measurement/reattribution.py``'s
``reattribute_affected(...) -> ReattributionResult``, reused by privacy erasure
(``reason="privacy_erasure"``) and by fraud-network takedown
(``reason="fraud_takedown"``). **M2** is the missing DSR-evidence link: when
re-attribution runs as part of a subject's request, its ``ReattributionResult``
summary must be recorded as first-class propagation evidence on the
``attribution_records`` DSR component, so a DSR/compliance audit shows the
subject's attribution was actually corrected — not merely that touchpoints /
conversions were tombstoned.

These tests exercise the DSR-evidence layer M2 owns
(``services/dsr_propagation``): ``DSRPropagationService.record_reattribution``
and the ``ReattributionEvidence`` shape. They prove the recorder is
trigger-agnostic (BOTH erasure and takedown summaries record identically),
accepts a ``ReattributionResult`` object / its ``to_dict()`` / a mapping / a
plain attribute object WITHOUT importing the measurement package, composes
*additively* with the erasure job's own ``mark_step`` receipt, and is
fail-closed (tenant isolation, unknown component, empty reason, negative
counts). The M1 privacy-erasure behavior and the erasure-job wiring are covered
by tests/dsr/test_erasure_reattribution.py and
tests/dsr/test_consent_erasure_job.py respectively and are unchanged here.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores

from services.dsr_propagation.models import ReattributionEvidence
from services.dsr_propagation.service import (
    REATTRIBUTION_COMPONENT,
    DSRPropagationService,
    _coerce_reattribution_evidence,
)

pytestmark = pytest.mark.asyncio

TENANT = "t-reattr-evidence"


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _svc() -> DSRPropagationService:
    return DSRPropagationService()


# ── A faithful stand-in for M3's ReattributionResult ──────────────────────────
# M3 (services/measurement/reattribution.py) lives on a sibling branch; this
# mirrors its ReattributionResult dataclass EXACTLY (fields + partial_failure +
# to_dict) so these tests prove record_reattribution accepts the real object via
# duck-typed ``to_dict()`` without coupling the DSR layer to the measurement
# package.
@dataclass
class _ReattributionResultStub:
    reason: str
    conversions_scanned: int = 0
    conversions_reattributed: int = 0
    runs_deactivated: int = 0
    runs_created: int = 0
    truncated: bool = False
    scope_limit: int = 2000
    touchpoints_scanned: int = 0
    errors: list = field(default_factory=list)

    @property
    def partial_failure(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "conversions_scanned": self.conversions_scanned,
            "conversions_reattributed": self.conversions_reattributed,
            "runs_deactivated": self.runs_deactivated,
            "runs_created": self.runs_created,
            "truncated": self.truncated,
            "scope_limit": self.scope_limit,
            "touchpoints_scanned": self.touchpoints_scanned,
            "errors": list(self.errors),
            "partial_failure": self.partial_failure,
        }


async def _open(svc: DSRPropagationService, dsr_type: str = "erasure") -> str:
    return await svc.open_request(
        tenant_id=TENANT, subject_ref="user:alice", dsr_type=dsr_type,
    )


def _reattr_step(status_record: dict) -> dict:
    return next(
        c for c in status_record["components"]
        if c["component"] == REATTRIBUTION_COMPONENT
    )


# ── the default component is attribution_records ──────────────────────────────

async def test_component_constant_is_attribution_records():
    assert REATTRIBUTION_COMPONENT == "attribution_records"


# ── records the ReattributionResult summary on attribution_records ────────────

async def test_records_reattribution_summary_on_attribution_records():
    svc = _svc()
    rid = await _open(svc)

    result = _ReattributionResultStub(
        reason="privacy_erasure",
        conversions_scanned=7,
        conversions_reattributed=4,
        runs_deactivated=4,
        runs_created=4,
        touchpoints_scanned=9,
        scope_limit=2000,
    )
    step = await svc.record_reattribution(rid, result, tenant_id=TENANT)

    assert step["component"] == "attribution_records"
    ev = step["reattribution"]
    assert ev is not None
    assert ev["reason"] == "privacy_erasure"
    assert ev["conversions_scanned"] == 7
    assert ev["conversions_reattributed"] == 4
    assert ev["runs_deactivated"] == 4
    assert ev["runs_created"] == 4
    assert ev["touchpoints_scanned"] == 9
    assert ev["scope_limit"] == 2000
    assert ev["truncated"] is False
    assert ev["partial_failure"] is False
    assert ev["errors_count"] == 0
    assert ev["recorded_at"]  # self-timestamped

    # Reading it back through status() surfaces the same evidence.
    status = await svc.status(rid, tenant_id=TENANT)
    assert _reattr_step(status)["reattribution"]["conversions_reattributed"] == 4


# ── BOTH triggers (erasure + takedown) record identically ─────────────────────

@pytest.mark.parametrize("reason", ["privacy_erasure", "fraud_takedown"])
async def test_both_erasure_and_takedown_reasons_record(reason):
    """The recorder keys only on the summary shape, so the erasure path
    (reason='privacy_erasure') and the fraud-takedown path
    (reason='fraud_takedown') both produce attribution_records evidence."""
    svc = _svc()
    rid = await _open(svc, dsr_type="erasure" if reason == "privacy_erasure" else "restriction")

    result = _ReattributionResultStub(
        reason=reason,
        conversions_scanned=3,
        conversions_reattributed=2,
        runs_deactivated=2,
        runs_created=2,
    )
    step = await svc.record_reattribution(rid, result, tenant_id=TENANT)
    ev = step["reattribution"]
    assert ev["reason"] == reason
    assert ev["conversions_reattributed"] == 2
    assert ev["runs_deactivated"] == 2
    assert ev["runs_created"] == 2


# ── accepts object.to_dict(), plain mapping, and attribute-only object ─────────

async def test_accepts_result_to_dict_mapping():
    svc = _svc()
    rid = await _open(svc)
    result = _ReattributionResultStub(reason="fraud_takedown", runs_created=5)
    step = await svc.record_reattribution(rid, result.to_dict(), tenant_id=TENANT)
    assert step["reattribution"]["reason"] == "fraud_takedown"
    assert step["reattribution"]["runs_created"] == 5


async def test_accepts_plain_mapping_summary():
    svc = _svc()
    rid = await _open(svc)
    summary = {
        "reason": "privacy_erasure",
        "conversions_reattributed": 1,
        "runs_deactivated": 1,
        "runs_created": 1,
        "truncated": False,
    }
    step = await svc.record_reattribution(rid, summary, tenant_id=TENANT)
    assert step["reattribution"]["conversions_reattributed"] == 1


async def test_accepts_attribute_only_object():
    """An object with the summary fields as attributes but neither to_dict()
    nor Mapping still resolves (duck-typed read)."""
    class _AttrOnly:
        reason = "fraud_takedown"
        conversions_reattributed = 3
        runs_deactivated = 3
        runs_created = 3

    svc = _svc()
    rid = await _open(svc)
    step = await svc.record_reattribution(rid, _AttrOnly(), tenant_id=TENANT)
    assert step["reattribution"]["reason"] == "fraud_takedown"
    assert step["reattribution"]["runs_created"] == 3


# ── truncation + partial-failure honesty flags are carried, errors summarized ──

async def test_truncated_and_partial_failure_flags_carried():
    svc = _svc()
    rid = await _open(svc)
    result = _ReattributionResultStub(
        reason="privacy_erasure",
        conversions_scanned=2000,
        conversions_reattributed=1500,
        runs_deactivated=1500,
        runs_created=1500,
        truncated=True,
        errors=[
            "reattribution_scope_truncated: ...",
            "reattribution:conv-9: boom",
        ],
    )
    step = await svc.record_reattribution(rid, result, tenant_id=TENANT)
    ev = step["reattribution"]
    assert ev["truncated"] is True
    # partial_failure derives from the summary (non-empty errors) ...
    assert ev["partial_failure"] is True
    # ... and the raw error strings are summarized to a count, never stored.
    assert ev["errors_count"] == 2
    assert "errors" not in ev


async def test_partial_failure_derived_from_errors_count_when_absent():
    """A mapping that omits partial_failure but supplies errors_count derives it
    (mirrors ReattributionResult.partial_failure)."""
    ev = _coerce_reattribution_evidence(
        {"reason": "fraud_takedown", "errors_count": 3}
    )
    assert ev.partial_failure is True
    assert ev.errors_count == 3


# ── additive: does not disturb the step's own erasure receipt / status ────────

async def test_additive_preserves_prior_mark_step_receipt():
    """record_reattribution attaches evidence WITHOUT changing status or the
    store's own tombstone receipt set by mark_step (the erasure-job order:
    mark completed, then record re-attribution)."""
    svc = _svc()
    rid = await _open(svc)

    # Erasure job marks attribution_records completed with its tombstone receipt.
    await svc.mark_step(
        rid, "attribution_records", "completed", tenant_id=TENANT,
        records_impacted=5, audit_event_id="job-123", requires_recompute=False,
    )
    # Then the re-attribution evidence is attached.
    result = _ReattributionResultStub(
        reason="privacy_erasure", conversions_reattributed=4,
        runs_deactivated=4, runs_created=4,
    )
    step = await svc.record_reattribution(rid, result, tenant_id=TENANT)

    # Both receipts coexist on the one component step.
    assert step["status"] == "completed"           # unchanged
    assert step["records_impacted"] == 5           # unchanged tombstone receipt
    assert step["audit_event_id"] == "job-123"     # unchanged audit pointer
    assert step["requires_recompute"] is False     # unchanged
    assert step["reattribution"]["conversions_reattributed"] == 4

    # Overall roll-up is unaffected (still driven by component status).
    status = await svc.status(rid, tenant_id=TENANT)
    assert _reattr_step(status)["records_impacted"] == 5
    assert _reattr_step(status)["reattribution"]["runs_created"] == 4


async def test_evidence_survives_a_later_mark_step():
    """The reverse order (record re-attribution mid-flight, THEN the job marks
    the component completed) also preserves the evidence — mark_step re-validates
    the whole step, carrying the reattribution field through."""
    svc = _svc()
    rid = await _open(svc)

    await svc.mark_step(rid, "attribution_records", "running", tenant_id=TENANT)
    result = _ReattributionResultStub(
        reason="privacy_erasure", conversions_reattributed=2,
        runs_deactivated=2, runs_created=2,
    )
    await svc.record_reattribution(rid, result, tenant_id=TENANT)
    # Job now finalizes the component with its tombstone receipt.
    step = await svc.mark_step(
        rid, "attribution_records", "completed", tenant_id=TENANT,
        records_impacted=5, audit_event_id="job-9",
    )
    assert step["status"] == "completed"
    assert step["records_impacted"] == 5
    assert step["reattribution"]["conversions_reattributed"] == 2  # survived


async def test_only_targeted_component_changes():
    svc = _svc()
    rid = await _open(svc)
    await svc.record_reattribution(
        rid, _ReattributionResultStub(reason="privacy_erasure"), tenant_id=TENANT,
    )
    status = await svc.status(rid, tenant_id=TENANT)
    for c in status["components"]:
        if c["component"] == "attribution_records":
            assert c["reattribution"] is not None
            # status untouched by a pure evidence attachment.
            assert c["status"] == "pending"
        else:
            assert c["reattribution"] is None
            assert c["status"] == "pending"


# ── one-shot wiring: mark_step accepts the reattribution evidence field ────────

async def test_mark_step_accepts_reattribution_evidence_passthrough():
    """The intended erasure-job one-shot: mark attribution_records completed with
    BOTH the tombstone receipt AND the re-attribution evidence in one call."""
    svc = _svc()
    rid = await _open(svc)
    evidence = ReattributionEvidence(
        reason="privacy_erasure", conversions_reattributed=4,
        runs_deactivated=4, runs_created=4,
    ).model_dump()
    step = await svc.mark_step(
        rid, "attribution_records", "completed", tenant_id=TENANT,
        records_impacted=5, audit_event_id="job-1", reattribution=evidence,
    )
    assert step["status"] == "completed"
    assert step["records_impacted"] == 5
    assert step["reattribution"]["reason"] == "privacy_erasure"
    assert step["reattribution"]["runs_created"] == 4


async def test_reattribution_is_not_a_completion_receipt_on_its_own():
    """reattribution evidence augments a completion receipt — it does not satisfy
    the 'completed requires the component's own receipt' gate by itself."""
    svc = _svc()
    rid = await _open(svc)
    evidence = ReattributionEvidence(reason="privacy_erasure").model_dump()
    with pytest.raises(Exception, match="evidence"):
        await svc.mark_step(
            rid, "attribution_records", "completed", tenant_id=TENANT,
            reattribution=evidence,
        )


# ── fail-closed guards ────────────────────────────────────────────────────────

async def test_tenant_isolation_on_record_reattribution():
    svc = _svc()
    rid = await _open(svc)
    # A different tenant cannot record against this record (not found).
    with pytest.raises(Exception):
        await svc.record_reattribution(
            rid, _ReattributionResultStub(reason="privacy_erasure"), tenant_id="t-other",
        )
    # And the record is untouched from the owning tenant's view.
    status = await svc.status(rid, tenant_id=TENANT)
    assert _reattr_step(status)["reattribution"] is None


async def test_record_reattribution_missing_record_raises():
    svc = _svc()
    with pytest.raises(Exception):
        await svc.record_reattribution(
            "dsrp_missing", _ReattributionResultStub(reason="privacy_erasure"),
            tenant_id=TENANT,
        )


async def test_unknown_component_rejected():
    svc = _svc()
    rid = await _open(svc)
    with pytest.raises(Exception):
        await svc.record_reattribution(
            rid, _ReattributionResultStub(reason="privacy_erasure"),
            tenant_id=TENANT, component="not_a_component",
        )


async def test_missing_or_empty_reason_rejected():
    svc = _svc()
    rid = await _open(svc)
    with pytest.raises(Exception):
        await svc.record_reattribution(rid, {"conversions_reattributed": 1}, tenant_id=TENANT)
    with pytest.raises(Exception):
        await svc.record_reattribution(rid, {"reason": "   "}, tenant_id=TENANT)
    with pytest.raises(Exception):
        await svc.record_reattribution(rid, None, tenant_id=TENANT)


async def test_negative_count_rejected():
    """A negative summary count is rejected by the model (ge=0), never persisted."""
    svc = _svc()
    rid = await _open(svc)
    with pytest.raises(Exception):
        await svc.record_reattribution(
            rid,
            {"reason": "privacy_erasure", "conversions_reattributed": -1},
            tenant_id=TENANT,
        )


# ── unit: the coercion helper + evidence model defaults ───────────────────────

async def test_coerce_defaults_zero_counts_and_stamps_time():
    ev = _coerce_reattribution_evidence({"reason": "privacy_erasure"})
    assert isinstance(ev, ReattributionEvidence)
    assert ev.reason == "privacy_erasure"
    assert ev.conversions_scanned == 0
    assert ev.conversions_reattributed == 0
    assert ev.runs_deactivated == 0
    assert ev.runs_created == 0
    assert ev.truncated is False
    assert ev.partial_failure is False
    assert ev.errors_count == 0
    assert ev.recorded_at  # default-stamped


async def test_coerce_from_result_object_matches_to_dict():
    result = _ReattributionResultStub(
        reason="fraud_takedown",
        conversions_scanned=5,
        conversions_reattributed=3,
        runs_deactivated=3,
        runs_created=3,
        touchpoints_scanned=8,
        truncated=True,
        errors=["x"],
    )
    ev = _coerce_reattribution_evidence(result)
    assert ev.reason == "fraud_takedown"
    assert ev.conversions_scanned == 5
    assert ev.conversions_reattributed == 3
    assert ev.runs_deactivated == 3
    assert ev.runs_created == 3
    assert ev.touchpoints_scanned == 8
    assert ev.truncated is True
    assert ev.partial_failure is True   # non-empty errors -> partial
    assert ev.errors_count == 1
