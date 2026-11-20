"""Exposure construction from canonical relationship facts and Silver exposure rows.

An exposure says "``to_subject`` could have observed ``from_subject``" at or
after ``observed_at``. It is built from:

* registered relationship predicates read from the tenant graph (social,
  on-chain ``PAYS``, and promoted Relationship360 facts), mapped to a channel
  and an exposure direction by :data:`EXPOSURE_DIRECTION`; and
* tenant in-app exposure events (Silver ``exposure`` family) that name the
  subject whose activity was shown (``exposed_subject_ref``).

Predicates that are inferential only (``SHARES_AFFINITY_WITH``), structural
membership (``MEMBER_OF``), or risk context (``SHARES_RISK_CONTEXT_WITH``) are
never exposure evidence. An edge without evidence refs is skipped and reported,
never trusted.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping, Optional

from intelligence.propagation.contracts import ExposureChannel, ExposureRef

# Direction of observation for each registered predicate on edge A -> B:
#   "reverse": B's activity is visible to A (A follows / subscribes to / was
#              referred by B), so exposure runs B -> A.
#   "forward": A's activity reaches B (A communicates to B).
#   "both":    either party can observe the other.
EXPOSURE_DIRECTION: dict[str, str] = {
    "FOLLOWS": "reverse",
    "SUBSCRIBES_TO": "reverse",
    "REFERRED_BY": "reverse",
    "COMMUNICATES_WITH": "forward",
    "MUTUAL_SOCIAL_CONNECTION": "both",
    "INTERACTS_WITH": "both",
    "COLLABORATES_WITH": "both",
    "PARTICIPATES_WITH": "both",
    "COMMUNITY_ASSOCIATION": "both",
    "RECURRING_SOCIAL_INTERACTION": "both",
    "RECIPROCAL_COMMUNICATION": "both",
    "RECURRING_CO_PRESENCE": "both",
    "PERSISTENT_MULTI_CONTEXT_ASSOCIATION": "both",
    "AGENT_MEDIATED_PRINCIPAL_INTERACTION": "both",
    "CO_EXPOSED": "both",
    "CO_PRESENT_WITH": "both",
    "PAYS": "both",
}
NON_EXPOSURE_PREDICATES = frozenset({"SHARES_AFFINITY_WITH", "MEMBER_OF", "SHARES_RISK_CONTEXT_WITH"})

_FAMILY_CHANNEL = {"SOCIAL": ExposureChannel.SOCIAL, "ECONOMIC": ExposureChannel.ONCHAIN}

# Silver exposure event types whose shown item is another user's activity.
IN_APP_EXPOSURE_TYPES = frozenset({
    "content_impression", "recommendation_exposed", "feature_exposed",
    "notification_presented", "search_result_exposed",
})


def _predicate_index() -> dict[str, dict[str, Any]]:
    """Graph edge type -> governed predicate entry (registered rows only)."""
    from shared.relationship_spine.generated_relationship_predicate_registry import (
        RELATIONSHIP_PREDICATES,
    )

    index: dict[str, dict[str, Any]] = {}
    for entry in RELATIONSHIP_PREDICATES:
        if entry.get("graphRegistrationState") == "REGISTERED" and entry.get("graphEdgeType"):
            index[str(entry["graphEdgeType"])] = dict(entry)
    return index


def exposure_edge_types() -> tuple[str, ...]:
    """Graph edge types that can carry exposure evidence."""
    return tuple(sorted(
        edge_type for edge_type, entry in _predicate_index().items()
        if entry.get("predicate") in EXPOSURE_DIRECTION
    ))


def channel_for(entry: Mapping[str, Any]) -> ExposureChannel:
    return _FAMILY_CHANNEL.get(str(entry.get("family") or ""), ExposureChannel.RELATIONSHIP)


def _edge_field(edge: Any, *names: str) -> Any:
    for name in names:
        if isinstance(edge, Mapping) and edge.get(name) is not None:
            return edge.get(name)
        value = getattr(edge, name, None)
        if value is not None:
            return value
    return None


def _edge_props(edge: Any) -> dict[str, Any]:
    props = _edge_field(edge, "properties")
    return dict(props) if isinstance(props, Mapping) else {}


def _tenant_of(props: Mapping[str, Any]) -> str:
    """Edge tenant in any accepted spelling (never a wildcard)."""
    from shared.graph.graph import tenant_of

    return str(tenant_of(dict(props)) or "")


def _evidence_ids(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            value = item.get("id") or item.get("evidence_id")
        else:
            value = item
        if value:
            out.append(str(value))
    return tuple(sorted(set(out)))


def _exposure_id(*parts: str) -> str:
    return "exp_" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


def exposures_from_edges(
    tenant_id: str,
    edges: Iterable[Any],
    *,
    channels: Iterable[ExposureChannel] = tuple(ExposureChannel),
) -> tuple[list[ExposureRef], set[str]]:
    """Map tenant graph edges to directional exposures.

    Returns ``(exposures, reason_codes)``. Edges from another tenant, revoked
    edges, unregistered edge types, and edges without evidence are skipped with
    a reason code.
    """
    allowed = set(channels)
    index = _predicate_index()
    exposures: list[ExposureRef] = []
    reasons: set[str] = set()
    for edge in edges:
        props = _edge_props(edge)
        edge_type = str(_edge_field(edge, "edge_type", "type") or "")
        entry = index.get(edge_type)
        if entry is None:
            reasons.add("exposure_edge_type_unregistered")
            continue
        predicate = str(entry["predicate"])
        if predicate in NON_EXPOSURE_PREDICATES or predicate not in EXPOSURE_DIRECTION:
            continue
        if _tenant_of(props) != tenant_id:
            reasons.add("exposure_edge_scope_mismatch")
            continue
        if props.get("revoked") or props.get("revoked_at"):
            continue
        channel = channel_for(entry)
        if channel not in allowed:
            continue
        source = str(_edge_field(edge, "from_vertex_id", "from") or "")
        target = str(_edge_field(edge, "to_vertex_id", "to") or "")
        if not source or not target or source == target:
            reasons.add("exposure_edge_endpoints_invalid")
            continue
        evidence = _evidence_ids(props.get("evidence_refs"))
        idem = props.get("idempotency_key")
        if idem:
            evidence = tuple(sorted({*evidence, str(idem)}))
        if not evidence:
            reasons.add("exposure_edge_evidence_unavailable")
            continue
        observed_at = props.get("observed_at") or props.get("valid_from")
        valid_to = props.get("valid_to")
        graph_edge = {
            "type": edge_type,
            "from": source,
            "to": target,
            "properties": dict(props),
        }
        direction = EXPOSURE_DIRECTION[predicate]
        pairs: list[tuple[str, str]] = []
        if direction in ("forward", "both"):
            pairs.append((source, target))
        if direction in ("reverse", "both"):
            pairs.append((target, source))
        for from_subject, to_subject in pairs:
            exposures.append(ExposureRef(
                exposure_id=_exposure_id(tenant_id, edge_type, source, target, from_subject),
                tenant_id=tenant_id,
                from_subject=from_subject,
                to_subject=to_subject,
                channel=channel,
                predicate=predicate,
                observed_at=str(observed_at) if observed_at else None,
                valid_to=str(valid_to) if valid_to else None,
                evidence_refs=evidence,
                graph_edge=graph_edge,
            ))
    return exposures, reasons


def exposures_from_in_app_events(
    tenant_id: str, rows: Iterable[Mapping[str, Any]],
) -> tuple[list[ExposureRef], set[str]]:
    """Map tenant in-app exposure rows to exposures.

    Accepts Silver ``silver_exposure_facts`` rows (``source_event_type``,
    ``user_id``, ``occurred_at``, ``source_event_id``, and the event
    properties in ``payload``) or the same fields in flat form. A row qualifies
    when it belongs to the tenant, has an in-app exposure type, names the
    viewer and the subject whose activity was shown
    (``exposed_subject_ref`` / ``payload.exposedSubjectRef``), and has an event
    id. The tenant SDK supplies ``exposedSubjectRef`` on the exposure event.
    """
    exposures: list[ExposureRef] = []
    reasons: set[str] = set()
    for row in rows:
        if str(row.get("tenant_id") or "") != tenant_id:
            reasons.add("in_app_exposure_scope_mismatch")
            continue
        kind = str(row.get("event_type") or row.get("type") or row.get("source_event_type") or "")
        if kind not in IN_APP_EXPOSURE_TYPES:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        viewer = str(row.get("subject_id") or row.get("entity_id") or row.get("user_id") or "")
        shown = row.get("exposed_subject_ref") or payload.get("exposedSubjectRef")
        event_id = str(row.get("event_id") or row.get("id") or row.get("source_event_id") or "")
        if not viewer or not shown or not event_id:
            reasons.add("in_app_exposure_fields_missing")
            continue
        if viewer == str(shown):
            continue
        when = row.get("timestamp") or row.get("observed_at") or row.get("occurred_at")
        exposures.append(ExposureRef(
            exposure_id=_exposure_id(tenant_id, "in_app", event_id),
            tenant_id=tenant_id,
            from_subject=str(shown),
            to_subject=viewer,
            channel=ExposureChannel.IN_APP,
            predicate=kind,
            observed_at=(when.isoformat() if hasattr(when, "isoformat") else str(when)) if when else None,
            evidence_refs=(event_id,),
        ))
    return exposures, reasons


__all__ = [
    "EXPOSURE_DIRECTION",
    "IN_APP_EXPOSURE_TYPES",
    "NON_EXPOSURE_PREDICATES",
    "channel_for",
    "exposure_edge_types",
    "exposures_from_edges",
    "exposures_from_in_app_events",
]
