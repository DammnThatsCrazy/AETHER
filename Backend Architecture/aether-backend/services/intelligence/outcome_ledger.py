"""Outcome ledger aggregation helpers for tenant and Kyber views."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sum(values: list[float | int | None]) -> float:
    return round(sum(float(v or 0.0) for v in values), 2)


class OutcomeLedgerAggregator:
    def __init__(self, stale_after_days: int = 30) -> None:
        self.stale_after = timedelta(days=stale_after_days)

    def build(self, recommendations: list[dict[str, Any]], decisions: list[dict[str, Any]], actions: list[dict[str, Any]], outcomes: list[dict[str, Any]], feedback: list[dict[str, Any]] | None = None, playbooks: list[dict[str, Any]] | None = None, runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        feedback = feedback or []
        playbooks = playbooks or []
        runs = runs or []
        decisions_by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
        actions_by_decision: dict[str, list[dict[str, Any]]] = defaultdict(list)
        outcomes_by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for decision in decisions:
            decisions_by_rec[decision.get("recommendation_id", "")].append(decision)
        for action in actions:
            actions_by_decision[action.get("decision_id", "")].append(action)
        for outcome in outcomes:
            outcomes_by_rec[outcome.get("recommendation_id", "")].append(outcome)

        now = datetime.now(timezone.utc)
        viewed = [r for r in recommendations if r.get("status") in {"viewed", "decided"}]
        success = [o for o in outcomes if o.get("label") == "success"]
        failure = [o for o in outcomes if o.get("label") == "failure"]
        neutral = [o for o in outcomes if o.get("label") == "neutral"]
        stale_loops = []
        incomplete_loops = []
        failed_loops = []
        ledger_items = []
        for rec in recommendations:
            rid = rec.get("recommendation_id") or rec.get("id")
            rec_decisions = decisions_by_rec.get(rid, [])
            rec_actions = [a for d in rec_decisions for a in actions_by_decision.get(d.get("decision_id", ""), [])]
            rec_outcomes = outcomes_by_rec.get(rid, [])
            rec_created = _parse_dt(rec.get("created_at") or rec.get("computed_at"))
            is_stale = bool(rec_created and now - rec_created > self.stale_after and not rec_outcomes)
            is_incomplete = not rec_decisions or not rec_actions or not rec_outcomes
            if is_stale:
                stale_loops.append(rid)
            if is_incomplete:
                incomplete_loops.append(rid)
            if any(o.get("label") == "failure" for o in rec_outcomes):
                failed_loops.append(rid)
            ledger_items.append({
                "recommendation_id": rid,
                "entity_id": rec.get("entity_id"),
                "recommendation_type": rec.get("recommendation_type"),
                "expected_value": rec.get("expected_value"),
                "observed_value": _sum([o.get("value") for o in rec_outcomes]),
                "decision_count": len(rec_decisions),
                "action_count": len(rec_actions),
                "outcome_count": len(rec_outcomes),
                "status": "failed" if rid in failed_loops else "stale" if is_stale else "incomplete" if is_incomplete else "complete",
            })

        confidence_deltas = [float(f.get("confidence_delta", 0.0)) for f in feedback]
        summary = {
            "recommendations_generated": len(recommendations),
            "recommendations_viewed": len(viewed),
            "decisions_recorded": len(decisions),
            "actions_logged": len(actions),
            "outcomes_observed": len(outcomes),
            "success_rate": round(len(success) / len(outcomes), 4) if outcomes else 0.0,
            "failure_rate": round(len(failure) / len(outcomes), 4) if outcomes else 0.0,
            "neutral_rate": round(len(neutral) / len(outcomes), 4) if outcomes else 0.0,
            "expected_value": _sum([r.get("expected_value") for r in recommendations]),
            "observed_value": _sum([o.get("value") for o in outcomes]),
            "outcome_capture_rate": round(len({o.get("recommendation_id") for o in outcomes}) / len(recommendations), 4) if recommendations else 0.0,
            "stale_loops": len(stale_loops),
            "incomplete_loops": len(incomplete_loops),
            "failed_loops": len(failed_loops),
            "confidence_delta_total": round(sum(confidence_deltas), 4),
        }
        return {
            "summary": summary,
            "items": ledger_items,
            "by_recommendation_type": self.group_by(recommendations, outcomes, "recommendation_type"),
            "by_entity": self.group_by(recommendations, outcomes, "entity_id"),
            "by_playbook": self.group_by_playbook(recommendations, outcomes, playbooks, runs),
            "confidence_deltas_over_time": feedback,
            "stale_loop_ids": stale_loops,
            "incomplete_loop_ids": incomplete_loops,
            "failed_loop_ids": failed_loops,
        }

    def group_by(self, recommendations: list[dict[str, Any]], outcomes: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        rec_by_id = {r.get("recommendation_id") or r.get("id"): r for r in recommendations}
        groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"recommendations": 0, "expected_value": 0.0, "observed_value": 0.0, "outcomes": 0})
        for rec in recommendations:
            key = str(rec.get(field) or "unknown")
            groups[key]["recommendations"] += 1
            groups[key]["expected_value"] += float(rec.get("expected_value") or 0.0)
        for outcome in outcomes:
            rec = rec_by_id.get(outcome.get("recommendation_id"), {})
            key = str(rec.get(field) or outcome.get(field) or "unknown")
            groups[key]["outcomes"] += 1
            groups[key]["observed_value"] += float(outcome.get("value") or 0.0)
        return [{"key": key, **{k: round(v, 2) if isinstance(v, float) else v for k, v in value.items()}} for key, value in sorted(groups.items())]

    def group_by_playbook(self, recommendations: list[dict[str, Any]], outcomes: list[dict[str, Any]], playbooks: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rec_ids_by_run = {rid for run in runs for rid in run.get("recommendation_ids", [])}
        playbook_by_id = {p.get("playbook_id") or p.get("id"): p for p in playbooks}
        result = []
        for run in runs:
            rec_ids = set(run.get("recommendation_ids", []))
            run_recs = [r for r in recommendations if (r.get("recommendation_id") or r.get("id")) in rec_ids]
            run_outcomes = [o for o in outcomes if o.get("recommendation_id") in rec_ids]
            playbook = playbook_by_id.get(run.get("playbook_id"), {})
            result.append({
                "playbook_id": run.get("playbook_id"),
                "playbook_name": playbook.get("name", "unknown"),
                "run_id": run.get("run_id"),
                "recommendations": len(run_recs),
                "expected_value": _sum([r.get("expected_value") for r in run_recs]),
                "observed_value": _sum([o.get("value") for o in run_outcomes]),
                "stale": bool(run.get("status") in {"queued", "running"} and (_parse_dt(run.get("started_at")) or datetime.now(timezone.utc)) < datetime.now(timezone.utc) - self.stale_after),
            })
        if not result and rec_ids_by_run:
            return []
        return result
