from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from value.economic.attribution_model_validation import _decision_for
from value.economic.value_confidence_evaluation import (
    ValueConfidenceEvaluationRepository, evaluate_attribution_run,
    validate_evaluation, verify_evaluation_sources,
)


def fixtures():
    now = datetime.now(timezone.utc)
    run_id, config_id, conversion_id = (str(uuid4()) for _ in range(3))
    config = {"tenant_id": "tenant-a", "model_config_id": config_id, "model_type": "linear",
              "model_version": "v2", "status": "active", "effective_from": now - timedelta(days=1)}
    run = {"tenant_id": "tenant-a", "attribution_run_id": run_id, "model_config_id": config_id,
           "conversion_id": conversion_id, "model_type": "linear", "model_version": "v2",
           "status": "complete", "created_at": now - timedelta(seconds=2),
           "completed_at": now - timedelta(seconds=1),
           "model_config_snapshot": {**config, "effective_from": str(config["effective_from"]),
             "click_lookback_window": 24, "view_lookback_window": 168, "identity_confidence_min": 0.0,
             "fraud_policy": "exclude", "direct_traffic_policy": "include", "engaged_view_threshold_ms": 0}}
    validation = _decision_for("tenant-a", run, config)
    touchpoint_id, credit_id = str(uuid4()), str(uuid4())
    conversion_at = now - timedelta(hours=1)
    touchpoint_at = conversion_at - timedelta(hours=1)
    conversion = {"tenant_id": "tenant-a", "conversion_id": conversion_id, "conversion_status": "confirmed",
                  "attribution_eligible": True, "occurred_at": conversion_at}
    touchpoint = {"tenant_id": "tenant-a", "touchpoint_id": touchpoint_id, "occurred_at": touchpoint_at}
    credit = {"tenant_id": "tenant-a", "attribution_run_id": run_id, "conversion_id": conversion_id,
              "credit_id": credit_id, "touchpoint_id": touchpoint_id, "created_at": now}
    return run, config, validation, conversion, touchpoint, credit


class Sources:
    def __init__(self, run, config, validation, conversion, touchpoint, credit):
        self.run, self.config, self.validation = run, config, validation
        self.conversion, self.touchpoint, self.credit = conversion, touchpoint, credit
        self.limit_seen = None

    async def get_run(self, run_id, tenant_id):
        return self.run if tenant_id == self.run["tenant_id"] and run_id == self.run["attribution_run_id"] else None

    async def get_model_config(self, tenant_id, config_id):
        return self.config if tenant_id == self.config["tenant_id"] and config_id == self.config["model_config_id"] else None

    async def get(self, tenant_id, row_id):
        if tenant_id != "tenant-a":
            return None
        if row_id == self.conversion["conversion_id"]:
            return self.conversion
        if row_id == self.touchpoint["touchpoint_id"]:
            return self.touchpoint
        return None

    async def list_credits_for_run(self, tenant_id, run_id, *, limit):
        self.limit_seen = limit
        return [self.credit] if tenant_id == "tenant-a" and run_id == self.run["attribution_run_id"] else []


class Validations:
    def __init__(self, decision): self.decision = decision
    async def get(self, tenant_id, run_id): return self.decision if tenant_id == "tenant-a" else None


class Persisted:
    def __init__(self): self.rows = []
    async def insert(self, row): self.rows.append(row)


AUTH = {"action": "value.model_evaluation", "permission": "write", "decision": "allow",
        "actor_id": "user-1", "evaluated_at": datetime.now(timezone.utc) - timedelta(seconds=1)}


@pytest.mark.asyncio
async def test_authenticated_producer_persists_reproducible_exact_run_evaluation():
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources, persisted = Sources(run, config, validation, conversion, touchpoint, credit), Persisted()
    result = await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=persisted)
    row = persisted.rows[0]
    assert sources.limit_seen == 101
    assert result["metric"] == "temporal_eligibility_accuracy" and result["value"] == 1.0
    assert result["calibration_state"] == "unvalidated" and result["causal_attribution_state"] == "unknown"
    assert validate_evaluation(row)
    assert await verify_evaluation_sources("tenant-a", row, runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations(validation))
    row["sample_refs"][0]["temporallyEligible"] = False
    assert not validate_evaluation(row)


@pytest.mark.asyncio
async def test_producer_repository_reader_round_trip_rejoins_canonical_source_stubs():
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources = Sources(run, config, validation, conversion, touchpoint, credit)
    repository = ValueConfidenceEvaluationRepository()
    result = await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=repository)
    loaded = await repository.latest_for_run("tenant-a", run["attribution_run_id"])
    assert loaded["evaluation_id"] == result["evaluation_id"]
    assert loaded["dataset_manifest_sha256"] == result["dataset_manifest_sha256"]
    assert await verify_evaluation_sources("tenant-a", loaded, runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations(validation))
    assert await repository.latest_for_run("tenant-b", run["attribution_run_id"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,match", [
    ("tenant", "completed tenant attribution run"), ("config", "run/config validation"),
    ("subject", "scope mismatch"), ("future_touchpoint", ""), ("truncated", "100 row bound"),
    ("duplicate_credit", "credit identity"), ("foreign_touchpoint", "canonical touchpoint"),
])
async def test_producer_rejects_scope_config_time_and_truncation(mutation, match):
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources = Sources(run, config, validation, conversion, touchpoint, credit)
    if mutation == "tenant":
        run["tenant_id"] = "tenant-b"
    elif mutation == "config":
        validation["config_snapshot_sha256"] = "f" * 64
    elif mutation == "subject":
        credit["conversion_id"] = str(uuid4())
    elif mutation == "truncated":
        async def too_many(*args, **kwargs): return [credit] * 101
        sources.list_credits_for_run = too_many
    elif mutation == "duplicate_credit":
        async def duplicate(*args, **kwargs): return [credit, dict(credit)]
        sources.list_credits_for_run = duplicate
    elif mutation == "foreign_touchpoint":
        touchpoint["tenant_id"] = "tenant-b"
    if mutation == "future_touchpoint":
        touchpoint["occurred_at"] = conversion["occurred_at"] + timedelta(seconds=1)
        result = await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
            authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
            validations=Validations(validation), evaluations=Persisted())
        assert result["value"] == 0.0
        return
    with pytest.raises(ValueError, match=match):
        await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
            authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
            validations=Validations(validation), evaluations=Persisted())


@pytest.mark.asyncio
async def test_producer_rejects_forged_or_missing_authorization_and_reader_rejoins_sources():
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources = Sources(run, config, validation, conversion, touchpoint, credit)
    with pytest.raises(ValueError, match="authorization"):
        await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
            authorization_evidence={**AUTH, "actor_id": "other"}, runs=sources, conversions=sources,
            touchpoints=sources, validations=Validations(validation), evaluations=Persisted())
    persisted = Persisted()
    result = await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=persisted)
    assert await verify_evaluation_sources("tenant-a", persisted.rows[0], runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations(validation))
    touchpoint["occurred_at"] += timedelta(days=1)
    assert not await verify_evaluation_sources("tenant-a", persisted.rows[0], runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations(validation))
    assert result["sample_count"] == 1


@pytest.mark.asyncio
async def test_all_ineligible_samples_have_valid_window_covering_conversion_and_touchpoints():
    run, config, validation, conversion, touchpoint, credit = fixtures()
    touchpoint["occurred_at"] = conversion["occurred_at"] + timedelta(hours=1)
    sources, persisted = Sources(run, config, validation, conversion, touchpoint, credit), Persisted()
    result = await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=persisted)
    row = persisted.rows[0]
    assert result["value"] == 0.0
    assert row["window_start"] == conversion["occurred_at"]
    assert row["window_end"] == touchpoint["occurred_at"]
    assert validate_evaluation(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda r: r.update(sample_count=True),
    lambda r: r.update(eligible_count=1.0),
    lambda r: r.update(eligible_count=2),
    lambda r: r.update(created_at=datetime.now(timezone.utc) - timedelta(days=2)),
    lambda r: r.update(created_at=datetime.now(timezone.utc) + timedelta(days=1)),
    lambda r: r.update(authorization_evaluated_at=datetime.now(timezone.utc) + timedelta(days=1)),
])
async def test_reader_rejects_malformed_counts_and_invalid_timestamp_order(mutate):
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources, persisted = Sources(run, config, validation, conversion, touchpoint, credit), Persisted()
    await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=persisted)
    row = dict(persisted.rows[0])
    mutate(row)
    assert not validate_evaluation(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["created_at", "completed_at"])
async def test_producer_rejects_future_run_source_times(field):
    run, config, validation, conversion, touchpoint, credit = fixtures()
    run[field] = datetime.now(timezone.utc) + timedelta(seconds=1)
    sources = Sources(run, config, validation, conversion, touchpoint, credit)
    with pytest.raises(ValueError, match="not future"):
        await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
            authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
            validations=Validations(validation), evaluations=Persisted())


@pytest.mark.asyncio
@pytest.mark.parametrize("source_time", ["conversion", "touchpoint", "credit", "authorization"])
async def test_producer_rejects_future_event_creation_and_authorization_times(source_time):
    run, config, validation, conversion, touchpoint, credit = fixtures()
    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    auth = dict(AUTH)
    if source_time == "conversion":
        conversion["occurred_at"] = future
        expected = "conversion event time"
    elif source_time == "touchpoint":
        touchpoint["received_at"] = future
        expected = "touchpoint event time"
    elif source_time == "credit":
        credit["created_at"] = future
        expected = "credit creation time"
    else:
        auth["evaluated_at"] = future
        expected = "authorization"
    sources = Sources(run, config, validation, conversion, touchpoint, credit)
    with pytest.raises(ValueError, match=expected):
        await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
            authorization_evidence=auth, runs=sources, conversions=sources, touchpoints=sources,
            validations=Validations(validation), evaluations=Persisted())


@pytest.mark.asyncio
async def test_reader_requires_exact_durable_validation_and_rejects_future_source_events():
    run, config, validation, conversion, touchpoint, credit = fixtures()
    sources, persisted = Sources(run, config, validation, conversion, touchpoint, credit), Persisted()
    await evaluate_attribution_run("tenant-a", run["attribution_run_id"], actor_id="user-1",
        authorization_evidence=AUTH, runs=sources, conversions=sources, touchpoints=sources,
        validations=Validations(validation), evaluations=persisted)
    row = persisted.rows[0]
    assert not await verify_evaluation_sources("tenant-a", row, runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations({**validation, "decision_id": "other"}))
    touchpoint["occurred_at"] = row["created_at"] + timedelta(seconds=1)
    assert not await verify_evaluation_sources("tenant-a", row, runs=sources, conversions=sources,
        touchpoints=sources, validations=Validations(validation))
