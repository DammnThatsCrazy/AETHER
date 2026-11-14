"""Registry lifecycle, review validity, calibration and the service workflow."""
from __future__ import annotations

import asyncio

import pytest

from intelligence.pattern_discovery.baselines import empty_baseline
from intelligence.pattern_discovery.contracts import (
    KIND_CROSS_DOMAIN, KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, STATUS_BENIGN, STATUS_CONFIRMED_MALICIOUS,
    STATUS_DEPRECATED, STATUS_SURFACED, STATUS_PROMOTED, STALE_AFTER_RUNS,
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

from .scenarios import T, FakeEventReader, FakeRiskStore, consent_reader, fraud_ring, normal_traffic, ring_keys


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
    check_transition("candidate", "surfaced")
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

def _service(rows, risk_store=None, resolver=None, consent=None):
    async def default_resolver(tenant_id, key):
        return ("entity", key.split(":", 1)[1]) if key.startswith("user:r") else None

    return PatternDiscoveryService(event_reader=FakeEventReader(rows), risk_store=risk_store or FakeRiskStore(),
                                   subject_resolver=resolver or default_resolver,
                                   consent_reader=consent or consent_reader())


@pytest.mark.asyncio
async def test_service_end_to_end_review_feedback_and_promotion():
    svc = _service(normal_traffic(1, 1))
    first = await svc.run(T)
    assert first["patterns_detected"] == 0 and first["baseline_updated"]
    svc._event_reader = FakeEventReader(normal_traffic(2, 2) + fraud_ring(2))
    second = await svc.run(T)
    assert second["patterns_detected"] >= 5
    queue = await svc.list_patterns(T, feed=True)
    assert queue["total"] >= 5 and all(i["status"] == STATUS_SURFACED for i in queue["items"])
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


@pytest.mark.asyncio
async def test_promotion_withholds_signals_without_consent():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2), consent=consent_reader(frozenset({"r0", "r1"})))
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    await svc.review(T, pid, reviewer_id="a", verdict="malicious", reason="shared card farm confirmed")
    promoted = await svc.promote(T, pid, reviewer_id="a", reason="promote with partial consent")
    by_entity = {o["entity"]: o for o in promoted["promotion"]["risk_signals"]}
    assert by_entity["user:r0"]["status"] == "consent_withheld"
    assert by_entity["user:r2"]["status"] == "written" and by_entity["user:r2"]["consent_receipt_id"] == "rcpt-r2"
    assert not any(row["subject_id"] in ("r0", "r1") for row in svc._risk_store.rows.values())


@pytest.mark.asyncio
async def test_entity_context_is_withheld_without_consent():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2), consent=consent_reader(frozenset({"r3"})))
    await svc.run(T)
    denied = await svc.entity_context(T, "user:r3")
    assert denied["withheld"] is True and denied["emerging_patterns"] == []
    granted = await svc.entity_context(T, "user:r4")
    assert granted["withheld"] is False and granted["emerging_patterns"]


@pytest.mark.asyncio
async def test_consent_lookup_failure_fails_closed():
    async def broken(**kwargs):
        raise RuntimeError("consent store down")

    svc = _service(normal_traffic(2, 2) + fraud_ring(2), consent=broken)
    await svc.run(T)
    ctx = await svc.entity_context(T, "user:r3")
    assert ctx["withheld"] is True and ctx["reason_code"] == "consent_lookup_failed"


# ── DSR erasure ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_erasure_redacts_the_subject_and_drops_patterns_it_would_reidentify(monkeypatch):
    from intelligence.pattern_discovery.erasure import erase_pattern_discovery

    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    before = {r["pattern_id"]: r for r in await svc.registry.scan(T)}
    named = [p for p in before.values() if "user:r0" in p["affected_entity_keys"]]
    assert named
    result = await erase_pattern_discovery(T, frozenset({"r0"}))
    assert result["status"] == "completed" and result["records_impacted"] >= len(named)
    after = {r["pattern_id"]: r for r in await svc.registry.scan(T)}
    import json as _json
    for pid in [p["pattern_id"] for p in named]:
        row = after.get(pid)
        if row is None:
            continue  # deleted: fewer than two entities remained
        assert "user:r0" not in row["affected_entity_keys"]
        assert '"user:r0"' not in _json.dumps(row)
        assert row["affected_entity_count"] == before[pid]["affected_entity_count"] - 1
        assert row["erasure_redactions"] == 1
    # Another subject's patterns are untouched; another tenant is untouched.
    untouched = [p for p in before.values() if "user:r0" not in p["affected_entity_keys"]]
    for p in untouched:
        assert after[p["pattern_id"]]["affected_entity_keys"] == p["affected_entity_keys"]
    again = await erase_pattern_discovery(T, frozenset({"r0"}))
    assert again["records_impacted"] == 0


@pytest.mark.asyncio
async def test_erasure_deletes_patterns_left_with_one_entity():
    from intelligence.pattern_discovery.erasure import erase_pattern_discovery

    repo = PatternRegistryRepository()
    rec = dict(_by_kind(_ring_records(), KIND_SEQUENCE))
    rec["affected_entity_keys"] = ["user:r0", "user:r1"]
    rec["affected_entities"] = [{"kind": "user", "id": "r0", "key": "user:r0"}, {"kind": "user", "id": "r1", "key": "user:r1"}]
    rec["affected_entity_count"] = 2
    await repo.upsert_detected(rec)
    out = await erase_pattern_discovery(T, frozenset({"r0"}))
    assert out["detail"]["patterns_deleted"] == 1
    assert await repo.get(T, rec["pattern_id"]) is None


@pytest.mark.asyncio
async def test_erasure_respects_legal_hold(monkeypatch):
    from intelligence.pattern_discovery import erasure
    from shared.storage import lifecycle

    async def hold(self, tenant_id, resource_type, subject_ref=None):
        return {"hold_id": "h1", "reason": "litigation"} if subject_ref == "user:r0" else None

    monkeypatch.setattr(lifecycle.StorageLifecycle, "active_hold", hold)
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    before = await svc.registry.scan(T)
    out = await erasure.erase_pattern_discovery(T, frozenset({"r0"}))
    assert out["status"] == "skipped_legal_hold"
    assert await svc.registry.scan(T) == before


@pytest.mark.asyncio
async def test_pattern_discovery_is_a_registered_dsr_component():
    from governance.consent import erasure_planes
    from governance.dsr_propagation.models import DSR_COMPONENTS

    assert "pattern_discovery" in DSR_COMPONENTS
    assert any("pattern_discovery" in comps for _n, comps, _p in erasure_planes.ENTITY_PLANES)


@pytest.mark.asyncio
async def test_erasure_scrubs_refs_embedded_in_signature_title_and_summary():
    from intelligence.pattern_discovery.erasure import erase_pattern_discovery

    repo = PatternRegistryRepository()
    rec = dict(_by_kind(_ring_records(), KIND_SEQUENCE))
    rec["pattern_id"] = f"{T}:pat:spawn-test"
    rec["signature"] = {"parent": "agent:orch"}
    rec["title"] = "Sub-agent spawning anomaly at agent:orch"
    rec["summary"] = "agent:orch spawned 12 sub-agents; principals: user:p1"
    rec["affected_entity_keys"] = ["agent:orch", "agent:w1", "agent:w2"]
    rec["affected_entities"] = [{"kind": "agent", "id": i, "key": f"agent:{i}"} for i in ("orch", "w1", "w2")]
    rec["affected_entity_count"] = 3
    await repo.upsert_detected(rec)
    await erase_pattern_discovery(T, frozenset({"orch"}))
    row = await repo.get(T, rec["pattern_id"])
    import json as _json
    assert "agent:orch" not in _json.dumps(row)
    assert row["signature_hash"] == rec["signature_hash"]
    assert row["title"] == "Sub-agent spawning anomaly at [erased]"


def test_a_queued_pattern_stays_queued_when_its_novelty_decays():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    assert rec["status"] == STATUS_SURFACED
    familiar = dict(rec, status="candidate", priority="low", last_run_id="r2")
    merged = merge_redetection(rec, familiar)
    assert merged["status"] == STATUS_SURFACED and merged["surfaced_at"]


@pytest.mark.asyncio
async def test_overlapping_windows_fold_into_the_baseline_once():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    first = await svc.run(T)
    second = await svc.run(T)  # same events, same window end
    assert first["baseline_updated"] is True
    assert second["baseline_updated"] is False
    assert second["coverage"]["baseline"]["status"] == "skipped_overlapping_window"
    assert (await svc.baselines.get(T))["runs"] == 1
    svc._event_reader = FakeEventReader(normal_traffic(5, 5))  # three days later
    assert (await svc.run(T))["baseline_updated"] is True


# ── Surfaced by default; curation is optional ───────────────────────────────

@pytest.mark.asyncio
async def test_patterns_reach_the_lenses_with_no_human_step():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    feed = await svc.list_patterns(T, feed=True)
    assert feed["total"] >= 5 and all(i["status"] == "surfaced" for i in feed["items"])
    section = await svc.section(T, "user:r0", "profile360")
    assert section["emerging_patterns"] and section["counts"]["surfaced"] >= 1


@pytest.mark.asyncio
async def test_hide_unhide_pin_and_rename():
    from intelligence.pattern_discovery.registry import LifecycleError as _LE

    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    items = (await svc.list_patterns(T, feed=True))["items"]
    a, b = items[0]["pattern_id"], items[1]["pattern_id"]
    hidden = await svc.curate(T, a, actor="u1", action="hide", reason="known QA traffic")
    assert hidden["status"] == "hidden" and hidden["hidden_from_status"] == "surfaced"
    assert a not in {i["pattern_id"] for i in (await svc.list_patterns(T, feed=True))["items"]}
    section = await svc.section(T, "user:r0", "risk360")
    assert a not in {f["pattern_id"] for f in section["pattern_findings"]}
    restored = await svc.curate(T, a, actor="u1", action="unhide")
    assert restored["status"] == "surfaced" and "hidden_from_status" not in restored
    await svc.curate(T, b, actor="u1", action="pin")
    renamed = await svc.curate(T, b, actor="u1", action="rename", title="Card farm on two devices")
    feed = (await svc.list_patterns(T, feed=True))["items"]
    assert feed[0]["pattern_id"] == b and feed[0]["title"] == "Card farm on two devices"
    assert renamed["title"] != renamed["display_title"]  # the detector title is kept
    with pytest.raises(_LE):
        await svc.curate(T, b, actor="u1", action="rename", title="  ")
    with pytest.raises(_LE):
        await svc.curate(T, b, actor="u1", action="unhide")
    stats = await svc.stats(T)
    assert stats["calibration"][hidden["kind"]]["noise"] >= 1  # hiding teaches the detector


@pytest.mark.asyncio
async def test_hidden_and_pinned_survive_redetection_until_the_pattern_changes():
    rec = _by_kind(_ring_records(), KIND_SEQUENCE)
    from intelligence.pattern_discovery.registry import apply_curation

    hidden = apply_curation(apply_curation(rec, actor="u", action="pin"), actor="u", action="hide")
    same = merge_redetection(hidden, dict(rec, last_run_id="r2"))
    assert same["status"] == "hidden" and same["pinned"] is True
    grown = merge_redetection(hidden, dict(rec, last_run_id="r3", evidence_fingerprint="grew-by-10x"))
    assert grown["status"] == rec["status"]
    assert grown["review_history"][-1]["decision"] == "resurfaced_after_material_change"


@pytest.mark.asyncio
async def test_erasure_scrubs_merged_duplicate_contributions_and_survives_redetection():
    from intelligence.pattern_discovery.erasure import erase_pattern_discovery
    from intelligence.pattern_discovery.registry import merge_duplicate

    import json as _json

    repo = PatternRegistryRepository()
    base = dict(_by_kind(_ring_records(), KIND_SEQUENCE))
    base["pattern_id"] = f"{T}:pat:canonical"
    base["affected_entity_keys"] = ["user:a", "user:b", "user:c"]
    base["affected_entities"] = [{"kind": "user", "id": i, "key": f"user:{i}"} for i in "abc"]
    base["affected_entity_count"] = 3
    dup = dict(base, pattern_id=f"{T}:pat:dup", affected_entity_keys=["user:x", "user:a"],
               affected_entity_count=2, evidence_fingerprint="fp-dup")
    merged = merge_duplicate(base, dup)
    assert "user:x" in merged["affected_entity_keys"]
    await repo.upsert_detected(merged)
    await erase_pattern_discovery(T, frozenset({"x"}))
    row = await repo.get(T, base["pattern_id"])
    assert "user:x" not in _json.dumps(row)            # gone from duplicates and base state too
    # Re-detection re-folds the duplicate contributions: the subject must not return.
    again = merge_redetection(row, dict(base))
    assert "user:x" not in again["affected_entity_keys"]
    assert "user:x" not in _json.dumps(again)


@pytest.mark.asyncio
async def test_erasure_finds_a_subject_held_only_in_duplicate_state():
    from intelligence.pattern_discovery.erasure import names_subject

    row = {"affected_entity_keys": ["user:a", "user:b"],
           "duplicates": [{"pattern_id": "d", "entity_keys": ["user:z"]}]}
    assert names_subject(row, {"user:z"})


class _DownReader:
    async def query_events(self, tenant_id, params, limit=100):
        raise ConnectionError("analytics store down")


@pytest.mark.asyncio
async def test_a_failed_evidence_read_never_ages_or_deprecates_patterns():
    svc = _service(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    before = {r["pattern_id"]: r for r in await svc.registry.scan(T)}
    assert before
    svc._event_reader = _DownReader()
    for _ in range(STALE_AFTER_RUNS + 1):
        out = await svc.run(T)
        assert out["coverage"]["store"] == "unavailable"
        assert out["coverage"]["aging"]["status"] == "skipped_store_unavailable"
    after = {r["pattern_id"]: r for r in await svc.registry.scan(T)}
    assert all(after[pid]["status"] == before[pid]["status"] for pid in before)
    assert not any(r["status"] == STATUS_DEPRECATED for r in after.values())


@pytest.mark.asyncio
async def test_the_scheduled_run_fails_when_the_evidence_store_is_unavailable(monkeypatch):
    from types import SimpleNamespace

    from intelligence.pattern_discovery import jobs, service as service_mod

    svc = _service([])
    svc._event_reader = _DownReader()
    monkeypatch.setattr(service_mod, "get_service", lambda: svc)
    outcome = await jobs.run_job({}, SimpleNamespace(tenant_id=T))
    assert outcome.status == "failed" and outcome.error == "event_store_unavailable"
    svc._event_reader = FakeEventReader(normal_traffic(1, 1))
    assert (await jobs.run_job({}, SimpleNamespace(tenant_id=T))).status == "succeeded"


class _FlakyRiskStore(FakeRiskStore):
    def __init__(self):
        super().__init__()
        self.down = True

    async def upsert_scoped(self, tenant_id, natural_id, data):
        if self.down:
            raise ConnectionError("risk store down")
        return await super().upsert_scoped(tenant_id, natural_id, data)


@pytest.mark.asyncio
async def test_a_promotion_retries_projections_a_transient_outage_left_incomplete():
    store = _FlakyRiskStore()
    svc = _service(normal_traffic(2, 2) + fraud_ring(2), risk_store=store)
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_CROSS_DOMAIN))["items"][0]["pattern_id"]
    await svc.review(T, pid, reviewer_id="a", verdict="malicious", reason="ring confirmed with chargebacks")
    first = await svc.promote(T, pid, reviewer_id="a", reason="standing risk signal for the ring")
    assert first["status"] == STATUS_PROMOTED
    assert {o["status"] for o in first["promotion"]["risk_signals"]} == {"failed"}
    assert store.rows == {}
    store.down = False
    retried = await svc.promote(T, pid, reviewer_id="a", reason="retry after the risk store recovered")
    assert retried["status"] == STATUS_PROMOTED
    assert {o["status"] for o in retried["promotion"]["risk_signals"]} == {"written"}
    assert retried["promotion"]["projection_retries"] == 1 and store.rows
    # Complete projections are not re-run, and no second lifecycle transition is recorded.
    again = await svc.promote(T, pid, reviewer_id="a", reason="nothing left to retry here")
    assert again["promotion"]["projection_retries"] == 1
    assert sum(1 for h in again["review_history"] if h.get("decision") == "promote") == 1


def test_a_redetected_duplicate_refreshes_its_contribution_when_members_change():
    from intelligence.pattern_discovery.registry import merge_duplicate

    base = dict(_by_kind(_ring_records(), KIND_SEQUENCE), affected_entity_keys=["user:a", "user:z"],
                affected_entity_count=2, occurrence_count=5)
    dup = dict(base, pattern_id=f"{T}:pat:dup", affected_entity_keys=["user:b", "user:c"],
               affected_entity_count=2, occurrence_count=2, evidence_fingerprint="same")
    merged = merge_duplicate(base, dup)
    assert {"user:b", "user:c"} <= set(merged["affected_entity_keys"])
    drifted = dict(dup, affected_entity_keys=["user:b", "user:d"], occurrence_count=12)  # same fingerprint
    again = merge_duplicate(merged, drifted)
    assert "user:d" in again["affected_entity_keys"] and "user:c" not in again["affected_entity_keys"]
    assert again["occurrence_count"] == 5 + 12
