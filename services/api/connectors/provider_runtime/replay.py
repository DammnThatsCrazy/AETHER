"""Bounded raw-provider replay through the existing normalization and bridge.

The jobs platform owns the durable lease, retry, idempotency key and payload
checkpoint. This module owns a tenant/connection/account/stream/time-scoped
Bronze reader and deterministic re-normalization. A live run only enqueues
canonical events through EventBridge; provider facts remain deferred from
SDK-only consumers and this service never changes a connector writer route.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.integration_contracts.events import RawProviderRecord, verify_checksum
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.provider_runtime.replay")

PROVIDER_REPLAY_JOB_TYPE = "provider.raw_replay"
PAGE_SIZE = 100

_RAW_PAGE_SQL = """
SELECT id, created_at, data
FROM bronze_provider_records
WHERE tenant_id = $1
  AND data->>'source' = $2
  AND data->'payload'->>'connection_id' = $3
  AND data->'payload'->>'account_id' = $4
  AND data->'payload'->>'stream_id' = $5
  AND (data->'payload'->>'source_account_realm') IS NOT DISTINCT FROM $6::text
  AND created_at >= $7 AND created_at < $8
  AND (created_at, id) > ($9, $10)
ORDER BY created_at, id
LIMIT $11
"""


class ReplayIntegrityError(RuntimeError):
    """Stored source, version, or normalizer output violated the replay scope."""


class ReplayScope(BaseModel):
    """One closed Bronze-ingest window; every dimension is explicit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    provider_identity: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    # V2 source revisions always carry this boundary. None selects only
    # historical v1 records whose realm cannot be proven from their envelope.
    source_account_realm: Literal["live", "test"] | None = None
    ingested_from: datetime
    ingested_before: datetime
    max_records: int = Field(ge=1, le=10000)
    dry_run: bool
    normalizer_version: str = Field(min_length=1)
    event_schema_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _closed_window(self) -> "ReplayScope":
        values = (
            self.tenant_id,
            self.connection_id,
            self.provider_identity,
            self.account_id,
            self.stream_id,
            self.normalizer_version,
            self.event_schema_version,
        )
        if any(not value.strip() for value in values):
            raise ValueError("replay scope values must be nonblank")
        if self.ingested_from.tzinfo is None or self.ingested_before.tzinfo is None:
            raise ValueError("replay window timestamps must include a timezone")
        if self.ingested_before <= self.ingested_from:
            raise ValueError("replay window must be nonempty")
        if self.ingested_before > datetime.now(timezone.utc):
            raise ValueError("replay window must have closed before enqueue")
        return self


class ReplayCursor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime
    bronze_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _aware(self) -> "ReplayCursor":
        if self.created_at.tzinfo is None:
            raise ValueError("replay cursor timestamp must include a timezone")
        return self


class ReplayRawRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: ReplayCursor
    record: RawProviderRecord


class ProviderRawReplayReader:
    """Keyset-scan persisted raw Bronze, with DB-side scope predicates."""

    async def page(
        self, scope: ReplayScope, cursor: ReplayCursor | None, limit: int
    ) -> list[ReplayRawRow]:
        from config.settings import Environment, settings
        from repositories.repos import _IN_MEMORY_STORES, get_pool

        if limit < 1 or limit > PAGE_SIZE + 1:
            raise ValueError("invalid replay page size")
        pool = await get_pool()
        if pool is None:
            if settings.env not in (Environment.LOCAL, Environment.DEV):
                raise RuntimeError("durable raw Bronze is unavailable for provider replay")
            stored = list(_IN_MEMORY_STORES.setdefault("bronze_provider_records", {}).values())
            rows = [(row.get("id"), row.get("created_at"), row) for row in stored]
        else:
            start = cursor.created_at if cursor else scope.ingested_from
            start_id = cursor.bronze_id if cursor else ""
            async with pool.acquire() as conn:
                fetched = await conn.fetch(
                    _RAW_PAGE_SQL,
                    scope.tenant_id,
                    scope.provider_identity,
                    scope.connection_id,
                    scope.account_id,
                    scope.stream_id,
                    scope.source_account_realm,
                    scope.ingested_from,
                    scope.ingested_before,
                    start,
                    start_id,
                    limit,
                )
            rows = [(row["id"], row["created_at"], row["data"]) for row in fetched]

        result: list[ReplayRawRow] = []
        for bronze_id, created_at, data in rows:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except ValueError as exc:
                    raise ReplayIntegrityError("raw Bronze envelope is invalid") from exc
            if pool is None:
                # Local stores can contain records from every tenant and
                # provider. Filter top-level scope before interpreting a raw
                # payload so unrelated legacy rows cannot block this replay.
                if not isinstance(data, dict) or (
                    data.get("tenant_id") != scope.tenant_id
                    or data.get("source") != scope.provider_identity
                ):
                    continue
                stamp = _aware_time(created_at)
                candidate = ReplayCursor(created_at=stamp, bronze_id=str(bronze_id))
                raw_payload = data.get("payload")
                if not isinstance(raw_payload, dict):
                    # Match the durable SQL path: a row without all required
                    # scope columns cannot belong to this replay window.
                    continue
                if not (
                    scope.ingested_from <= stamp < scope.ingested_before
                    and (cursor is None or _cursor_key(candidate) > _cursor_key(cursor))
                    and raw_payload.get("connection_id") == scope.connection_id
                    and raw_payload.get("account_id") == scope.account_id
                    and raw_payload.get("stream_id") == scope.stream_id
                    and raw_payload.get("source_account_realm") == scope.source_account_realm
                ):
                    continue
            if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
                raise ReplayIntegrityError("raw Bronze envelope is invalid")
            # Replay is another normalization entry point, so require the
            # persisted Bronze admission result. Missing legacy markers and
            # contradictory provenance/quarantine fields fail closed.
            if (
                data.get("quarantine_status") != "not_quarantined"
                or data.get("provenance_status") != "valid"
            ):
                raise ReplayIntegrityError(
                    "raw provider record is quarantined or provenance is unverified"
                )
            if pool is not None:
                stamp = _aware_time(created_at)
                candidate = ReplayCursor(created_at=stamp, bronze_id=str(bronze_id))
            try:
                raw = RawProviderRecord.model_validate(data["payload"])
            except ValueError as exc:
                # Validation details can contain source PII. Job errors must
                # stay safe for operator timelines and dead-letter notices.
                raise ReplayIntegrityError("raw provider record is invalid") from exc
            if (
                data.get("id") != str(bronze_id)
                or data.get("tenant_id") != scope.tenant_id
                or data.get("source") != scope.provider_identity
                or data.get("provider_record_id") != raw.bronze_provider_record_id
                or data.get("schema_version") != raw.schema_version
                or data.get("idempotency_key") != raw.idempotency_key
            ):
                raise ReplayIntegrityError("raw Bronze lineage mismatch")
            _verify_raw_scope(scope, raw)
            result.append(ReplayRawRow(cursor=candidate, record=raw))
        result.sort(key=lambda item: _cursor_key(item.cursor))
        return result[:limit]


def _aware_time(value: datetime | str) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ReplayIntegrityError("raw Bronze timestamp is timezone-naive")
    return parsed.astimezone(timezone.utc)


def _cursor_key(cursor: ReplayCursor) -> tuple[datetime, str]:
    return cursor.created_at, cursor.bronze_id


def _verify_raw_scope(scope: ReplayScope, raw: RawProviderRecord) -> None:
    if (
        not raw.record_id
        or raw.tenant_id != scope.tenant_id
        or raw.connection_id != scope.connection_id
        or raw.provider_identity != scope.provider_identity
        or raw.account_id != scope.account_id
        or raw.stream_id != scope.stream_id
        or raw.source_account_realm != scope.source_account_realm
    ):
        raise ReplayIntegrityError("raw record escaped replay scope")
    if not verify_checksum(raw):
        raise ReplayIntegrityError("raw provider checksum mismatch")


Checkpoint = Callable[[ReplayCursor, dict[str, int]], Awaitable[None]]
Heartbeat = Callable[[], Awaitable[bool]]


class ProviderRawReplayService:
    def __init__(
        self,
        *,
        reader=None,
        bridge=None,
        registry=None,
        connections=None,
        jobs=None,
        rights_admission=None,
    ) -> None:
        self.reader = reader or ProviderRawReplayReader()
        self.bridge = bridge
        self.registry = registry
        self.connections = connections
        self.jobs = jobs
        self.rights_admission = rights_admission

    def _rights(self):
        if self.rights_admission is None:
            from connectors.provider_runtime.rights_admission import ProviderRawRightsAdmission

            self.rights_admission = ProviderRawRightsAdmission()
        return self.rights_admission

    def _plugin(self, identity: str):
        if self.registry is None:
            from connectors.provider_runtime.registry import registry

            self.registry = registry
        plugin = self.registry.get(identity)
        if plugin is None:
            raise ReplayIntegrityError("provider plugin is not installed")
        return plugin

    async def _validate_connection(self, scope: ReplayScope) -> None:
        if self.connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            self.connections = ProviderConnectionRepository()
        connection = await self.connections.find(scope.connection_id)
        if (
            connection is None
            or connection.tenant_id != scope.tenant_id
            or connection.provider_identity != scope.provider_identity
            or scope.account_id not in connection.selected_accounts
        ):
            raise ReplayIntegrityError("provider connection is outside replay scope")

    def _normalizer(self, scope: ReplayScope):
        plugin = self._plugin(scope.provider_identity)
        from connectors.provider_runtime.normalization import NormalizationEngine

        engine = NormalizationEngine(plugin)
        normalizer = engine._normalizer()
        if (
            normalizer is None
            or str(getattr(normalizer, "normalizer_version", "")) != scope.normalizer_version
        ):
            raise ReplayIntegrityError("pinned provider normalizer version is unavailable")
        return engine

    def _bridge(self):
        if self.bridge is None:
            from connectors.provider_runtime.bridge import EventBridge

            self.bridge = EventBridge()
        return self.bridge

    async def enqueue(
        self, scope: ReplayScope, *, run_key: str, actor_ref: str, decision_ref: str
    ) -> dict:
        """Create an internal-only durable job; no API or RBAC claim is made."""
        if not run_key.strip() or not actor_ref.strip() or not decision_ref.strip():
            raise ValueError("replay run, actor, and decision references are required")
        from config.settings import settings

        if not settings.provider_runtime.enabled:
            raise RuntimeError("provider runtime is disabled; replay handler is unavailable")
        await self._validate_connection(scope)
        self._normalizer(scope)
        if self.jobs is None:
            from config.settings import Environment, settings
            from repositories.repos import get_pool
            from workers.jobs.service import JobsService

            if (
                settings.env in (Environment.STAGING, Environment.PRODUCTION)
                and await get_pool() is None
            ):
                raise RuntimeError("durable jobs database is unavailable for provider replay")
            self.jobs = JobsService()
        payload = {
            "scope": scope.model_dump(mode="json"),
            "cursor": None,
            "counts": {
                "scanned": 0,
                "candidates": 0,
                "accepted": 0,
                "skipped": 0,
                "dry_run_admitted": 0,
            },
            "decision_ref": decision_ref,
        }
        # JobsRepository requeues a FAILED row for a repeated idempotency key
        # before returning it. Bind the key to the exact scope and audit
        # references so a caller cannot accidentally requeue work recorded
        # under another operator or decision.
        scope_key = json.dumps(payload["scope"], sort_keys=True, separators=(",", ":"))
        idempotency_key = hashlib.sha256(
            json.dumps(
                [run_key.strip(), scope_key, actor_ref.strip(), decision_ref.strip()],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        job = await self.jobs.enqueue(
            scope.tenant_id,
            PROVIDER_REPLAY_JOB_TYPE,
            payload,
            idempotency_key=idempotency_key,
            requested_by=actor_ref,
            max_attempts=3,
        )
        if (
            job.get("payload", {}).get("scope") != payload["scope"]
            or job.get("payload", {}).get("decision_ref") != decision_ref
            or job.get("requested_by") != actor_ref
        ):
            raise ReplayIntegrityError(
                "replay run key was reused with different scope or audit references"
            )
        return job

    async def run_window(
        self,
        scope: ReplayScope,
        *,
        cursor: ReplayCursor | None,
        counts: dict[str, int],
        checkpoint: Checkpoint,
        heartbeat: Heartbeat,
    ) -> dict[str, Any]:
        """Resume a job from its durable cursor; emit no graph or pull writes."""
        await self._validate_connection(scope)
        normalizer = self._normalizer(scope)
        if cursor is not None and not (
            scope.ingested_from <= cursor.created_at < scope.ingested_before
        ):
            raise ReplayIntegrityError("replay cursor is outside the closed window")
        totals = {
            key: int(counts.get(key, 0))
            for key in ("scanned", "candidates", "accepted", "skipped", "dry_run_admitted")
        }
        if (
            any(value < 0 for value in totals.values())
            or totals["scanned"] > scope.max_records
            or (cursor is None and totals["scanned"] != 0)
            or (cursor is not None and totals["scanned"] == 0)
        ):
            raise ReplayIntegrityError("replay checkpoint counts are invalid")
        current = cursor
        while totals["scanned"] < scope.max_records:
            if not await heartbeat():
                raise ReplayIntegrityError("provider replay worker lease was lost")
            remaining = scope.max_records - totals["scanned"]
            page = await self.reader.page(scope, current, min(PAGE_SIZE, remaining + 1))
            if not page:
                return _result("completed", scope, current, totals)
            for item in page[:remaining]:
                _verify_raw_scope(scope, item.record)
                try:
                    await self._rights().authorize_replay(item.record)
                except Exception as exc:
                    # Keep grant, tenant, and source details out of job errors.
                    raise ReplayIntegrityError(
                        "raw provider rights admission is no longer valid"
                    ) from exc
                result = normalizer.run([item.record])
                if result.dropped:
                    raise ReplayIntegrityError("normalizer dropped a stored raw record")
                if not result.events and result.skipped != 1:
                    raise ReplayIntegrityError("normalizer returned no event or explicit skip")
                if result.normalizer_version != scope.normalizer_version:
                    raise ReplayIntegrityError("normalizer version changed during replay")
                event_ids: set[str] = set()
                for event in result.events:
                    if (
                        event.tenant_id != scope.tenant_id
                        or event.provider_identity != scope.provider_identity
                        or event.account_id != scope.account_id
                        or event.source_record_id != item.record.record_id
                        or event.schema_version != scope.event_schema_version
                        or not event.event_id
                        or event.event_id in event_ids
                    ):
                        raise ReplayIntegrityError(
                            "normalized event escaped pinned replay contract"
                        )
                    event_ids.add(event.event_id)
                if scope.dry_run:
                    admitted = 0
                    for event in result.events:
                        if await self._bridge()._consent_allows(scope.tenant_id, event):
                            admitted += 1
                    accepted = 0
                else:
                    # The bridge owns ingress consent and atomic canonical
                    # Bronze/outbox writes; a duplicate from a retry is safe.
                    accepted = await self._bridge().ingest_events(scope.tenant_id, result.events)
                    admitted = 0
                totals["scanned"] += 1
                totals["candidates"] += len(result.events)
                totals["accepted"] += accepted
                totals["skipped"] += result.skipped
                totals["dry_run_admitted"] += admitted
                if not await heartbeat():
                    raise ReplayIntegrityError("provider replay worker lease was lost")
                await checkpoint(item.cursor, totals)
                current = item.cursor
            if len(page) > remaining:
                return _result("limit_reached", scope, current, totals)

        # Probe one more row when the cap falls exactly on a page boundary.
        extra = await self.reader.page(scope, current, 1)
        status = "limit_reached" if extra else "completed"
        return _result(status, scope, current, totals)


def _result(
    status: str, scope: ReplayScope, cursor: ReplayCursor | None, counts: dict[str, int]
) -> dict[str, Any]:
    metrics.increment(
        "provider_raw_replay_runs_total",
        labels={"status": status, "dry_run": str(scope.dry_run).lower()},
    )
    return {
        "status": status,
        **counts,
        "cursor": cursor.model_dump(mode="json") if cursor else None,
    }


def register_provider_raw_replay_handler() -> None:
    """Register one internal-only jobs-platform handler when runtime is enabled."""
    from config.settings import settings
    from workers.jobs.handlers import HANDLER_REGISTRY, JobOutcome, register_handler

    if not settings.provider_runtime.enabled or PROVIDER_REPLAY_JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(PROVIDER_REPLAY_JOB_TYPE, tenant_invocable=False)
    async def _handle(payload, ctx):
        from repositories.jobs_repo import get_jobs_repository

        scope = ReplayScope.model_validate(payload.get("scope"))
        if scope.tenant_id != ctx.tenant_id:
            return JobOutcome(status="failed", result={}, error="replay job tenant mismatch")
        cursor = ReplayCursor.model_validate(payload["cursor"]) if payload.get("cursor") else None
        repo = get_jobs_repository()

        async def checkpoint(next_cursor: ReplayCursor, counts: dict[str, int]) -> None:
            next_payload = {
                **payload,
                "cursor": next_cursor.model_dump(mode="json"),
                "counts": dict(counts),
            }
            updated = await repo.update_payload(ctx.job_id, next_payload, worker_id=ctx.worker_id)
            if updated is None:
                raise ReplayIntegrityError("provider replay checkpoint lease was lost")
            payload.update(next_payload)

        result = await ProviderRawReplayService().run_window(
            scope,
            cursor=cursor,
            counts=payload.get("counts") or {},
            checkpoint=checkpoint,
            heartbeat=ctx.heartbeat,
        )
        await ctx.emit_event(
            "provider.raw_replay.progress",
            {
                key: result[key]
                for key in (
                    "status",
                    "scanned",
                    "candidates",
                    "accepted",
                    "skipped",
                    "dry_run_admitted",
                )
            },
        )
        return JobOutcome(
            status="succeeded" if result["status"] == "completed" else "partially_succeeded",
            result=result,
        )


__all__ = [
    "PROVIDER_REPLAY_JOB_TYPE",
    "ProviderRawReplayReader",
    "ProviderRawReplayService",
    "ReplayCursor",
    "ReplayIntegrityError",
    "ReplayRawRow",
    "ReplayScope",
    "register_provider_raw_replay_handler",
]
