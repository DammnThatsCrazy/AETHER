"""Bounded, reproducible evaluation of attribution credit temporal eligibility.

This contract evaluates whether credited touchpoints are canonical and precede
the independently recorded conversion. It does not measure causal contribution
or calibrate model-reported confidence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from repositories.typed_repo import TypedTableRepository

CONTRACT = "value-credit-temporal-eligibility.v1"
MAX_CREDITS = 100


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _not_future(value: Any, *, as_of: datetime) -> datetime | None:
    """Parse an aware source time and reject timestamps beyond the producer clock."""
    parsed = _instant(value)
    return parsed if parsed is not None and parsed <= as_of else None


def _optional_source_times_valid(row: dict[str, Any], fields: tuple[str, ...], *, as_of: datetime) -> bool:
    return all(
        field not in row or row[field] is None or _not_future(row[field], as_of=as_of) is not None
        for field in fields
    )


def _uuid(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _manifest_sha(*, tenant_id: str, run_id: str, config_id: str,
                  validation_id: str, start: datetime, end: datetime,
                  samples: list[dict[str, Any]]) -> str:
    return _sha({"tenantId": tenant_id, "attributionRunId": run_id,
                 "modelConfigId": config_id, "validationDecisionId": validation_id,
                 "contractVersion": CONTRACT, "windowStart": start.isoformat(),
                 "windowEnd": end.isoformat(), "samples": samples})


class ValueConfidenceEvaluationRepository(TypedTableRepository):
    table_name = "value_confidence_evaluations"
    columns = ("evaluation_id", "tenant_id", "attribution_run_id", "model_config_id",
               "validation_decision_id", "contract_version", "dataset_manifest_sha256",
               "sample_count", "eligible_count", "window_start", "window_end", "sample_refs",
               "actor_id", "authorization_action", "authorization_permission",
               "authorization_decision", "authorization_actor_id", "authorization_evaluated_at", "created_at")
    jsonb_columns = frozenset({"sample_refs"})
    conflict_key = ("tenant_id", "evaluation_id")

    async def latest_for_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        pool = await self._pool()
        if pool is None:
            rows = [r for r in self._rows if r.get("tenant_id") == tenant_id and _uuid(r.get("attribution_run_id")) == _uuid(run_id)]
            return max(rows, key=lambda r: _instant(r.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), default=None)
        row = await pool.fetchrow("SELECT * FROM value_confidence_evaluations WHERE tenant_id=$1 AND attribution_run_id=$2 ORDER BY created_at DESC, evaluation_id DESC LIMIT 1", tenant_id, UUID(str(run_id)))
        if row is None:
            return None
        result = dict(row)
        if isinstance(result.get("sample_refs"), str):
            result["sample_refs"] = json.loads(result["sample_refs"])
        return result


async def evaluate_attribution_run(
    tenant_id: str, run_id: str, *, actor_id: str, authorization_evidence: dict[str, Any],
    runs: Any = None, conversions: Any = None, touchpoints: Any = None,
    validations: Any = None, evaluations: ValueConfidenceEvaluationRepository | None = None,
) -> dict[str, Any]:
    """Compute temporal eligibility from canonical conversion and touchpoint rows."""
    run_uuid = _uuid(run_id)
    authorized_at = _instant(authorization_evidence.get("evaluated_at")) if isinstance(authorization_evidence, dict) else None
    producer_now = datetime.now(timezone.utc)
    if (not tenant_id or run_uuid is None or not isinstance(actor_id, str) or not actor_id.strip()
            or not isinstance(authorization_evidence, dict)
            or authorization_evidence.get("action") != "value.model_evaluation"
            or authorization_evidence.get("permission") != "write"
            or authorization_evidence.get("decision") != "allow"
            or authorization_evidence.get("actor_id") != actor_id or authorized_at is None
            or authorized_at > producer_now):
        raise ValueError("exact authenticated evaluation authorization evidence is required")
    if runs is None:
        from journeys.measurement.repositories.attribution_run_repo import AttributionRunRepository
        runs = AttributionRunRepository()
    if conversions is None:
        from journeys.measurement.repositories.conversion_repo import ConversionRepository
        conversions = ConversionRepository()
    if touchpoints is None:
        from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository
        touchpoints = TouchpointRepository()
    from value.economic.attribution_model_validation import AttributionModelValidationRepository, _decision_for, _same_decision
    run = await runs.get_run(run_uuid, tenant_id=tenant_id)
    if not isinstance(run, dict) or run.get("tenant_id") != tenant_id or _uuid(run.get("attribution_run_id")) != run_uuid or run.get("status") != "complete":
        raise ValueError("exact completed tenant attribution run is required")
    if (any(_not_future(run.get(field), as_of=producer_now) is None
            for field in ("created_at", "completed_at"))
            or not _optional_source_times_valid(run, ("started_at",), as_of=producer_now)):
        raise ValueError("attribution run creation and completion times must be valid and not future")
    config_id = _uuid(run.get("model_config_id"))
    if not config_id:
        raise ValueError("attribution run has no exact model config")
    config = await runs.get_model_config(tenant_id, config_id)
    expected = _decision_for(tenant_id, run, config) if isinstance(config, dict) else None
    validation_repo = validations or AttributionModelValidationRepository()
    validation = await validation_repo.get(tenant_id, run_uuid)
    if expected is None or not isinstance(validation, dict) or not _same_decision(validation, expected):
        raise ValueError("durable exact run/config validation is required")
    conversion_id = _uuid(run.get("conversion_id"))
    conversion = await conversions.get(tenant_id, conversion_id) if conversion_id else None
    if (not isinstance(conversion, dict) or conversion.get("tenant_id") != tenant_id
            or _uuid(conversion.get("conversion_id")) != conversion_id
            or conversion.get("conversion_status") != "confirmed" or conversion.get("attribution_eligible") is not True):
        raise ValueError("independently confirmed canonical conversion is required")
    conversion_at = _not_future(conversion.get("occurred_at"), as_of=producer_now)
    if (conversion_at is None or not _optional_source_times_valid(
            conversion, ("observed_at", "confirmed_at"), as_of=producer_now)):
        raise ValueError("canonical conversion event time is unavailable")
    credits = await runs.list_credits_for_run(tenant_id, run_uuid, limit=MAX_CREDITS + 1)
    if not isinstance(credits, list) or len(credits) > MAX_CREDITS:
        raise ValueError("attribution credit dataset is invalid or exceeds the 100 row bound")
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for credit in credits:
        if (not isinstance(credit, dict) or credit.get("tenant_id") != tenant_id
                or _uuid(credit.get("attribution_run_id")) != run_uuid
                or _uuid(credit.get("conversion_id")) != conversion_id):
            raise ValueError("credit tenant/run/conversion scope mismatch")
        credit_id, touchpoint_id = _uuid(credit.get("credit_id")), _uuid(credit.get("touchpoint_id"))
        if not credit_id or credit_id in seen or not touchpoint_id:
            raise ValueError("credit identity or exact touchpoint link is invalid")
        seen.add(credit_id)
        touchpoint = await touchpoints.get(tenant_id, touchpoint_id)
        if (not isinstance(touchpoint, dict) or touchpoint.get("tenant_id") != tenant_id
                or _uuid(touchpoint.get("touchpoint_id")) != touchpoint_id):
            raise ValueError("canonical touchpoint is unavailable or out of tenant scope")
        touchpoint_at = _not_future(touchpoint.get("occurred_at"), as_of=producer_now)
        if (touchpoint_at is None or not _optional_source_times_valid(
                touchpoint, ("received_at", "processed_at", "source_classified_at"), as_of=producer_now)):
            raise ValueError("canonical touchpoint event time is unavailable or future")
        credit_created_at = _not_future(credit.get("created_at"), as_of=producer_now)
        if credit_created_at is None:
            raise ValueError("attribution credit creation time is unavailable or future")
        eligible = touchpoint_at <= conversion_at
        samples.append({"creditId": credit_id, "touchpointId": touchpoint_id,
                        "conversionId": conversion_id, "touchpointOccurredAt": touchpoint_at.isoformat(),
                        "conversionOccurredAt": conversion_at.isoformat(), "temporallyEligible": eligible,
                        "creditObservedAt": credit_created_at.isoformat()})
    if not samples:
        raise ValueError("no canonical attribution credits are available for evaluation")
    samples.sort(key=lambda x: x["creditId"])
    # The evaluation window covers the entire canonical sample interval, including
    # conversion time even when every credited touchpoint occurs afterward.
    window_start = min(
        [conversion_at, *(_instant(s["touchpointOccurredAt"]) for s in samples)]
    )
    window_end = max(
        [conversion_at, *(_instant(s["touchpointOccurredAt"]) for s in samples)]
    )
    eligible_count = sum(1 for sample in samples if sample["temporallyEligible"])
    row = {
        "evaluation_id": "vce_" + uuid4().hex, "tenant_id": tenant_id,
        "attribution_run_id": run_uuid, "model_config_id": config_id,
        "validation_decision_id": validation["decision_id"], "contract_version": CONTRACT,
        "dataset_manifest_sha256": _manifest_sha(
            tenant_id=tenant_id, run_id=run_uuid, config_id=config_id,
            validation_id=validation["decision_id"], start=window_start,
            end=window_end, samples=samples,
        ), "sample_count": len(samples),
        "eligible_count": eligible_count, "window_start": window_start,
        "window_end": window_end, "sample_refs": samples, "actor_id": actor_id,
        "authorization_action": authorization_evidence["action"],
        "authorization_permission": authorization_evidence["permission"],
        "authorization_decision": authorization_evidence["decision"],
        "authorization_actor_id": authorization_evidence["actor_id"],
        "authorization_evaluated_at": authorized_at, "created_at": producer_now,
    }
    await (evaluations or ValueConfidenceEvaluationRepository()).insert(row)
    return {**row, "state": "evaluated", "metric": "temporal_eligibility_accuracy",
            "value": eligible_count / len(samples), "calibration_state": "unvalidated",
            "causal_attribution_state": "unknown"}


def validate_evaluation(row: Any) -> bool:
    """Validate persisted evaluation shape and recompute its manifest and metric."""
    if not isinstance(row, dict) or row.get("contract_version") != CONTRACT:
        return False
    samples = row.get("sample_refs")
    sample_count, eligible_count = row.get("sample_count"), row.get("eligible_count")
    if (not isinstance(samples, list) or not samples or len(samples) > MAX_CREDITS
            or type(sample_count) is not int or sample_count != len(samples)
            or type(eligible_count) is not int or not 0 <= eligible_count <= sample_count):
        return False
    if not all(
        isinstance(sample, dict)
        and _uuid(sample.get("creditId")) is not None
        and _uuid(sample.get("touchpointId")) is not None
        and _uuid(sample.get("conversionId")) is not None
        and _instant(sample.get("touchpointOccurredAt")) is not None
        and _instant(sample.get("conversionOccurredAt")) is not None
        and _instant(sample.get("creditObservedAt")) is not None
        and isinstance(sample.get("temporallyEligible"), bool)
        and sample["temporallyEligible"] == (
            _instant(sample["touchpointOccurredAt"]) <= _instant(sample["conversionOccurredAt"])
        )
        for sample in samples
    ):
        return False
    start, end = _instant(row.get("window_start")), _instant(row.get("window_end"))
    if start is None or end is None or start > end:
        return False
    sample_times = [
        instant for sample in samples
        for instant in (_instant(sample["touchpointOccurredAt"]), _instant(sample["conversionOccurredAt"]))
    ]
    if start != min(sample_times) or end != max(sample_times):
        return False
    if _manifest_sha(tenant_id=row.get("tenant_id"), run_id=_uuid(row.get("attribution_run_id")),
                     config_id=_uuid(row.get("model_config_id")), validation_id=row.get("validation_decision_id"),
                     start=start, end=end, samples=samples) != row.get("dataset_manifest_sha256"):
        return False
    if row.get("eligible_count") != sum(1 for s in samples if isinstance(s, dict) and s.get("temporallyEligible") is True):
        return False
    authorization_at = _instant(row.get("authorization_evaluated_at"))
    created_at = _instant(row.get("created_at"))
    validation_now = datetime.now(timezone.utc)
    return bool(isinstance(row.get("evaluation_id"), str) and row["evaluation_id"].startswith("vce_")
                and isinstance(row.get("tenant_id"), str) and row["tenant_id"].strip()
                and isinstance(row.get("actor_id"), str) and row["actor_id"].strip()
                and _uuid(row.get("attribution_run_id")) and _uuid(row.get("model_config_id")) and row.get("validation_decision_id")
                and row.get("authorization_action") == "value.model_evaluation"
                and row.get("authorization_permission") == "write"
                and row.get("authorization_decision") == "allow"
                and row.get("authorization_actor_id") == row.get("actor_id")
                and authorization_at is not None and created_at is not None
                and authorization_at <= created_at <= validation_now
                and authorization_at <= validation_now
                and all(
                    max(_instant(sample["touchpointOccurredAt"]), _instant(sample["conversionOccurredAt"]),
                         _instant(sample["creditObservedAt"])) <= created_at
                    for sample in samples
                ))


async def verify_evaluation_sources(tenant_id: str, row: Any, *, runs: Any = None,
                                   conversions: Any = None, touchpoints: Any = None,
                                   validations: Any = None) -> bool:
    """Rejoin every persisted sample to current canonical run, credit and event rows."""
    if not validate_evaluation(row) or row.get("tenant_id") != tenant_id:
        return False
    if runs is None:
        from journeys.measurement.repositories.attribution_run_repo import AttributionRunRepository
        runs = AttributionRunRepository()
    if conversions is None:
        from journeys.measurement.repositories.conversion_repo import ConversionRepository
        conversions = ConversionRepository()
    if touchpoints is None:
        from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository
        touchpoints = TouchpointRepository()
    if validations is None:
        from value.economic.attribution_model_validation import AttributionModelValidationRepository
        validations = AttributionModelValidationRepository()
    run_id = _uuid(row.get("attribution_run_id"))
    run = await runs.get_run(run_id, tenant_id=tenant_id) if run_id else None
    if (not isinstance(run, dict) or run.get("tenant_id") != tenant_id
            or _uuid(run.get("attribution_run_id")) != run_id
            or _uuid(run.get("model_config_id")) != _uuid(row.get("model_config_id"))
            or run.get("status") != "complete"):
        return False
    evaluation_created_at = _instant(row.get("created_at"))
    verifier_now = datetime.now(timezone.utc)
    if (evaluation_created_at is None or evaluation_created_at > verifier_now
            or any(_not_future(run.get(field), as_of=evaluation_created_at) is None
                   for field in ("created_at", "completed_at"))
            or not _optional_source_times_valid(run, ("started_at",), as_of=evaluation_created_at)):
        return False
    conversion_id = _uuid(run.get("conversion_id"))
    conversion = await conversions.get(tenant_id, conversion_id) if conversion_id else None
    conversion_at = _not_future(conversion.get("occurred_at"), as_of=evaluation_created_at) if isinstance(conversion, dict) else None
    if (not isinstance(conversion, dict) or conversion.get("tenant_id") != tenant_id
            or _uuid(conversion.get("conversion_id")) != conversion_id
            or conversion.get("conversion_status") != "confirmed"
            or conversion.get("attribution_eligible") is not True or conversion_at is None
            or not _optional_source_times_valid(
                conversion, ("observed_at", "confirmed_at"), as_of=evaluation_created_at)):
        return False
    from value.economic.attribution_model_validation import _decision_for, _same_decision
    config_id = _uuid(row.get("model_config_id"))
    config = await runs.get_model_config(tenant_id, config_id) if config_id else None
    expected_validation = _decision_for(tenant_id, run, config) if isinstance(config, dict) else None
    validation = await validations.get(tenant_id, run_id)
    if (expected_validation is None or not isinstance(validation, dict)
            or validation.get("decision_id") != row.get("validation_decision_id")
            or not _same_decision(validation, expected_validation)):
        return False
    credits = await runs.list_credits_for_run(tenant_id, run_id, limit=MAX_CREDITS + 1)
    if not isinstance(credits, list) or len(credits) > MAX_CREDITS or len(credits) != len(row["sample_refs"]):
        return False
    credits_by_id = {_uuid(c.get("credit_id")): c for c in credits if isinstance(c, dict)}
    if len(credits_by_id) != len(credits):
        return False
    expected_samples = []
    for sample in row["sample_refs"]:
        credit = credits_by_id.get(_uuid(sample.get("creditId")))
        touchpoint_id = _uuid(sample.get("touchpointId"))
        if (not credit or credit.get("tenant_id") != tenant_id
                or _uuid(credit.get("attribution_run_id")) != run_id
                or _uuid(credit.get("conversion_id")) != conversion_id
                or _uuid(credit.get("touchpoint_id")) != touchpoint_id):
            return False
        touchpoint = await touchpoints.get(tenant_id, touchpoint_id) if touchpoint_id else None
        touchpoint_at = _instant(touchpoint.get("occurred_at")) if isinstance(touchpoint, dict) else None
        if (not isinstance(touchpoint, dict) or touchpoint.get("tenant_id") != tenant_id
                or _uuid(touchpoint.get("touchpoint_id")) != touchpoint_id
                or _not_future(touchpoint.get("occurred_at"), as_of=evaluation_created_at) is None
                or touchpoint_at is None
                or not _optional_source_times_valid(
                    touchpoint, ("received_at", "processed_at", "source_classified_at"),
                    as_of=evaluation_created_at)
                or _not_future(credit.get("created_at"), as_of=evaluation_created_at) is None):
            return False
        expected_samples.append({"creditId": _uuid(credit.get("credit_id")), "touchpointId": touchpoint_id,
                                 "conversionId": conversion_id, "touchpointOccurredAt": touchpoint_at.isoformat(),
                                 "conversionOccurredAt": conversion_at.isoformat(),
                                 "temporallyEligible": touchpoint_at <= conversion_at,
                                 "creditObservedAt": _instant(credit.get("created_at")).isoformat()
                                 if _instant(credit.get("created_at")) else None})
    expected_samples.sort(key=lambda x: x["creditId"])
    return expected_samples == row["sample_refs"] and _manifest_sha(
        tenant_id=tenant_id, run_id=run_id, config_id=_uuid(row.get("model_config_id")),
        validation_id=row.get("validation_decision_id"),
        start=_instant(row.get("window_start")), end=_instant(row.get("window_end")),
        samples=expected_samples,
    ) == row["dataset_manifest_sha256"]
