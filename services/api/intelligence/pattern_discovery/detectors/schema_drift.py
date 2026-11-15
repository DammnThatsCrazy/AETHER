"""Schema drift: sources whose payload shape changed against the tenant baseline.

Compares this window's field profiles (per ``source|event_type``) with the
decayed profiles in the baseline:

* a new event group (source/type never seen before),
* new fields present in a meaningful share of events,
* fields that used to be present and vanished,
* fields whose dominant value type changed (``number`` -> ``string`` ...),
* new fields that look like identifiers (the riskiest kind of addition: they
  can silently create or break identity links downstream).

Drift is a structural fact about the evidence, so it carries the highest
confidence cap of any kind, but it is still only a candidate: most drift is a
release, not an attack.
"""
from __future__ import annotations

from collections import defaultdict

from ..contracts import KIND_SCHEMA_DRIFT, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import DiscoveryFrame, bounds, event_refs, plural

NAME = "schema_drift"
NEW_FIELD_PRESENCE = 0.2
DROPPED_FIELD_PRESENCE = 0.5


def current_profiles(frame: DiscoveryFrame) -> tuple[dict[str, dict[str, dict]], dict[str, int]]:
    ex = frame.extraction
    out: dict[str, dict[str, dict]] = {}
    for group, paths in ex.profiles.items():
        n = max(ex.event_counts[group], 1)
        out[group] = {
            path: {"dominant_kind": prof.dominant_kind, "presence": round(prof.count / n, 4),
                   "identifier_like": prof.identifier_like(),
                   "semantic": prof.semantic.most_common(1)[0][0] if prof.semantic else None}
            for path, prof in paths.items()
        }
    return out, dict(ex.event_counts)


def detect_schema_drift(frame: DiscoveryFrame) -> DetectorOutput:
    cfg = frame.config
    profiles, counts = current_profiles(frame)
    baseline_profiles = frame.baseline.get("field_profiles") or {}
    has_history = int(frame.baseline.get("runs") or 0) > 0
    contribution = {
        "field_profiles": {g: {p: {"dominant_kind": i["dominant_kind"], "presence": i["presence"]}
                               for p, i in paths.items()} for g, paths in profiles.items()},
        "group_events": counts,
    }
    if not has_history:
        return DetectorOutput(NAME, [], contribution, {"groups": len(profiles), "reported": 0,
                                                       "note": "first run establishes the schema baseline"})
    events_by_group = defaultdict(list)
    for ev in frame.extraction.events:
        events_by_group[f"{ev.source}|{ev.event_type}"].append(ev)

    patterns: list[RawPattern] = []
    for group in sorted(profiles):
        if counts.get(group, 0) < cfg.drift_min_events:
            continue
        now = profiles[group]
        before = baseline_profiles.get(group)
        changes: list[dict] = []
        if before is None:
            changes.append({"change": "new_event_group", "group": group})
        else:
            for path, info in sorted(now.items()):
                prev = before.get(path)
                if (prev is None or float(prev.get("presence") or 0) < 0.01) and info["presence"] >= NEW_FIELD_PRESENCE:
                    changes.append({"change": "new_identifier_field" if info["identifier_like"] or info["semantic"] in
                                    {"email", "wallet", "ip", "device", "payment_instrument", "phone"} else "new_field",
                                    "path": path, "presence": info["presence"], "kind": info["dominant_kind"],
                                    "semantic": info["semantic"]})
                elif prev and prev.get("dominant_kind") and info["presence"] >= NEW_FIELD_PRESENCE \
                        and float(prev.get("presence") or 0) >= NEW_FIELD_PRESENCE \
                        and prev["dominant_kind"] != info["dominant_kind"]:
                    changes.append({"change": "type_changed", "path": path,
                                    "from": prev["dominant_kind"], "to": info["dominant_kind"]})
            for path, prev in sorted(before.items()):
                if float(prev.get("presence") or 0) >= DROPPED_FIELD_PRESENCE and path not in now:
                    changes.append({"change": "dropped_field", "path": path,
                                    "previous_presence": prev.get("presence")})
        if not changes:
            continue
        evs = events_by_group[group]
        ents = sorted({e.entity for e in evs if e.entity})
        first, last = bounds(evs)
        kinds = sorted({c["change"] for c in changes})
        strength = 0.25 + 0.1 * len(kinds) + (0.15 if "new_identifier_field" in kinds else 0.0)
        signature = {"group": group,
                     "changes": sorted(f"{c['change']}:{c.get('path', '')}" for c in changes)[:40]}
        source, _, event_type = group.partition("|")
        patterns.append(RawPattern(
            kind=KIND_SCHEMA_DRIFT,
            signature=signature,
            title=f"Schema drift in {event_type} from {source}",
            summary=(f"{plural(len(changes), 'schema change')} in {event_type} ({source}): "
                     + ", ".join(sorted({c['change'].replace('_', ' ') for c in changes})) + "."),
            affected_entities=ents[:500],
            evidence=[
                EvidenceItem("schema_changes", "observed", min(0.6, strength), {
                    "group": group, "events": counts[group], "changes": changes[:50],
                }, event_refs(evs)),
            ],
            occurrence_count=counts[group],
            first_observed_at=first,
            last_observed_at=last,
            risk_categories=["operational"] + (["identity"] if "new_identifier_field" in kinds else []),
            competing_explanations=[
                {"id": "sdk_or_integration_release", "note": "A client or provider release changes payloads without any abuse."},
                {"id": "sampling_window", "note": "Optional fields appear and vanish with the mix of traffic in a short window."},
            ],
            novelty=1.0,
            baseline={"previous_fields": len(before or {}), "current_fields": len(now)},
            episode_count=counts[group],
            detector=NAME,
        ))
    return DetectorOutput(NAME, patterns[: cfg.max_patterns_per_detector], contribution,
                          {"groups": len(profiles), "reported": min(len(patterns), cfg.max_patterns_per_detector)})
