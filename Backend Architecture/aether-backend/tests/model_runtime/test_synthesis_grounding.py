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


def test_foreign_item_tenant_raises_grounding_violation() -> None:
    # REGRESSION (Codex PRRT_kwDORdw-AM6bhAIV): EvidenceSet.tenant_id alone is
    # NOT authoritative. EvidenceSet does not enforce item/set tenant
    # homogeneity, so a caller can build a set labeled "tenant-a" that carries
    # an item from "tenant-b". The gate compared only EvidenceSet.tenant_id
    # with the request tenant, the set-level check passed, and the foreign item
    # reached the model as a citation. EVERY item must be tenant-scoped: a
    # mixed set with one foreign item must fail the whole gate closed.
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        tenant_id="tenant-a",
        items=(
            _item("r-own", tenant_id="tenant-a", now=now),
            _item("r-foreign", tenant_id="tenant-b", now=now),
        ),
        now=now,
    )
    _raises(
        GroundingViolation,
        lambda: GroundingPolicy(now=now).check(
            _request(tenant_id="tenant-a", evidence=evidence, now=now)
        ),
    )


def test_foreign_item_rejected_before_freshness() -> None:
    # REGRESSION (Codex PRRT_kwDORdw-AM6bhAIV): the per-item tenant check runs
    # BEFORE freshness. A foreign item that is also stale must be reported as a
    # tenant violation (GroundingViolation), not as StaleEvidence — the gate's
    # first failing condition wins so the failure mode is precise and the
    # foreign data can never be grounded on, even when it is also out of the
    # freshness bound.
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        tenant_id="tenant-a",
        items=(_item("r-foreign", tenant_id="tenant-b", age_seconds=3600, now=now),),
        now=now,
    )
    _raises(
        GroundingViolation,
        lambda: GroundingPolicy(now=now).check(
            _request(tenant_id="tenant-a", evidence=evidence, now=now)
        ),
    )


def test_ready_false_for_foreign_item_tenant() -> None:
    # The non-raising ``ready`` mirror must also fail closed when a single item
    # carries a foreign tenant_id, even though the set label matches.
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        tenant_id="tenant-a",
        items=(
            _item("r-own", tenant_id="tenant-a", now=now),
            _item("r-foreign", tenant_id="tenant-b", now=now),
        ),
        now=now,
    )
    assert GroundingPolicy(now=now).ready(
        _request(tenant_id="tenant-a", evidence=evidence, now=now)
    ) is False


def test_homogeneous_item_tenants_pass() -> None:
    # Guard against over-rejection: a set whose every item matches the set and
    # request tenant still passes the gate (no false positives from the new
    # per-item check).
    now = datetime.now(timezone.utc)
    evidence = _evidence(
        tenant_id="tenant-a",
        items=(
            _item("r-1", tenant_id="tenant-a", now=now),
            _item("r-2", tenant_id="tenant-a", now=now),
        ),
        now=now,
    )
    assert GroundingPolicy(now=now).check(
        _request(tenant_id="tenant-a", evidence=evidence, now=now)
    ) is None


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


def test_mixed_fresh_and_stale_set_raises_stale() -> None:
    # ANY stale item fails the gate: a mixed set with one fresh + one stale
    # item is rejected (synthesis must not ground on stale evidence).
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
    _raises(StaleEvidence, lambda: policy.check(_request(evidence=mixed, now=now)))


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


def test_real_clock_read_per_check_when_now_not_injected() -> None:
    """A policy with no injected ``now`` reads the real clock on every check.

    The freshness gate must use the clock at check time, not at construction: a
    long-lived policy (``SynthesisService`` reuses its engine) must reject
    evidence that aged past ``max_age_seconds`` after the policy was built. The
    previous implementation captured ``datetime.now(timezone.utc)`` once at
    init and reused it forever, so evidence collected after startup appeared
    future-dated and never went stale. This test swaps the module's ``datetime``
    binding to a fixed clock and advances it between two ``check`` calls on the
    SAME policy + evidence: the second call must see the evidence as stale.
    """
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=301)

    class _FixedClock:
        current = t0

        @classmethod
        def now(cls, tz=timezone.utc):
            return cls.current

    real_datetime = grounding_module.datetime
    grounding_module.datetime = _FixedClock
    try:
        policy = GroundingPolicy(max_age_seconds=300)  # now intentionally omitted
        evidence = _evidence(items=(_item("r-1", age_seconds=100, now=t0),), now=t0)
        # Fresh at construction time (age 100s < max_age 300s).
        assert policy.check(_request(evidence=evidence, now=t0)) is None
        # Time advances past the freshness bound; the SAME policy + evidence is
        # now stale — proving the real clock is read per check.
        _FixedClock.current = t1
        _raises(StaleEvidence, lambda: policy.check(_request(evidence=evidence, now=t1)))
    finally:
        grounding_module.datetime = real_datetime


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
