"""GroundingPolicy tests for ADR-008 D6 grounded synthesis (Commit 9, Agent C).

Exercises the fail-closed retrieval-before-synthesis gate (D6): tenant scope
rejection, evidence presence/count, all-stale rejection, the non-raising
``ready`` mirror, custom ``min_evidence`` / ``max_age_seconds``, and
``now``-injection determinism.

Requests are built with sibling A's ``SynthesisRequest`` from
``services.model_runtime.synthesis.models`` when that module has landed
(concurrent commit). Before it lands, a spec-exact local stand-in exposing the
same attribute surface is used so the gate is genuinely exercised rather than
skipped; once ``synthesis.models`` is present the real class is used
automatically. Evidence models come from the landed context layer
(``EvidenceSet`` / ``EvidenceItem``), and ``EvidenceSet.model_construct`` is
used for edge-case sets to bypass field validators (frozen models).

All timestamps use aware UTC datetimes via ``datetime.now(timezone.utc)`` plus
``timedelta`` so the policy's freshness subtraction is deterministic. Plain
asserts with a tiny ``_raises`` helper — no pytest fixtures required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import services.model_runtime.synthesis.grounding as grounding_module
from services.model_runtime.context.evidence import (
    EvidenceItem,
    EvidenceSet,
)
from services.model_runtime.synthesis.grounding import (
    GroundingPolicy,
    GroundingViolation,
    InsufficientEvidence,
    StaleEvidence,
)

_NOW = datetime.now(timezone.utc)


def _raises(exc_type, fn) -> None:
    """Assert that ``fn()`` raises ``exc_type`` (plain-assert style)."""
    try:
        fn()
    except exc_type:
        return
    except Exception as err:  # pragma: no cover - failure diagnostic path
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


# ---------------------------------------------------------------------------
# Request construction: prefer the landed sibling model, else a spec-exact
# stand-in so the D6 gate can be exercised before that module lands.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - branch depends on whether sibling A has landed
    from services.model_runtime.synthesis.models import (
        SynthesisRequest as _LandedSynthesisRequest,
    )
except ImportError:  # sibling A's models.py not yet landed (concurrent commit)
    _LandedSynthesisRequest = None


class _FallbackSynthesisRequest:
    """Spec-exact stand-in for sibling A's ``SynthesisRequest`` (pre-landing).

    Mirrors the documented field surface of
    ``services.model_runtime.synthesis.models.SynthesisRequest`` so the D6 gate
    can be exercised before that module lands (concurrent commit). The real
    model is preferred whenever it is importable; this fallback is replaced
    automatically once it lands.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        query: str,
        plan_kind: str,
        evidence: EvidenceSet | None = None,
        synthesis_instructions: str = "",
        created_at: datetime,
    ) -> None:
        self.tenant_id = tenant_id
        self.profile_id = profile_id
        self.query = query
        self.plan_kind = plan_kind
        self.evidence = evidence
        self.synthesis_instructions = synthesis_instructions
        self.created_at = created_at


def _request(
    *,
    tenant_id: str = "tenant-a",
    evidence: EvidenceSet | None = None,
    plan_kind: str = "grounded",
    now: datetime | None = None,
):
    """Build a synthesis-shaped request using the landed model when available."""
    RequestClass = _LandedSynthesisRequest or _FallbackSynthesisRequest
    return RequestClass(
        tenant_id=tenant_id,
        profile_id="profile-1",
        query="What is the running balance?",
        plan_kind=plan_kind,
        evidence=evidence,
        created_at=now if now is not None else _NOW,
    )


def _item(
    reference_id: str,
    *,
    tenant_id: str = "tenant-a",
    content: str = "grounding evidence",
    age_seconds: int = 0,
    now: datetime | None = None,
) -> EvidenceItem:
    """Build an evidence item with an optional age relative to ``now``."""
    base = now if now is not None else _NOW
    return EvidenceItem(
        reference_id=reference_id,
        source="aether.records.transactions",
        tenant_id=tenant_id,
        content=content,
        collected_at=base - timedelta(seconds=age_seconds),
    )


def _evidence(
    *,
    tenant_id: str = "tenant-a",
    items: tuple[EvidenceItem, ...] = (),
    now: datetime | None = None,
) -> EvidenceSet:
    """Build a tenant-scoped evidence set via normal (validated) construction."""
    base = now if now is not None else _NOW
    return EvidenceSet(
        tenant_id=tenant_id,
        profile_id="profile-1",
        query="What is the running balance?",
        items=items,
        created_at=base,
    )


def _evidence_construct(
    *,
    tenant_id: str = "tenant-a",
    items: tuple[EvidenceItem, ...] = (),
    now: datetime | None = None,
) -> EvidenceSet:
    """Build an evidence set via ``model_construct``, bypassing field validators."""
    base = now if now is not None else _NOW
    return EvidenceSet.model_construct(
        tenant_id=tenant_id,
        profile_id="profile-1",
        query="What is the running balance?",
        items=items,
        created_at=base,
    )


# ---------------------------------------------------------------------------
# Fail-closed D6 gate behavior
# ---------------------------------------------------------------------------
def test_none_evidence_raises_insufficient() -> None:
    _raises(
        InsufficientEvidence,
        lambda: GroundingPolicy().check(_request(evidence=None)),
    )


def test_empty_evidence_raises_insufficient() -> None:
    _raises(
        InsufficientEvidence,
        lambda: GroundingPolicy().check(_request(evidence=_evidence())),
    )


def test_fewer_than_min_evidence_raises_insufficient() -> None:
    evidence = _evidence(items=(_item("r-1"),))
    _raises(
        InsufficientEvidence,
        lambda: GroundingPolicy(min_evidence=3).check(_request(evidence=evidence)),
    )


def test_tenant_mismatch_raises_grounding_violation() -> None:
    evidence = _evidence(
        tenant_id="tenant-b",
        items=(_item("r-1", tenant_id="tenant-b"),),
    )
    _raises(
        GroundingViolation,
        lambda: GroundingPolicy().check(
            _request(tenant_id="tenant-a", evidence=evidence)
        ),
    )


def test_all_stale_items_raise_stale() -> None:
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        items=(
            _item("r-1", age_seconds=301, now=now),
            _item("r-2", age_seconds=3600, now=now),
        ),
        now=now,
    )
    _raises(
        StaleEvidence,
        lambda: GroundingPolicy(now=now).check(_request(evidence=evidence, now=now)),
    )


def test_fresh_items_pass() -> None:
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        items=(
            _item("r-1", age_seconds=0, now=now),
            _item("r-2", age_seconds=120, now=now),
        ),
        now=now,
    )
    assert GroundingPolicy(now=now).check(_request(evidence=evidence, now=now)) is None


def test_single_fresh_item_carries_the_gate() -> None:
    # A fully-stale set fails; adding one fresh item carries the gate.
    now = datetime.now(timezone.utc)
    stale_only = _evidence(items=(_item("r-old", age_seconds=3600, now=now),), now=now)
    policy = GroundingPolicy(now=now)
    _raises(StaleEvidence, lambda: policy.check(_request(evidence=stale_only, now=now)))
    mixed = _evidence(
        items=(
            _item("r-fresh", age_seconds=0, now=now),
            _item("r-old", age_seconds=3600, now=now),
        ),
        now=now,
    )
    assert policy.check(_request(evidence=mixed, now=now)) is None


def test_ready_mirrors_check() -> None:
    now = datetime.now(timezone.utc)
    policy = GroundingPolicy(now=now)

    fresh = _evidence(items=(_item("r-1", now=now),), now=now)
    assert policy.ready(_request(evidence=fresh, now=now)) is True

    assert policy.ready(_request(evidence=None, now=now)) is False
    assert policy.ready(_request(evidence=_evidence(now=now), now=now)) is False

    stale = _evidence(items=(_item("r-1", age_seconds=301, now=now),), now=now)
    assert policy.ready(_request(evidence=stale, now=now)) is False

    cross_tenant = _evidence(
        tenant_id="tenant-b",
        items=(_item("r-1", tenant_id="tenant-b", now=now),),
        now=now,
    )
    assert policy.ready(_request(tenant_id="tenant-a", evidence=cross_tenant, now=now)) is False


# ---------------------------------------------------------------------------
# Custom bounds and now-injection determinism
# ---------------------------------------------------------------------------
def test_custom_min_evidence_honored() -> None:
    now = datetime.now(timezone.utc)
    one_item = _evidence(items=(_item("r-1", now=now),), now=now)
    two_items = _evidence(
        items=(_item("r-1", now=now), _item("r-2", now=now)),
        now=now,
    )
    policy = GroundingPolicy(min_evidence=2, now=now)
    _raises(InsufficientEvidence, lambda: policy.check(_request(evidence=one_item, now=now)))
    assert policy.check(_request(evidence=two_items, now=now)) is None


def test_custom_max_age_seconds_honored() -> None:
    now = datetime.now(timezone.utc)
    aged_120 = _evidence(items=(_item("r-1", age_seconds=120, now=now),), now=now)
    aged_30 = _evidence(items=(_item("r-1", age_seconds=30, now=now),), now=now)
    policy = GroundingPolicy(max_age_seconds=60, now=now)
    _raises(StaleEvidence, lambda: policy.check(_request(evidence=aged_120, now=now)))
    assert policy.check(_request(evidence=aged_30, now=now)) is None


def test_now_injection_determinism_at_boundary() -> None:
    # Age == max_age is NOT stale (strictly-greater bound); max_age + 1 is stale.
    now = datetime.now(timezone.utc)
    at_boundary = _evidence(items=(_item("r-1", age_seconds=300, now=now),), now=now)
    assert GroundingPolicy(now=now).check(_request(evidence=at_boundary, now=now)) is None

    over_boundary = _evidence(items=(_item("r-1", age_seconds=301, now=now),), now=now)
    _raises(
        StaleEvidence,
        lambda: GroundingPolicy(now=now).check(_request(evidence=over_boundary, now=now)),
    )


# ---------------------------------------------------------------------------
# Init validation, model_construct edge sets, exports
# ---------------------------------------------------------------------------
def test_init_validates_positive_bounds() -> None:
    _raises(ValueError, lambda: GroundingPolicy(min_evidence=0))
    _raises(ValueError, lambda: GroundingPolicy(min_evidence=-1))
    _raises(ValueError, lambda: GroundingPolicy(max_age_seconds=0))
    _raises(ValueError, lambda: GroundingPolicy(max_age_seconds=-300))


def test_model_construct_edge_set_still_gated() -> None:
    # Edge-case sets built via model_construct (bypassing field validators)
    # are still subject to the fail-closed grounding gate.
    now = datetime.now(timezone.utc)
    stale_set = _evidence_construct(
        items=(_item("r-1", age_seconds=600, now=now),),
        now=now,
    )
    _raises(
        StaleEvidence,
        lambda: GroundingPolicy(now=now).check(_request(evidence=stale_set, now=now)),
    )


def test_request_uses_landed_synthesis_model_when_present() -> None:
    if _LandedSynthesisRequest is None:
        return  # sibling A not yet landed; the spec-exact stand-in is exercised
    req = _request(evidence=_evidence())
    assert isinstance(req, _LandedSynthesisRequest)


def test_grounding_module_exports_complete() -> None:
    expected = {
        "InsufficientEvidence",
        "StaleEvidence",
        "GroundingViolation",
        "GroundingPolicy",
    }
    assert set(grounding_module.__all__) == expected
    for name in expected:
        assert hasattr(grounding_module, name), name
