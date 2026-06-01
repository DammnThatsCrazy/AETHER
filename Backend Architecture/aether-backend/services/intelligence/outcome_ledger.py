"""Tenant-scoped outcome ledger aggregation for Decision & Outcome Intelligence."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sum(values: list[Any]) -> float:
    return round(sum(_as_number(v) for v in values), 2)


class OutcomeLedgerAggregator:
    """Build commercial ROI and loop-health summaries from OODA records."""

    def __init__(self, stale_after_days: int = 30) -> None:
        self.stale_after = timedelta(days=stale_after_days)

    def build(
        self,
        recommendations: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        feedback: list[dict[str, Any]] | None = None,
        playbooks: list[dict[str, Any]] | None = None,
        runs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        feedback = feedback or []
        playbooks = playbooks or []
        runs = runs or []

        decisions_by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
        actions_by_decision: dict[str, list[dict[str, Any]]] = defaultdict(list)
        outcomes_by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for decision in decisions:
            decisions_by_rec[str(decision.get("recommendation_id", ""))].append(decision)
        for action in actions:
            actions_by_decision[str(action.get("decision_id", ""))].append(action)
        for outcome in outcomes:
            outcomes_by_rec[str(outcome.get("recommendation_id", ""))].append(outcome)

        now = datetime.now(timezone.utc)
        success_count = sum(1 for outcome in outcomes if outcome.get("label") == "success")
        failure_count = sum(1 for outcome in outcomes if outcome.get("label") == "failure")
        neutral_count = sum(1 for outcome in outcomes if outcome.get("label") == "neutral")
        viewed_count = sum(1 for rec in recommendations if rec.get("status") in {"viewed", "decided"})

        stale_loop_ids: list[str] = []
        incomplete_loop_ids: list[str] = []
        failed_loop_ids: list[str] = []
        items: list[dict[str, Any]] = []

        for rec in recommendations:
            rec_id = str(rec.get("recommendation_id") or rec.get("id") or "")
            rec_decisions = decisions_by_rec.get(rec_id, [])
            rec_actions = [
                action
                for decision in rec_decisions
                for action in actions_by_decision.get(str(decision.get("decision_id", "")), [])
            ]
            rec_outcomes = outcomes_by_rec.get(rec_id, [])
            rec_created = _parse_dt(rec.get("created_at") or rec.get("computed_at"))
            expected_value = _as_number(rec.get("expected_value"))
            observed_value = _sum([outcome.get("value") for outcome in rec_outcomes])
            is_stale = bool(rec_created and now - rec_created > self.stale_after and not rec_outcomes)
            is_incomplete = not rec_decisions or not rec_actions or not rec_outcomes
            is_failed = any(outcome.get("label") == "failure" for outcome in rec_outcomes)

            if is_stale:
                stale_loop_ids.append(rec_id)
            if is_incomplete:
                incomplete_loop_ids.append(rec_id)
            if is_failed:
                failed_loop_ids.append(rec_id)

            items.append({
                "recommendation_id": rec_id,
                "entity_id": rec.get("entity_id"),
                "population_id": rec.get("population_id"),
                "recommendation_type": rec.get("recommendation_type"),
                "status": "failed" if is_failed else "stale" if is_stale else "incomplete" if is_incomplete else "complete",
                "expected_value": round(expected_value, 2),
                "observed_value": observed_value,
                "pending_value": round(max(expected_value - observed_value, 0.0), 2),
                "decision_count": len(rec_decisions),
                "action_count": len(rec_actions),
                "outcome_count": len(rec_outcomes),
            })

        expected_value = _sum([rec.get("expected_value") for rec in recommendations])
        observed_value = _sum([outcome.get("value") for outcome in outcomes])
        confidence_deltas = self.confidence_deltas(feedback)
        summary = {
            "recommendations_generated": len(recommendations),
            "recommendations_viewed": viewed_count,
            "decisions_recorded": len(decisions),
            "actions_logged": len(actions),
            "outcomes_observed": len(outcomes),
            "success_count": success_count,
            "failure_count": failure_count,
            "neutral_count": neutral_count,
            "success_rate": round(success_count / len(outcomes), 4) if outcomes else 0.0,
            "failure_rate": round(failure_count / len(outcomes), 4) if outcomes else 0.0,
            "neutral_rate": round(neutral_count / len(outcomes), 4) if outcomes else 0.0,
            "outcome_capture_rate": round(len({outcome.get("recommendation_id") for outcome in outcomes}) / len(recommendations), 4) if recommendations else 0.0,
            "expected_value": expected_value,
            "observed_value": observed_value,
            "pending_value": round(max(expected_value - observed_value, 0.0), 2),
            "stale_loops": len(stale_loop_ids),
            "incomplete_loops": len(incomplete_loop_ids),
            "failed_loops": len(failed_loop_ids),
            "confidence_delta_total": round(sum(delta["confidence_delta"] for delta in confidence_deltas), 4),
        }
        return {
            "summary": summary,
            "items": items,
            "by_recommendation_type": self.group_by(recommendations, outcomes, "recommendation_type"),
            "by_entity": self.group_by(recommendations, outcomes, "entity_id"),
            "by_playbook": self.group_by_playbook(recommendations, outcomes, playbooks, runs),
            "confidence_deltas_over_time": confidence_deltas,
            "stale_loop_ids": stale_loop_ids,
            "incomplete_loop_ids": incomplete_loop_ids,
            "failed_loop_ids": failed_loop_ids,
        }

    def confidence_deltas(self, feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "recommendation_id": item.get("recommendation_id"),
                "outcome_id": item.get("outcome_id"),
                "confidence_delta": round(_as_number(item.get("confidence_delta")), 4),
                "created_at": item.get("created_at") or item.get("computed_at"),
            }
            for item in sorted(feedback, key=lambda value: str(value.get("created_at") or value.get("computed_at") or ""))
        ]

    def group_by(self, recommendations: list[dict[str, Any]], outcomes: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        rec_by_id = {str(rec.get("recommendation_id") or rec.get("id") or ""): rec for rec in recommendations}
        groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "recommendations": 0,
            "outcomes": 0,
            "success_count": 0,
            "failure_count": 0,
            "neutral_count": 0,
            "expected_value": 0.0,
            "observed_value": 0.0,
        })
        for rec in recommendations:
            key = str(rec.get(field) or "unknown")
            groups[key]["recommendations"] += 1
            groups[key]["expected_value"] += _as_number(rec.get("expected_value"))
        for outcome in outcomes:
            rec = rec_by_id.get(str(outcome.get("recommendation_id", "")), {})
            key = str(rec.get(field) or outcome.get(field) or "unknown")
            groups[key]["outcomes"] += 1
            groups[key]["observed_value"] += _as_number(outcome.get("value"))
            label = outcome.get("label")
            if label in {"success", "failure", "neutral"}:
                groups[key][f"{label}_count"] += 1
        return [self._finalize_group(key, values) for key, values in sorted(groups.items())]

    def group_by_playbook(
        self,
        recommendations: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        playbooks: list[dict[str, Any]],
        runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rec_by_id = {str(rec.get("recommendation_id") or rec.get("id") or ""): rec for rec in recommendations}
        outcomes_by_rec: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for outcome in outcomes:
            outcomes_by_rec[str(outcome.get("recommendation_id", ""))].append(outcome)
        playbook_by_id = {str(playbook.get("playbook_id") or playbook.get("id") or ""): playbook for playbook in playbooks}

        groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "playbook_id": "unknown",
            "playbook_name": "unknown",
            "runs": 0,
            "recommendations": 0,
            "outcomes": 0,
            "success_count": 0,
            "failure_count": 0,
            "neutral_count": 0,
            "expected_value": 0.0,
            "observed_value": 0.0,
            "stale_runs": 0,
        })
        now = datetime.now(timezone.utc)
        for run in runs:
            playbook_id = str(run.get("playbook_id") or "unknown")
            playbook = playbook_by_id.get(playbook_id, {})
            group = groups[playbook_id]
            group["playbook_id"] = playbook_id
            group["playbook_name"] = playbook.get("name") or playbook_id
            group["runs"] += 1
            started_at = _parse_dt(run.get("started_at"))
            if run.get("status") in {"queued", "running"} and started_at and now - started_at > self.stale_after:
                group["stale_runs"] += 1
            rec_ids = {str(rec_id) for rec_id in run.get("recommendation_ids", [])}
            for rec_id in rec_ids:
                rec = rec_by_id.get(rec_id)
                if not rec:
                    continue
                group["recommendations"] += 1
                group["expected_value"] += _as_number(rec.get("expected_value"))
                for outcome in outcomes_by_rec.get(rec_id, []):
                    group["outcomes"] += 1
                    group["observed_value"] += _as_number(outcome.get("value"))
                    label = outcome.get("label")
                    if label in {"success", "failure", "neutral"}:
                        group[f"{label}_count"] += 1
        return [
            {
                **{key: value for key, value in group.items() if key not in {"expected_value", "observed_value"}},
                "expected_value": round(group["expected_value"], 2),
                "observed_value": round(group["observed_value"], 2),
                "pending_value": round(max(group["expected_value"] - group["observed_value"], 0.0), 2),
                "success_rate": round(group["success_count"] / group["outcomes"], 4) if group["outcomes"] else 0.0,
            }
            for _, group in sorted(groups.items())
        ]

    def _finalize_group(self, key: str, values: dict[str, Any]) -> dict[str, Any]:
        expected_value = _as_number(values["expected_value"])
        observed_value = _as_number(values["observed_value"])
        outcomes = int(values["outcomes"])
        return {
            "key": key,
            "recommendations": values["recommendations"],
            "outcomes": outcomes,
            "success_count": values["success_count"],
            "failure_count": values["failure_count"],
            "neutral_count": values["neutral_count"],
            "success_rate": round(values["success_count"] / outcomes, 4) if outcomes else 0.0,
            "expected_value": round(expected_value, 2),
            "observed_value": round(observed_value, 2),
            "pending_value": round(max(expected_value - observed_value, 0.0), 2),
        }
