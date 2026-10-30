"""Artifact scoped evaluation over exact, explicitly adjudicated outcomes.

Evaluation labels are read from canonical OutcomeTruthStore records carrying
the Profile adjudication contract and exact prediction link. Silver facts are
inputs to that recorder, never evaluation evidence themselves.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from repositories.typed_repo import TypedTableRepository

PROFILE_LABEL_CONTRACT = "profile-state-adjudication.v1"
MAX_EVALUATION_ROWS = 5_000
# This first contract is deliberately closed over two canonical outcome event
# types. Other generic outcome labels have no state adjudication semantics.
PROFILE_OUTCOME_TO_STATE = {
    "churn_observed": "churned",
    "retention_observed": "retained",
}


class ModelEvaluationRepository(TypedTableRepository):
    table_name = "model_governance_evaluations"
    columns = ("evaluation_id", "tenant_id", "domain", "model_id", "artifact_version",
               "artifact_checksum_sha256", "dataset_manifest_sha256", "split", "window_start", "window_end",
               "sample_count", "sample_refs", "metrics", "method", "actor_id", "created_at")
    jsonb_columns = frozenset({"sample_refs", "metrics"})
    conflict_key = ("tenant_id", "evaluation_id")

    async def get_evaluation(self, tenant_id: str, evaluation_id: str) -> dict[str, Any] | None:
        if not tenant_id or not evaluation_id:
            return None
        pool = await self._pool()
        if pool is None:
            return next((dict(row) for row in self._rows
                         if row.get("tenant_id") == tenant_id
                         and row.get("evaluation_id") == evaluation_id), None)
        row = await pool.fetchrow(
            "SELECT * FROM model_governance_evaluations WHERE tenant_id=$1 AND evaluation_id=$2",
            tenant_id, evaluation_id,
        )
        if row is None:
            return None
        result = dict(row)
        for field in ("metrics", "sample_refs"):
            if isinstance(result.get(field), str):
                result[field] = json.loads(result[field])
        return result

    async def latest_for_artifact(self, tenant_id: str, domain: str, model_id: str,
                                  artifact_version: str, artifact_checksum_sha256: str) -> dict[str, Any] | None:
        pool = await self._pool()
        if pool is None:
            rows = [r for r in self._rows if r.get("tenant_id") == tenant_id
                    and r.get("domain") == domain and r.get("model_id") == model_id
                    and r.get("artifact_version") == artifact_version
                    and r.get("artifact_checksum_sha256") == artifact_checksum_sha256]
            return max(rows, key=lambda r: _instant(r.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), default=None)
        row = await pool.fetchrow(
            "SELECT * FROM model_governance_evaluations WHERE tenant_id=$1 AND domain=$2 AND model_id=$3 AND artifact_version=$4 AND artifact_checksum_sha256=$5 ORDER BY created_at DESC, evaluation_id DESC LIMIT 1",
            tenant_id, domain, model_id, artifact_version, artifact_checksum_sha256,
        )
        if row is None:
            return None
        result = dict(row)
        if isinstance(result.get("metrics"), str):
            result["metrics"] = json.loads(result["metrics"])
        return result


class ProfileAdjudicationOutcomeReader:
    """Read bounded canonical outcome truth carrying exact prediction links."""

    async def list_for_profile_adjudication(
        self, tenant_id: str, label_contract_version: str,
        window_start: datetime, window_end: datetime, *, prediction_ids: list[str],
    ) -> list[dict[str, Any]]:
        from shared.backend_interpretation.flags import outcome_truth_store_enabled
        from shared.backend_interpretation.stores import OutcomeTruthStore

        if not outcome_truth_store_enabled():
            return []
        store = OutcomeTruthStore()
        start, end = _instant(window_start), _instant(window_end)
        result = []
        if len(prediction_ids) > MAX_EVALUATION_ROWS:
            raise ValueError("adjudicated prediction dataset exceeds the 5000 row bound")
        for prediction_id in prediction_ids:
            records, truncated, invalid = await store.list_for_prediction(
                tenant_id, prediction_id, label_contract_version, limit=2,
            )
            if truncated or invalid:
                raise ValueError("canonical adjudication lookup is truncated or invalid")
            for record in records:
                observed = _instant(record.observed_at)
                if observed is None or start is None or end is None or not start <= observed < end:
                    continue
                result.append({
                    "tenant_id": record.tenant_id,
                    "prediction_id": record.prediction_id,
                    "prediction_label_contract_version": record.prediction_label_contract_version,
                    "user_id": getattr(record.subject, "id", None),
                    "subject_kind": getattr(record.subject, "kind", None),
                    "occurred_at": observed,
                    "achieved_at": _instant(record.achieved_at),
                    "outcome_type": record.definition_ref,
                    "source_event_type": record.definition_ref,
                    "claim_type": record.claim_type,
                    "outcome_id": record.outcome_id,
                    "source_event_ids": list(record.source_event_ids),
                    "evidence_refs": [ref.model_dump(mode="json") for ref in record.evidence_refs],
                    "superseded_by": record.superseded_by,
                })
                if len(result) > MAX_EVALUATION_ROWS:
                    raise ValueError("adjudicated outcome dataset exceeds the 5000 row bound")
        return result


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result.astimezone(timezone.utc) if result.tzinfo else None
        except ValueError:
            return None
    return None


async def evaluate_profile_artifact(
    tenant_id: str, model_id: str, artifact_version: str, *,
    window_start: datetime, window_end: datetime, split: str, actor_id: str,
    predictions: Any = None, outcomes: Any = None, evaluations: Any = None,
    policy_verifier: Any = None, artifact_resolver: Any = None,
) -> dict[str, Any]:
    """Compute top-state accuracy and multiclass Brier score from exact labels."""
    start, end = _instant(window_start), _instant(window_end)
    now = datetime.now(timezone.utc)
    if (not tenant_id or not model_id or not artifact_version or not actor_id
            or start is None or end is None or start >= end
            or end > now
            or split not in {"evaluation", "holdout"}):
        raise ValueError("exact tenant, artifact, actor, bounded window, and evaluation split are required")
    from identity.profile.prediction_authority import ProfilePredictionOutputRepository
    from identity.profile.prediction_authority import (
        ProfilePredictionOutput, approved_production_artifact,
        verify_prediction_policy_evidence,
    )
    prediction_repo = predictions or ProfilePredictionOutputRepository()
    outcome_reader = outcomes or ProfileAdjudicationOutcomeReader()
    rows, truncated = await prediction_repo.list_for_artifact(
        tenant_id, model_id, artifact_version, start, end, limit=5000,
    )
    if truncated:
        raise ValueError("evaluation prediction dataset exceeds the 5000 row bound")
    truth_rows = await outcome_reader.list_for_profile_adjudication(
        tenant_id, PROFILE_LABEL_CONTRACT, start, end,
        prediction_ids=[str(row.get("prediction_id")) for row in rows if isinstance(row, dict)
                        and isinstance(row.get("prediction_id"), str)],
    )
    verify_policy = policy_verifier or verify_prediction_policy_evidence
    resolve_artifact = artifact_resolver or approved_production_artifact
    artifact = resolve_artifact(model_id, artifact_version)
    artifact_valid = (
        artifact is not None
        and getattr(artifact, "model_id", None) == model_id
        and getattr(artifact, "artifact_version", None) == artifact_version
        and getattr(artifact, "promotion_state", None) == "promoted"
        and not bool(getattr(artifact, "disabled", True))
        and not bool(getattr(artifact, "synthetic_data", True))
        and bool(getattr(artifact, "threshold_passed", False))
        and bool(getattr(artifact, "production_allowed", False))
        and isinstance(getattr(artifact, "checksum_sha256", None), str)
        and re.fullmatch(r"[0-9a-f]{64}", artifact.checksum_sha256) is not None
    )
    if not artifact_valid:
        raise ValueError("exact promoted production artifact is unavailable")
    by_prediction: dict[str, list[Any]] = {}
    for truth in truth_rows:
        if (truth.get("tenant_id") == tenant_id
                and truth.get("prediction_id")
                and truth.get("prediction_label_contract_version") == PROFILE_LABEL_CONTRACT):
            by_prediction.setdefault(str(truth["prediction_id"]), []).append(truth)
    sample_rows: list[dict[str, Any]] = []
    correct = 0
    brier_sum = 0.0
    calibration_bins = [[0, 0.0, 0] for _ in range(10)]
    for raw in rows:
        try:
            validated = ProfilePredictionOutput.model_validate(raw)
            generated = _instant(validated.generated_at)
            prediction = raw if isinstance(raw, dict) else {}
            if (generated is None or generated < start or generated >= end or generated > now
                    or validated.tenant_id != tenant_id
                    or validated.model_id != model_id
                    or validated.artifact_version != artifact_version
                    or validated.artifact_checksum_sha256 != artifact.checksum_sha256
                    or not await verify_policy(validated)):
                continue
            states = [state.model_dump(mode="json") for state in validated.states]
            outcomes_for_prediction = by_prediction.get(str(prediction.get("prediction_id")), [])
            # Ambiguous labels are excluded rather than selecting an arbitrary fact.
            if len(outcomes_for_prediction) != 1:
                continue
            truth = outcomes_for_prediction[0]
            evidence_refs = truth.get("evidence_refs")
            source_event_ids = truth.get("source_event_ids")
            if (
                truth.get("source_event_type") != truth.get("outcome_type")
                or truth.get("claim_type") != "observed"
                or truth.get("subject_kind") != "user"
                or not truth.get("user_id")
                or not truth.get("outcome_id")
                or not isinstance(source_event_ids, list) or len(source_event_ids) != 1
                or not isinstance(evidence_refs, list) or len(evidence_refs) != 1
                or not isinstance(evidence_refs[0], dict)
                or evidence_refs[0].get("id") != source_event_ids[0]
                or evidence_refs[0].get("source") != "silver_outcome_facts"
                or truth.get("superseded_by") is not None
            ):
                continue
            observed_at = _instant(truth.get("occurred_at"))
            achieved_at = _instant(truth.get("achieved_at"))
            valid_from, valid_until = _instant(validated.valid_from), _instant(validated.valid_until)
            if (observed_at is None or observed_at < generated or observed_at > now or observed_at >= end
                    or valid_from is None or valid_until is None
                    or valid_until > now
                    or observed_at < valid_from or observed_at > valid_until
                    or achieved_at is None or achieved_at < generated
                    or achieved_at < valid_from or achieved_at > valid_until
                    or achieved_at >= end
                    or truth.get("user_id") != validated.entity_id):
                continue
            actual_state = PROFILE_OUTCOME_TO_STATE.get(truth.get("outcome_type"))
            if actual_state is None:
                continue
            # Stable server-owned 80/20 evaluation/holdout assignment prevents
            # caller-selected rows from defining the report split.
            prediction_split = (
                "holdout"
                if int(hashlib.sha256(validated.prediction_id.encode()).hexdigest()[:2], 16) % 5 == 0
                else "evaluation"
            )
            if prediction_split != split:
                continue
            if not actual_state:
                continue
            total = 0.0
            for state in states:
                probability = state.get("probability") if isinstance(state, dict) else None
                code = state.get("state") if isinstance(state, dict) else None
                if (not isinstance(probability, (int, float)) or isinstance(probability, bool)
                        or not 0 <= probability <= 1):
                    raise ValueError("prediction probability invalid")
                total += (float(probability) - (1.0 if code == actual_state else 0.0)) ** 2
            if not any(state.get("state") == actual_state for state in states):
                # The observed class has probability zero in a complete but
                # sparse ranked distribution and contributes its own squared error.
                total += 1.0
            # Unlisted states have probability zero only when the model's output contract
            # supplies a complete ranked state distribution. Require an exact unit sum.
            prob_sum = sum(float(s["probability"]) for s in states)
            if abs(prob_sum - 1.0) > 1e-6:
                continue
            top = max(states, key=lambda state: (float(state["probability"]), -int(state["rank"])))
            matched = top.get("state") == actual_state
            correct += int(matched)
            brier_sum += total
            confidence = float(top["probability"])
            bin_index = min(int(confidence * 10), 9)
            calibration_bins[bin_index][0] += 1
            calibration_bins[bin_index][1] += confidence
            calibration_bins[bin_index][2] += int(matched)
            sample_rows.append({
                "predictionId": prediction["prediction_id"],
                "tenantId": validated.tenant_id,
                "entityId": validated.entity_id,
                "modelId": validated.model_id,
                "artifactVersion": validated.artifact_version,
                "split": prediction_split,
                "outcomeId": str(truth["outcome_id"]),
                "sourceEventId": str(source_event_ids[0]),
                "actualState": actual_state,
                "predictedState": top["state"],
                "predictedConfidence": confidence,
                "predictedDistribution": [
                    {"state": state["state"], "probability": float(state["probability"]), "rank": int(state["rank"])}
                    for state in sorted(states, key=lambda item: int(item["rank"]))
                ],
                "correct": matched,
                "artifactChecksumSha256": validated.artifact_checksum_sha256,
                "policyDecisionId": validated.policy_decision_id,
                "policyVersion": validated.policy_version,
                "actorId": validated.actor_id,
                "predictionValidFrom": valid_from.isoformat(),
                "predictionValidUntil": valid_until.isoformat(),
                "predictionEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in validated.evidence_refs
                ],
                "outcomeEvidenceRefs": evidence_refs,
                "predictionGeneratedAt": generated.isoformat(),
                "outcomeObservedAt": observed_at.isoformat(),
                "labelContractVersion": PROFILE_LABEL_CONTRACT,
            })
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    manifest = hashlib.sha256(json.dumps(sorted(sample_rows, key=lambda x: x["predictionId"]),
                                          sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result: dict[str, Any] = {
        "evaluation_id": "mge_" + uuid4().hex,
        "tenant_id": tenant_id,
        "domain": "profile360",
        "model_id": model_id,
        "artifact_version": artifact_version,
        "artifact_checksum_sha256": artifact.checksum_sha256,
        "dataset_manifest_sha256": manifest,
        "split": split,
        "window_start": start,
        "window_end": end,
        "sample_count": len(sample_rows),
        "sample_refs": sample_rows,
        "metrics": ({"top_state_accuracy": correct / len(sample_rows),
                     "multiclass_brier_score": brier_sum / len(sample_rows),
                     "expected_calibration_error": sum(
                         count / len(sample_rows) * abs(mean_confidence / count - correct_count / count)
                         for count, mean_confidence, correct_count in calibration_bins if count
                     ),
                     "reliability_bins": calibration_bins}
                    if sample_rows else {}),
        "method": "profile-state-adjudication.v1; prediction_id_sha256_mod_5.v1 split (80/20 evaluation/holdout); top-ranked exact state accuracy, multiclass Brier score, and 10-bin expected calibration error; exact tenant/prediction/event provenance",
        "actor_id": actor_id,
        "created_at": datetime.now(timezone.utc),
    }
    await (evaluations or ModelEvaluationRepository()).insert(result)
    return {**result, "state": "evaluated" if sample_rows else "unknown",
            "reason": None if sample_rows else "no_exact_adjudicated_evaluation_samples"}


__all__ = ["PROFILE_LABEL_CONTRACT", "ModelEvaluationRepository", "evaluate_profile_artifact"]
