"""Propagation & Diffusion lens: exposure -> adoption engine, adoption, exposures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import validate

from intelligence.propagation.adoption import adoptions_from_fill_events
from intelligence.propagation.contracts import (
    AdoptionEvent,
    ClaimType,
    EpisodeClassification,
    ExposureChannel,
    ExposureRef,
    PropagationQuery,
)
from intelligence.propagation.engine import compute_propagation
from intelligence.propagation.exposure import (
    exposure_edge_types,
    exposures_from_edges,
    exposures_from_in_app_events,
)

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "packages/shared/contracts/propagation-run.schema.json").read_text())
FIXTURES = ROOT / "services/api/tests/fixtures/provider_payloads/derivatives"
T = "tenant_prop"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
HYPE = "hyperliquid:mainnet:HYPE"


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def adopt(subject: str, minutes: float, *, instrument: str = HYPE, side: str = "long", tenant: str = T) -> AdoptionEvent:
    return AdoptionEvent(
        tenant_id=tenant, subject_id=subject, instrument_key=instrument, side=side,
        adopted_at=at(minutes), venue="hyperliquid", account_ref=f"0x{subject}",
        canonical_market_id=instrument, evidence_refs=(f"hyperliquid:fill:{subject}",),
    )


def follows(follower: str, followed: str, *, start: float = -10_000, tenant: str = T, evidence=True) -> dict:
    props = {
        "tenant_id": tenant, "relationship_predicate": "FOLLOWS", "valid_from": at(start),
        "idempotency_key": f"edge:{follower}:{followed}",
    }
    if evidence:
        props["evidence_refs"] = [{"id": f"ev:{follower}:{followed}"}]
    else:
        props.pop("idempotency_key")
    return {"type": "FOLLOWS_SOCIAL", "from": follower, "to": followed, "properties": props}


def query(**kw) -> PropagationQuery:
    base = dict(tenant_id=T, window_start=at(-60), window_end=at(24 * 60))
    base.update(kw)
    return PropagationQuery(**base)


def run(adoptions, edges=(), population=(), in_app=(), **kw):
    exposures, _ = exposures_from_edges(T, edges)
    app, _ = exposures_from_in_app_events(T, in_app)
    result = compute_propagation(query(**kw), adoptions, [*exposures, *app], population, computed_at=at(0))
    validate(result.to_dict(), SCHEMA)
    return result


POP = [f"u{i}" for i in range(1, 11)]


def test_follow_cascade_is_viral_with_radius_two():
    result = run(
        [adopt("u1", 0), adopt("u2", 60), adopt("u3", 120), adopt("u4", 180), adopt("u6", 200)],
        [follows("u2", "u1"), follows("u3", "u2"), follows("u4", "u1"), follows("u5", "u1")],
        POP,
    )
    (episode,) = result.episodes
    assert episode.seed_subject == "u1"
    assert episode.classification is EpisodeClassification.VIRAL
    assert episode.claim_type is ClaimType.INFERRED
    m = episode.metrics
    assert (m.adopters, m.exposed_adopters, m.independent_adopters) == (5, 3, 1)
    assert m.propagation_radius == 2 and m.max_breadth == 2
    assert m.channels == {"social": 3}
    assert m.median_lag_seconds == 3600
    b = episode.baseline
    assert (b.exposed, b.exposed_adopters, b.unexposed, b.unexposed_adopters) == (4, 3, 5, 1)
    assert b.lift == pytest.approx(3.75)
    deepest = next(p for p in episode.paths if p.target_subject == "u3")
    assert [h.from_subject for h in deepest.hops] == ["u1", "u2"]
    assert all(h.evidence_refs for h in deepest.hops)
    assert deepest.claim_type is ClaimType.OBSERVED
    assert 0 <= deepest.certified_depth <= deepest.depth
    assert deepest.influence is not None


def test_no_exposure_between_adopters_is_organic():
    edges = [follows("u5", "u1"), follows("u6", "u2"), follows("u7", "u3"), follows("u8", "u1")]
    result = run([adopt("u1", 0), adopt("u2", 90), adopt("u3", 300), adopt("u9", 400)], edges, POP)
    (episode,) = result.episodes
    assert episode.metrics.exposed_adopters == 0
    assert episode.metrics.propagation_radius == 0
    assert episode.classification is EpisodeClassification.ORGANIC
    assert episode.baseline.lift == 0


def test_lockstep_entries_are_coordinated():
    adoptions = [adopt(f"u{i}", i * 0.1) for i in range(1, 7)]
    result = run(adoptions, [follows("u9", "u1")], POP)
    (episode,) = result.episodes
    assert episode.classification is EpisodeClassification.COORDINATED
    assert "lockstep_entry_group" in episode.classification_reasons
    assert len(episode.coordination.lockstep_groups[0]) >= 5


def test_shared_onchain_funding_with_lockstep_entry_is_coordinated():
    pays = {"type": "PAYS", "from": "u1", "to": "u2", "properties": {
        "tenant_id": T, "relationship_predicate": "PAYS", "valid_from": at(-100),
        "evidence_refs": [{"id": "tx:1"}], "idempotency_key": "pays:1"}}
    result = run([adopt("u1", 0), adopt("u2", 0.5)], [pays], POP)
    (episode,) = result.episodes
    assert episode.coordination.shared_funding_pairs == (("u1", "u2"),)
    assert episode.classification is EpisodeClassification.COORDINATED


def test_single_adopter_and_missing_exposure_evidence_are_insufficient():
    single = run([adopt("u1", 0)], [follows("u2", "u1")], POP)
    assert single.episodes[0].classification is EpisodeClassification.INSUFFICIENT_DATA
    assert single.episodes[0].claim_type is ClaimType.OBSERVED
    blind = run([adopt("u1", 0), adopt("u2", 30)], [], POP)
    episode = blind.episodes[0]
    assert episode.classification is EpisodeClassification.INSUFFICIENT_DATA
    assert episode.metrics.propagation_radius is None  # unknown, not zero
    assert "no_exposure_evidence" in episode.metrics.unknown_reasons


def test_exposure_must_precede_adoption():
    late_edge = follows("u2", "u1", start=90)  # relationship began after u2 adopted
    result = run([adopt("u1", 0), adopt("u2", 60)], [late_edge], POP)
    assert result.episodes[0].metrics.exposed_adopters == 0


def test_in_app_exposure_must_fall_between_adoptions():
    def row(event_id, minutes):
        return {"tenant_id": T, "event_type": "content_impression", "subject_id": "u2",
                "exposed_subject_ref": "u1", "event_id": event_id, "timestamp": at(minutes)}

    before = run([adopt("u1", 0), adopt("u2", 60)], in_app=[row("e1", -5)], population=POP)
    assert before.episodes[0].metrics.exposed_adopters == 0
    between = run([adopt("u1", 0), adopt("u2", 60)], in_app=[row("e2", 30)], population=POP)
    episode = between.episodes[0]
    assert episode.metrics.exposed_adopters == 1
    assert episode.metrics.channels == {"in_app": 1}
    assert episode.paths[0].influence is None  # no governed graph edge behind an in-app event


def test_exposure_window_bounds_parents():
    result = run([adopt("u1", 0), adopt("u2", 5 * 24 * 60)], [follows("u2", "u1")], POP,
                 window_end=at(6 * 24 * 60))
    assert result.episodes[0].metrics.exposed_adopters == 0


def test_other_tenant_data_never_enters_a_run():
    foreign_edge = follows("u2", "u1", tenant="tenant_other")
    exposures, reasons = exposures_from_edges(T, [foreign_edge])
    assert exposures == [] and "exposure_edge_scope_mismatch" in reasons
    result = compute_propagation(
        query(), [adopt("u1", 0), adopt("u2", 10, tenant="tenant_other")],
        [ExposureRef("x", "tenant_other", "u1", "u2", ExposureChannel.SOCIAL, "FOLLOWS", at(-1), evidence_refs=("e",))],
        POP,
    )
    assert [a.subject_id for e in result.episodes for a in e.adopters] == ["u1"]


def test_event_contract_outcomes_are_separate_episodes():
    c = "polymarket:mainnet:0xcond"
    result = run([adopt("u1", 0, instrument=c, side="Yes"), adopt("u2", 10, instrument=c, side="No")],
                 [follows("u2", "u1")], POP)
    assert sorted(e.side for e in result.episodes) == ["No", "Yes"]
    assert all(e.metrics.exposed_adopters == 0 for e in result.episodes)


def test_runs_are_deterministic():
    args = ([adopt("u1", 0), adopt("u2", 60)], [follows("u2", "u1")], POP)
    first, second = run(*args), run(*args)
    assert first.run_id == second.run_id and first.input_digest == second.input_digest
    assert first.to_dict() == second.to_dict()


def test_edge_mapping_direction_evidence_and_exclusions():
    affinity = {"type": "SHARES_AFFINITY_WITH", "from": "a", "to": "b", "properties": {
        "tenant_id": T, "evidence_refs": [{"id": "x"}], "valid_from": at(0)}}
    exposures, reasons = exposures_from_edges(T, [follows("a", "b"), follows("c", "d", evidence=False), affinity])
    assert [(e.from_subject, e.to_subject, e.channel) for e in exposures] == [("b", "a", ExposureChannel.SOCIAL)]
    assert "exposure_edge_evidence_unavailable" in reasons
    assert "FOLLOWS_SOCIAL" in exposure_edge_types() and "SHARES_AFFINITY_WITH" not in exposure_edge_types()


# ── adoption from venue fills ────────────────────────────────────────────────


def fill(account, fid, side, minutes, *, market="hyperliquid:mainnet:HYPE", qty="1", direction=None, **extra):
    payload = {"venue_id": market.split(":")[0], "canonical_market_id": market,
               "trading_account_id": f"acct_{account}", "fill_id": fid, "side": side,
               "price": "10", "quantity": qty, "executed_at": at(minutes)}
    if direction:
        payload["direction"] = direction
    payload.update(extra)
    return {"event_name": "derivatives_fill_observed", "payload": payload}


def test_only_the_first_entry_counts_as_adoption():
    links = {("hyperliquid", "0xa"): "u1", ("hyperliquid", "0xb"): "u2"}
    events = [
        fill("0xa", "1", "buy", 0, direction="Open Long"),
        fill("0xa", "2", "buy", 5, direction="Open Long"),      # add to position: ignored
        fill("0xa", "3", "sell", 10, qty="2", direction="Close Long"),
        fill("0xa", "4", "sell", 20, direction="Open Short"),   # later re-entry: ignored
        fill("0xb", "5", "sell", 1, direction="Close Long"),    # history truncated: skipped
        fill("0xc", "6", "buy", 2, direction="Open Long"),      # unlinked account: ignored
    ]
    adoptions, reasons = adoptions_from_fill_events(T, events, links)
    assert [(a.subject_id, a.side, a.adopted_at) for a in adoptions] == [("u1", "long", at(0))]
    assert {"fill_history_truncated", "fill_account_not_linked"} <= reasons


def test_event_contract_adoption_uses_condition_and_outcome():
    cond = "polymarket:mainnet:0xcond"
    links = {("polymarket", "0xa"): "u1"}
    events = [
        fill("0xa", "1", "buy", 3, market="polymarket:mainnet:tokNo", instrument_type="event_contract",
             event_contract_ref=cond, outcome="No"),
        fill("0xa", "2", "buy", 1, market="polymarket:mainnet:tokYes", instrument_type="event_contract",
             event_contract_ref=cond, outcome="Yes"),
    ]
    adoptions, _ = adoptions_from_fill_events(T, events, links)
    assert [(a.instrument_key, a.side) for a in adoptions] == [(cond, "Yes")]


def test_live_polymarket_capture_yields_linked_adoptions():
    import asyncio

    import httpx

    from value.derivatives.adapters.polymarket import PolymarketAdapter

    pm = json.loads((FIXTURES / "polymarket_live_capture.json").read_text())

    def handler(request):
        if request.url.path.endswith("/v2/trades"):
            return httpx.Response(200, json=pm["trades"], request=request)
        return httpx.Response(200, json=pm["positions"], request=request)

    async def _noop(_):
        return None

    adapter = PolymarketAdapter(http_transport=httpx.MockTransport(handler), account_ref=pm["account_ref"], sleeper=_noop)
    events, _ = asyncio.run(adapter.pull_events())
    adoptions, _ = adoptions_from_fill_events(T, events, {("polymarket", pm["account_ref"]): "user_live"})
    assert adoptions, "live capture should contain at least one first-entry buy"
    assert all(a.subject_id == "user_live" and a.instrument_key.startswith("polymarket:mainnet:0x") for a in adoptions)
    assert len({a.instrument_key for a in adoptions}) == len(adoptions)


def test_subject_summary_lists_roles_and_paths():
    from intelligence.propagation.engine import subject_summary

    result = run([adopt("u1", 0), adopt("u2", 60), adopt("u3", 120)],
                 [follows("u2", "u1"), follows("u3", "u2")], POP)
    middle = subject_summary(result, "u2")
    assert [e["role"] for e in middle["episodes"]] == ["adopter"]
    assert [p["target_subject"] for p in middle["inbound_paths"]] == ["u2"]
    assert [p["target_subject"] for p in middle["outbound_paths"]] == ["u3"]
    seed = subject_summary(result, "u1")
    assert seed["seeded_episodes"] == 1 and seed["inbound_paths"] == []
    absent = subject_summary(result, "u9")
    assert absent["episodes"] == [] and absent["seeded_episodes"] == 0


def test_offsetless_exposure_time_is_unknown_not_assumed_utc():
    naive = ExposureRef("x1", T, "u1", "u2", ExposureChannel.SOCIAL, "FOLLOWS", "2026-10-01T00:00:00",
                        evidence_refs=("e",))
    result = compute_propagation(query(), [adopt("u1", 0), adopt("u2", 30)], [naive], POP, computed_at=at(0))
    episode = result.episodes[0]
    assert episode.metrics.exposed_adopters == 0
    assert "exposure_time_unknown" in episode.metrics.unknown_reasons


def test_mixed_utc_offsets_order_chronologically():
    early = AdoptionEvent(T, "u1", HYPE, "long", "2026-11-01T12:00:00+02:00", "hyperliquid", "0xu1", HYPE, ("f1",))
    late = AdoptionEvent(T, "u2", HYPE, "long", "2026-11-01T11:00:00+00:00", "hyperliquid", "0xu2", HYPE, ("f2",))
    result = compute_propagation(query(window_start="2026-11-01T00:00:00+00:00"), [late, early],
                                 exposures_from_edges(T, [follows("u2", "u1")])[0], POP, computed_at=at(0))
    (episode,) = result.episodes
    assert episode.seed_subject == "u1"  # 10:00Z precedes 11:00Z despite the string order
    assert episode.metrics.exposed_adopters == 1


def test_funding_after_the_entries_is_not_coordination_evidence():
    def pays(start):
        return {"type": "PAYS", "from": "u1", "to": "u2", "properties": {
            "tenant_id": T, "relationship_predicate": "PAYS", "valid_from": at(start),
            "evidence_refs": [{"id": f"tx:{start}"}], "idempotency_key": f"pays:{start}"}}

    later = run([adopt("u1", 0), adopt("u2", 0.5)], [pays(9 * 24 * 60)], POP)
    episode = later.episodes[0]
    assert episode.coordination.shared_funding_pairs == ()
    assert episode.classification is not EpisodeClassification.COORDINATED
    before = run([adopt("u1", 0), adopt("u2", 0.5)], [pays(-100)], POP)
    assert before.episodes[0].classification is EpisodeClassification.COORDINATED


def test_case_sensitive_account_refs_keep_exact_attribution():
    links = {("hyperliquid", "Account-X"): "alice", ("hyperliquid", "account-x"): "bob",
             ("hyperliquid", "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"): "carol"}
    events = [
        fill("Account-X", "1", "buy", 0, direction="Open Long"),
        fill("0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD", "2", "buy", 1, direction="Open Long"),
    ]
    adoptions, _ = adoptions_from_fill_events(T, events, links)
    assert sorted(a.subject_id for a in adoptions) == ["alice", "carol"]
