"""Incident correlation — one root cause, one incident.

One bad deploy produces failed events, connector warnings, graph drift and
tenant reports. Treating those as four problems is how a small team drowns; the
job of this module is to attach them to one incident and record *why*.

Deterministic before heuristic
------------------------------
Bases are evaluated in a fixed order and the first match wins, so the strongest
available evidence is always the one recorded:

======================================  ==========  ============================
basis                                   confidence  kind
======================================  ==========  ============================
``release_id``                          1.0         deterministic
``service_window``                      0.8         deterministic-ish
``error_signature``                     0.7         heuristic
``graph_dependency``                    0.6         heuristic, needs graph plane
``time_proximity``                      0.3         weakest — never attaches
======================================  ==========  ============================

Every attachment stores its basis and confidence on the signal *and* appends to
the incident's correlation log, so a wrong correlation is auditable rather than
mysterious.

Why time proximity cannot attach
--------------------------------
Over-merging is worse than under-merging. A correlator that folds a second,
unrelated failure into an open incident hides it: the incident already has an
owner, a status and a next action, so the new failure inherits attention that
is aimed somewhere else and nobody opens a second investigation. Two things
failing at the same time is the single most common coincidence in a distributed
system, so ``time_proximity`` is recorded as a *weak link* — visible in the
incident's ``metadata["weak_links"]`` — and the signal still opens its own
incident. Incident-to-incident merging is narrower still: only ``release_id``
(confidence 1.0) is merge-eligible.

Relationship to the other incident planes
-----------------------------------------
``services/reliability`` already owns ``reliability_incidents`` — a
service-health-shaped record with its own audit table and lifecycle. This
module does not replace, wrap or modify it. Theirs answers "is this service
healthy"; this one is the cross-cutting record that links alert → command →
audit → tenant impact, which is a different question with a different owner.
A reliability incident is therefore an *input*: it arrives as an
:class:`IncidentSignal` with ``source="reliability"``. The same holds for
``services/agent/ops_alerts`` — an existing compressed alert is ingested as a
signal (``source="ops_alert"``) rather than re-detected here.
"""
from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, Coroutine, Optional

from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from .contracts import Incident, IncidentSignal, Severity, now_iso
from .repository import (
    IncidentRepository,
    IncidentSignalRepository,
)
from .severity import escalate_severity, severity_rank

logger = get_logger("aether.kyber.ops.correlation")

# ── Correlation bases ────────────────────────────────────────────────────────

BASIS_RELEASE = "release_id"
BASIS_SERVICE_WINDOW = "service_window"
BASIS_ERROR_SIGNATURE = "error_signature"
BASIS_GRAPH_DEPENDENCY = "graph_dependency"
BASIS_TIME_PROXIMITY = "time_proximity"
#: The caller named the incident itself — no inference was made.
BASIS_EXPLICIT = "explicit"
#: This signal opened the incident. Not a correlation: recording it as one
#: would claim evidence that was never evaluated.
BASIS_FOUNDING = "founding_signal"

#: Basis → confidence. Deterministic bases first; the tuple order *is* the
#: evaluation order, so a stronger basis can never be shadowed by a weaker one.
CORRELATION_BASES: tuple[tuple[str, float], ...] = (
    (BASIS_RELEASE, 1.0),
    (BASIS_SERVICE_WINDOW, 0.8),
    (BASIS_ERROR_SIGNATURE, 0.7),
    (BASIS_GRAPH_DEPENDENCY, 0.6),
    (BASIS_TIME_PROXIMITY, 0.3),
)

BASIS_CONFIDENCE: dict[str, float] = dict(CORRELATION_BASES)

#: Bases strong enough to attach a signal to an existing incident. Time
#: proximity is deliberately absent — see the module docstring.
ATTACHING_BASES: frozenset[str] = frozenset({
    BASIS_RELEASE, BASIS_SERVICE_WINDOW, BASIS_ERROR_SIGNATURE, BASIS_GRAPH_DEPENDENCY,
})

#: Bases strong enough to merge two whole incidents. Narrower still: only an
#: identical release is deterministic enough that folding two investigations
#: into one cannot hide a second failure.
MERGE_ELIGIBLE_BASES: frozenset[str] = frozenset({BASIS_RELEASE})

DEFAULT_CORRELATION_WINDOW_SECONDS = 900

#: The graph plane's blast-radius module. Resolved lazily and by name because
#: the graph plane is a separate deployment slice: when it is absent the
#: dependency basis is *skipped and reported* in ``missing_inputs`` rather than
#: silently scoring lower, because "we could not check" and "we checked and
#: found nothing" must never look the same to an operator.
GRAPH_BLAST_RADIUS_MODULE = "services.kyber.graph.blast_radius"

#: Callable names accepted on the blast-radius singleton, in preference order.
_BLAST_RADIUS_ATTRS: tuple[str, ...] = ("assess", "blast_radius", "assess_blast_radius")

MISSING_GRAPH_PLANE = "graph_blast_radius_plane_unavailable"
MISSING_GRAPH_ENTRYPOINT = "graph_blast_radius_entrypoint_unresolved"
MISSING_TIMESTAMP = "unparseable_signal_timestamp"

#: Incident statuses that still need someone.
ACTIVE_INCIDENT_STATUSES: tuple[str, ...] = (
    "detected", "investigating", "identified", "mitigating", "monitoring",
)

#: Statuses whose resume card an operator needs when they come back to a
#: half-finished response.
IN_PROGRESS_STATUSES: tuple[str, ...] = ("investigating", "identified", "mitigating")

#: Fields ``update_incident`` will set. Anything else is refused rather than
#: silently dropped: an operator who thinks they recorded a next action has to
#: be right about that.
UPDATABLE_INCIDENT_FIELDS: frozenset[str] = frozenset({
    "status", "severity", "root_cause", "last_action", "next_action", "blocked_by",
    "pending_verification", "affected_tenants", "affected_features",
    "affected_services", "release_id", "customer_visible", "revenue_exposure",
    "security_exposure", "data_integrity_exposure", "title",
})

_SEVERITY_BASE_PRIORITY: dict[str, float] = {
    "critical": 90.0, "high": 70.0, "medium": 45.0, "low": 20.0, "info": 5.0,
}


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp, or ``None`` when it cannot be trusted."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _seconds_between(left: Optional[str], right: Optional[str]) -> Optional[float]:
    """Absolute distance in seconds, or ``None`` if either side is unparseable."""
    first, second = _parse_iso(left), _parse_iso(right)
    if first is None or second is None:
        return None
    if (first.tzinfo is None) != (second.tzinfo is None):
        return None
    return abs((first - second).total_seconds())


def _union(current: list[str], incoming: list[str]) -> list[str]:
    """Order-preserving union; an incident's reach only grows."""
    merged = list(current or [])
    for value in incoming or []:
        if value and value not in merged:
            merged.append(value)
    return merged


class IncidentCorrelator:
    """Attach signals to incidents on recorded evidence, and never over-merge."""

    def __init__(
        self,
        incidents: Optional[IncidentRepository] = None,
        signals: Optional[IncidentSignalRepository] = None,
    ) -> None:
        self._incidents = incidents or IncidentRepository()
        self._signals = signals or IncidentSignalRepository()

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _audit(
        self,
        *,
        actor_id: str,
        event_type: str,
        action: str,
        incident_id: str,
        outcome: str = "allowed",
        tenant_id: Optional[str] = None,
        actor_type: str = "olympus_operator",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record one incident transition in the shared tamper-evident ledger.

        Fail-open on the write: an incident record with no audit entry is bad,
        but an operator who cannot mitigate because the ledger is busy is worse.
        A missing module is a declared seam and fails the seam gate instead.
        """
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(
                actor_id=actor_id,
                actor_type=actor_type,
                event_type=event_type,
                resource_type="kyber_incident",
                action=action,
                outcome=outcome,
                tenant_id=tenant_id,
                resource_id=incident_id,
                metadata=metadata or {},
            )
        except Exception as exc:  # pragma: no cover - audit must not block ops
            logger.warning(
                "kyber incident audit unavailable (fail-open): event=%s incident=%s error=%s",
                event_type, incident_id, exc,
            )

    # ── Graph plane (optional) ───────────────────────────────────────────────

    def _resolve_blast_radius(self) -> tuple[Optional[Any], Optional[str]]:
        """Resolve the graph plane's blast-radius callable, or say why not.

        Returns ``(callable, missing_input)``. Exactly one side is populated:
        an unavailable graph plane yields a ``missing_inputs`` token, never a
        quietly reduced confidence.
        """
        try:
            module = importlib.import_module(GRAPH_BLAST_RADIUS_MODULE)
        except ImportError:
            return None, MISSING_GRAPH_PLANE
        owner = getattr(module, "blast_radius_service", module)
        for name in _BLAST_RADIUS_ATTRS:
            candidate = getattr(owner, name, None)
            if callable(candidate):
                return candidate, None
        return None, MISSING_GRAPH_ENTRYPOINT

    async def _graph_dependency_overlap(
        self, signal: IncidentSignal, incident: Incident
    ) -> tuple[bool, Optional[str]]:
        """Whether the signal's service can reach anything the incident affects."""
        if not signal.service or not incident.affected_services:
            return False, None
        resolver, missing = self._resolve_blast_radius()
        if resolver is None:
            return False, missing
        try:
            result = resolver(
                subject_type="Service",
                subject_id=signal.service,
                environment=signal.payload.get("environment"),
            )
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:  # pragma: no cover - graph plane is advisory
            logger.warning("graph blast-radius lookup failed (skipped): %s", exc)
            return False, MISSING_GRAPH_ENTRYPOINT
        reachable = getattr(result, "affected_services", None)
        if reachable is None and isinstance(result, dict):
            reachable = result.get("affected_services")
        if not reachable:
            return False, None
        return bool(set(reachable) & set(incident.affected_services)), None

    # ── Basis evaluation ─────────────────────────────────────────────────────

    async def _match(
        self, signal: IncidentSignal, incident: Incident, window_seconds: int
    ) -> tuple[Optional[str], float, list[str]]:
        """Strongest basis linking ``signal`` to ``incident``.

        Returns ``(basis, confidence, missing_inputs)``. ``basis`` may be
        :data:`BASIS_TIME_PROXIMITY`, which the caller must treat as a weak link
        rather than an attachment.
        """
        missing: list[str] = []
        distance = _seconds_between(
            signal.observed_at,
            incident.metadata.get("last_signal_at") or incident.opened_at,
        )
        in_window = distance is not None and distance <= window_seconds
        if distance is None:
            missing.append(MISSING_TIMESTAMP)

        # 1 — same release. Deterministic: one deploy, one cause.
        if signal.release_id and incident.release_id and signal.release_id == incident.release_id:
            return BASIS_RELEASE, BASIS_CONFIDENCE[BASIS_RELEASE], missing

        # 2 — same service inside the window. Deterministic-ish: the same
        # component failing twice in fifteen minutes is one failure until
        # proven otherwise.
        if signal.service and signal.service in (incident.affected_services or []) and in_window:
            return BASIS_SERVICE_WINDOW, BASIS_CONFIDENCE[BASIS_SERVICE_WINDOW], missing

        # 3 — identical error signature. Heuristic: same stack, same bug.
        signatures = incident.metadata.get("error_signatures") or []
        if signal.error_signature and signal.error_signature in signatures:
            return BASIS_ERROR_SIGNATURE, BASIS_CONFIDENCE[BASIS_ERROR_SIGNATURE], missing

        # 4 — shared graph dependency. Skipped (and reported) without the plane.
        overlap, graph_missing = await self._graph_dependency_overlap(signal, incident)
        if graph_missing:
            missing.append(graph_missing)
        elif overlap:
            return BASIS_GRAPH_DEPENDENCY, BASIS_CONFIDENCE[BASIS_GRAPH_DEPENDENCY], missing

        # 5 — time proximity alone. Weakest; caller must not attach on it.
        if in_window:
            return BASIS_TIME_PROXIMITY, BASIS_CONFIDENCE[BASIS_TIME_PROXIMITY], missing

        return None, 0.0, missing

    # ── Ingest ───────────────────────────────────────────────────────────────

    async def ingest_signal(self, signal: IncidentSignal) -> tuple[Incident, bool]:
        """Attribute one signal to an incident, opening one if nothing matches.

        Args:
            signal: The observation. ``source`` names where it came from —
                ``"ops_alert"`` for an existing compressed alert,
                ``"reliability"`` for a service-health incident, and so on.

        Returns:
            ``(incident, created)``. ``created`` is ``True`` when no basis
            strong enough to attach was found and a new incident was opened —
            which is the correct outcome for an unrelated failure.
        """
        window = DEFAULT_CORRELATION_WINDOW_SECONDS

        if signal.incident_id:
            existing = await self.get_incident(signal.incident_id)
            if existing is not None:
                signal.correlation_basis = signal.correlation_basis or BASIS_EXPLICIT
                signal.correlation_confidence = signal.correlation_confidence or 1.0
                await self._signals.save(signal.model_dump())
                incident = await self._absorb(existing, signal)
                return incident, False

        candidates = [Incident(**row) for row in await self._incidents.list_open(limit=200)]
        candidates.sort(
            key=lambda inc: str(inc.metadata.get("last_signal_at") or inc.opened_at),
            reverse=True,
        )

        best_incident: Optional[Incident] = None
        best_basis: Optional[str] = None
        best_confidence = 0.0
        missing: list[str] = []
        weak_links: list[Incident] = []

        for candidate in candidates:
            basis, confidence, candidate_missing = await self._match(signal, candidate, window)
            for token in candidate_missing:
                if token not in missing:
                    missing.append(token)
            if basis is None:
                continue
            if basis not in ATTACHING_BASES:
                weak_links.append(candidate)
                continue
            if confidence > best_confidence:
                best_incident, best_basis, best_confidence = candidate, basis, confidence
            if best_confidence >= 1.0:
                break

        if best_incident is not None and best_basis is not None:
            signal.correlation_basis = best_basis
            signal.correlation_confidence = best_confidence
            signal.incident_id = best_incident.incident_id
            await self._signals.save(signal.model_dump())
            incident = await self._absorb(best_incident, signal, missing_inputs=missing)
            metrics.observe(
                "kyber_correlation_confidence", best_confidence, labels={"basis": best_basis}
            )
            logger.info(
                "kyber signal %s attached to incident %s basis=%s confidence=%.2f",
                signal.signal_id, incident.incident_id, best_basis, best_confidence,
            )
            return incident, False

        # Nothing strong enough. Open a separate incident and record the
        # coincidences we declined to merge on, so the decision is inspectable.
        signal.correlation_basis = None
        signal.correlation_confidence = 0.0
        await self._signals.save(signal.model_dump())
        incident = await self.open_incident(
            title=_signal_title(signal),
            severity=_signal_severity(signal),
            signals=[signal],
            release_id=signal.release_id,
            affected_services=[signal.service] if signal.service else [],
            affected_features=[signal.feature] if signal.feature else [],
            affected_tenants=[signal.tenant_id] if signal.tenant_id else [],
            missing_inputs=missing,
            weak_links=[
                {
                    "incident_id": other.incident_id,
                    "basis": BASIS_TIME_PROXIMITY,
                    "confidence": BASIS_CONFIDENCE[BASIS_TIME_PROXIMITY],
                    "note": "temporal coincidence only — not merged",
                }
                for other in weak_links
            ],
        )
        return incident, True

    async def _absorb(
        self,
        incident: Incident,
        signal: IncidentSignal,
        *,
        missing_inputs: Optional[list[str]] = None,
    ) -> Incident:
        """Fold an attached signal into its incident and re-rank it."""
        incident.signal_count = int(incident.signal_count or 0) + 1
        incident.severity = escalate_severity(incident.severity, _signal_severity(signal))
        incident.affected_services = _union(
            incident.affected_services, [signal.service] if signal.service else []
        )
        incident.affected_features = _union(
            incident.affected_features, [signal.feature] if signal.feature else []
        )
        incident.affected_tenants = _union(
            incident.affected_tenants, [signal.tenant_id] if signal.tenant_id else []
        )
        if signal.release_id and not incident.release_id:
            incident.release_id = signal.release_id

        metadata = dict(incident.metadata)
        metadata["last_signal_at"] = signal.observed_at
        metadata["error_signatures"] = _union(
            metadata.get("error_signatures") or [],
            [signal.error_signature] if signal.error_signature else [],
        )
        metadata["sources"] = _union(metadata.get("sources") or [], [signal.source])
        metadata["correlations"] = [
            *(metadata.get("correlations") or []),
            {
                "signal_id": signal.signal_id,
                "basis": signal.correlation_basis,
                "confidence": signal.correlation_confidence,
                "attached_at": now_iso(),
            },
        ]
        if missing_inputs:
            metadata["missing_inputs"] = _union(metadata.get("missing_inputs") or [], missing_inputs)
        incident.metadata = metadata
        incident.priority_score = _incident_priority(incident)
        incident.updated_at = now_iso()
        await self._incidents.update(incident.incident_id, incident.model_dump())

        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.incident.signal_attached",
            action="attach_signal",
            incident_id=incident.incident_id,
            tenant_id=signal.tenant_id,
            metadata={
                "signal_id": signal.signal_id,
                "basis": signal.correlation_basis,
                "confidence": signal.correlation_confidence,
                "source": signal.source,
                "signal_count": incident.signal_count,
            },
        )
        return incident

    # ── Sweep ────────────────────────────────────────────────────────────────

    async def correlate(
        self, *, window_seconds: int = DEFAULT_CORRELATION_WINDOW_SECONDS
    ) -> dict[str, Any]:
        """Attach loose signals, then merge only what is deterministically one thing.

        Two passes, in order:

        1. every signal no incident has claimed is re-evaluated against the
           open incidents;
        2. open incidents that share a ``release_id`` are merged, because one
           deploy is one cause. No other basis merges incidents — see the
           module docstring for why over-merging is the more expensive error.

        Returns:
            A summary: signals examined, attachments by basis, incidents
            created, incidents merged, weak links declined, and the
            ``missing_inputs`` encountered (an unavailable graph plane shows up
            here rather than as quietly lower confidence).
        """
        loose = await self._signals.list_unattached(limit=1000)
        by_basis: dict[str, int] = {}
        missing: list[str] = []
        created = 0
        attached = 0
        weak_declined = 0

        for row in loose:
            signal = IncidentSignal(**row)
            candidates = [Incident(**item) for item in await self._incidents.list_open(limit=200)]
            best_incident: Optional[Incident] = None
            best_basis: Optional[str] = None
            best_confidence = 0.0
            for candidate in candidates:
                basis, confidence, candidate_missing = await self._match(
                    signal, candidate, window_seconds
                )
                for token in candidate_missing:
                    if token not in missing:
                        missing.append(token)
                if basis is None:
                    continue
                if basis not in ATTACHING_BASES:
                    weak_declined += 1
                    continue
                if confidence > best_confidence:
                    best_incident, best_basis, best_confidence = candidate, basis, confidence

            if best_incident is not None and best_basis is not None:
                signal.correlation_basis = best_basis
                signal.correlation_confidence = best_confidence
                signal.incident_id = best_incident.incident_id
                await self._signals.update(signal.signal_id, signal.model_dump())
                await self._absorb(best_incident, signal, missing_inputs=missing)
                metrics.observe(
                    "kyber_correlation_confidence", best_confidence, labels={"basis": best_basis}
                )
                by_basis[best_basis] = by_basis.get(best_basis, 0) + 1
                attached += 1
            else:
                await self.open_incident(
                    title=_signal_title(signal),
                    severity=_signal_severity(signal),
                    signals=[signal],
                    release_id=signal.release_id,
                    affected_services=[signal.service] if signal.service else [],
                    missing_inputs=missing,
                )
                created += 1

        merged = await self._merge_by_release()

        return {
            "window_seconds": window_seconds,
            "signals_examined": len(loose),
            "attached": attached,
            "created": created,
            "merged_incidents": merged,
            "weak_links_declined": weak_declined,
            "by_basis": by_basis,
            "merge_eligible_bases": sorted(MERGE_ELIGIBLE_BASES),
            "missing_inputs": missing,
            "generated_at": now_iso(),
        }

    async def _merge_by_release(self) -> int:
        """Merge open incidents that share a release. Deterministic only."""
        incidents = [Incident(**row) for row in await self._incidents.list_open(limit=200)]
        by_release: dict[str, list[Incident]] = {}
        for incident in incidents:
            if incident.release_id:
                by_release.setdefault(incident.release_id, []).append(incident)

        merged = 0
        for release_id, group in by_release.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda inc: str(inc.opened_at))
            primary = group[0]
            for secondary in group[1:]:
                await self._merge(primary, secondary, release_id)
                merged += 1
        return merged

    async def _merge(self, primary: Incident, secondary: Incident, release_id: str) -> None:
        """Fold ``secondary`` into ``primary`` and close it, with an audit trail."""
        for row in await self._signals.list_for_incident(secondary.incident_id):
            signal = IncidentSignal(**row)
            signal.incident_id = primary.incident_id
            signal.correlation_basis = BASIS_RELEASE
            signal.correlation_confidence = BASIS_CONFIDENCE[BASIS_RELEASE]
            await self._signals.update(signal.signal_id, signal.model_dump())

        primary.signal_count = int(primary.signal_count or 0) + int(secondary.signal_count or 0)
        primary.severity = escalate_severity(primary.severity, secondary.severity)
        primary.affected_services = _union(primary.affected_services, secondary.affected_services)
        primary.affected_features = _union(primary.affected_features, secondary.affected_features)
        primary.affected_tenants = _union(primary.affected_tenants, secondary.affected_tenants)
        primary.customer_visible = primary.customer_visible or secondary.customer_visible
        primary.security_exposure = primary.security_exposure or secondary.security_exposure
        primary.data_integrity_exposure = (
            primary.data_integrity_exposure or secondary.data_integrity_exposure
        )
        metadata = dict(primary.metadata)
        metadata["merged_incident_ids"] = _union(
            metadata.get("merged_incident_ids") or [], [secondary.incident_id]
        )
        metadata["error_signatures"] = _union(
            metadata.get("error_signatures") or [],
            (secondary.metadata or {}).get("error_signatures") or [],
        )
        primary.metadata = metadata
        primary.priority_score = _incident_priority(primary)
        primary.updated_at = now_iso()
        await self._incidents.update(primary.incident_id, primary.model_dump())

        secondary.status = "closed"
        secondary.closed_at = now_iso()
        secondary.updated_at = secondary.closed_at
        secondary.metadata = {
            **secondary.metadata,
            "merged_into": primary.incident_id,
            "merge_basis": BASIS_RELEASE,
            "merge_confidence": BASIS_CONFIDENCE[BASIS_RELEASE],
        }
        await self._incidents.update(secondary.incident_id, secondary.model_dump())

        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.incident.merged",
            action="merge_incident",
            incident_id=primary.incident_id,
            metadata={
                "merged_incident_id": secondary.incident_id,
                "basis": BASIS_RELEASE,
                "confidence": BASIS_CONFIDENCE[BASIS_RELEASE],
                "release_id": release_id,
            },
        )
        logger.info(
            "kyber incident %s merged into %s (release %s)",
            secondary.incident_id, primary.incident_id, release_id,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def open_incident(
        self,
        *,
        title: str,
        severity: Severity = "medium",
        signals: Optional[list[IncidentSignal]] = None,
        **fields: Any,
    ) -> Incident:
        """Open an incident and attach its founding signals.

        Args:
            title: What is wrong, in operator language.
            severity: Initial severity; later signals may escalate it.
            signals: Signals to attach immediately.
            **fields: Any other :class:`Incident` field, plus the two
                bookkeeping keys ``missing_inputs`` and ``weak_links`` which are
                stored in metadata (an unavailable input and a coincidence we
                declined to merge are both facts about the correlation, not
                about the incident).
        """
        missing_inputs = fields.pop("missing_inputs", None) or []
        weak_links = fields.pop("weak_links", None) or []
        metadata = dict(fields.pop("metadata", None) or {})
        if missing_inputs:
            metadata["missing_inputs"] = list(missing_inputs)
        if weak_links:
            metadata["weak_links"] = list(weak_links)

        known = {key: value for key, value in fields.items() if key in Incident.model_fields}
        unknown = sorted(set(fields) - set(known))
        if unknown:
            raise BadRequestError(f"unknown incident fields: {', '.join(unknown)}")

        incident = Incident(title=title, severity=severity, metadata=metadata, **known)
        incident.priority_score = _incident_priority(incident)
        await self._incidents.save(incident.model_dump())

        metrics.increment(
            "kyber_incident_open_total",
            labels={"severity": incident.severity, "status": incident.status},
        )
        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.incident.opened",
            action="open_incident",
            incident_id=incident.incident_id,
            tenant_id=(incident.affected_tenants or [None])[0],
            metadata={
                "title": incident.title,
                "severity": incident.severity,
                "release_id": incident.release_id,
                "missing_inputs": metadata.get("missing_inputs", []),
            },
        )

        for signal in signals or []:
            signal.incident_id = incident.incident_id
            if signal.correlation_basis is None:
                signal.correlation_basis = BASIS_EXPLICIT
                signal.correlation_confidence = 1.0
            stored = await self._signals.find_by_id(signal.signal_id)
            if stored is None:
                await self._signals.save(signal.model_dump())
            else:
                await self._signals.update(signal.signal_id, signal.model_dump())
            incident = await self._absorb(incident, signal)

        logger.info(
            "kyber incident opened id=%s severity=%s signals=%d",
            incident.incident_id, incident.severity, incident.signal_count,
        )
        return incident

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        """One incident, or ``None``."""
        row = await self._incidents.find_by_id(incident_id)
        return Incident(**row) if row else None

    async def list_incidents(
        self, *, status: Optional[str] = "open", limit: int = 100
    ) -> list[Incident]:
        """Incidents by status, worst-priority first."""
        rows = await self._incidents.list_by_status(status, limit=max(limit * 2, limit))
        incidents = [Incident(**row) for row in rows]
        incidents.sort(
            key=lambda inc: (severity_rank(inc.severity), -float(inc.priority_score or 0.0))
        )
        return incidents[:limit]

    async def signals_for(self, incident_id: str, *, limit: int = 200) -> list[IncidentSignal]:
        """Every signal attributed to an incident, oldest first."""
        rows = await self._signals.list_for_incident(incident_id, limit=limit)
        return [IncidentSignal(**row) for row in rows]

    async def update_incident(
        self, incident_id: str, *, actor_id: str, **fields: Any
    ) -> Incident:
        """Apply an operator update, including the interruption-recovery fields.

        ``last_action``, ``next_action``, ``blocked_by`` and
        ``pending_verification`` are what a returning operator reads first, so
        they are ordinary updatable fields and they survive every other update:
        nothing here clears a field that was not named.

        Args:
            incident_id: Target incident.
            actor_id: Who is updating — recorded in the audit entry and in
                ``operator_notes`` when ``note`` is supplied.
            **fields: Any of :data:`UPDATABLE_INCIDENT_FIELDS`, plus ``note``.

        Raises:
            NotFoundError: No such incident.
            BadRequestError: A field outside the allowed set was supplied.
        """
        incident = await self.get_incident(incident_id)
        if incident is None:
            raise NotFoundError(f"kyber incident {incident_id}")

        note = fields.pop("note", None)
        unknown = sorted(set(fields) - UPDATABLE_INCIDENT_FIELDS)
        if unknown:
            raise BadRequestError(f"unknown incident fields: {', '.join(unknown)}")

        changed: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            setattr(incident, key, value)
            changed[key] = value

        if note:
            incident.operator_notes = [
                *incident.operator_notes,
                {"actor_id": actor_id, "note": note, "at": now_iso()},
            ]
            changed["note"] = note

        incident.priority_score = _incident_priority(incident)
        incident.updated_at = now_iso()
        await self._incidents.update(incident_id, incident.model_dump())

        await self._audit(
            actor_id=actor_id,
            event_type="kyber.incident.updated",
            action="update_incident",
            incident_id=incident_id,
            tenant_id=(incident.affected_tenants or [None])[0],
            metadata={"changed": sorted(changed), "status": incident.status},
        )
        return incident

    async def resolve_incident(
        self, incident_id: str, *, actor_id: str, root_cause: Optional[str] = None
    ) -> Incident:
        """Resolve an incident, recording the root cause.

        The root cause is stored on the incident rather than only in an audit
        note, because the next person to see a similar signal needs it at the
        top of the record, not in a log search.
        """
        incident = await self.get_incident(incident_id)
        if incident is None:
            raise NotFoundError(f"kyber incident {incident_id}")
        if incident.status in ("resolved", "closed"):
            raise BadRequestError(f"incident {incident_id} is already {incident.status}")

        previous = incident.status
        incident.status = "resolved"
        incident.resolved_at = now_iso()
        incident.updated_at = incident.resolved_at
        if root_cause:
            incident.root_cause = root_cause
        incident.next_action = None
        incident.blocked_by = None
        incident.last_action = f"resolved by {actor_id}"
        await self._incidents.update(incident_id, incident.model_dump())

        await self._audit(
            actor_id=actor_id,
            event_type="kyber.incident.resolved",
            action="resolve_incident",
            incident_id=incident_id,
            tenant_id=(incident.affected_tenants or [None])[0],
            metadata={
                "from_status": previous,
                "root_cause": incident.root_cause or "",
                "signal_count": incident.signal_count,
                "pending_verification": incident.pending_verification,
            },
        )
        logger.info(
            "kyber incident resolved id=%s actor=%s root_cause=%s",
            incident_id, actor_id, bool(incident.root_cause),
        )
        return incident

    # ── Briefing support ─────────────────────────────────────────────────────

    def resume_card(self, incident: Incident) -> dict[str, Any]:
        """What a returning operator needs to pick this incident back up.

        Deterministic fields only. A summary may be layered on top later, but
        the card itself must be readable when no summariser is available.
        """
        return {
            "incident_id": incident.incident_id,
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "priority_score": incident.priority_score,
            "last_action": incident.last_action,
            "next_action": incident.next_action,
            "blocked_by": incident.blocked_by,
            "pending_verification": list(incident.pending_verification or []),
            "root_cause": incident.root_cause,
            "signal_count": incident.signal_count,
            "affected_services": list(incident.affected_services or []),
            "affected_tenants": list(incident.affected_tenants or []),
            "opened_at": incident.opened_at,
            "updated_at": incident.updated_at,
            "missing_inputs": list((incident.metadata or {}).get("missing_inputs") or []),
        }

    async def resume_cards(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Resume cards for every incident someone is part-way through."""
        cards: list[dict[str, Any]] = []
        for status in IN_PROGRESS_STATUSES:
            for incident in await self.list_incidents(status=status, limit=limit):
                cards.append(self.resume_card(incident))
        cards.sort(key=lambda card: -float(card.get("priority_score") or 0.0))
        return cards[:limit]


def _signal_title(signal: IncidentSignal) -> str:
    """A human-first incident title derived from the founding signal."""
    subject = signal.service or signal.feature or signal.source
    detail = signal.error_signature or signal.signal_type
    return f"{subject}: {detail}"


def _signal_severity(signal: IncidentSignal) -> Severity:
    """Severity carried on the signal payload, defaulting to ``medium``.

    Signals arrive from planes with their own vocabularies (ops_alerts uses
    ``P0``–``P4``), so a payload value is only trusted when it is already a
    Kyber severity. Anything unrecognised falls back to ``medium`` rather than
    guessing a mapping the source did not intend.
    """
    candidate = (signal.payload or {}).get("severity")
    if candidate in ("critical", "high", "medium", "low", "info"):
        return candidate  # type: ignore[return-value]
    return "medium"


def _incident_priority(incident: Incident) -> float:
    """Rank an incident: severity floor, plus bounded reach and volume.

    Deliberately the same shape as the exception scorer — consequence dominates
    and volume is capped — so the two queues cannot disagree about which of two
    things is worse.
    """
    base = _SEVERITY_BASE_PRIORITY.get(incident.severity, 45.0)
    reach = min(6.0, 2.0 * len(incident.affected_tenants or []))
    volume = min(4.0, float(incident.signal_count or 0) * 0.5)
    exposure = 0.0
    if incident.security_exposure:
        exposure += 6.0
    if incident.data_integrity_exposure:
        exposure += 5.0
    if incident.customer_visible:
        exposure += 4.0
    if incident.revenue_exposure:
        exposure += 3.0
    return round(min(100.0, base + reach + volume + exposure), 4)


#: Process-wide singleton. Worker O2 and the routes both call this.
incident_correlator = IncidentCorrelator()


def build_incident_correlator_coro() -> Coroutine[Any, Any, dict[str, Any]]:
    """Zero-argument factory for a correlation sweep.

    The background scheduler wants something it can call with no arguments and
    await. Returning a fresh coroutine each call (rather than a shared one)
    keeps a retried tick from awaiting an already-consumed coroutine.
    """
    return incident_correlator.correlate()


__all__ = [
    "ATTACHING_BASES",
    "BASIS_CONFIDENCE",
    "BASIS_ERROR_SIGNATURE",
    "BASIS_GRAPH_DEPENDENCY",
    "BASIS_RELEASE",
    "BASIS_SERVICE_WINDOW",
    "BASIS_TIME_PROXIMITY",
    "CORRELATION_BASES",
    "DEFAULT_CORRELATION_WINDOW_SECONDS",
    "MERGE_ELIGIBLE_BASES",
    "MISSING_GRAPH_ENTRYPOINT",
    "MISSING_GRAPH_PLANE",
    "IncidentCorrelator",
    "build_incident_correlator_coro",
    "incident_correlator",
]
