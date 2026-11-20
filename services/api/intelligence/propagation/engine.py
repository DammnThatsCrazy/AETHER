"""Pure exposure -> adoption propagation computation (read-only, deterministic).

Given one tenant's first-entry adoptions, exposures between its subjects, and
its linked population, this builds one :class:`DiffusionEpisode` per
``(instrument_key, side)`` group:

1. **Seed** — the earliest adopter in the group.
2. **Parents** — for each later adopter B, the earlier adopters A in the same
   group with a qualifying exposure A -> B: A adopted strictly before B, within
   ``exposure_window_seconds``, and the exposure was in force when B adopted.
   A standing relationship qualifies when it began on or before B's adoption
   and had not ended before A's. An in-app exposure must fall between A's and
   B's adoptions (B saw A's trade after A made it). The parent is the closest
   earlier qualifying adopter; more than one qualifying parent counts as
   repeated exposure. Adopters with no parent are independent roots.
3. **Paths** — root -> adopter chains of observed hops. Each path also carries
   the governed influence coverage from ``decompose_influence_propagation``;
   ``certified_depth`` is the longest prefix the predicate registry allows to
   carry influence.
4. **Metrics** — reach, exposed vs independent adopters, radius (max observed
   depth), certified radius, breadth, velocity, median lag, channels. Unknown
   stays ``None`` with a reason; measured zero stays zero.
5. **Baseline** — adoption rate among exposed linked subjects vs unexposed
   linked subjects in the same tenant, instrument, side, and window.
6. **Coordination** — lockstep groups (pattern discovery's lockstep semantics:
   many distinct subjects in one short window) and adopter pairs sharing an
   on-chain funding link who entered within the lockstep window.
7. **Classification** — ``coordinated`` when a coordination signal exists;
   otherwise ``viral`` when lift meets the threshold with enough exposed
   adopters, ``organic`` when the baseline is measurable and lift does not;
   ``insufficient_data`` otherwise. Classifications are ``inferred`` claims;
   ``causally_supported`` is never emitted.

Nothing here touches storage, the network, or the graph.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from intelligence.propagation.contracts import (
    AdoptionEvent,
    BaselineComparison,
    ClaimType,
    CoordinationSignal,
    DiffusionEpisode,
    EpisodeClassification,
    EpisodeMetrics,
    ExposureChannel,
    ExposureRef,
    InfluenceAssessment,
    PropagationHop,
    PropagationPath,
    PropagationQuery,
    PropagationRun,
    _plain,
)

LIMITATIONS: tuple[str, ...] = (
    "adoption_is_first_entry_within_observed_history",
    "exposure_requires_evidence_backed_relationship_or_in_app_event",
    "classification_is_inferred_not_causal",
    "tenant_scoped_population_only",
)


def _parse(value: Optional[str]) -> Optional[datetime]:
    """Strict instant parse: an ISO string without an explicit offset is unknown."""
    if not value:
        return None
    from shared.temporal.instant import try_parse_instant

    parsed, _error = try_parse_instant(str(value))
    return parsed


_FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _adoption_order(adoption: AdoptionEvent) -> tuple[datetime, str, str]:
    """Chronological order by parsed instant (ISO strings with different
    offsets do not sort chronologically); unparseable instants sort last."""
    return (_parse(adoption.adopted_at) or _FAR_FUTURE, adoption.adopted_at, adoption.subject_id)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _exposure_qualifies(
    exposure: ExposureRef, parent_at: datetime, child_at: datetime,
) -> Optional[bool]:
    """True/False when decidable; None when the exposure time is unknown."""
    observed = _parse(exposure.observed_at)
    if observed is None:
        return None
    if observed > child_at:
        return False
    if exposure.channel is ExposureChannel.IN_APP and observed < parent_at:
        return False
    valid_to = _parse(exposure.valid_to)
    if valid_to is not None and valid_to <= parent_at:
        return False
    return True


def _influence(hops: tuple[PropagationHop, ...], edges: list[Optional[dict]], as_of: str) -> tuple[Optional[InfluenceAssessment], int]:
    """Governed influence coverage for a path and its certified prefix depth."""
    if not hops or any(edge is None for edge in edges):
        return None, 0
    from shared.relationship_spine.influence_propagation import decompose_influence_propagation

    def run(k: int):
        return decompose_influence_propagation(
            list(edges[:k]), source_ref=hops[0].from_subject, target_ref=hops[k - 1].to_subject, as_of=as_of,
        )

    full = run(len(hops))
    certified = 0
    for k in range(1, len(hops) + 1):
        if run(k).propagation_certified:
            certified = k
        else:
            break
    return InfluenceAssessment(
        decision=str(full.decision),
        propagation_certified=bool(full.propagation_certified),
        available_component_ids=tuple(full.available_component_ids),
        reason_codes=tuple(sorted(str(r) for r in full.reason_codes)),
        algorithm=str(full.algorithm),
        version=str(full.version),
    ), certified


def _lockstep_groups(adopters: list[AdoptionEvent], window: int, min_entities: int) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    times = [(_parse(a.adopted_at), a.subject_id) for a in adopters]
    i = 0
    while i < len(times):
        start = times[i][0]
        members = [s for t, s in times[i:] if t is not None and start is not None and (t - start).total_seconds() <= window]
        if len(set(members)) >= min_entities:
            groups.append(tuple(sorted(set(members))))
            i += len(members)
        else:
            i += 1
    return groups


def _episode(
    query: PropagationQuery,
    instrument_key: str,
    side: str,
    adopters: list[AdoptionEvent],
    exposures_by_pair: dict[tuple[str, str], list[ExposureRef]],
    exposures_from: dict[str, list[ExposureRef]],
    population: set[str],
    any_exposure_evidence: bool,
) -> DiffusionEpisode:
    adopters = sorted(adopters, key=_adoption_order)
    at = {a.subject_id: _parse(a.adopted_at) for a in adopters}
    seed = adopters[0]
    unknown: set[str] = set()

    parent: dict[str, tuple[str, ExposureRef, int]] = {}
    repeated = 0
    for i, child in enumerate(adopters[1:], start=1):
        child_at = at[child.subject_id]
        qualifying: list[tuple[datetime, str, ExposureRef]] = []
        for candidate in adopters[:i]:
            cand_at = at[candidate.subject_id]
            if cand_at is None or child_at is None or not cand_at < child_at:
                continue
            if (child_at - cand_at).total_seconds() > query.exposure_window_seconds:
                continue
            options = []
            for exposure in exposures_by_pair.get((candidate.subject_id, child.subject_id), ()):
                verdict = _exposure_qualifies(exposure, cand_at, child_at)
                if verdict is None:
                    unknown.add("exposure_time_unknown")
                elif verdict:
                    options.append(exposure)
            if options:
                options.sort(key=lambda e: (e.observed_at or "", e.exposure_id))
                qualifying.append((cand_at, candidate.subject_id, options[0]))
        if not qualifying:
            continue
        if len(qualifying) > 1:
            repeated += 1
        qualifying.sort(key=lambda q: (q[0], q[1]), reverse=True)
        _, parent_id, exposure = qualifying[0]
        lag = int((child_at - at[parent_id]).total_seconds())
        parent[child.subject_id] = (parent_id, exposure, lag)

    depth: dict[str, int] = {}
    paths: list[PropagationPath] = []
    for adopter in adopters:
        chain: list[tuple[str, str, ExposureRef, int]] = []
        node = adopter.subject_id
        while node in parent and len(chain) < query.max_hops:
            p, exposure, lag = parent[node]
            chain.append((p, node, exposure, lag))
            node = p
        if node in parent:
            unknown.add("path_truncated_at_max_hops")
        depth[adopter.subject_id] = len(chain)
        if not chain:
            continue
        chain.reverse()
        hops = tuple(
            PropagationHop(
                from_subject=f, to_subject=t, exposure_id=e.exposure_id, channel=e.channel,
                predicate=e.predicate, lag_seconds=lag, evidence_refs=e.evidence_refs,
            )
            for f, t, e, lag in chain
        )
        influence, certified = _influence(
            hops, [e.graph_edge for _, _, e, _ in chain], query.as_of or adopter.adopted_at,
        )
        paths.append(PropagationPath(
            path_id="pp_" + _digest([query.tenant_id, instrument_key, side, [asdict(h) for h in hops]])[:24],
            seed_subject=hops[0].from_subject,
            target_subject=adopter.subject_id,
            hops=hops,
            depth=len(hops),
            certified_depth=certified,
            claim_type=ClaimType.OBSERVED,
            influence=influence,
        ))

    children: dict[str, int] = defaultdict(int)
    for p, _e, _lag in parent.values():
        children[p] += 1
    lags = [lag for _p, _e, lag in parent.values()]
    channels: dict[str, int] = defaultdict(int)
    for _p, exposure, _lag in parent.values():
        channels[exposure.channel.value] += 1

    exposure_known = any_exposure_evidence
    if not exposure_known:
        unknown.add("no_exposure_evidence")
    first, last = at[seed.subject_id], at[adopters[-1].subject_id]
    hours = (last - first).total_seconds() / 3600 if first and last else 0
    metrics = EpisodeMetrics(
        adopters=len(adopters),
        exposed_adopters=len(parent),
        independent_adopters=len(adopters) - 1 - len(parent),
        propagation_radius=max(depth.values()) if exposure_known else None,
        certified_radius=(max((p.certified_depth for p in paths), default=0) if exposure_known else None),
        max_breadth=(max(children.values(), default=0) if exposure_known else None),
        velocity_per_hour=(round((len(adopters) - 1) / hours, 6) if len(adopters) > 1 and hours > 0 else None),
        median_lag_seconds=int(statistics.median(lags)) if lags else None,
        repeated_exposure_adopters=repeated,
        channels=dict(sorted(channels.items())),
        unknown_reasons=tuple(sorted(unknown)),
    )

    # ── baseline ─────────────────────────────────────────────────────────
    adopter_ids = {a.subject_id for a in adopters}
    universe = set(population) | adopter_ids
    window_end = _parse(query.window_end)
    exposed_non_adopters: set[str] = set()
    for adopter in adopters:
        a_at = at[adopter.subject_id]
        for exposure in exposures_from.get(adopter.subject_id, ()):
            target = exposure.to_subject
            if target in adopter_ids or target not in universe or a_at is None or window_end is None:
                continue
            if _exposure_qualifies(exposure, a_at, window_end):
                exposed_non_adopters.add(target)
    exposed = set(parent) | exposed_non_adopters
    unexposed = universe - exposed - {seed.subject_id}
    unexposed_adopters = len(adopters) - 1 - len(parent)
    b_reasons: list[str] = []
    exposed_rate = len(parent) / len(exposed) if exposed else None
    unexposed_rate = unexposed_adopters / len(unexposed) if unexposed else None
    if len(exposed) < query.min_exposed_for_baseline:
        b_reasons.append("baseline_exposed_group_too_small")
    if len(unexposed) < query.min_exposed_for_baseline:
        b_reasons.append("baseline_unexposed_group_too_small")
    lift: Optional[float] = None
    if exposed_rate is not None and unexposed_rate is not None:
        if unexposed_rate > 0:
            lift = round(exposed_rate / unexposed_rate, 6)
        else:
            b_reasons.append("baseline_unexposed_rate_zero")
    baseline = BaselineComparison(
        population=len(universe),
        exposed=len(exposed),
        exposed_adopters=len(parent),
        unexposed=len(unexposed),
        unexposed_adopters=unexposed_adopters,
        exposed_rate=round(exposed_rate, 6) if exposed_rate is not None else None,
        unexposed_rate=round(unexposed_rate, 6) if unexposed_rate is not None else None,
        lift=lift,
        reason_codes=tuple(b_reasons),
    )

    # ── coordination ─────────────────────────────────────────────────────
    lockstep = _lockstep_groups(adopters, query.lockstep_window_seconds, query.lockstep_min_entities)
    funding: set[tuple[str, str]] = set()
    funding_time_unknown = False
    for (a, b), exposures in exposures_by_pair.items():
        if not (a in adopter_ids and b in adopter_ids and a < b):
            continue
        ta, tb = at[a], at[b]
        if not (ta and tb and abs((ta - tb).total_seconds()) <= query.lockstep_window_seconds):
            continue
        # Funding is coordination evidence only when it was in force before
        # the first of the two entries; a later payment cannot explain them.
        first_entry = min(ta, tb)
        for exposure in exposures:
            if exposure.channel is not ExposureChannel.ONCHAIN:
                continue
            observed = _parse(exposure.observed_at)
            valid_to = _parse(exposure.valid_to)
            if observed is None:
                funding_time_unknown = True
                continue
            if observed <= first_entry and (valid_to is None or valid_to > first_entry):
                funding.add((a, b))
                break
    c_reasons = []
    if lockstep:
        c_reasons.append("lockstep_entry_group")
    if funding:
        c_reasons.append("shared_onchain_funding_lockstep_entry")
    coordinated = bool(lockstep or funding)
    if funding_time_unknown and not funding:
        c_reasons.append("funding_time_unknown")
    coordination = CoordinationSignal(
        lockstep_groups=tuple(lockstep),
        shared_funding_pairs=tuple(sorted(funding)),
        reason_codes=tuple(c_reasons),
    )

    # ── classification ───────────────────────────────────────────────────
    sizes_ok = not ({"baseline_exposed_group_too_small", "baseline_unexposed_group_too_small"} & set(b_reasons))
    enough_exposed_adopters = len(parent) >= query.min_exposed_for_baseline
    reasons: list[str]
    if len(adopters) < 2:
        classification, reasons = EpisodeClassification.INSUFFICIENT_DATA, ["single_adopter"]
    elif coordinated:
        classification, reasons = EpisodeClassification.COORDINATED, [
            r for r in coordination.reason_codes if r != "funding_time_unknown"
        ]
    elif not exposure_known:
        classification, reasons = EpisodeClassification.INSUFFICIENT_DATA, ["no_exposure_evidence"]
    elif not sizes_ok:
        classification, reasons = EpisodeClassification.INSUFFICIENT_DATA, list(b_reasons)
    elif lift is not None and lift >= query.viral_lift_threshold and enough_exposed_adopters:
        classification, reasons = EpisodeClassification.VIRAL, ["exposed_adoption_lift_at_or_above_threshold"]
    elif lift is None and "baseline_unexposed_rate_zero" in b_reasons and enough_exposed_adopters:
        classification, reasons = EpisodeClassification.VIRAL, ["adoption_only_among_exposed"]
    elif lift is not None or (exposed_rate == 0 and unexposed_rate == 0):
        classification, reasons = EpisodeClassification.ORGANIC, ["exposed_adoption_lift_below_threshold"]
    else:
        classification, reasons = EpisodeClassification.INSUFFICIENT_DATA, list(b_reasons) or ["baseline_unmeasurable"]
    claim = (
        ClaimType.OBSERVED if classification is EpisodeClassification.INSUFFICIENT_DATA else ClaimType.INFERRED
    )

    return DiffusionEpisode(
        episode_id="pe_" + _digest([query.tenant_id, instrument_key, side, seed.subject_id, seed.adopted_at])[:24],
        tenant_id=query.tenant_id,
        instrument_key=instrument_key,
        side=side,
        seed_subject=seed.subject_id,
        started_at=seed.adopted_at,
        ended_at=adopters[-1].adopted_at,
        classification=classification,
        claim_type=claim,
        classification_reasons=tuple(reasons),
        metrics=metrics,
        baseline=baseline,
        coordination=coordination,
        paths=tuple(sorted(paths, key=lambda p: (p.target_subject, p.path_id))),
        adopters=tuple(adopters),
    )


def compute_propagation(
    query: PropagationQuery,
    adoptions: Iterable[AdoptionEvent],
    exposures: Iterable[ExposureRef],
    population: Iterable[str],
    *,
    computed_at: Optional[str] = None,
    limitations: Iterable[str] = (),
) -> PropagationRun:
    """Run the propagation computation for one tenant. Pure and deterministic."""
    start, end = _parse(query.window_start), _parse(query.window_end)
    if start is None or end is None or end < start:
        raise ValueError("window_start/window_end must be ISO instants with start <= end")
    wanted = set(query.instrument_keys)

    first: dict[tuple[str, str], AdoptionEvent] = {}
    for adoption in adoptions:
        when = _parse(adoption.adopted_at)
        if adoption.tenant_id != query.tenant_id or when is None or not (start <= when <= end):
            continue
        if wanted and adoption.instrument_key not in wanted:
            continue
        key = (adoption.subject_id, adoption.instrument_key)
        if key not in first or (_adoption_order(adoption), adoption.side) < (
            _adoption_order(first[key]), first[key].side,
        ):
            first[key] = adoption

    channels = set(query.channels)
    scoped = sorted(
        (e for e in exposures if e.tenant_id == query.tenant_id and e.channel in channels),
        key=lambda e: e.exposure_id,
    )
    by_pair: dict[tuple[str, str], list[ExposureRef]] = defaultdict(list)
    by_from: dict[str, list[ExposureRef]] = defaultdict(list)
    for exposure in scoped:
        by_pair[(exposure.from_subject, exposure.to_subject)].append(exposure)
        by_from[exposure.from_subject].append(exposure)

    groups: dict[tuple[str, str], list[AdoptionEvent]] = defaultdict(list)
    for adoption in first.values():
        groups[(adoption.instrument_key, adoption.side)].append(adoption)

    population_set = set(population)
    episodes = [
        _episode(query, instrument, side, members, by_pair, by_from, population_set, bool(scoped))
        for (instrument, side), members in sorted(groups.items())
    ]
    input_digest = _digest({
        "adoptions": sorted((asdict(a) for a in first.values()), key=lambda d: (d["subject_id"], d["instrument_key"])),
        "exposures": [asdict(e) for e in scoped],
        "population": sorted(population_set),
    })
    run_id = "pr_" + _digest([query.tenant_id, asdict(query), input_digest])[:24]
    return PropagationRun(
        run_id=run_id,
        tenant_id=query.tenant_id,
        query=query,
        computed_at=computed_at or datetime.now(timezone.utc).isoformat(),
        episodes=tuple(episodes),
        input_digest=input_digest,
        limitations=tuple(sorted(set(LIMITATIONS) | set(limitations))),
    )


def subject_summary(run: PropagationRun, subject_id: str) -> dict[str, Any]:
    """Profile-facing view of one subject inside a run (no new computation).

    Lists the episodes the subject seeded or adopted in, the paths that reached
    the subject (inbound) and the paths that passed through it (outbound), with
    each episode's classification and claim type. A subject absent from every
    episode returns empty lists, not zeros of an invented metric.
    """
    episodes = []
    inbound = []
    outbound = []
    for episode in run.episodes:
        adopter = next((a for a in episode.adopters if a.subject_id == subject_id), None)
        if adopter is None:
            continue
        role = "seed" if episode.seed_subject == subject_id else "adopter"
        episodes.append({
            "episode_id": episode.episode_id,
            "instrument_key": episode.instrument_key,
            "side": episode.side,
            "role": role,
            "adopted_at": adopter.adopted_at,
            "classification": episode.classification.value,
            "claim_type": episode.claim_type.value,
        })
        for path in episode.paths:
            if path.target_subject == subject_id:
                inbound.append({"episode_id": episode.episode_id, **_plain(asdict(path))})
            elif any(h.from_subject == subject_id for h in path.hops):
                outbound.append({"episode_id": episode.episode_id, **_plain(asdict(path))})
    return {
        "run_id": run.run_id,
        "tenant_id": run.tenant_id,
        "subject_id": subject_id,
        "episodes": episodes,
        "inbound_paths": inbound,
        "outbound_paths": outbound,
        "seeded_episodes": sum(1 for e in episodes if e["role"] == "seed"),
        "limitations": list(run.limitations),
    }


__all__ = ["LIMITATIONS", "compute_propagation", "subject_summary"]
