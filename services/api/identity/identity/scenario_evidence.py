"""Durable tenant-scoped records from executed identity-continuity scenarios.

Rows are written only when the staging runner submits an explicit terminal
outcome together with assertion counts and a digest of its run artifact. This
module never derives a pass from repository state or aggregate health.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repositories.repos import get_pool
from shared.common.common import utc_now
from config.settings import settings

IDENTITY_CONTINUITY_SCENARIOS = (
    "A_import_first_sdk_later",
    "B_shared_device_no_merge",
    "C_bad_merge_split",
    "D_agent_human_no_merge",
    "shared_email_review",
    "cross_tenant_block",
    "deleted_suppressed_identity_block",
    "multi_sdk_same_user",
    "connector_reimport_idempotency",
    "projection_restatement",
)

IDENTITY_SCENARIO_EVIDENCE_DDL = """
CREATE TABLE IF NOT EXISTS identity_scenario_execution_evidence (
    tenant_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    execution_id UUID NOT NULL,
    scenario_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'failed')),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    assertions_passed INTEGER NOT NULL CHECK (assertions_passed > 0),
    assertions_failed INTEGER NOT NULL CHECK (assertions_failed >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_ref TEXT NOT NULL,
    PRIMARY KEY (tenant_id, deployment_id, execution_id, scenario_id),
    CHECK ((outcome = 'passed' AND assertions_failed = 0) OR
           (outcome = 'failed' AND assertions_failed > 0)),
    CHECK (scenario_id IN (
      'A_import_first_sdk_later', 'B_shared_device_no_merge',
      'C_bad_merge_split', 'D_agent_human_no_merge', 'shared_email_review',
      'cross_tenant_block', 'deleted_suppressed_identity_block',
      'multi_sdk_same_user', 'connector_reimport_idempotency',
      'projection_restatement'
    ))
)
;
CREATE OR REPLACE FUNCTION prevent_identity_scenario_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    -- Tenant erasure is the only permitted deletion. The lifecycle service
    -- sets this transaction-local value only after revoking the tenant keys.
    IF TG_OP = 'DELETE'
       AND COALESCE(current_setting('aether.tenant_erasure', true), '') = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'identity scenario execution evidence is append-only';
END;
$$ LANGUAGE plpgsql;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_identity_scenario_evidence_append_only'
          AND tgrelid = 'identity_scenario_execution_evidence'::regclass
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_identity_scenario_evidence_append_only
            BEFORE UPDATE OR DELETE ON identity_scenario_execution_evidence
            FOR EACH ROW EXECUTE FUNCTION prevent_identity_scenario_evidence_mutation()';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_identity_scenario_evidence_no_truncate'
          AND tgrelid = 'identity_scenario_execution_evidence'::regclass
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_identity_scenario_evidence_no_truncate
            BEFORE TRUNCATE ON identity_scenario_execution_evidence
            FOR EACH STATEMENT EXECUTE FUNCTION prevent_identity_scenario_evidence_mutation()';
    END IF;
END;
$$;
"""


class ScenarioExecutionRequest(BaseModel):
    """A runner's explicit result; caller-supplied claims are cross-checked."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
    scenario_id: str
    outcome: Literal["passed", "failed"]
    evidence_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    assertions_passed: int = Field(ge=1, le=100_000)
    assertions_failed: int = Field(ge=0, le=100_000)
    started_at: datetime

    @field_validator("scenario_id")
    @classmethod
    def known_scenario_only(cls, value: str) -> str:
        if value not in IDENTITY_CONTINUITY_SCENARIOS:
            raise ValueError("unknown identity continuity scenario")
        return value

    @field_validator("evidence_sha256")
    @classmethod
    def normalize_digest(cls, value: str) -> str:
        return value.lower()

    @field_validator("started_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("started_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def outcome_must_match_assertions(self) -> "ScenarioExecutionRequest":
        if self.outcome == "passed" and self.assertions_failed != 0:
            raise ValueError("passed outcome requires zero failed assertions")
        if self.outcome == "failed" and self.assertions_failed == 0:
            raise ValueError("failed outcome requires at least one failed assertion")
        if self.started_at > utc_now():
            raise ValueError("started_at cannot be in the future")
        if (utc_now() - self.started_at).total_seconds() > 24 * 60 * 60:
            raise ValueError("scenario execution evidence must be recorded within 24 hours")
        return self


_MEMORY_ROWS: dict[tuple[str, str, str, str], dict[str, Any]] = {}
_MEMORY_LOCK: asyncio.Lock | None = None
_MEMORY_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _lock() -> asyncio.Lock:
    global _MEMORY_LOCK, _MEMORY_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEMORY_LOCK is None or _MEMORY_LOCK_LOOP is not loop:
        _MEMORY_LOCK = asyncio.Lock()
        _MEMORY_LOCK_LOOP = loop
    return _MEMORY_LOCK


def reset_identity_scenario_evidence_memory() -> None:
    _MEMORY_ROWS.clear()


def _row_matches(row: dict[str, Any], values: dict[str, Any]) -> bool:
    for field, expected in values.items():
        actual = row.get(field)
        if field == "execution_id":
            if str(actual).lower() != str(expected).lower():
                return False
        elif actual != expected:
            return False
    return True


class IdentityScenarioEvidenceRepository:
    async def record(
        self, *, tenant_id: str, deployment_id: str, execution_id: str,
        scenario_id: str, outcome: str, evidence_sha256: str,
        assertions_passed: int, assertions_failed: int, started_at: datetime,
        actor_ref: str,
    ) -> dict[str, Any]:
        if scenario_id not in IDENTITY_CONTINUITY_SCENARIOS:
            raise ValueError("unknown identity continuity scenario")
        if outcome not in {"passed", "failed"}:
            raise ValueError("scenario outcome must be an explicit terminal result")
        if (outcome == "passed") != (assertions_failed == 0) or assertions_passed < 1:
            raise ValueError("scenario outcome does not match assertion counts")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise ValueError("scenario evidence digest is invalid")
        key = (tenant_id, deployment_id, execution_id, scenario_id)
        values = {
            "tenant_id": tenant_id,
            "deployment_id": deployment_id,
            "execution_id": execution_id,
            "scenario_id": scenario_id,
            "outcome": outcome,
            "evidence_sha256": evidence_sha256,
            "assertions_passed": assertions_passed,
            "assertions_failed": assertions_failed,
            "started_at": started_at.astimezone(timezone.utc),
            "actor_ref": actor_ref,
        }
        pool = await get_pool()
        if pool is None:
            if settings.env.value not in {"local", "dev"}:
                raise RuntimeError("durable database is required for staging identity scenario evidence")
            async with _lock():
                prior = _MEMORY_ROWS.get(key)
                if prior:
                    if not _row_matches(prior, values):
                        raise ValueError("execution result is immutable once recorded")
                    return dict(prior)
                row = {**values, "executed_at": utc_now()}
                _MEMORY_ROWS[key] = row
                return dict(row)

        async with pool.acquire() as conn:
            await conn.execute(IDENTITY_SCENARIO_EVIDENCE_DDL)
            row = await conn.fetchrow(
                """INSERT INTO identity_scenario_execution_evidence
                     (tenant_id, deployment_id, execution_id, scenario_id, outcome,
                      evidence_sha256, assertions_passed, assertions_failed,
                      started_at, actor_ref)
                   VALUES ($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10)
                   ON CONFLICT (tenant_id, deployment_id, execution_id, scenario_id)
                   DO NOTHING
                   RETURNING *""",
                tenant_id, deployment_id, execution_id, scenario_id, outcome,
                evidence_sha256, assertions_passed, assertions_failed,
                values["started_at"], actor_ref,
            )
            if row:
                return dict(row)
            prior = await conn.fetchrow(
                """SELECT * FROM identity_scenario_execution_evidence
                   WHERE tenant_id=$1 AND deployment_id=$2
                     AND execution_id=$3::uuid AND scenario_id=$4""",
                tenant_id, deployment_id, execution_id, scenario_id,
            )
        if prior is None:
            raise RuntimeError("scenario evidence write could not be confirmed")
        result = dict(prior)
        if not _row_matches(result, values):
            raise ValueError("execution result is immutable once recorded")
        return result

    async def list_for_tenant(
        self, tenant_id: str, deployment_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        pool = await get_pool()
        if pool is None:
            if settings.env.value not in {"local", "dev"}:
                raise RuntimeError("durable database is required for staging identity scenario evidence")
            async with _lock():
                rows = [
                    dict(row) for row in _MEMORY_ROWS.values()
                    if row["tenant_id"] == tenant_id and row["deployment_id"] == deployment_id
                ]
            return sorted(
                rows,
                key=lambda row: (row["executed_at"], str(row["execution_id"]), row["scenario_id"]),
                reverse=True,
            )[:limit]
        async with pool.acquire() as conn:
            await conn.execute(IDENTITY_SCENARIO_EVIDENCE_DDL)
            rows = await conn.fetch(
                """SELECT * FROM identity_scenario_execution_evidence
                   WHERE tenant_id=$1 AND deployment_id=$2
                   ORDER BY executed_at DESC, execution_id DESC, scenario_id ASC LIMIT $3""",
                tenant_id, deployment_id, max(1, min(limit, 1000)),
            )
        return [dict(row) for row in rows]

    async def delete_for_tenant(self, tenant_id: str) -> int:
        """Erase evidence with its owner during the authorized tenant cascade."""
        pool = await get_pool()
        if pool is None:
            if settings.env.value not in {"local", "dev"}:
                raise RuntimeError("durable database is required for staging identity scenario evidence erasure")
            async with _lock():
                keys = [key for key in _MEMORY_ROWS if key[0] == tenant_id]
                for key in keys:
                    _MEMORY_ROWS.pop(key, None)
                return len(keys)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('aether.tenant_erasure', 'on', true)")
                result = await conn.execute(
                    "DELETE FROM identity_scenario_execution_evidence WHERE tenant_id=$1",
                    tenant_id,
                )
        return int(result.split()[-1]) if result else 0
