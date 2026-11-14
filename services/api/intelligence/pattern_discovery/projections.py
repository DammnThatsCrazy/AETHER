"""Projections of patterns into Risk360 and the 360 entity views.

**Risk360.** A pattern becomes durable risk intelligence only when a reviewer
promotes it. Promotion writes one canonical :class:`RiskSignal` per affected
subject and per registered risk dimension the pattern reads as:

* ``claim_state = attributed``: a human attributed the pattern after review.
  It is never ``verified`` and never ``observed``; a pattern is an inference.
* the subject must be a *canonical* subject: a canonical entity (merge
  tombstones followed), a canonical Agent, or a wallet address. A raw
  ``user`` / ``anon`` / ``session`` ref that the identity authority cannot
  resolve gets **no** signal and is reported ``unresolved_subject``; nothing is
  guessed.
* signal ids are content-derived, so re-promoting converges.

The same conversion is registered as the ``pattern_discovery`` producer in
``intelligence.risk360.signals`` so any Risk360 pipeline can adapt a pattern
record on demand.

**Entity context.** :func:`entity_context` is the "emerging patterns" read for
Profile 360 / Agent 360 / Risk 360 panels: patterns involving an entity, the
entities most often co-implicated with it, and its open versus reviewed
patterns. It is advisory context, labelled as such.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from shared.contracts_models.epistemic import EpistemicStatus
from shared.logger.logger import get_logger

from .contracts import (
    DETECTOR_VERSION, PROMOTABLE_STATUSES, QUEUE_STATUSES, REVIEWED_STATUSES, STATUS_PROMOTED,
    content_hash,
)

logger = get_logger("aether.pattern_discovery.projections")

PRODUCER = "pattern_discovery"
SIGNAL_STATUSES = PROMOTABLE_STATUSES | {STATUS_PROMOTED}
MAX_SUBJECTS_PER_PROMOTION = 500


def _risk_dimensions(pattern: dict[str, Any]) -> list[str]:
    from intelligence.risk360.dimensions import RISK_DIMENSION_KEYS

    dims = [c for c in pattern.get("risk_categories") or [] if c in RISK_DIMENSION_KEYS]
    return sorted(set(dims)) or ["behavioral"]


def pattern_risk_signals(pattern: dict[str, Any], *, subject_kind: str, subject_id: str,
                         source_entity_key: Optional[str] = None,
                         observed_at: Optional[datetime] = None) -> list[Any]:
    """Canonical Risk360 signals for one subject of a reviewed pattern.

    Returns ``[]`` for a pattern no human confirmed: an unreviewed candidate
    is queue material, not risk intelligence.
    """
    from graph.operational_intelligence.models import EvidenceRef
    from intelligence.risk360.contracts import RiskSignal

    if pattern.get("status") not in SIGNAL_STATUSES:
        return []
    key = source_entity_key or f"{subject_kind}:{subject_id}"
    if key not in (pattern.get("affected_entity_keys") or []) and source_entity_key is not None:
        raise ValueError("subject is not implicated by this pattern")
    pid = pattern["pattern_id"]
    refs = [
        EvidenceRef(
            id=f"{pid}#evidence/{e.get('type')}",
            type="model_output",
            source=PRODUCER,
            observedAt=pattern.get("last_observed_at"),
            confidence=min(max(float(e.get("strength") or 0.0), 0.0), 1.0),
            uri=f"store://discovered_patterns/{pid}#evidence/{e.get('type')}",
        )
        for e in pattern.get("evidence") or []
    ]
    history = pattern.get("review_history") or []
    if history:
        refs.append(EvidenceRef(
            id=f"{pid}#review/{len(history)}", type="annotation", source=f"{PRODUCER}_review",
            observedAt=history[-1].get("at"), uri=f"store://discovered_patterns/{pid}#review/{len(history)}",
        ))
    verdict = (pattern.get("promotion") or {}).get("verdict") or (
        "malicious" if pattern.get("status") == "confirmed_malicious" else "valid"
    )
    out = []
    for dim in _risk_dimensions(pattern):
        out.append(RiskSignal(
            signal_id="rsk_" + content_hash({"producer": PRODUCER, "tenant": pattern["tenant_id"],
                                             "pattern": pid, "subject": [subject_kind, subject_id],
                                             "dimension": dim}, 24),
            tenant_id=pattern["tenant_id"],
            subject_kind=subject_kind,
            subject_id=subject_id,
            risk_dimension=dim,
            claim_state=EpistemicStatus.ATTRIBUTED,
            confidence=float(pattern.get("confidence") or 0.0),
            evidence_refs=refs,
            source=f"{PRODUCER}.{pattern.get('kind')}.{verdict}",
            detector_version=pattern.get("detector_version") or DETECTOR_VERSION,
            observed_at=observed_at,
            score=float(pattern.get("severity_score") or 0.0) if pattern.get("severity_score") is not None else None,
            value=float(pattern.get("affected_entity_count") or 0),
        ))
    return out


def signals_from_pattern(artifact: Any, *, subject_kind: str, subject_id: str, tenant_id: str,
                         observed_at: Optional[datetime] = None) -> list[Any]:
    """Risk360 producer adapter (``adapt_producer_signal("pattern_discovery", ...)``)."""
    if artifact is None:
        return []
    pattern = artifact if isinstance(artifact, dict) else getattr(artifact, "__dict__", {})
    if pattern.get("tenant_id") != tenant_id:
        raise ValueError("pattern belongs to another tenant")
    return pattern_risk_signals(pattern, subject_kind=subject_kind, subject_id=subject_id,
                                observed_at=observed_at)


Resolver = Callable[[str, str], Awaitable[Optional[tuple[str, str]]]]


async def resolve_subject(tenant_id: str, entity_key: str) -> Optional[tuple[str, str]]:
    """Map a pattern entity key onto a canonical Risk360 subject, or None."""
    kind, _, ident = entity_key.partition(":")
    if not ident:
        return None
    if kind == "wallet":
        return "wallet", ident.lower() if ident.startswith("0x") else ident
    if kind == "agent":
        from intelligence.fraud_networks.fleet_fraud360 import resolve_canonical_agent

        canonical = await resolve_canonical_agent(tenant_id, ident)
        return ("agent", canonical) if canonical else None
    if kind in ("entity", "user"):
        from identity.identity.repository import IdentityResolutionRepository

        repo = IdentityResolutionRepository()
        surviving = await repo.resolve_surviving_canonical_entity_id(tenant_id, ident)
        subject = await repo.get_subject_by_canonical_entity_id(tenant_id, surviving)
        if subject and subject.get("tenant_id", tenant_id) == tenant_id:
            return "entity", surviving
        return None
    return None


async def promote_to_risk(pattern: dict[str, Any], *, resolver: Optional[Resolver] = None,
                          store: Optional[Any] = None) -> list[dict[str, Any]]:
    """Write attributed Risk360 signals for every resolvable affected subject.

    Returns one outcome row per affected entity: ``written`` (with signal ids),
    ``unresolved_subject`` or ``failed``. A failure on one subject never stops
    the others.
    """
    if pattern.get("status") not in SIGNAL_STATUSES:
        raise ValueError("only promoted or reviewer-confirmed patterns produce risk signals")
    if store is None:
        from intelligence.risk360.store import RiskSignalRepository

        store = RiskSignalRepository()
    resolver = resolver or resolve_subject
    tenant_id = pattern["tenant_id"]
    outcomes: list[dict[str, Any]] = []
    for key in (pattern.get("affected_entity_keys") or [])[:MAX_SUBJECTS_PER_PROMOTION]:
        try:
            subject = await resolver(tenant_id, key)
        except Exception as exc:  # noqa: BLE001 - resolution failure excludes, never guesses
            outcomes.append({"entity": key, "status": "unresolved_subject", "error_type": type(exc).__name__})
            continue
        if subject is None:
            outcomes.append({"entity": key, "status": "unresolved_subject"})
            continue
        try:
            signals = pattern_risk_signals(pattern, subject_kind=subject[0], subject_id=subject[1],
                                           source_entity_key=key)
            for sig in signals:
                await store.upsert_scoped(tenant_id, sig.signal_id, sig.model_dump(mode="json"))
            outcomes.append({"entity": key, "status": "written", "subject_kind": subject[0],
                             "subject_id": subject[1], "signal_ids": [s.signal_id for s in signals]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("pattern_discovery.risk_write_failed",
                           extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
            outcomes.append({"entity": key, "status": "failed", "error_type": type(exc).__name__})
    return outcomes


def _brief(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p.get(k) for k in (
        "pattern_id", "kind", "title", "summary", "status", "priority", "severity", "confidence",
        "novelty", "affected_entity_count", "risk_categories", "first_observed_at", "last_observed_at",
        "version", "claim_state",
    )}


def entity_context(entity_key: str, patterns: list[dict[str, Any]], *, similar_limit: int = 10) -> dict[str, Any]:
    """Emerging-pattern context for one entity (Profile / Agent / Risk 360 panels)."""
    relevant = [p for p in patterns if p.get("status") != "deprecated"]
    co = Counter()
    for p in relevant:
        for other in p.get("affected_entity_keys") or []:
            if other != entity_key:
                co[other] += 1
    open_ = [p for p in relevant if p.get("status") in QUEUE_STATUSES or p.get("status") == "candidate"]
    reviewed = [p for p in relevant if p.get("status") in REVIEWED_STATUSES or p.get("status") == STATUS_PROMOTED]
    identity_overlap = [
        p for p in relevant if any(e.get("type") == "identity_overlap_candidate" for e in p.get("evidence") or [])
    ]
    return {
        "entity": entity_key,
        "claim_state": "inferred",
        "advisory": True,
        "note": "Discovered patterns are review material; they do not merge identities or change risk decisions.",
        "emerging_patterns": [_brief(p) for p in open_],
        "reviewed_patterns": [_brief(p) for p in reviewed],
        "unresolved_identity_overlaps": [_brief(p) for p in identity_overlap],
        "co_implicated_entities": [{"entity": e, "shared_patterns": c} for e, c in co.most_common(similar_limit)],
        "kinds": sorted({p.get("kind") for p in relevant}),
        "risk_categories": sorted({c for p in relevant for c in p.get("risk_categories") or []}),
        "counts": {"open": len(open_), "reviewed": len(reviewed), "total": len(relevant)},
    }


def similar_patterns(pattern: dict[str, Any], others: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Patterns sharing the family or overlapping entities (for reviewer context)."""
    mine = set(pattern.get("affected_entity_keys") or [])
    scored = []
    for o in others:
        if o.get("pattern_id") == pattern.get("pattern_id"):
            continue
        theirs = set(o.get("affected_entity_keys") or [])
        jac = len(mine & theirs) / len(mine | theirs) if mine and theirs else 0.0
        same_family = o.get("family") == pattern.get("family")
        if jac <= 0 and not same_family:
            continue
        scored.append((jac + (0.5 if same_family else 0.0), o, jac, same_family))
    scored.sort(key=lambda t: (-t[0], t[1].get("pattern_id", "")))
    return [{**_brief(o), "entity_overlap": round(j, 3), "same_family": f} for _s, o, j, f in scored[:limit]]
