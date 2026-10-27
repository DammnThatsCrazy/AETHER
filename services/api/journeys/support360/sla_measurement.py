"""Tenant-registered support SLA measurement contracts.

Registration adopts one exact source policy revision for one canonical case and
timer. Provider SLA events remain observations; a registered contract does not
turn a source-reported breach into a measured outcome.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph.operational_intelligence.models import EvidenceRef
from journeys.support360.cases import SupportCaseRepository
from repositories.repos import get_pool

_TABLE = "support_sla_measurement_contracts"
_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_LOCAL_CONTRACTS: dict[str, dict[str, Any]] = {}
_MAX_CASE_CONTRACTS = 200


def _payload_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise SupportSLAMeasurementContractError("SLA contract payload is invalid")
    return value


class SupportSLAMeasurementContractError(RuntimeError):
    """Registration lacks exact authority or conflicts with an immutable revision."""


class SupportSLAMeasurementContract(BaseModel):
    """One operator-adopted source SLA policy revision for an exact case timer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = Field(min_length=1, max_length=256)
    case_id: str
    source_connection_id: str = Field(min_length=1, max_length=256)
    source_provider_identity: str = Field(min_length=1, max_length=256)
    source_sla_id: str = Field(min_length=1, max_length=256)
    source_policy_id: str = Field(min_length=1, max_length=256)
    source_policy_version: str = Field(min_length=1, max_length=128)
    timer_kind: str = Field(pattern="^(first_response|resolution|custom)$")
    custom_timer_name: Optional[str] = Field(default=None, max_length=128)
    target_duration_seconds: int = Field(ge=1, le=315360000)
    registered_by: str = Field(min_length=1, max_length=256)
    registered_at: datetime

    @field_validator("case_id")
    @classmethod
    def canonical_case_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("registered_at")
    @classmethod
    def utc_registered_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registered_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def timer_shape(self) -> "SupportSLAMeasurementContract":
        if (self.timer_kind == "custom") != (self.custom_timer_name is not None):
            raise ValueError("custom_timer_name is required only for custom timers")
        if self.custom_timer_name is not None and not self.custom_timer_name.strip():
            raise ValueError("custom_timer_name must not be blank")
        for value in (
            self.source_connection_id, self.source_provider_identity,
            self.source_sla_id, self.source_policy_id, self.source_policy_version,
            self.registered_by, self.custom_timer_name,
        ):
            if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("contract identifiers must be printable")
        return self

    @property
    def contract_id(self) -> str:
        key = "\0".join((
            self.tenant_id, self.case_id, self.source_connection_id,
            self.source_provider_identity, self.source_sla_id,
            self.source_policy_id, self.source_policy_version,
            self.timer_kind, self.custom_timer_name or "",
        ))
        return "support_sla_" + hashlib.sha256(key.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class SupportSLAMeasurementContractRead:
    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


def contract_evidence(contract: SupportSLAMeasurementContract) -> EvidenceRef:
    return EvidenceRef(
        id=contract.contract_id,
        type="document",
        source=_TABLE,
        observedAt=contract.registered_at.isoformat(),
        uri=f"store://{_TABLE}/{contract.contract_id}",
    )


def _same_registration(existing: dict[str, Any], requested: dict[str, Any]) -> bool:
    """Replay retains the original registration timestamp and actor."""
    return all(
        existing.get(key) == value
        for key, value in requested.items()
        if key not in {"registered_at", "registered_by"}
    )


class SupportSLAMeasurementContractRepository:
    """Append-only writer and bounded case-scoped contract reader."""

    def __init__(self, pool: Any = None) -> None:
        self._injected_pool = pool

    async def _pool(self) -> Any:
        pool = self._injected_pool if self._injected_pool is not None else await get_pool()
        if pool is None and os.environ.get("AETHER_ENV", "local").lower() not in _LOCAL_ENVIRONMENTS:
            raise RuntimeError("support SLA contract authority requires PostgreSQL")
        return pool

    async def register(self, contract: SupportSLAMeasurementContract) -> SupportSLAMeasurementContract:
        typed = SupportSLAMeasurementContract.model_validate(contract)
        values = typed.model_dump(mode="json")
        values["contract_id"] = typed.contract_id
        pool = await self._pool()
        if pool is None:
            existing = _LOCAL_CONTRACTS.get(typed.contract_id)
            if existing is not None:
                if not _same_registration(existing, values):
                    raise SupportSLAMeasurementContractError("SLA contract revision is immutable")
                return SupportSLAMeasurementContract.model_validate(
                    {key: value for key, value in existing.items() if key != "contract_id"}
                )
            _LOCAL_CONTRACTS.setdefault(typed.contract_id, values)
            return typed
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT contract_id, payload FROM {_TABLE} WHERE tenant_id=$1 AND contract_id=$2",
                typed.tenant_id, typed.contract_id,
            )
            if row is not None:
                existing = _payload_mapping(row["payload"])
                if not _same_registration(existing, values):
                    raise SupportSLAMeasurementContractError("SLA contract revision is immutable")
                return SupportSLAMeasurementContract.model_validate(
                    {key: value for key, value in existing.items() if key != "contract_id"}
                )
            inserted = await conn.fetchrow(
                f"INSERT INTO {_TABLE} (contract_id, tenant_id, case_id, source_connection_id, "
                "source_provider_identity, source_sla_id, source_policy_id, source_policy_version, "
                "timer_kind, custom_timer_name, registered_at, payload) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb) "
                "ON CONFLICT DO NOTHING RETURNING contract_id",
                typed.contract_id, typed.tenant_id, typed.case_id, typed.source_connection_id,
                typed.source_provider_identity, typed.source_sla_id, typed.source_policy_id,
                typed.source_policy_version, typed.timer_kind, typed.custom_timer_name,
                typed.registered_at, json.dumps(values, sort_keys=True),
            )
            if inserted is None:
                row = await conn.fetchrow(
                    f"SELECT contract_id, payload FROM {_TABLE} WHERE tenant_id=$1 AND contract_id=$2",
                    typed.tenant_id, typed.contract_id,
                )
                if row is None or not _same_registration(_payload_mapping(row["payload"]), values):
                    raise SupportSLAMeasurementContractError("SLA contract revision conflicted")
                return SupportSLAMeasurementContract.model_validate(
                    {key: value for key, value in _payload_mapping(row["payload"]).items()
                     if key != "contract_id"}
                )
        return typed

    async def read_for_case(
        self, tenant_id: str, case_id: str, connection_id: str, *, limit: int = _MAX_CASE_CONTRACTS
    ) -> SupportSLAMeasurementContractRead:
        if not tenant_id or not case_id or not connection_id:
            return SupportSLAMeasurementContractRead((), False, False, "exact_case_scope_required")
        bounded = min(max(int(limit), 1), _MAX_CASE_CONTRACTS)
        try:
            pool = await self._pool()
            if pool is None:
                rows = [
                    row for row in _LOCAL_CONTRACTS.values()
                    if row.get("tenant_id") == tenant_id and row.get("case_id") == case_id
                    and row.get("source_connection_id") == connection_id
                ]
                rows.sort(key=lambda row: (row["registered_at"], row["contract_id"]), reverse=True)
            else:
                async with pool.acquire() as conn:
                    records = await conn.fetch(
                        f"SELECT payload FROM {_TABLE} WHERE tenant_id=$1 AND case_id=$2 "
                        "AND source_connection_id=$3 ORDER BY registered_at DESC, contract_id DESC LIMIT $4",
                        tenant_id, case_id, connection_id, bounded + 1,
                    )
                rows = [_payload_mapping(row["payload"]) for row in records]
            complete = len(rows) <= bounded
            return SupportSLAMeasurementContractRead(tuple(rows[:bounded]), True, complete,
                None if complete else "support_sla_contract_read_truncated")
        except Exception:  # noqa: BLE001 - absent contract authority remains unknown
            return SupportSLAMeasurementContractRead((), False, False, "support_sla_contract_read_unavailable")


class SupportSLAMeasurementContractService:
    """Register only for an existing tenant case on its verified connection."""

    def __init__(self, *, repository: Optional[SupportSLAMeasurementContractRepository] = None,
                 cases: Optional[SupportCaseRepository] = None, connections: Any = None) -> None:
        self._repository = repository or SupportSLAMeasurementContractRepository()
        self._cases = cases or SupportCaseRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository
            connections = ProviderConnectionRepository()
        self._connections = connections

    async def register(self, contract: SupportSLAMeasurementContract) -> SupportSLAMeasurementContract:
        typed = SupportSLAMeasurementContract.model_validate(contract)
        connection = await self._connections.find(typed.source_connection_id)
        def field(name: str) -> Any:
            value = connection.get(name) if isinstance(connection, dict) else getattr(connection, name, None)
            return value.value if isinstance(value, Enum) else value
        if (
            field("tenant_id") != typed.tenant_id
            or field("provider_identity") != typed.source_provider_identity
            or field("state") not in {"verified", "connected"}
            or not field("last_verified_at")
        ):
            raise SupportSLAMeasurementContractError("verified provider connection required")
        read = await self._cases.get_case(typed.tenant_id, typed.case_id, limit=1)
        case = read.record if read.available and not read.expired else None
        if (
            not isinstance(case, dict)
            or case.get("tenant_id") != typed.tenant_id
            or str(case.get("case_id")) != typed.case_id
            or case.get("source_connection_id") != typed.source_connection_id
            or case.get("source_provider_identity") != typed.source_provider_identity
        ):
            raise SupportSLAMeasurementContractError("exact tenant case and provider required")
        return await self._repository.register(typed)


def reset_local_support_sla_contract_store() -> None:
    _LOCAL_CONTRACTS.clear()
