"""Pattern discovery service: evidence loading, persistence and the review workflow.

Orchestrates I/O around the pure :mod:`engine`:

* ``run`` – read the tenant's recent events (bounded, truncation reported) and
  any inline evidence, load baseline and analyst feedback, run the engine,
  upsert pattern records, age patterns the run did not re-observe, fold the
  run into the baseline and store a run record.
* ``review`` / ``promote`` / ``deprecate`` – the human lifecycle; every review
  is also an analyst-feedback row (the calibration source).
* ``entity_context`` – emerging-pattern context for Profile / Agent / Risk 360.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from .baselines import PatternBaselineRepository
from .contracts import (
    KIND_NOVEL_MOTIF, KIND_TRAFFIC_ANOMALY, PATTERN_KINDS, VISIBLE_STATUSES, STATUS_DEPRECATED,
    STATUS_PROMOTED,
)
from .detectors import DETECTORS
from .engine import new_run_id, run_discovery
from .extraction import extract_events, extract_payload
from .feed import (
    PatternViewerStateRepository, annotate_new, notify_new_patterns, resolve_since, summarize, whats_new,
)
from .graph import project_promotion, revoke_promotion, tenant_graph_edges
from .graphview import keys_for_ids, overlay, pattern_subgraph
from .lenses import LENSES, SEGMENT_LENSES, lens_segment_key, lens_view
from .ml import score_windows
from .registry import LifecycleError
from .projections import consent_allows, entity_context, promote_to_risk, similar_patterns
from .registry import (
    PatternDiscoveryRunRepository, PatternFeedbackRepository, PatternRegistryRepository,
    apply_curation, apply_deprecation, apply_promotion, apply_review, mark_unseen, merge_duplicate,
)

logger = get_logger("aether.pattern_discovery.service")


def _config():
    from config.settings import settings

    return settings.pattern_discovery


def _advances(last: Optional[str], current: str, window_hours: int) -> bool:
    """Fold a run into the baseline only once its window has moved on by at
    least half a window. Overlapping scheduled runs over mostly the same events
    would otherwise count one stretch of activity many times (and make an
    ongoing pattern look "familiar" within hours)."""
    if not last:
        return True
    from shared.temporal.instant import coerce_utc_lenient

    a, b = coerce_utc_lenient(last), coerce_utc_lenient(current)
    if a is None or b is None:
        return True
    return (b - a).total_seconds() >= window_hours * 3600 / 2


class PatternDiscoveryService:
    def __init__(self, *, registry: Optional[PatternRegistryRepository] = None,
                 baselines: Optional[PatternBaselineRepository] = None,
                 feedback: Optional[PatternFeedbackRepository] = None,
                 runs: Optional[PatternDiscoveryRunRepository] = None,
                 event_reader: Optional[Any] = None,
                 risk_store: Optional[Any] = None,
                 subject_resolver: Optional[Any] = None,
                 consent_reader: Optional[Any] = None,
                 graph_client: Optional[Any] = None,
                 ml_client: Optional[Any] = None,
                 viewer_state: Optional[Any] = None,
                 notifier: Optional[Any] = None) -> None:
        self.registry = registry or PatternRegistryRepository()
        self.baselines = baselines or PatternBaselineRepository()
        self.feedback = feedback or PatternFeedbackRepository()
        self.runs = runs or PatternDiscoveryRunRepository()
        self._event_reader = event_reader
        self._risk_store = risk_store
        self._resolver = subject_resolver
        self._consent = consent_reader
        self._graph = graph_client
        self._ml_client = ml_client
        self.viewer_state = viewer_state or PatternViewerStateRepository()
        self._notifier = notifier or notify_new_patterns

    # ── Evidence ─────────────────────────────────────────────────────────────
    async def _read_events(self, tenant_id: str, window_hours: int, max_events: int) -> tuple[list[dict], dict]:
        reader = self._event_reader
        if reader is None:
            from dependencies.providers import get_cache
            from repositories.repos import AnalyticsRepository

            reader = AnalyticsRepository(get_cache())
        since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        try:
            rows = await reader.query_events(tenant_id, {"start_date": since}, limit=max_events + 1)
        except Exception as exc:  # noqa: BLE001 - an unavailable store is reported, not hidden
            logger.warning("pattern_discovery.event_read_failed",
                           extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
            return [], {"store": "unavailable", "error_type": type(exc).__name__}
        truncated = len(rows) > max_events
        return rows[:max_events], {"store": "ok", "rows": min(len(rows), max_events), "truncated": truncated,
                                   "window_hours": window_hours, "since": since, "limit": max_events}

    # ── Discovery run ────────────────────────────────────────────────────────
    async def run(self, tenant_id: str, *, window_hours: Optional[int] = None,
                  max_events: Optional[int] = None, kinds: Optional[list[str]] = None,
                  events: Optional[list[dict]] = None, edges: Optional[list[dict]] = None,
                  include_store: bool = True, requested_by: Optional[str] = None) -> dict[str, Any]:
        cfg = _config()
        window_hours = window_hours or cfg.window_hours
        max_events = max_events or cfg.max_events
        started_at = utc_now().isoformat()
        rows: list[dict] = []
        coverage: dict[str, Any] = {"store": "skipped"}
        if include_store:
            rows, coverage = await self._read_events(tenant_id, window_hours, max_events)
        inline = [dict(e, tenant_id=e.get("tenant_id") or tenant_id) for e in (events or [])]
        foreign = sum(1 for e in inline if e.get("tenant_id") != tenant_id)
        rows = rows + [e for e in inline if e.get("tenant_id") == tenant_id]
        coverage["inline_rows"] = len(inline) - foreign
        coverage["inline_foreign_rows_rejected"] = foreign

        baseline = await self.baselines.get(tenant_id)
        feedback = await self.feedback.aggregate(tenant_id)
        run_id = new_run_id(tenant_id)
        extraction = extract_events(rows, tenant_id)

        graph_edges = list(edges or [])
        if edges is None and cfg.graph_motifs_enabled and (not kinds or KIND_NOVEL_MOTIF in kinds):
            graph_edges, coverage["graph"] = await tenant_graph_edges(tenant_id, self._graph)
        else:
            coverage["graph"] = {"graph": "inline" if edges is not None else "disabled", "edges": len(graph_edges)}

        ml_scores: dict[str, float] = {}
        if cfg.ml_scoring_enabled and (not kinds or KIND_TRAFFIC_ANOMALY in kinds) and extraction.events:
            ml_scores, coverage["ml"] = await score_windows(extraction, self._ml_client)
        else:
            coverage["ml"] = {"status": "disabled"}

        prior = [r for r in await self.registry.scan(tenant_id, limit=2_000)
                 if r.get("status") not in (STATUS_DEPRECATED, "duplicate", "benign")]
        result = run_discovery(tenant_id, rows, baseline=baseline, feedback=feedback, edges=graph_edges,
                               kinds=kinds, run_id=run_id, extraction=extraction,
                               ml_window_scores=ml_scores, prior_patterns=prior)

        saved: list[dict[str, Any]] = []
        merged = 0
        for record in result.records:
            stored = await self.registry.upsert_detected(record)
            saved.append(stored)
            if stored.get("status") == "duplicate" and stored.get("duplicate_of"):
                target = await self.registry.mutate(
                    tenant_id, stored["duplicate_of"], lambda row, dup=stored: merge_duplicate(row, dup))
                merged += bool(target)
        newly_surfaced = [r for r in saved if r.get("status") == "surfaced"
                          and (r.get("surfaced_at") or "") >= started_at]
        notification = None
        if newly_surfaced and cfg.notifications_enabled:
            notification = await self._notifier(tenant_id, newly_surfaced, run_id=run_id)
        seen = {r["pattern_id"] for r in result.records}
        aged = deprecated = 0
        for existing in await self.registry.scan(tenant_id):
            if (existing["pattern_id"] in seen or existing.get("kind") not in result.kinds_run
                    or existing.get("status") in (STATUS_DEPRECATED, STATUS_PROMOTED)):
                continue
            updated = await self.registry.mutate(tenant_id, existing["pattern_id"],
                                                 lambda row: mark_unseen(row, run_id))
            aged += 1
            if updated and updated.get("status") == STATUS_DEPRECATED:
                deprecated += 1
        baseline_updated = False
        window_end = result.stats.get("window_end")
        if rows and window_end and _advances(baseline.get("last_window_end"), window_end, window_hours):
            def fold(current: dict[str, Any]) -> dict[str, Any]:
                out = result.apply_to_baseline(current)
                out["last_window_end"] = window_end
                return out

            await self.baselines.save(tenant_id, fold)
            baseline_updated = True
        elif rows:
            coverage["baseline"] = {"status": "skipped_overlapping_window",
                                    "last_window_end": baseline.get("last_window_end"), "window_end": window_end}

        by_status: dict[str, int] = {}
        for r in saved:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        run = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "requested_by": requested_by,
            "started_at": started_at,
            "finished_at": utc_now().isoformat(),
            "coverage": coverage,
            "kinds_run": result.kinds_run,
            "detectors_run": result.detectors_run,
            "stats": result.stats,
            "patterns_detected": len(saved),
            "patterns_by_status_after_merge": by_status,
            "pattern_ids": [r["pattern_id"] for r in saved][:500],
            "duplicates_merged": merged,
            "newly_surfaced": len(newly_surfaced),
            "notification_id": (notification or {}).get("id") if isinstance(notification, dict) else None,
            "aged_patterns": aged,
            "auto_deprecated": deprecated,
            "baseline_updated": baseline_updated,
        }
        await self.runs.save_run(run)
        metrics.increment("pattern_discovery_runs_total", labels={"tenant_scoped": "true"})
        metrics.increment("pattern_discovery_patterns_total", value=len(saved))
        return {**run, "patterns": [self._summary(r) for r in saved],
                "observations_sample": result.observations_sample[:50]}

    @staticmethod
    def _summary(r: dict[str, Any]) -> dict[str, Any]:
        out = {k: r.get(k) for k in (
            "pattern_id", "kind", "summary", "status", "priority", "severity", "severity_score",
            "confidence", "confidence_cap", "novelty", "affected_entity_count", "risk_categories",
            "first_observed_at", "last_observed_at", "version", "times_observed", "detector",
            "suppressed_by_feedback", "claim_state", "pinned", "surfaced_at", "changed_at",
            "deprecated_at", "segment_keys",
        )}
        out["title"] = r.get("display_title") or r.get("title")
        out["detector_title"] = r.get("title")
        return out

    # ── Reads ────────────────────────────────────────────────────────────────
    async def list_patterns(self, tenant_id: str, *, status: Optional[str] = None, feed: bool = False,
                            kind: Optional[str] = None, min_confidence: float = 0.0,
                            limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """``feed=True`` is the default surfaced view (visible statuses, pinned first)."""
        statuses = set(VISIBLE_STATUSES) if feed else ({status} if status else None)
        rows, total = await self.registry.list_patterns(
            tenant_id, statuses=statuses, kind=kind, min_confidence=min_confidence,
            limit=max(1, min(limit, 200)), offset=max(0, offset),
        )
        return {"items": [self._summary(r) for r in rows], "count": len(rows), "total": total}

    async def get_pattern(self, tenant_id: str, pid: str) -> Optional[dict[str, Any]]:
        row = await self.registry.get(tenant_id, pid)
        if row is None:
            return None
        others = await self.registry.scan(tenant_id, limit=2_000)
        row["similar_patterns"] = similar_patterns(row, others)
        row["members"] = [
            self._summary(o) for o in others if o.get("pattern_id") in set(row.get("member_pattern_ids") or [])
        ]
        return row

    async def entity_context(self, tenant_id: str, entity_key: str) -> dict[str, Any]:
        """Advisory context, released only with an affirmative analytics consent receipt."""
        allowed, receipt, reason = await consent_allows(tenant_id, entity_key, reader=self._consent)
        if not allowed:
            return {"entity": entity_key, "withheld": True, "reason_code": reason, "advisory": True,
                    "claim_state": "inferred", "emerging_patterns": [], "reviewed_patterns": [],
                    "unresolved_identity_overlaps": [], "co_implicated_entities": [],
                    "kinds": [], "risk_categories": [], "counts": {"open": 0, "reviewed": 0, "total": 0}}
        ctx = entity_context(entity_key, await self.registry.for_entity(tenant_id, entity_key, limit=200))
        ctx["withheld"] = False
        ctx["consent_receipt_id"] = receipt
        return ctx

    async def section(self, tenant_id: str, entity_key: str, surface: str,
                      viewer_id: Optional[str] = None) -> dict[str, Any]:
        """Profile 360 / Agent 360 / Risk 360 section for one entity (consent-gated)."""
        from .sections import SECTIONS

        builder = SECTIONS[surface]
        allowed, receipt, reason = await consent_allows(tenant_id, entity_key, reader=self._consent)
        if not allowed:
            out = builder(entity_key, [])
            out.update({"withheld": True, "reason_code": reason})
            return out
        # A profile id may be a raw user id or a canonical entity id: read both keys.
        kind, _, ident = entity_key.partition(":")
        keys = [entity_key] + ([f"entity:{ident}"] if surface == "profile360" and kind == "user" else [])
        rows: dict[str, dict[str, Any]] = {}
        for key in keys:
            for row in await self.registry.for_entity(tenant_id, key, limit=200):
                rows.setdefault(row["pattern_id"], row)
        out = builder(entity_key, list(rows.values()))
        out.update({"withheld": False, "consent_receipt_id": receipt})
        return await self._with_last_seen(out, tenant_id, viewer_id, f"{surface}:{entity_key}")

    async def _with_last_seen(self, out: dict[str, Any], tenant_id: str, viewer_id: Optional[str],
                              scope: str) -> dict[str, Any]:
        """Attach the viewer's last-seen time for ``scope`` and mark new/changed rows."""
        last_seen = await self.viewer_state.get_last_seen(tenant_id, viewer_id, scope) if viewer_id else None
        out["scope"] = scope
        out["last_seen_at"] = last_seen
        for value in out.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and "pattern_id" in value[0]:
                annotate_new(value, last_seen)
        for group in out.get("groups") or []:
            annotate_new(group.get("patterns") or [], last_seen)
        out["new_count"] = len({r["pattern_id"] for v in out.values() if isinstance(v, list)
                                for r in v if isinstance(r, dict) and r.get("is_new")})
        return out

    # ── What's new ───────────────────────────────────────────────────────────
    async def _scope_patterns(self, tenant_id: str, scope: str) -> list[dict[str, Any]]:
        if scope == "feed":
            return await self.registry.scan(tenant_id)
        if scope.startswith("lens:"):
            _, lens, subject = (scope.split(":", 2) + ["", ""])[:3]
            if lens in SEGMENT_LENSES:
                return await self.registry.for_segment(tenant_id, lens_segment_key(lens, subject))
            if lens == "journey360":
                return await self.registry.for_entity(tenant_id, f"user:{subject}", limit=500)
            raise LifecycleError(f"unknown lens {lens!r}")
        surface, _, entity_key = scope.partition(":")
        if surface in ("profile360", "agent360", "risk360") and ":" in entity_key:
            return await self.registry.for_entity(tenant_id, entity_key, limit=500)
        raise LifecycleError("scope must be 'feed', '<surface>:<kind>:<id>' or 'lens:<lens>:<subject>'")

    async def whats_new(self, tenant_id: str, *, viewer_id: str, scope: str = "feed",
                        since: Optional[str] = None) -> dict[str, Any]:
        """New, changed and retired patterns since the viewer last looked at ``scope``."""
        last_seen = await self.viewer_state.get_last_seen(tenant_id, viewer_id, scope)
        since_dt = resolve_since(since, last_seen)
        if scope != "feed" and not scope.startswith("lens:") or scope.startswith("lens:journey360:"):
            key = scope.partition(":")[2] if not scope.startswith("lens:") else f"user:{scope.split(':', 2)[2]}"
            allowed, _receipt, reason = await consent_allows(tenant_id, key, reader=self._consent)
            if not allowed:
                return {"scope": scope, "withheld": True, "reason_code": reason, "since": since_dt.isoformat(),
                        "last_seen_at": last_seen, "new": [], "changed": [], "retired": [],
                        "digest": {"new": summarize([]), "changed": summarize([]), "retired": summarize([])}}
        buckets = whats_new(await self._scope_patterns(tenant_id, scope), since=since_dt)
        return {
            "scope": scope,
            "withheld": False,
            "since": since_dt.isoformat(),
            "since_source": "explicit" if since else ("last_seen" if last_seen else "default_lookback"),
            "last_seen_at": last_seen,
            "as_of": utc_now().isoformat(),
            **{name: [self._summary(r) for r in rows] for name, rows in buckets.items()},
            "digest": {name: summarize(rows) for name, rows in buckets.items()},
        }

    async def mark_seen(self, tenant_id: str, *, viewer_id: str, scope: str = "feed",
                        at: Optional[str] = None) -> dict[str, Any]:
        if scope != "feed":
            await self._scope_patterns(tenant_id, scope)  # validates the scope
        return await self.viewer_state.mark_seen(tenant_id, viewer_id, scope, at)

    # ── Lenses ───────────────────────────────────────────────────────────────
    async def lens(self, tenant_id: str, lens: str, subject: str, viewer_id: Optional[str] = None) -> dict[str, Any]:
        if lens not in LENSES:
            raise LifecycleError(f"lens must be one of {list(LENSES)}")
        subject = (subject or "").strip()
        if not subject:
            raise LifecycleError("subject is required")
        if lens == "journey360":
            key = f"user:{subject}"
            allowed, _receipt, reason = await consent_allows(tenant_id, key, reader=self._consent)
            if not allowed:
                out = lens_view(lens, subject, [])
                out.update({"withheld": True, "reason_code": reason})
                return out
            rows = await self.registry.for_entity(tenant_id, key, limit=500)
            rows += [r for r in await self.registry.for_entity(tenant_id, f"entity:{subject}", limit=500)
                     if r["pattern_id"] not in {x["pattern_id"] for x in rows}]
        elif lens == "communication360" and subject.lower() == "all":
            rows = [r for r in await self.registry.scan(tenant_id)
                    if any(k.startswith("channel=") for k in r.get("segment_keys") or [])
                    or "communication" in (r.get("risk_categories") or [])]
        else:
            rows = await self.registry.for_segment(tenant_id, lens_segment_key(lens, subject))
        out = lens_view(lens, subject, rows)
        out["withheld"] = False
        return await self._with_last_seen(out, tenant_id, viewer_id, f"lens:{lens}:{subject}")

    # ── Graph ────────────────────────────────────────────────────────────────
    async def pattern_graph(self, tenant_id: str, pid: str) -> Optional[dict[str, Any]]:
        row = await self.registry.get(tenant_id, pid)
        return pattern_subgraph(row) if row is not None else None

    async def graph_overlay(self, tenant_id: str, node_ids: list[str]) -> dict[str, Any]:
        ids = [str(i) for i in node_ids][:500]
        lookup = keys_for_ids(ids)
        out = overlay(ids, await self.registry.for_entities(tenant_id, list(lookup)))
        out["nodes_requested"] = len(ids)
        return out

    async def stats(self, tenant_id: str) -> dict[str, Any]:
        from .scoring import calibration_factors, suppressed_families

        rows = await self.registry.scan(tenant_id)
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for r in rows:
            by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1
            by_kind[r.get("kind")] = by_kind.get(r.get("kind"), 0) + 1
        feedback = await self.feedback.aggregate(tenant_id)
        baseline = await self.baselines.get(tenant_id)
        return {
            "patterns": len(rows),
            "by_status": by_status,
            "by_kind": by_kind,
            "visible": sum(by_status.get(s, 0) for s in VISIBLE_STATUSES),
            "surfaced": by_status.get("surfaced", 0),
            "watching": by_status.get("candidate", 0),
            "hidden": by_status.get("hidden", 0),
            "feedback": {"total": feedback.get("total", 0), "kinds": feedback.get("kinds", {})},
            "calibration": calibration_factors(feedback),
            "suppressed_families": sorted(suppressed_families(feedback)),
            "baseline": {"runs": baseline.get("runs", 0), "updated_at": baseline.get("updated_at"),
                         "tokens": len(baseline.get("token_rate") or {}),
                         "signatures": len(baseline.get("signatures") or {}),
                         "event_groups": len(baseline.get("field_profiles") or {})},
            "kinds": list(PATTERN_KINDS),
            "detectors": sorted(DETECTORS) + ["cross_domain"],
        }

    async def list_runs(self, tenant_id: str, limit: int = 20) -> dict[str, Any]:
        rows = await self.runs.list_runs(tenant_id, limit=limit)
        return {"items": rows, "count": len(rows)}

    def extract(self, tenant_id: str, payload: Any, *, event_type: Optional[str] = None,
                text: Optional[str] = None) -> dict[str, Any]:
        return extract_payload(payload, tenant_id, event_type=event_type, text=text)

    # ── Human lifecycle ──────────────────────────────────────────────────────
    async def review(self, tenant_id: str, pid: str, *, reviewer_id: str, verdict: str, reason: str,
                     duplicate_of: Optional[str] = None) -> Optional[dict[str, Any]]:
        if duplicate_of and await self.registry.get(tenant_id, duplicate_of) is None:
            from .registry import LifecycleError

            raise LifecycleError("duplicate_of does not name a pattern in this tenant")
        updated = await self.registry.mutate(
            tenant_id, pid,
            lambda row: apply_review(row, reviewer_id=reviewer_id, verdict=verdict, reason=reason,
                                     duplicate_of=duplicate_of),
        )
        if updated is not None:
            await self.feedback.record(tenant_id, updated, reviewer_id=reviewer_id, verdict=verdict, reason=reason)
            if verdict == "duplicate" and duplicate_of:
                await self.registry.mutate(tenant_id, duplicate_of,
                                           lambda row, dup=updated: merge_duplicate(row, dup))
            metrics.increment("pattern_discovery_reviews_total", labels={"verdict": verdict})
        return updated

    async def curate(self, tenant_id: str, pid: str, *, actor: str, action: str,
                     title: Optional[str] = None, reason: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Hide / unhide / pin / unpin / rename an automatically surfaced pattern.
        ``hide`` is also recorded as noise feedback so similar patterns are
        surfaced less eagerly; ``unhide`` is not counted either way."""
        updated = await self.registry.mutate(
            tenant_id, pid, lambda row: apply_curation(row, actor=actor, action=action, title=title, reason=reason))
        if updated is not None and action == "hide":
            await self.feedback.record(tenant_id, updated, reviewer_id=actor, verdict="hidden",
                                       reason=reason or "hidden by user")
        return updated

    async def promote(self, tenant_id: str, pid: str, *, reviewer_id: str, reason: str) -> Optional[dict[str, Any]]:
        updated = await self.registry.mutate(
            tenant_id, pid, lambda row: apply_promotion(row, reviewer_id=reviewer_id, reason=reason),
        )
        if updated is None:
            return None
        outcomes: list[dict[str, Any]] = []
        risk_status = "disabled"
        if _config().risk_promotion_enabled:
            outcomes = await promote_to_risk(updated, resolver=self._resolver, store=self._risk_store,
                                             consent_reader=self._consent)
            risk_status = "written" if any(o["status"] == "written" for o in outcomes) else "no_resolvable_subjects"

        graph_report: dict[str, Any] = {"status": "disabled"}
        if _config().graph_promotion_enabled:
            graph_report = await project_promotion(updated, outcomes, self._graph)

        def record_outcomes(row: dict[str, Any]) -> dict[str, Any]:
            promotion = dict(row.get("promotion") or {})
            promotion["risk_signals"] = outcomes
            promotion["risk_projection"] = risk_status
            promotion["graph_projection"] = graph_report
            row["promotion"] = promotion
            return row

        final = await self.registry.mutate(tenant_id, pid, record_outcomes)
        metrics.increment("pattern_discovery_promotions_total", labels={"risk_projection": risk_status})
        return final

    async def deprecate(self, tenant_id: str, pid: str, *, actor: str, reason: str) -> Optional[dict[str, Any]]:
        """Deprecate; a promoted pattern's graph memberships are soft-revoked too.
        Its Risk360 signals stay: they are attributed history the risk plane owns."""
        updated = await self.registry.mutate(tenant_id, pid,
                                             lambda row: apply_deprecation(row, actor=actor, reason=reason))
        if updated is not None and (updated.get("promotion") or {}).get("graph_projection", {}).get("status") == "projected":
            report = await revoke_promotion(updated, self._graph)

            def note(row: dict[str, Any]) -> dict[str, Any]:
                promotion = dict(row.get("promotion") or {})
                promotion["graph_revocation"] = report
                row["promotion"] = promotion
                return row

            updated = await self.registry.mutate(tenant_id, pid, note)
        return updated


_service: Optional[PatternDiscoveryService] = None


def get_service() -> PatternDiscoveryService:
    global _service
    if _service is None:
        _service = PatternDiscoveryService()
    return _service


def set_service(service: Optional[PatternDiscoveryService]) -> None:
    global _service
    _service = service
