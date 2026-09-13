"""WS-D Section-25 evidence dedupe (blueprint §25 / gap rows 9 + 26).

The blueprint's dedupe rule: the SAME real-world outcome observed through the
browser SDK, a webhook and a connector is ONE canonical outcome with THREE
evidence refs — never three outcomes or three duplicate evidence rows.

Two distinct collapses live here:

* :func:`dedupe_evidence` — group a batch of already-normalized observation
  records by their *canonical-outcome key* (the correlation family first:
  ``correlation_id`` > ``causation_id`` > ``parent_observation_id`` > a
  subject+type+temporal fallback) and merge their per-channel evidence refs
  into ONE group. Literal duplicates (the same event id delivered twice on the
  same channel) collapse by :func:`default_fingerprint`.
* :func:`canonical_outcome_key` — the raw key extractor, exported so WS-A/B
  back-link seams and tests can reuse it without reaching into this module.

Flag gating is the caller's job (``evidence_dedupe_enabled()``); this module
is a pure function surface with no side effects so it is trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from services.operational_intelligence.models import EvidenceRef

# A normalized observation is an Envelope-B ``model_dump()`` (JSON) or any
# mapping that exposes the same dotted paths. We only read, never write, and we
# tolerate missing paths (evidence-preservation rule: absence is not an error).
ObservationRecord = dict[str, Any]

_CORRELATION = "correlation"
_IDENTITY = "identity"
_EVENT = "event"
_SUBJECT = "subject"
_TIMESTAMP = "timestamp"


def _dig(record: ObservationRecord, *path: str) -> Any:
    """Read a dotted path off a JSON-ish record, tolerating absence."""
    cur: Any = record
    for part in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            # list-of-dict path: take first element that has the key
            found = None
            for item in cur:
                if isinstance(item, dict) and part in item:
                    found = item.get(part)
                    break
            cur = found
        else:
            return None
    return cur


def _first(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def canonical_outcome_key(record: ObservationRecord) -> Optional[str]:
    """Canonical-outcome key for one normalized observation record.

    Prefers the correlation family ids (Invariant #12 canonical correlation);
    falls back to a stable subject+type+occurred-day key so observations from
    independent channels that the source did not correlate can still be
    grouped when their subject/type/day agree. Returns ``None`` only when the
    record is too sparse to be keyed at all.
    """
    correlation_id = _dig(record, _CORRELATION, "correlation_id")
    causation_id = _dig(record, _CORRELATION, "causation_id")
    parent = _dig(record, _CORRELATION, "parent_observation_id")

    family = _first(correlation_id, causation_id, parent)
    if family is not None:
        return f"correlation:{family}"

    subject_kind = _dig(record, _SUBJECT, "kind")
    subject_id = _dig(record, _SUBJECT, "id")
    event_type = _dig(record, _EVENT, "type")
    if not subject_id and not event_type:
        return None
    day = None
    timestamp = _dig(record, "temporal", "source_time") or _dig(
        record, "temporal", "occurred_at"
    )
    if isinstance(timestamp, str) and len(timestamp) >= 10:
        day = timestamp[:10]
    return ":".join(
        str(part or "")
        for part in (
            "subject-type",
            subject_kind,
            subject_id,
            event_type,
            day,
        )
    )


def default_fingerprint(record: ObservationRecord) -> Optional[str]:
    """Stable literal-identity for ONE underlying event/observation.

    The same event id on the same channel is the same evidence — but the same
    real-world outcome via a webhook carries a different event id and must be a
    DIFFERENT fingerprint (that is exactly the §25 collapse we keep).
    """
    source_type = _dig(record, "source", "type") or _dig(record, "source_type")
    source_id = _dig(record, "source", "id")
    event_id = _dig(record, "event", "id")
    gateway_id = _dig(record, "gateway", "observation_id") or _dig(
        record, "event", "gateway_id"
    )
    best = _first(event_id, gateway_id, source_id)
    if best is None:
        return None
    prefix = _first(source_type, "unknown")
    return f"{prefix}:{best}"


_CANONICAL_EVIDENCE_TYPES = frozenset(
    {"event", "entity", "relationship", "document", "transaction", "model_output", "annotation"}
)


def _to_evidence_ref(evidence: dict[str, Any]) -> EvidenceRef:
    """Build an EvidenceRef from an Envelope-B evidence dump or a bare ref dict.

    Non-canonical ``type`` strings are mapped to ``event`` (the fallback member
    of the canonical EvidenceType vocabulary) so an off-vocabulary source label
    can never crash the dedupe seam.
    """
    raw_type = str(
        evidence.get("type") or evidence.get("evidence_type") or "event"
    )
    ev_type = raw_type if raw_type in _CANONICAL_EVIDENCE_TYPES else "event"
    return EvidenceRef(
        id=str(evidence.get("id") or evidence.get("evidence_id") or ""),
        type=ev_type,
        source=str(evidence.get("source") or ""),
        observedAt=evidence.get("observedAt"),
        confidence=evidence.get("confidence"),
        uri=evidence.get("uri"),
    )


def _observation_evidence(record: ObservationRecord) -> dict[str, Any]:
    """Reshape one normalized observation record into a bare evidence dict.

    A wrapped ``evidence`` block (dict, or first element of a list) wins when
    present; otherwise the observation's own event/gateway identity is lifted so
    every observation contributes exactly one evidence ref. Absence is not an
    error — the returned dict is simply sparser (the ``_to_evidence_ref``
    mapping still fills a canonical ``type``).
    """
    wrapped = record.get("evidence")
    if isinstance(wrapped, dict):
        return wrapped
    if isinstance(wrapped, list) and wrapped and isinstance(wrapped[0], dict):
        return wrapped[0]
    # An Envelope-B observation ``model_dump()`` (or any mapping exposing the
    # same dotted paths) carries its event identity nested under ``event``.
    return {
        "id": _first(
            _dig(record, "event", "id"),
            _dig(record, "event", "evidence_id"),
            _dig(record, "gateway", "observation_id"),
            _dig(record, "id"),
        ),
        "type": _first(
            _dig(record, "evidence_type"), _dig(record, "type"), "event"
        ),
        "source": _first(
            _dig(record, "source", "type"),
            _dig(record, "source_type"),
            _dig(record, "source", "id"),
        ),
        "observedAt": _dig(record, "temporal", "observed_at"),
    }


@dataclass(frozen=True)
class DedupeGroup:
    """One canonical outcome after §25 dedupe.

    ``evidence_refs`` holds ONE ref per distinct underlying event (channel
    collapse), ``fingerprints`` the distinct event identities merged into the
    group, and ``observation_count`` the raw observation records consumed.
    """

    canonical_key: str
    evidence_refs: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    fingerprints: tuple[str, ...] = field(default_factory=tuple)
    observation_count: int = 0
    sources: tuple[str, ...] = field(default_factory=tuple)

    def model_dump(self) -> dict[str, Any]:
        return {
            "canonicalKey": self.canonical_key,
            "evidenceRefs": [ref.model_dump() for ref in self.evidence_refs],
            "fingerprints": list(self.fingerprints),
            "observationCount": self.observation_count,
            "sources": list(self.sources),
        }


def dedupe_evidence(
    observations: Iterable[ObservationRecord],
    *,
    key: Optional[Callable[[ObservationRecord], Optional[str]]] = None,
    fingerprint: Optional[
        Callable[[ObservationRecord], Optional[str]]
    ] = None,
    evidence_extractor: Optional[
        Callable[[ObservationRecord], Optional[dict[str, Any]]]
    ] = None,
) -> list[DedupeGroup]:
    """Collapse observations to canonical outcomes with merged evidence.

    ``key`` (default :func:`canonical_outcome_key`) decides which observations
    describe the same real-world outcome; ``fingerprint`` (default
    :func:`default_fingerprint`) decides which are literally the same event and
    are therefore ONE evidence ref, not several. ``evidence_extractor`` (default
    :func:`_observation_evidence`) reshapes one observation record into its
    single evidence dict; pass a custom one when a caller's records carry their
    evidence under a non-standard shape. Records that yield no key are skipped
    (they carry no §25 identity); records with no fingerprint are still merged
    as evidence (their ref still counts once per group).
    """
    key_fn = key or canonical_outcome_key
    fp_fn = fingerprint or default_fingerprint
    extract = evidence_extractor or _observation_evidence

    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in observations:
        group_key = key_fn(record)
        if not group_key:
            continue
        if group_key not in groups:
            groups[group_key] = {
                "evidence": {},
                "fp": {},
                "count": 0,
                "sources": set(),
            }
            order.append(group_key)
        group = groups[group_key]
        group["count"] += 1
        raw = extract(record)
        if isinstance(raw, dict) and raw:
            ref = _to_evidence_ref(raw)
            if ref.id:
                # One EvidenceRef per distinct underlying event identity.
                fp = fp_fn(record)
                if fp:
                    if fp not in group["fp"]:
                        group["fp"][fp] = ref
                elif ref.id not in {r.id for r in group["evidence"].values()}:
                    group["evidence"][ref.id] = ref
                source = raw.get("source") or raw.get("source_type")
                if isinstance(source, str) and source:
                    group["sources"].add(source)
    if not groups:
        return []

    result: list[DedupeGroup] = []
    for group_key in order:
        group = groups[group_key]
        # Fingerprinted refs first (stable), then non-fingerprinted refs.
        merged = list(group["fp"].values())
        merged.extend(group["evidence"].values())
        seen: set[str] = set()
        refs: list[EvidenceRef] = []
        for ref in merged:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
        result.append(
            DedupeGroup(
                canonical_key=group_key,
                evidence_refs=tuple(refs),
                fingerprints=tuple(group["fp"].keys()),
                observation_count=group["count"],
                sources=tuple(sorted(group["sources"])),
            )
        )
    return result


__all__ = [
    "DedupeGroup",
    "ObservationRecord",
    "canonical_outcome_key",
    "default_fingerprint",
    "dedupe_evidence",
]
