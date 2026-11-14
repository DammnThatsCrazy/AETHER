"""Registry lifecycle, review validity, calibration and the service workflow."""
from __future__ import annotations

import asyncio

import pytest

from intelligence.pattern_discovery.baselines import empty_baseline
from intelligence.pattern_discovery.contracts import (
    KIND_CROSS_DOMAIN, KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, STATUS_BENIGN, STATUS_CONFIRMED_MALICIOUS,
    STATUS_DEPRECATED, STATUS_NEEDS_REVIEW, STATUS_PROMOTED, STALE_AFTER_RUNS,
)
from intelligence.pattern_discovery.engine import run_discovery
from intelligence.pattern_discovery.projections import entity_context, pattern_risk_signals
from intelligence.pattern_discovery.registry import (
    LifecycleError, PatternRegistryRepository, apply_promotion, apply_review, check_transition,
    merge_redetection,
)
from intelligence.pattern_discovery.scoring import calibration_factors, suppressed_families
from intelligence.pattern_discovery.service import PatternDiscoveryService
from repositories.repos import reset_in_memory_stores
from shared.contracts_models.epistemic import EpistemicStatus

from .scenarios import T, FakeEventReader, FakeRiskStore, fraud_ring, normal_traffic, ring_keys


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _ring_records():
    first = run_discovery(T, normal_traffic(1, 1), baseline=empty_baseline(T))
    baseline = first.apply_to_baseline(empty_baseline(T))
    return run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=baseline).records


def _by_kind(records, kind):
    return next(r for r in records if r["kind"] == kind)


# ── Pure lifecycle ───────────────────────────────────────────────────────────

def test_only_a_human_verdict_leaves_the_funnel_and_needs_a_reason():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    with pytest.raises(LifecycleError):
        apply_review(rec, reviewer_id="", verdict="malicious", reason="looks like card testing")
    with pytest.raises(LifecycleError):
        apply_review(rec, reviewer_id="a1", verdict="malicious", reason="short")
    with pytest.raises(LifecycleError):
        apply_review(rec, reviewer_id="a1", verdict="duplicate", reason="same as the other one")
    reviewed = apply_review(rec, reviewer_id="a1", verdict="malicious", reason="card testing ring, case 77")
    assert reviewed["status"] == STATUS_CONFIRMED_MALICIOUS
    assert reviewed["reviewed_fingerprint"] == rec["evidence_fingerprint"]
    assert reviewed["review_history"][-1]["decision"] == "malicious"


def test_promotion_requires_confirmation_and_unchanged_evidence():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    with pytest.raises(LifecycleError):
        apply_promotion(rec, reviewer_id="a1", reason="promote straight from the queue")
    benign = apply_review(rec, reviewer_id="a1", verdict="benign", reason="QA traffic from the test lab")
    with pytest.raises(LifecycleError):
        apply_promotion(benign, reviewer_id="a1", reason="promote a benign pattern")
    ok = apply_review(rec, reviewer_id="a1", verdict="valid", reason="confirmed with the payments team")
    drifted = dict(ok, evidence_fingerprint="changed")
    with pytest.raises(LifecycleError):
        apply_promotion(drifted, reviewer_id="a1", reason="evidence moved after review")
    promoted = apply_promotion(ok, reviewer_id="a1", reason="becomes a standing risk signal")
    assert promoted["status"] == STATUS_PROMOTED and promoted["promotion"]["verdict"] == "valid"


def test_illegal_transitions_are_refused():
    check_transition("candidate", "needs_review")
    with pytest.raises(LifecycleError):
        check_transition("candidate", "promoted")
    with pytest.raises(LifecycleError):
        check_transition("promoted", "confirmed_valid")
    with pytest.raises(LifecycleError):
        check_transition("deprecated", "confirmed_malicious")


def test_redetection_keeps_a_review_only_for_the_same_evidence():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    benign = apply_review(rec, reviewer_id="a1", verdict="benign", reason="known retry behaviour in app v3")
    same = merge_redetection(benign, dict(rec, last_run_id="run2"))
    assert same["status"] == STATUS_BENIGN and same["times_observed"] == 2 and same["version"] == 1
    grown = dict(rec, last_run_id="run3", affected_entity_count=400,
                 evidence_fingerprint="different-because-it-grew")
    superseded = merge_redetection(benign, grown)
    assert superseded["status"] == rec["status"]
    assert superseded["review_history"][-1]["decision"] == "superseded"
    assert superseded["version"] == 2


def test_promoted_patterns_are_sticky_known_patterns():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    promoted = apply_promotion(apply_review(rec, reviewer_id="a", verdict="malicious", reason="card testing confirmed"),
                               reviewer_id="a", reason="standing signal for this ring")
    again = merge_redetection(promoted, dict(rec, last_run_id="r9"))
    assert again["status"] == STATUS_PROMOTED and again["priority"] == "low"


def test_calibration_and_family_suppression():
    feedback = {"kinds": {"sequence": {"benign": 6}, "lockstep": {"malicious": 5}},
                "families": {"sequence:abc": {"benign": 3}, "lockstep:x": {"benign": 3, "valid": 1}}}
    cal = calibration_factors(feedback)
    assert cal["sequence"]["factor"] < 1.0 < cal["lockstep"]["factor"]
    assert suppressed_families(feedback) == {"sequence:abc"}


def test_analyst_feedback_changes_future_scoring():
    first = run_discovery(T, normal_traffic(1, 1), baseline=empty_baseline(T))
    baseline = first.apply_to_baseline(empty_baseline(T))
    rows = normal_traffic(2, 2) + fraud_ring(2)
    plain = _by_kind(run_discovery(T, rows, baseline=baseline).records, KIND_SEQUENCE)
    family = plain["family"]
    noisy = {"kinds": {"sequence": {"benign": 8}}, "families": {family: {"benign": 3}}}
    damped = _by_kind(run_discovery(T, rows, baseline=baseline, feedback=noisy).records, KIND_SEQUENCE)
    assert damped["confidence"] < plain["confidence"]
    assert damped["suppressed_by_feedback"] and damped["status"] == "candidate" and damped["priority"] == "low"


# ── Risk projection ──────────────────────────────────────────────────────────

def test_unreviewed_patterns_never_become_risk_signals():
    rec = _by_kind(_ring_records(), KIND_SHARED_ATTRIBUTE)
    assert pattern_risk_signals(rec, subject_kind="entity", subject_id="r0") == []


def test_confirmed_patterns_become_attributed_never_verified_signals():
    rec = _by_kind(_ring_records(), KIND_SHARED_ATTRIBUTE)
    confirmed = apply_review(rec, reviewer_id="a", verdict="malicious", reason="shared card farm confirmed")
    sigs = pattern_risk_signals(confirmed, subject_kind="entity", subject_id="r0", source_entity_key="user:r0")
    assert sigs and all(s.claim_state is EpistemicStatus.ATTRIBUTED for s in sigs)
    assert {s.risk_dimension for s in sigs} <= set(confirmed["risk_categories"]) | {"behavioral"}
    again = pattern_risk_signals(confirmed, subject_kind="entity", subject_id="r0", source_entity_key="user:r0")
    assert [s.signal_id for s in sigs] == [s.signal_id for s in again]
    with pytest.raises(ValueError):
        pattern_risk_signals(confirmed, subject_kind="entity", subject_id="zz", source_entity_key="user:zz")


def test_risk360_producer_registry_knows_pattern_discovery():
    from intelligence.risk360.signals import KNOWN_PRODUCERS, adapt_producer_signal

    assert "pattern_discovery" in KNOWN_PRODUCERS
    rec = apply_review(_by_kind(_ring_records(), KIND_SEQUENCE), reviewer_id="a", verdict="valid",
                       reason="confirmed by the analyst on call")
    out = adapt_producer_signal("pattern_discovery", rec, subject_kind="entity", subject_id="r1", tenant_id=T)
    assert out and out[0].source.startswith("pattern_discovery.sequence")
    with pytest.raises(ValueError):
        adapt_producer_signal("pattern_discovery", rec, subject_kind="entity", subject_id="r1", tenant_id="other")


def test_entity_context_is_advisory():
    records = _ring_records()
    ctx = entity_context("user:r3", [r for r in records if "user:r3" in r["affected_entity_keys"]])
    assert ctx["advisory"] is True and ctx["claim_state"] == "inferred"
    assert ctx["counts"]["open"] >= 4
    assert {c["entity"] for c in ctx["co_implicated_entities"]} <= ring_keys() | {f"user:u{i}" for i in range(200)}
    assert ctx["unresolved_identity_overlaps"]


# ── Service workflow ─────────────────────────────────────────────────────────

def _service(rows, risk_store=None, resolver=None):
    async def default_resolver(tenant_id, key):
        return ("entity", key.split(":", 1)[1]) if key.startswith("user:r") else None

    return PatternDiscoveryService(event_reader=FakeEventReader(rows), risk_store=risk_store or FakeRiskStore(),
                                   subject_resolver=resolver or default_resolver)


@pytest.mark.asyncio
async def test_service_end_to_end_review_feedback_and_promotion():
    svc = _service(normal_traffic(1, 1))
    first = await svc.run(T)
    assert first["patterns_detected"] == 0 and first["baseline_updated"]
    svc._event_reader = FakeEventReader(normal_traffic(2, 2) + fraud_ring(2))
    second = await svc.run(T)
    assert second["patterns_detected"] >= 5
    queue = await svc.list_patterns(T, queue=True)
    assert queue["total"] >= 5 and all(i["status"] == STATUS_NEEDS_REVIEW for i in queue["items"])
    composite = next(i for i in (await svc.list_patterns(T, kind=KIND_CROSS_DOMAIN))["items"])
    detail = await svc.get_pattern(T, composite["pattern_id"])
    assert detail["members"] and detail["similar_patterns"]

    reviewed = await svc.review(T, composite["pattern_id"], reviewer_id="analyst-1", verdict="malicious",
                                reason="card-testing ring confirmed with chargebacks")
    assert reviewed["status"] == STATUS_CONFIRMED_MALICIOUS
    stats = await svc.stats(T)
    assert stats["feedback"]["total"] == 1 and stats["calibration"][KIND_CROSS_DOMAIN]["useful"] == 1

    promoted = await svc.promote(T, composite["pattern_id"], reviewer_id="admin-1",
                                 reason="standing risk signal for the ring members")
    assert promoted["status"] == STATUS_PROMOTED
    outcomes = promoted["promotion"]["risk_signals"]
    assert {o["status"] for o in outcomes} == {"written"}
    assert len(svc._risk_store.rows) >= len(ring_keys())
    assert all(row["claim_state"] == "attributed" for row in svc._risk_store.rows.values())


@pytest.mark.asyncio
async def test_unresolvable_subjects_get_no_risk_signal():
    async def nobody(tenant_id, key):
        return None

    svc = _service(normal_traffic(2, 2) + fraud_ring(2), resolver=nobody)
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    await svc.review(T, pid, reviewer_id="a", verdict="valid", reason="shared infrastructure confirmed")
    promoted = await svc.promote(T, pid, reviewer_id="a", reason="promote even though nothing resolves")
    assert promoted["promotion"]["risk_projection"] == "no_resolvable_subjects"
    assert svc._risk_store.rows == {}


@pytest.mark.asyncio
async def test_open_patterns_go_stale_and_reviewed_ones_do_not():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    items = (await svc.list_patterns(T))["items"]
    keep = next(i for i in items if i["kind"] == KIND_SEQUENCE)["pattern_id"]
    await svc.review(T, keep, reviewer_id="a", verdict="unresolved", reason="need more data before deciding")
    svc._event_reader = FakeEventReader(normal_traffic(3, 3))
    for _ in range(STALE_AFTER_RUNS):
        await svc.run(T)
    rows = {r["pattern_id"]: r for r in await svc.registry.scan(T)}
    assert rows[keep]["status"] == "unresolved"
    assert any(r["status"] == STATUS_DEPRECATED and r["review_history"][-1]["decision"] == "deprecate_stale"
               for r in rows.values())


@pytest.mark.asyncio
async def test_inline_evidence_from_another_tenant_is_rejected():
    svc = _service([])
    out = await svc.run(T, include_store=False, events=fraud_ring(2, tenant="other"))
    assert out["coverage"]["inline_foreign_rows_rejected"] == len(fraud_ring(2))
    assert out["patterns_detected"] == 0


@pytest.mark.asyncio
async def test_tenants_never_see_each_others_patterns():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    pid = (await svc.list_patterns(T))["items"][0]["pattern_id"]
    assert await svc.get_pattern("other", pid) is None
    assert (await svc.list_patterns("other"))["total"] == 0
    assert await svc.review("other", pid, reviewer_id="a", verdict="benign", reason="cross tenant attempt") is None


@pytest.mark.asyncio
async def test_concurrent_reviews_are_both_recorded():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_SEQUENCE))["items"][0]["pattern_id"]
    await asyncio.gather(
        svc.review(T, pid, reviewer_id="a", verdict="unresolved", reason="first reviewer needs more data"),
        svc.review(T, pid, reviewer_id="b", verdict="malicious", reason="second reviewer saw chargebacks"),
    )
    row = await svc.registry.get(T, pid)
    assert [h["reviewer_id"] for h in row["review_history"]][-2:] in (["a", "b"], ["b", "a"])


@pytest.mark.asyncio
async def test_repository_reads_are_copies():
    repo = PatternRegistryRepository()
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    await repo.upsert_detected(rec)
    got = await repo.get(T, rec["pattern_id"])
    got["status"] = "promoted"
    assert (await repo.get(T, rec["pattern_id"]))["status"] == rec["status"]
