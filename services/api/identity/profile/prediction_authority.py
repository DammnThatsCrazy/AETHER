"""Governed Profile360 future-state prediction records.

This authority records only explicit model outputs that can be tied to an
approved production artifact, an allowed inference policy decision, one exact
tenant entity, a bounded validity interval, and tenant/entity-scoped source
event evidence. It never manufactures a future state from a score or label.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repositories.typed_repo import TypedTableRepository
from shared.temporal.instant import parse_instant_strict

TABLE_NAME = "profile_prediction_outputs"
MAX_PROFILE_PREDICTION_STATES = 20
MAX_PROFILE_PREDICTION_EVIDENCE_REFS = 20
MAX_PROFILE_PREDICTION_EVIDENCE_EVENTS = 1_000
MAX_PROFILE_PREDICTION_READ = 100
MAX_PROFILE_PREDICTION_AGE = timedelta(hours=24)
PROFILE_FUTURE_STATE_SCHEMA_VERSION = "profile_future_state.v1"

# These request shapes are defined in ``ml_serving.routes._build_payload``.
# Session identifiers require a canonical resolved identity link before the
# inference can be attributed to a Profile360 entity.
_SESSION_MODEL_IDS = frozenset({"intent_prediction", "bot_detection", "session_scorer"})
_IDENTITY_MODEL_IDS = frozenset({"churn_prediction", "ltv_prediction", "journey_prediction"})


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = parse_instant_strict(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


class FutureStatePrediction(BaseModel):
    """One explicitly forecast state under the versioned Profile contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: str = Field(min_length=1, max_length=128)
    probability: float = Field(ge=0.0, le=1.0, strict=True)
    rank: int = Field(ge=1, le=MAX_PROFILE_PREDICTION_STATES, strict=True)

    @field_validator("state")
    @classmethod
    def _state_is_compact(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", value):
            raise ValueError("state must be a canonical lowercase state code")
        return value


class PredictionSourceEvidence(BaseModel):
    """A tenant/entity-scoped input event resolved by the API before write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=512)
    source: Literal["analytics_events"]
    observed_at: datetime
    event_type: Optional[str] = Field(default=None, max_length=128)


class PredictionAuthorityEvidence(BaseModel):
    """Provenance reference carried by the persisted prediction output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=1024)
    type: Literal["event", "entity", "model_output", "annotation"]
    source: str = Field(min_length=1, max_length=128)
    observed_at: Optional[datetime] = None


class ProfilePredictionOutput(BaseModel):
    """Append-only, versioned output from an approved model inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    model_id: str = Field(min_length=1, max_length=128)
    artifact_version: str = Field(min_length=1, max_length=128)
    artifact_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_approval_state: Literal["promoted"]
    feature_schema_hash: str = Field(min_length=1, max_length=128)
    feature_digest: str = Field(pattern=r"^[0-9a-f]{16}$")
    state_schema_version: Literal["profile_future_state.v1"]
    policy_decision_id: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=256)
    generated_at: datetime
    valid_from: datetime
    valid_until: datetime
    states: list[FutureStatePrediction] = Field(min_length=1, max_length=MAX_PROFILE_PREDICTION_STATES)
    evidence_refs: list[PredictionAuthorityEvidence] = Field(
        min_length=3, max_length=MAX_PROFILE_PREDICTION_EVIDENCE_REFS + 3
    )

    @model_validator(mode="after")
    def _validate_temporal_and_evidence(self) -> "ProfilePredictionOutput":
        generated = _utc(self.generated_at)
        valid_from = _utc(self.valid_from)
        valid_until = _utc(self.valid_until)
        if generated is None or valid_from is None or valid_until is None:
            raise ValueError("prediction timestamps must be timezone-aware")
        if valid_until <= valid_from or generated > valid_until:
            raise ValueError("prediction must have a non-empty interval that has not expired")
        ids = {row.id for row in self.evidence_refs}
        if self.policy_decision_id not in ids:
            raise ValueError("policy decision must be present in evidence_refs")
        expected_artifact_evidence = (
            f"{self.model_id}@{self.artifact_version}:{self.artifact_checksum_sha256}"
        )
        if not any(
            row.id == expected_artifact_evidence
            and row.source == "model_artifact_registry"
            and row.type == "model_output"
            for row in self.evidence_refs
        ):
            raise ValueError("exact approved model artifact must be present in evidence_refs")
        if not any(
            row.id == self.policy_decision_id
            and row.source == "consent_policy_decisions"
            and row.type == "annotation"
            for row in self.evidence_refs
        ):
            raise ValueError("exact inference policy decision must be present in evidence_refs")
        if not any(row.source == "analytics_events" and row.type == "event" for row in self.evidence_refs):
            raise ValueError("at least one resolved input event is required")
        state_codes = [row.state for row in self.states]
        state_ranks = [row.rank for row in self.states]
        if len(state_codes) != len(set(state_codes)) or len(state_ranks) != len(set(state_ranks)):
            raise ValueError("future states and ranks must be unique")
        return self


@dataclass(frozen=True)
class ProfilePredictionRead:
    """Bounded exact-subject read with source coverage kept explicit."""

    rows: list[ProfilePredictionOutput]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class ProfilePredictionWrite:
    """Result from the fail-closed inference writer."""

    output: Optional[ProfilePredictionOutput]
    stored: bool
    reason: str


def approved_production_artifact(model_id: str, artifact_version: str) -> Any | None:
    """Return exact active production artifact metadata or ``None``.

    The model catalog alone is not approval. The active artifact must be the
    exact version that served the inference, be promoted, pass thresholds, use
    real data, allow production, and load with its checksum/signature verified.
    """

    if not model_id or not artifact_version:
        return None
    try:
        from common.artifact_registry import load_artifact, resolve_active_artifact
        from common.model_registry import get_model, resolve_model_id

        canonical_id = resolve_model_id(model_id)
        entry = get_model(canonical_id) if canonical_id else None
        if (
            entry is None
            or canonical_id != model_id
            or not bool(getattr(entry, "serving_supported", False))
            or not bool(getattr(entry, "production_promotion_allowed", False))
        ):
            return None
        model_root = Path(os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models"))
        active_dir = resolve_active_artifact(model_root, model_id, env="production")
        if active_dir is None:
            return None
        _artifact_path, metadata = load_artifact(active_dir, env="production")
        if (
            metadata.model_id != model_id
            or metadata.artifact_version != artifact_version
            or metadata.promotion_state != "promoted"
            or metadata.disabled
            or metadata.synthetic_data
            or not metadata.threshold_passed
            or not metadata.production_allowed
            or not re.fullmatch(r"[0-9a-f]{64}", metadata.checksum_sha256)
        ):
            return None
        return metadata
    except Exception:  # noqa: BLE001 - absent or unverifiable approval stays unknown
        return None


def consent_policy_version() -> Optional[str]:
    """Read the active consent contract version used by the inference gate."""
    try:
        from intelligence.model_governance.policy import consent_policy_version as current_version

        return current_version()
    except Exception:  # noqa: BLE001 - versionless decisions cannot qualify
        return None


async def verify_prediction_policy_evidence(output: ProfilePredictionOutput) -> bool:
    """Rejoin the inference decision and any session identity binding.

    The decision is historical evidence; current consent and historical
    identity state are not established by this read.
    """
    try:
        from governance.policy.repositories import ConsentPolicyDecisionRepository

        decision = await ConsentPolicyDecisionRepository().find_by_id(output.policy_decision_id)
        if not isinstance(decision, dict):
            return False
        subject = decision.get("subject_ref")
        decision_at = _utc(decision.get("created_at"))
        if (
            decision.get("tenant_id") != output.tenant_id
            or decision.get("policy_decision_id") != output.policy_decision_id
            or decision.get("actor_id") != output.actor_id
            or decision.get("action") != "serve_inference"
            or decision.get("resource_type") != "ml_model"
            or decision.get("resource_id") != output.model_id
            or decision.get("consent_policy_version") != output.policy_version
            or decision.get("allowed") is not True
            or decision_at is None
            or decision_at > output.generated_at
            or not isinstance(subject, str)
            or not subject.strip()
        ):
            return False
        if output.model_id in _IDENTITY_MODEL_IDS:
            return subject == output.entity_id
        if output.model_id not in _SESSION_MODEL_IDS:
            return False
        identity_refs = [
            ref.id for ref in output.evidence_refs
            if ref.source == "identity_source_identities" and ref.type == "entity"
        ]
        if len(identity_refs) != 1:
            return False
        from identity.identity.repository import IdentityResolutionRepository

        rows = await IdentityResolutionRepository()._source_identities.find_many(
            filters={"tenant_id": output.tenant_id, "session_id": subject, "status": "resolved"},
            limit=2,
        )
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return False
        row = rows[0]
        return (
            row.get("tenant_id") == output.tenant_id
            and row.get("session_id") == subject
            and row.get("status") == "resolved"
            and str(row.get("canonical_entity_id") or "") == output.entity_id
            and str(row.get("id") or row.get("source_identity_id") or "") == identity_refs[0]
        )
    except Exception:  # noqa: BLE001 - inaccessible evidence fails closed
        return False


class ProfilePredictionOutputRepository(TypedTableRepository):
    """Append-only typed repository for approved profile prediction outputs."""

    table_name = TABLE_NAME
    columns = (
        "prediction_id",
        "idempotency_key",
        "tenant_id",
        "entity_id",
        "model_id",
        "artifact_version",
        "artifact_checksum_sha256",
        "artifact_approval_state",
        "feature_schema_hash",
        "feature_digest",
        "state_schema_version",
        "policy_decision_id",
        "policy_version",
        "actor_id",
        "generated_at",
        "valid_from",
        "valid_until",
        "states",
        "evidence_refs",
    )

    async def get_prediction(self, tenant_id: str, prediction_id: str) -> Optional[dict[str, Any]]:
        """Return one exact tenant/prediction row for canonical outcome binding."""
        if not tenant_id or not prediction_id:
            return None
        pool = await self._pool()
        if pool is None:
            row = next((row for row in self._rows
                        if row.get("tenant_id") == tenant_id
                        and row.get("prediction_id") == prediction_id), None)
            return dict(row) if row is not None else None
        row = await pool.fetchrow(
            f"SELECT {', '.join(self.columns)} FROM {self.table_name} WHERE tenant_id=$1 AND prediction_id=$2",
            tenant_id, prediction_id,
        )
        return self._decode_row(dict(row)) if row is not None else None
    jsonb_columns = frozenset({"states", "evidence_refs"})
    conflict_key = ("tenant_id", "idempotency_key")

    async def record(self, output: ProfilePredictionOutput) -> bool:
        row = output.model_dump(mode="python")
        return await self.insert(row)

    async def read_valid_for_subject(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        as_of: datetime,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read only exact, currently-valid rows under a hard upper bound."""

        anchor = _utc(as_of)
        if not tenant_id or not entity_id or anchor is None:
            return [], False
        bounded = min(max(int(limit), 1), MAX_PROFILE_PREDICTION_READ)
        pool = await self._pool()
        if pool is None:
            candidates = [
                dict(row)
                for row in self._rows
                if row.get("tenant_id") == tenant_id
                and row.get("entity_id") == entity_id
                and (_utc(row.get("generated_at")) or datetime.max.replace(tzinfo=timezone.utc)) <= anchor
                and (_utc(row.get("valid_from")) or datetime.max.replace(tzinfo=timezone.utc)) <= anchor
                and (_utc(row.get("valid_until")) or datetime.min.replace(tzinfo=timezone.utc)) >= anchor
            ]
            candidates.sort(
                key=lambda row: (_utc(row.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("prediction_id") or "")),
                reverse=True,
            )
            return candidates[:bounded], len(candidates) > bounded

        rows = await pool.fetch(
            f"""SELECT {', '.join(self.columns)} FROM {self.table_name}
                WHERE tenant_id = $1 AND entity_id = $2
                  AND generated_at <= $3 AND valid_from <= $3 AND valid_until >= $3
                ORDER BY generated_at DESC, prediction_id ASC LIMIT $4""",
            tenant_id,
            entity_id,
            anchor,
            bounded + 1,
        )
        decoded = [self._decode_row(dict(row)) for row in rows]
        return decoded[:bounded], len(decoded) > bounded

    async def list_for_artifact(
        self, tenant_id: str, model_id: str, artifact_version: str,
        window_start: datetime, window_end: datetime, *, limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Bounded exact tenant/model/artifact prediction dataset read."""
        bounded = min(max(int(limit), 1), 5_000)
        start, end = _utc(window_start), _utc(window_end)
        if not tenant_id or not model_id or not artifact_version or start is None or end is None or start >= end:
            return [], False
        pool = await self._pool()
        if pool is None:
            candidates = [
                dict(row) for row in self._rows
                if row.get("tenant_id") == tenant_id
                and row.get("model_id") == model_id
                and row.get("artifact_version") == artifact_version
                and start <= (_utc(row.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc)) < end
            ]
            candidates.sort(key=lambda row: (str(row.get("prediction_id") or "")))
            return candidates[:bounded], len(candidates) > bounded
        rows = await pool.fetch(
            f"""SELECT {', '.join(self.columns)} FROM {self.table_name}
                WHERE tenant_id = $1 AND model_id = $2 AND artifact_version = $3
                  AND generated_at >= $4 AND generated_at < $5
                ORDER BY prediction_id LIMIT $6""",
            tenant_id, model_id, artifact_version, start, end, bounded + 1,
        )
        decoded = [self._decode_row(dict(row)) for row in rows]
        return decoded[:bounded], len(decoded) > bounded


async def record_eligible_profile_prediction(
    *,
    tenant_id: str,
    requested_subject_id: str,
    actor_id: str,
    model_id: str,
    feature_digest: Optional[str],
    feature_schema_hash: Optional[str],
    policy_decision_id: Optional[str],
    policy_version: Optional[str],
    policy_allowed: bool,
    model_result: Any,
    cache: Any = None,
    repository: Optional[ProfilePredictionOutputRepository] = None,
    artifact_resolver=approved_production_artifact,
) -> ProfilePredictionWrite:
    """Persist only a fully qualified model output; otherwise return a reason.

    Model output must explicitly provide a future-state list, a validity
    interval, and analytics event IDs that resolve under the same tenant and
    canonical entity. Scores, intent labels, arbitrary feature payloads, and
    cache entries are not converted into states.
    """

    def skip(reason: str) -> ProfilePredictionWrite:
        return ProfilePredictionWrite(output=None, stored=False, reason=reason)

    if not tenant_id.strip() or not requested_subject_id.strip() or not actor_id.strip():
        return skip("prediction_tenant_or_subject_missing")
    if not isinstance(model_result, dict):
        return skip("prediction_model_result_not_object")
    if not policy_allowed or not policy_decision_id or not policy_version:
        return skip("prediction_inference_policy_not_allowed_or_versioned")
    if not feature_digest or not feature_schema_hash:
        return skip("prediction_feature_context_provenance_missing")

    raw_states = model_result.get("likely_next_states")
    raw_valid_from = model_result.get("valid_from")
    raw_valid_until = model_result.get("valid_until")
    raw_evidence = model_result.get("evidence_refs")
    artifact_version = model_result.get("artifact_version")
    artifact_checksum = model_result.get("artifact_checksum_sha256")
    state_schema_version = model_result.get("state_schema_version")
    if not isinstance(raw_states, list) or not raw_states:
        return skip("model_did_not_supply_likely_next_states")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        return skip("prediction_input_evidence_refs_missing")
    if not isinstance(artifact_version, str) or not artifact_version.strip():
        return skip("prediction_model_artifact_version_missing")
    if state_schema_version != PROFILE_FUTURE_STATE_SCHEMA_VERSION:
        return skip("prediction_state_schema_version_missing_or_unsupported")
    if not isinstance(artifact_checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_checksum):
        return skip("prediction_model_artifact_checksum_missing_or_invalid")
    if len(raw_states) > MAX_PROFILE_PREDICTION_STATES:
        return skip("prediction_future_state_output_exceeds_limit")

    try:
        states = [FutureStatePrediction.model_validate(row) for row in raw_states]
    except Exception:  # noqa: BLE001 - malformed model output is not promoted
        return skip("prediction_future_state_output_invalid")
    generated_at = datetime.now(timezone.utc)
    valid_from = _utc(raw_valid_from)
    valid_until = _utc(raw_valid_until)
    if (
        valid_from is None
        or valid_until is None
        or valid_until <= valid_from
        or generated_at > valid_until
    ):
        return skip("prediction_validity_interval_missing_or_invalid")

    # Resolve the caller's identifier only through the exact input contract
    # already used by the ML serving adapter. A session ID needs a unique active
    # tenant identity binding; an identity ID must itself be a canonical entity.
    identity_evidence: Optional[PredictionAuthorityEvidence] = None
    if model_id in _SESSION_MODEL_IDS:
        try:
            from identity.identity.repository import IdentityResolutionRepository

            identity_repo = IdentityResolutionRepository()
            identity_rows = await identity_repo._source_identities.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "session_id": requested_subject_id,
                    "status": "resolved",
                },
                limit=2,
            )
        except Exception:  # noqa: BLE001 - missing binding stays unknown
            return skip("prediction_session_identity_authority_unavailable")
        if not isinstance(identity_rows, list) or len(identity_rows) != 1:
            return skip("prediction_session_identity_binding_not_unique")
        identity_row = identity_rows[0]
        if (
            not isinstance(identity_row, dict)
            or identity_row.get("tenant_id") != tenant_id
            or identity_row.get("session_id") != requested_subject_id
            or identity_row.get("status") != "resolved"
            or not str(identity_row.get("canonical_entity_id") or "").strip()
        ):
            return skip("prediction_session_identity_binding_scope_invalid")
        entity_id = str(identity_row["canonical_entity_id"])
        identity_evidence = PredictionAuthorityEvidence(
            id=str(identity_row.get("id") or identity_row.get("source_identity_id") or ""),
            type="entity",
            source="identity_source_identities",
            observed_at=_utc(identity_row.get("updated_at") or identity_row.get("created_at")),
        )
        if not identity_evidence.id:
            return skip("prediction_session_identity_evidence_missing")
    elif model_id in _IDENTITY_MODEL_IDS:
        entity_id = requested_subject_id
    else:
        return skip("prediction_model_subject_binding_not_registered")

    try:
        from repositories.repos import EntityRepository

        entity_rows = await EntityRepository().find_many(
            filters={"tenant_id": tenant_id, "entity_id": entity_id}, limit=2
        )
    except Exception:  # noqa: BLE001 - canonical entity authority unavailable
        return skip("prediction_canonical_entity_authority_unavailable")
    if not isinstance(entity_rows, list) or len(entity_rows) != 1:
        return skip("prediction_canonical_entity_not_unique")
    entity = entity_rows[0]
    if (
        not isinstance(entity, dict)
        or entity.get("tenant_id") != tenant_id
        or str(entity.get("entity_id") or "") != entity_id
        or str(entity.get("entity_type") or "").lower() != "human"
    ):
        return skip("prediction_canonical_human_entity_scope_invalid")

    try:
        from governance.policy.repositories import ConsentPolicyDecisionRepository

        policy_decision = await ConsentPolicyDecisionRepository().find_by_id(policy_decision_id)
    except Exception:  # noqa: BLE001 - missing policy evidence stays unknown
        return skip("prediction_policy_decision_authority_unavailable")
    if (
        not isinstance(policy_decision, dict)
        or policy_decision.get("tenant_id") != tenant_id
        or policy_decision.get("policy_decision_id") != policy_decision_id
        or policy_decision.get("action") != "serve_inference"
        or policy_decision.get("resource_type") != "ml_model"
        or policy_decision.get("resource_id") != model_id
        or policy_decision.get("subject_ref") != requested_subject_id
        or policy_decision.get("actor_id") != actor_id
        or policy_decision.get("allowed") is not True
        or policy_decision.get("consent_policy_version") != policy_version
    ):
        return skip("prediction_policy_decision_scope_or_version_invalid")

    try:
        artifact = artifact_resolver(model_id, artifact_version)
    except Exception:  # noqa: BLE001 - approval checks fail closed
        artifact = None
    if artifact is None:
        return skip("prediction_model_artifact_not_active_production_approved")
    if str(getattr(artifact, "checksum_sha256", "") or "") != artifact_checksum:
        return skip("prediction_model_artifact_checksum_mismatch")
    if str(getattr(artifact, "feature_schema_hash", "") or "") != feature_schema_hash:
        return skip("prediction_artifact_feature_schema_mismatch")

    if len(raw_evidence) > MAX_PROFILE_PREDICTION_EVIDENCE_REFS:
        return skip("prediction_input_evidence_exceeds_limit")
    evidence_ids: list[str] = []
    for reference in raw_evidence:
        if (
            not isinstance(reference, dict)
            or reference.get("source") != "analytics_events"
            or reference.get("type") != "event"
        ):
            return skip("prediction_input_evidence_reference_type_unsupported")
        ref_id = str(reference.get("id") or reference.get("event_id") or "").strip()
        if not ref_id or ref_id in evidence_ids:
            return skip("prediction_input_evidence_reference_invalid_or_duplicate")
        evidence_ids.append(ref_id)
    if not evidence_ids:
        return skip("prediction_input_evidence_refs_missing")

    try:
        if cache is None:
            from dependencies.providers import get_cache

            cache = get_cache()
        from repositories.repos import AnalyticsRepository

        source_events = await AnalyticsRepository(cache).query_events(
            tenant_id,
            {"canonical_entity_id": entity_id},
            limit=MAX_PROFILE_PREDICTION_EVIDENCE_EVENTS + 1,
        )
    except Exception:  # noqa: BLE001 - source facts cannot be verified
        return skip("prediction_input_evidence_authority_unavailable")
    if not isinstance(source_events, list) or len(source_events) > MAX_PROFILE_PREDICTION_EVIDENCE_EVENTS:
        return skip("prediction_input_evidence_scan_truncated_or_invalid")
    if any(
        not isinstance(row, dict)
        or row.get("tenant_id") != tenant_id
        or str(row.get("canonical_entity_id") or "") != entity_id
        for row in source_events
    ):
        return skip("prediction_input_evidence_source_scope_invalid")

    by_event_id = {
        str(row.get("event_id")): row
        for row in source_events
        if str(row.get("event_id") or "").strip()
    }
    resolved_events: list[PredictionSourceEvidence] = []
    for ref_id in evidence_ids:
        row = by_event_id.get(ref_id)
        observed_at = _utc(row.get("occurred_at")) if row else None
        if row is None or observed_at is None or observed_at > generated_at:
            return skip("prediction_input_evidence_not_found_for_exact_entity")
        resolved_events.append(
            PredictionSourceEvidence(
                record_id=ref_id,
                source="analytics_events",
                observed_at=observed_at,
                event_type=(str(row.get("event_type"))[:128] if row.get("event_type") else None),
            )
        )

    evidence_refs = [
        PredictionAuthorityEvidence(
            id=ref.record_id,
            type="event",
            source=ref.source,
            observed_at=ref.observed_at,
        )
        for ref in resolved_events
    ]
    if identity_evidence is not None:
        evidence_refs.append(identity_evidence)
    artifact_checksum = str(getattr(artifact, "checksum_sha256", "") or "")
    if len(artifact_checksum) != 64:
        return skip("prediction_model_artifact_checksum_unavailable")
    evidence_refs.extend(
        [
            PredictionAuthorityEvidence(
                id=f"{model_id}@{artifact_version}:{artifact_checksum}",
                type="model_output",
                source="model_artifact_registry",
                observed_at=_utc(getattr(artifact, "created_at", None)),
            ),
            PredictionAuthorityEvidence(
                id=policy_decision_id,
                type="annotation",
                source="consent_policy_decisions",
                observed_at=_utc(policy_decision.get("created_at")),
            ),
        ]
    )

    idempotency_key = make_prediction_idempotency_key(
        tenant_id=tenant_id,
        entity_id=entity_id,
        model_id=model_id,
        artifact_version=artifact_version,
        artifact_checksum=artifact_checksum,
        feature_digest=feature_digest,
        policy_decision_id=policy_decision_id,
        states=states,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    try:
        output = ProfilePredictionOutput(
            prediction_id=f"ppout_{uuid.uuid4().hex}",
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            entity_id=entity_id,
            model_id=model_id,
            artifact_version=artifact_version,
            artifact_checksum_sha256=artifact_checksum,
            artifact_approval_state="promoted",
            feature_schema_hash=feature_schema_hash,
            feature_digest=feature_digest,
            state_schema_version=PROFILE_FUTURE_STATE_SCHEMA_VERSION,
            policy_decision_id=policy_decision_id,
            policy_version=policy_version,
            actor_id=actor_id,
            generated_at=generated_at,
            valid_from=valid_from,
            valid_until=valid_until,
            states=states,
            evidence_refs=evidence_refs,
        )
    except Exception:  # noqa: BLE001 - authority model is a fail-closed boundary
        return skip("prediction_output_contract_invalid")
    try:
        stored = await (repository or ProfilePredictionOutputRepository()).record(output)
    except Exception:  # noqa: BLE001 - successful inference does not imply persisted authority
        return skip("prediction_output_authority_write_failed")
    return ProfilePredictionWrite(
        output=output if stored else None,
        stored=stored,
        reason="prediction_output_recorded" if stored else "prediction_output_replay_duplicate",
    )


def make_prediction_idempotency_key(
    *,
    tenant_id: str,
    entity_id: str,
    model_id: str,
    artifact_version: str,
    artifact_checksum: str,
    feature_digest: str,
    policy_decision_id: str,
    states: list[FutureStatePrediction],
    valid_from: datetime,
    valid_until: datetime,
) -> str:
    """Stable digest for idempotent retries of one governed inference result."""

    payload = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "model_id": model_id,
        "artifact_version": artifact_version,
        "artifact_checksum": artifact_checksum,
        "state_schema_version": PROFILE_FUTURE_STATE_SCHEMA_VERSION,
        "feature_digest": feature_digest,
        "policy_decision_id": policy_decision_id,
        "states": [row.model_dump(mode="json") for row in states],
        "valid_from": valid_from.astimezone(timezone.utc).isoformat(),
        "valid_until": valid_until.astimezone(timezone.utc).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "FutureStatePrediction",
    "MAX_PROFILE_PREDICTION_AGE",
    "MAX_PROFILE_PREDICTION_EVIDENCE_EVENTS",
    "MAX_PROFILE_PREDICTION_EVIDENCE_REFS",
    "MAX_PROFILE_PREDICTION_READ",
    "MAX_PROFILE_PREDICTION_STATES",
    "PredictionAuthorityEvidence",
    "PredictionSourceEvidence",
    "ProfilePredictionOutput",
    "ProfilePredictionOutputRepository",
    "ProfilePredictionRead",
    "ProfilePredictionWrite",
    "PROFILE_FUTURE_STATE_SCHEMA_VERSION",
    "approved_production_artifact",
    "consent_policy_version",
    "make_prediction_idempotency_key",
    "record_eligible_profile_prediction",
]
