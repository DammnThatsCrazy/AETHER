"""Pattern registry: versioned pattern records and their governed lifecycle.

A pattern's identity is ``(tenant, kind, signature)``. Re-detecting the same
signature in a later run updates the same record (support, evidence,
``times_observed``) instead of creating a new one, and bumps ``version`` when
the evidence fingerprint changes.

Lifecycle::

    candidate <-> needs_review --(reviewer verdict)--> confirmed_valid
                                                       confirmed_malicious --(promote)--> promoted
                                                       benign / duplicate / unresolved
    any open or reviewed state --(reviewer or staleness)--> deprecated --(re-detected)--> funnel

Rules:

* Only :func:`apply_review` sets a reviewed status, and it requires a reviewer
  and a reason. Only :func:`apply_promotion` promotes, and only from a
  confirmed status.
* A verdict is valid for the evidence it was made on. A re-detection whose
  evidence fingerprint differs from the reviewed fingerprint supersedes the
  verdict (kept in ``review_history``) and the pattern re-enters the funnel.
* Promotion is sticky: a promoted pattern is a known pattern; re-detection
  refreshes its support but never re-queues it.
* Open patterns not re-observed for :data:`STALE_AFTER_RUNS` runs are
  deprecated automatically; reviewed ones are never auto-deprecated.
* Every write after the first is a compare-and-set on ``revision``.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Callable, Optional

from repositories.repos import BaseRepository
from shared.common.common import ConflictError, utc_now

from .contracts import (
    DETECTOR_VERSION, MAX_AFFECTED_ENTITIES, PROMOTABLE_STATUSES, REVIEWED_STATUSES,
    STALE_AFTER_RUNS, STATUS_CANDIDATE, STATUS_DEPRECATED, STATUS_DUPLICATE, STATUS_NEEDS_REVIEW,
    STATUS_PROMOTED, SYSTEM_STATUSES, VERDICT_STATUS, RawPattern, content_hash, entity_ref,
    pattern_id, size_bucket,
)

_VERDICT_TARGETS = frozenset(VERDICT_STATUS.values())
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_CANDIDATE: frozenset({STATUS_NEEDS_REVIEW, STATUS_DEPRECATED}) | _VERDICT_TARGETS,
    STATUS_NEEDS_REVIEW: frozenset({STATUS_CANDIDATE, STATUS_DEPRECATED}) | _VERDICT_TARGETS,
    **{s: (_VERDICT_TARGETS - {s}) | {STATUS_DEPRECATED} for s in REVIEWED_STATUSES},
    STATUS_PROMOTED: frozenset({STATUS_DEPRECATED}),
    STATUS_DEPRECATED: frozenset({STATUS_CANDIDATE, STATUS_NEEDS_REVIEW}),
}
for _s in PROMOTABLE_STATUSES:
    LEGAL_TRANSITIONS[_s] = LEGAL_TRANSITIONS[_s] | {STATUS_PROMOTED}

MAX_RUNS_TRACKED = 10


class LifecycleError(ValueError):
    pass


def check_transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in LEGAL_TRANSITIONS.get(current, frozenset()):
        raise LifecycleError(f"illegal pattern transition {current} -> {target}")


def evidence_fingerprint(record: dict[str, Any]) -> str:
    """What a reviewer evaluated: the signature, the kinds of evidence, the
    order of magnitude of the affected population and the risk reading.
    Individual entities coming and going is drift, not a new claim."""
    return content_hash({
        "kind": record.get("kind"),
        "signature_hash": record.get("signature_hash"),
        "evidence_types": sorted(str(e.get("type")) for e in record.get("evidence", [])),
        "size_bucket": size_bucket(int(record.get("affected_entity_count") or 0)),
        "risk_categories": sorted(record.get("risk_categories") or []),
    }, 32)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def build_record(tenant_id: str, raw: RawPattern, scored: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    now = utc_now().isoformat()
    sig_hash = raw.signature_hash
    entities = sorted(dict.fromkeys(raw.affected_entities))
    span = ((raw.last_observed_at - raw.first_observed_at).total_seconds()
            if raw.first_observed_at and raw.last_observed_at else None)
    record = {
        "pattern_id": pattern_id(tenant_id, raw.kind, sig_hash),
        "tenant_id": tenant_id,
        "kind": raw.kind,
        "signature": raw.signature,
        "signature_hash": sig_hash,
        "family": scored["family"],
        "title": raw.title[:300],
        "summary": raw.summary[:2000],
        "version": 1,
        "status": scored["status"],
        "priority": scored["priority"],
        "severity": scored["severity"],
        "severity_score": scored["severity_score"],
        "confidence": scored["confidence"],
        "confidence_cap": scored["confidence_cap"],
        "raw_confidence": scored["raw_confidence"],
        "calibration": scored["calibration"],
        "suppressed_by_feedback": scored["suppressed_by_feedback"],
        "novelty": scored["novelty"],
        "novelty_detail": scored["novelty_detail"],
        "claim_state": "inferred",
        "affected_entities": [entity_ref(e) for e in entities[:MAX_AFFECTED_ENTITIES]],
        "affected_entity_keys": entities[:MAX_AFFECTED_ENTITIES],
        "affected_entity_count": len(entities),
        "affected_entities_truncated": len(entities) > MAX_AFFECTED_ENTITIES,
        "entity_kinds": sorted({e.split(":", 1)[0] for e in entities}),
        "occurrence_count": raw.occurrence_count,
        "episode_count": raw.episode_count,
        "first_observed_at": _iso(raw.first_observed_at),
        "last_observed_at": _iso(raw.last_observed_at),
        "span_seconds": span,
        "evidence": [e.to_dict() for e in raw.evidence],
        "risk_categories": sorted(set(raw.risk_categories)),
        "competing_explanations": raw.competing_explanations,
        "baseline": raw.baseline,
        "detector": raw.detector,
        "detector_version": DETECTOR_VERSION,
        "member_pattern_ids": raw.member_pattern_ids,
        "duplicate_of": None,
        "run_ids": [run_id],
        "last_run_id": run_id,
        "runs_since_seen": 0,
        "times_observed": 1,
        "review_history": [],
        "promotion": None,
        "created_at": now,
        "detected_at": now,
    }
    record["evidence_fingerprint"] = evidence_fingerprint(record)
    return record


def merge_redetection(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Fold a re-detection into the stored record (pure)."""
    record = copy.deepcopy(fresh)
    record["created_at"] = existing.get("created_at", fresh["created_at"])
    record["review_history"] = list(existing.get("review_history") or [])
    record["promotion"] = existing.get("promotion")
    record["duplicate_of"] = existing.get("duplicate_of")
    record["times_observed"] = int(existing.get("times_observed") or 0) + 1
    record["run_ids"] = ([*existing.get("run_ids", []), fresh["last_run_id"]])[-MAX_RUNS_TRACKED:]
    if existing.get("first_observed_at") and (
        not record.get("first_observed_at") or existing["first_observed_at"] < record["first_observed_at"]
    ):
        record["first_observed_at"] = existing["first_observed_at"]
    changed = existing.get("evidence_fingerprint") != record["evidence_fingerprint"]
    record["version"] = int(existing.get("version") or 1) + (1 if changed else 0)
    status = existing.get("status", STATUS_CANDIDATE)
    now = utc_now().isoformat()
    if status in SYSTEM_STATUSES:
        pass  # the funnel recomputes freely
    elif status == STATUS_DEPRECATED:
        record["review_history"].append({
            "decision": "revived", "reason": "re_detected_after_deprecation",
            "previous_status": status, "at": now,
        })
    elif status == STATUS_PROMOTED:
        record["status"] = STATUS_PROMOTED
        record["priority"] = "low"
        if changed:
            record["review_history"].append({
                "decision": "evidence_changed_after_promotion", "previous_fingerprint":
                existing.get("evidence_fingerprint"), "new_fingerprint": record["evidence_fingerprint"], "at": now,
            })
    elif status in REVIEWED_STATUSES:
        reviewed = existing.get("reviewed_fingerprint") or existing.get("evidence_fingerprint")
        if reviewed == record["evidence_fingerprint"]:
            record["status"] = status
            record["reviewed_fingerprint"] = reviewed
            record["priority"] = existing.get("priority", record["priority"])
        else:
            record["review_history"].append({
                "decision": "superseded",
                "reason": "evidence_changed_since_review",
                "previous_status": status,
                "reviewed_fingerprint": reviewed,
                "new_fingerprint": record["evidence_fingerprint"],
                "at": now,
            })
    return record


def apply_review(record: dict[str, Any], *, reviewer_id: str, verdict: str, reason: str,
                 duplicate_of: Optional[str] = None) -> dict[str, Any]:
    if verdict not in VERDICT_STATUS:
        raise LifecycleError(f"verdict must be one of {sorted(VERDICT_STATUS)}")
    if not reviewer_id.strip():
        raise LifecycleError("reviewer is required")
    if len(reason.strip()) < 10:
        raise LifecycleError("a reason of at least 10 characters is required")
    target = VERDICT_STATUS[verdict]
    if target == STATUS_DUPLICATE:
        if not duplicate_of or duplicate_of == record.get("pattern_id"):
            raise LifecycleError("a duplicate verdict must name a different pattern in duplicate_of")
    elif duplicate_of:
        raise LifecycleError("duplicate_of is only valid with a duplicate verdict")
    check_transition(record.get("status", STATUS_CANDIDATE), target)
    updated = copy.deepcopy(record)
    updated["status"] = target
    updated["duplicate_of"] = duplicate_of if target == STATUS_DUPLICATE else None
    updated["reviewed_fingerprint"] = record.get("evidence_fingerprint")
    updated["priority"] = "low"
    updated["review_history"] = [*record.get("review_history", []), {
        "reviewer_id": reviewer_id.strip(), "decision": verdict, "reason": reason.strip()[:2000],
        "previous_status": record.get("status"), "evidence_fingerprint": record.get("evidence_fingerprint"),
        "duplicate_of": duplicate_of, "at": utc_now().isoformat(),
    }]
    return updated


def apply_promotion(record: dict[str, Any], *, reviewer_id: str, reason: str) -> dict[str, Any]:
    if not reviewer_id.strip():
        raise LifecycleError("reviewer is required")
    if len(reason.strip()) < 10:
        raise LifecycleError("a reason of at least 10 characters is required")
    status = record.get("status")
    if status not in PROMOTABLE_STATUSES:
        raise LifecycleError("only a reviewer-confirmed pattern (valid or malicious) can be promoted")
    if record.get("reviewed_fingerprint") and record["reviewed_fingerprint"] != record.get("evidence_fingerprint"):
        raise LifecycleError("evidence changed since review; review again before promoting")
    check_transition(status, STATUS_PROMOTED)
    updated = copy.deepcopy(record)
    now = utc_now().isoformat()
    updated["status"] = STATUS_PROMOTED
    updated["priority"] = "low"
    updated["promotion"] = {
        "promoted_by": reviewer_id.strip(), "promoted_at": now, "reason": reason.strip()[:2000],
        "from_status": status, "verdict": "malicious" if status == "confirmed_malicious" else "valid",
        "evidence_fingerprint": record.get("evidence_fingerprint"), "risk_signals": [],
    }
    updated["review_history"] = [*record.get("review_history", []), {
        "reviewer_id": reviewer_id.strip(), "decision": "promote", "reason": reason.strip()[:2000],
        "previous_status": status, "at": now,
    }]
    return updated


def apply_deprecation(record: dict[str, Any], *, actor: str, reason: str, automatic: bool = False) -> dict[str, Any]:
    if not automatic and len(reason.strip()) < 10:
        raise LifecycleError("a reason of at least 10 characters is required")
    check_transition(record.get("status", STATUS_CANDIDATE), STATUS_DEPRECATED)
    updated = copy.deepcopy(record)
    updated["status"] = STATUS_DEPRECATED
    updated["priority"] = "low"
    updated["review_history"] = [*record.get("review_history", []), {
        "reviewer_id": actor, "decision": "deprecate_stale" if automatic else "deprecate",
        "reason": reason.strip()[:2000], "previous_status": record.get("status"),
        "at": utc_now().isoformat(),
    }]
    return updated


def mark_unseen(record: dict[str, Any], run_id: str) -> dict[str, Any]:
    """A run that did not re-observe the pattern. Open patterns go stale."""
    updated = copy.deepcopy(record)
    updated["runs_since_seen"] = int(record.get("runs_since_seen") or 0) + 1
    if record.get("status") in SYSTEM_STATUSES and updated["runs_since_seen"] >= STALE_AFTER_RUNS:
        updated = apply_deprecation(updated, actor="system", automatic=True,
                                    reason=f"not re-observed for {updated['runs_since_seen']} runs (last run {run_id})")
    return updated


_MAX_WRITE_ATTEMPTS = 5
_SCAN_PAGE = 500
_SCAN_LIMIT = 5_000


class PatternRegistryRepository(BaseRepository):
    """Tenant-scoped JSONB store of discovered patterns (``discovered_patterns``)."""

    def __init__(self) -> None:
        super().__init__("discovered_patterns")

    async def get(self, tenant_id: str, pid: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(pid)
        return copy.deepcopy(row) if row and row.get("tenant_id") == tenant_id else None

    async def upsert_detected(self, record: dict[str, Any]) -> dict[str, Any]:
        tenant_id = record["tenant_id"]
        for _ in range(_MAX_WRITE_ATTEMPTS):
            existing = await self.get(tenant_id, record["pattern_id"])
            if existing is None:
                fresh = copy.deepcopy(record)
                fresh["revision"] = 1
                if await self.insert_if_absent(fresh["pattern_id"], fresh, tenant_id):
                    return copy.deepcopy(fresh)
                continue
            merged = merge_redetection(existing, record)
            merged["revision"] = int(existing.get("revision", 0)) + 1
            if await self.replace_if_matches(merged["pattern_id"], merged, tenant_id,
                                             {"revision": existing.get("revision", 0)}):
                return copy.deepcopy(merged)
        raise ConflictError("pattern changed concurrently; retry")

    async def mutate(self, tenant_id: str, pid: str,
                     fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Apply ``fn`` atomically; ``None`` when the pattern does not exist.
        ``LifecycleError`` from ``fn`` propagates unchanged."""
        for _ in range(_MAX_WRITE_ATTEMPTS):
            row = await self.get(tenant_id, pid)
            if row is None:
                return None
            expected = row.get("revision", 0)  # before fn, which may mutate row in place
            updated = fn(copy.deepcopy(row))
            updated["revision"] = int(expected) + 1
            if await self.replace_if_matches(pid, updated, tenant_id, {"revision": expected}):
                return copy.deepcopy(updated)
        raise ConflictError("pattern changed concurrently; retry")

    async def scan(self, tenant_id: str, *, status: Optional[str] = None, kind: Optional[str] = None,
                   limit: int = _SCAN_LIMIT) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        if kind:
            filters["kind"] = kind
        out: list[dict[str, Any]] = []
        offset = 0
        while len(out) < limit:
            page = await self.find_many(filters=filters, limit=_SCAN_PAGE, offset=offset)
            out.extend(copy.deepcopy(r) for r in page if r.get("tenant_id") == tenant_id)
            if len(page) < _SCAN_PAGE:
                break
            offset += _SCAN_PAGE
        return out[:limit]

    async def list_patterns(self, tenant_id: str, *, statuses: Optional[set[str]] = None,
                            kind: Optional[str] = None, min_confidence: float = 0.0,
                            limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        rows = await self.scan(tenant_id, kind=kind)
        rows = [r for r in rows if (not statuses or r.get("status") in statuses)
                and float(r.get("confidence") or 0) >= min_confidence]
        prio = {"high": 0, "normal": 1, "low": 2}
        rows.sort(key=lambda r: (prio.get(r.get("priority"), 3), -float(r.get("severity_score") or 0),
                                 -float(r.get("confidence") or 0), r.get("pattern_id", "")))
        return rows[offset: offset + limit], len(rows)

    async def for_entity(self, tenant_id: str, entity_key: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = [r for r in await self.scan(tenant_id) if entity_key in (r.get("affected_entity_keys") or [])]
        rows.sort(key=lambda r: (-float(r.get("severity_score") or 0), r.get("pattern_id", "")))
        return rows[:limit]


class PatternFeedbackRepository(BaseRepository):
    """Append-only analyst verdicts; the calibration source."""

    def __init__(self) -> None:
        super().__init__("pattern_feedback")

    async def record(self, tenant_id: str, pattern: dict[str, Any], *, reviewer_id: str,
                     verdict: str, reason: str) -> dict[str, Any]:
        now = utc_now().isoformat()
        fid = f"{tenant_id}:pfb:{content_hash([pattern['pattern_id'], reviewer_id, verdict, now], 24)}"
        row = {
            "feedback_id": fid, "tenant_id": tenant_id, "pattern_id": pattern["pattern_id"],
            "kind": pattern.get("kind"), "family": pattern.get("family"), "detector": pattern.get("detector"),
            "verdict": verdict, "reviewer_id": reviewer_id, "reason": reason[:2000],
            "evidence_fingerprint": pattern.get("evidence_fingerprint"), "created_at": now,
        }
        await self.insert_if_absent(fid, row, tenant_id)
        return row

    async def aggregate(self, tenant_id: str) -> dict[str, Any]:
        kinds: dict[str, dict[str, int]] = {}
        families: dict[str, dict[str, int]] = {}
        total = 0
        offset = 0
        while offset < 20_000:
            page = await self.find_many(filters={"tenant_id": tenant_id}, limit=_SCAN_PAGE, offset=offset)
            for row in page:
                if row.get("tenant_id") != tenant_id:
                    continue
                total += 1
                v = str(row.get("verdict"))
                kinds.setdefault(str(row.get("kind")), {}).setdefault(v, 0)
                kinds[str(row.get("kind"))][v] += 1
                if row.get("family"):
                    families.setdefault(str(row["family"]), {}).setdefault(v, 0)
                    families[str(row["family"])][v] += 1
            if len(page) < _SCAN_PAGE:
                break
            offset += _SCAN_PAGE
        return {"kinds": kinds, "families": families, "total": total}


class PatternDiscoveryRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("pattern_discovery_runs")

    async def save_run(self, run: dict[str, Any]) -> dict[str, Any]:
        await self.insert_if_absent(run["run_id"], copy.deepcopy(run), run["tenant_id"])
        return run

    async def list_runs(self, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=max(1, min(limit, 200)),
                                    sort_by="created_at")
        return [copy.deepcopy(r) for r in rows if r.get("tenant_id") == tenant_id]

    async def get_run(self, tenant_id: str, run_id: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(run_id)
        return copy.deepcopy(row) if row and row.get("tenant_id") == tenant_id else None
