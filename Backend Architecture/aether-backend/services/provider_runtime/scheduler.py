"""Pull scheduler — runs provider syncs through the provider-neutral runtime.

Mirrors the canonical ordering of ``ConnectorService.sync()``:

    open SyncRun ledger → pull().fetch → raw store → normalize → bridge →
    advance cursor → complete_run → meter

Zero returned records is a SUCCESS **only when the provider actually returned
none**; a provider failure marks the sync run failed with a typed error and is
never a silent empty success. The sync-run ledger is best-effort (a truthful
record, never a sync gate), exactly like the legacy connector service.

:class:`PullScheduler` is the engine Team D's ``ConnectionOrchestrator.run_sync``
delegates to (``scheduler.run(connection=..., since=...)``); :meth:`run_sync` is
the spec-named entry point and :meth:`run` is the D↔E-compatible alias.

Team seams consumed here (constructor-injected so tests pass lightweight fakes;
defaults resolve lazily from the team-owned modules):

* ``services.provider_runtime.registry`` — ``registry.get(identity_key)``
  returning a ``ProviderPlugin`` or ``None`` (None ⇒ :class:`ProviderNotInstalled`).
* ``services.provider_runtime.credential_broker`` — ``CredentialBroker.reveal``.
* ``services.provider_runtime.raw_store`` — ``RawProviderRecordStore.ingest``.
* ``services.provider_runtime.normalization`` — ``NormalizationEngine(plugin).run``.
* ``services.provider_runtime.bridge`` — ``EventBridge.ingest_events(tenant_id, events)``.
* ``services.provider_runtime.connection`` — the ``ProviderConnection`` object.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from services.comms.sync_runs import SyncRun, SyncRunService
from services.integrations.connectors.base import now_iso
from services.provider_runtime.errors import (
    ProviderNotInstalled,
    ProviderPullFailed,
)
from services.provider_runtime.metering import meter as _default_meter
from services.provider_runtime.rate_limit import RateLimitCoordinator
from services.provider_runtime.retry import RetryCoordinator
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import AetherEvent, ReadBatch
from shared.integration_contracts.results import AdapterResult, AdapterStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_account_id(connection: Any) -> str:
    """First selected account (Team D's ProviderConnection shape)."""
    selected = getattr(connection, "selected_accounts", None) or []
    return str(selected[0]) if selected else ""


class ProviderCursorRepository(BaseRepository):
    """Durable cursor position per (tenant, connection, provider_identity)."""

    def __init__(self) -> None:
        super().__init__("provider_cursors")

    @staticmethod
    def _cursor_id(tenant_id: str, connection_id: str, provider_identity: str) -> str:
        return f"{tenant_id}:{connection_id}:{provider_identity}"

    async def get_cursor(
        self, tenant_id: str, connection_id: str, provider_identity: str
    ) -> Optional[dict[str, Any]]:
        return await self.find_by_id(
            self._cursor_id(tenant_id, connection_id, provider_identity)
        )

    async def set_cursor(
        self,
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        cursor_value: str,
        event_count: int = 0,
    ) -> dict[str, Any]:
        cursor_id = self._cursor_id(tenant_id, connection_id, provider_identity)
        now = _now_iso()
        return await self.insert(cursor_id, {
            "cursor_id": cursor_id,
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "provider_identity": provider_identity,
            "cursor_value": cursor_value,
            "last_synced_at": now,
            "last_event_count": event_count,
            "updated_at": now,
        })


class PullScheduler:
    """Run a sync: open SyncRun ledger → paginate pull().fetch → raw store →
    normalize → bridge → advance cursor → complete_run → meter."""

    # Defensive page cap: a misbehaving provider that never clears ``has_more``
    # must not loop forever. A legitimately huge sync stays under this in
    # practice; crossing it is a provider contract violation.
    MAX_PAGES = 500

    def __init__(
        self,
        *,
        raw_store: Any = None,
        normalization: Any = None,
        bridge: Any = None,
        cursors: Any = None,
        retry: Any = None,
        rate_limit: Any = None,
        broker: Any = None,
        registry: Any = None,
        connections: Any = None,
        sync_runs: Any = None,
        meters: Any = None,
    ) -> None:
        self.raw_store = raw_store
        self.normalization = normalization
        self.bridge = bridge
        self.cursors = cursors or ProviderCursorRepository()
        self.retry = retry or RetryCoordinator()
        self.rate_limit = rate_limit or RateLimitCoordinator()
        self.broker = broker
        self.registry = registry
        self.connections = connections
        self.sync_runs = sync_runs
        self.meter = meters or _default_meter

    # ── Seam defaults (resolved lazily so imports stay decoupled) ──────────

    def _registry(self) -> Any:
        if self.registry is None:
            from services.provider_runtime.registry import registry
            self.registry = registry
        return self.registry

    def _broker(self) -> Any:
        if self.broker is None:
            from services.provider_runtime.credential_broker import CredentialBroker
            self.broker = CredentialBroker()
        return self.broker

    def _connections(self) -> Any:
        if self.connections is None:
            from services.provider_runtime.connection import (
                ProviderConnectionRepository,
            )
            self.connections = ProviderConnectionRepository()
        return self.connections

    def _raw_store(self) -> Any:
        if self.raw_store is None:
            from services.provider_runtime.raw_store import RawProviderRecordStore
            self.raw_store = RawProviderRecordStore()
        return self.raw_store

    def _normalization_engine(self, plugin: Any) -> Any:
        if self.normalization is not None:
            return self.normalization
        from services.provider_runtime.normalization import NormalizationEngine
        return NormalizationEngine(plugin)

    def _bridge(self) -> Any:
        if self.bridge is None:
            from services.provider_runtime.bridge import EventBridge
            self.bridge = EventBridge()
        return self.bridge

    # ── Run ────────────────────────────────────────────────────────────────

    async def run(
        self,
        connection: Any,
        *,
        since: Optional[str] = None,
    ) -> SyncRun | dict[str, Any]:
        """D↔E-compatible alias — Team D's ``ConnectionOrchestrator`` calls
        ``PullScheduler().run(connection=..., since=...)``."""
        return await self.run_sync(connection, since=since)

    async def run_sync(
        self,
        connection: Any,
        *,
        since: Optional[str] = None,
    ) -> SyncRun | dict[str, Any]:
        """connection: ProviderConnection (Team D).

        Ordering mirrors ConnectorService.sync(). Returns the SyncRun returned
        by SyncRunService.complete_run (its real type), or a dict summary if the
        ledger was unavailable (best-effort ledger, never a sync gate).
        """
        tenant_id = connection.tenant_id
        connection_id = connection.connection_id
        provider_identity = connection.provider_identity

        # Resolve the plugin once. A missing plugin is a hard error — there is
        # nothing honest we can sync against.
        plugin = self._resolve_plugin(provider_identity)
        pull = plugin.pull() if plugin is not None else None
        if pull is None:
            detail = (
                f"provider {provider_identity} does not implement the pull capability"
            )
            return await self._fail_run(
                connection, None, None,
                error_code="provider_pull_not_supported", detail=detail,
            )

        # Open a durable sync-run ledger entry BEFORE provider work (mirror
        # ConnectorService.sync §12.4). Best-effort: never a sync gate.
        run_service = self.sync_runs or SyncRunService()
        sync_run: Optional[SyncRun] = None
        prev_cursor: Optional[dict[str, Any]] = None
        try:
            prev_cursor = await self.cursors.get_cursor(
                tenant_id, connection_id, provider_identity
            )
            sync_run = await run_service.open_run(
                tenant_id=tenant_id,
                connector_instance_id=connection_id,
                provider=provider_identity,
                mode="incremental" if since else "backfill",
                requested_window=since,
                cursor_before=(prev_cursor or {}).get("cursor_value"),
                triggered_by="system",
            )
        except Exception as exc:  # pragma: no cover - ledger must never break sync
            self._warn(f"provider sync-run open failed tenant={tenant_id}: {exc}")

        # Resolve the credential once (a sync's credential does not change
        # across pages). Missing/None is passed through — the adapter classifies
        # it (typically UNAUTHORIZED), which fails the run with a typed error.
        credential = await self._resolve_credential(connection)
        context = AcquisitionContext(
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            connection_id=connection_id,
            account_id=_connection_account_id(connection),
            config=dict(getattr(connection, "config", None) or {}),
            credential=credential,
        )
        normalization = self._normalization_engine(plugin)

        cursor: Optional[str] = since or (prev_cursor or {}).get("cursor_value")
        page = 0
        retry_count = 0
        rate_limit_events = 0
        records_received = 0
        events_published = 0
        last_cursor: Optional[str] = cursor
        terminal: Optional[ProviderPullFailed] = None

        try:
            while True:
                page += 1
                if page > self.MAX_PAGES:
                    raise _pull_failed(
                        f"provider {provider_identity} exceeded {self.MAX_PAGES} "
                        "pages without clearing has_more (sync aborted)",
                        provider_identity=provider_identity,
                        error_code="provider_pull_failed",
                        detail="pagination cap exceeded (has_more never cleared)",
                    )
                result, page_retries, page_rate_limits = await self._fetch_with_retry(
                    pull, context, cursor,
                    tenant_id=tenant_id,
                    provider_identity=provider_identity,
                    connection_id=connection_id,
                )
                retry_count += page_retries
                rate_limit_events += page_rate_limits
                if result.status != AdapterStatus.OK:
                    terminal = self._classify_failure(
                        provider_identity, result, retry_count=retry_count,
                    )
                    break
                batch = self._batch_of(result)
                records = list(batch.records or [])
                records_received += len(records)

                # raw store → normalize → bridge (each best-effort, never
                # breaks the sync — mirroring bronze_connectors.ingest).
                try:
                    await self._raw_store().ingest(records)
                except Exception as exc:  # pragma: no cover - best-effort
                    self._warn(
                        f"provider raw ingest failed tenant={tenant_id} "
                        f"provider={provider_identity}: {exc}"
                    )
                events = await self._normalize_records(normalization, records)
                if events:
                    try:
                        await self._bridge().ingest_events(tenant_id, events)
                    except Exception as exc:  # pragma: no cover - best-effort
                        self._warn(
                            f"provider event bridge failed tenant={tenant_id} "
                            f"provider={provider_identity}: {exc}"
                        )
                events_published += len(events)

                last_cursor = batch.next_cursor or last_cursor
                if not batch.has_more:
                    break
                cursor = batch.next_cursor
        except ProviderPullFailed as exc:
            terminal = exc
        except Exception as exc:  # pragma: no cover - defensive: adapter raised
            # Any untyped exception from the provider boundary is a sync
            # failure. Convert it to a typed ProviderPullFailed so the ledger
            # closes as failed and the caller gets a typed error — mirror the
            # legacy connector's `except Exception -> status="failed"`, never a
            # silent empty success nor a hung open run.
            self._warn(
                f"provider pull raised tenant={tenant_id} "
                f"provider={provider_identity}: {exc!r}"
            )
            terminal = _pull_failed(
                f"provider pull raised for {provider_identity}",
                provider_identity=provider_identity,
                error_code="provider_pull_failed",
                detail=str(exc)[:500],
            )

        if terminal is not None:
            return await self._fail_run(
                connection, run_service, sync_run,
                error_code=terminal.details.get("error_code") or "provider_pull_failed",
                detail=terminal.details.get("detail") or str(terminal),
                retry_count=retry_count,
                rate_limit_events=rate_limit_events,
                pages=page,
            )

        # Success: advance cursor, close the ledger with honest counts, record
        # the connection's last_successful_sync_at, and meter.
        try:
            await self.cursors.set_cursor(
                tenant_id, connection_id, provider_identity,
                cursor_value=last_cursor or "",
                event_count=records_received,
            )
        except Exception as exc:  # pragma: no cover - best-effort, never break sync
            self._warn(f"provider cursor upsert failed tenant={tenant_id}: {exc}")

        completed = sync_run
        if sync_run is not None and run_service is not None:
            try:
                completed = await run_service.complete_run(
                    sync_run,
                    status="completed",
                    cursor_after=last_cursor,
                    counts={
                        "records_received": records_received,
                        "pages_requested": page,
                        "retry_count": retry_count,
                        "rate_limit_events": rate_limit_events,
                        "facts_written": events_published,
                    },
                )
            except Exception as exc:  # pragma: no cover - best-effort
                self._warn(
                    f"provider sync-run close(completed) failed tenant={tenant_id}: {exc}"
                )
        await self._record_connection_success(connection, last_sync_at=now_iso())
        await self.meter(
            tenant_id, "provider.sync.completed", connection_id, "provider_runtime",
        )
        if completed is not None:
            return completed
        return {
            "provider_identity": provider_identity,
            "connection_id": connection_id,
            "status": "completed",
            "records_received": records_received,
            "events_published": events_published,
            "cursor_after": last_cursor,
        }

    # ── Internals ───────────────────────────────────────────────────────────

    def _resolve_plugin(self, provider_identity: str) -> Any:
        plugin = self._registry().get(provider_identity)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {provider_identity} is not installed in the runtime registry"
            )
        return plugin

    async def _resolve_credential(self, connection: Any) -> Any:
        credential_ref = getattr(connection, "credential_ref", None)
        if not credential_ref:
            return None
        try:
            return await self._broker().reveal(
                connection.tenant_id, credential_ref,
            )
        except Exception as exc:  # pragma: no cover - credential is best-effort
            self._warn(
                f"provider credential resolution failed tenant={connection.tenant_id}: {exc}"
            )
            return None

    async def _fetch_with_retry(
        self,
        pull: Any,
        context: AcquisitionContext,
        cursor: Optional[str],
        *,
        tenant_id: str,
        provider_identity: str,
        connection_id: str,
    ) -> tuple[AdapterResult[Any], int, int]:
        """Fetch one page, retrying RATE_LIMITED / RETRYABLE_ERROR with backoff.

        Returns ``(result, retries_used, rate_limit_hits)``.
        """
        attempt = 0
        retries = 0
        rate_limit_hits = 0
        while True:
            result = await pull.fetch(context, cursor=cursor, limit=None)
            if result.status == AdapterStatus.OK:
                return result, retries, rate_limit_hits
            if (
                result.status in (AdapterStatus.RETRYABLE_ERROR, AdapterStatus.RATE_LIMITED)
                and self.retry.should_retry(result.status, attempt=attempt)
            ):
                if result.status == AdapterStatus.RATE_LIMITED:
                    rate_limit_hits += 1
                    await self.rate_limit.on_rate_limited(
                        tenant_id=tenant_id,
                        identity_key=provider_identity,
                        info=result.rate_limit,
                    )
                delay_ms = self.retry.delay_ms(attempt, info=result.rate_limit)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)
                retries += 1
                attempt += 1
                continue
            return result, retries, rate_limit_hits

    @staticmethod
    def _batch_of(result: AdapterResult[Any]) -> ReadBatch:
        batch = result.data
        if isinstance(batch, ReadBatch):
            return batch
        if batch is None:
            return ReadBatch(records=[], next_cursor=None, has_more=False)
        return ReadBatch(**batch)  # type: ignore[arg-type]

    async def _normalize_records(
        self, normalization: Any, records: list[Any],
    ) -> list[AetherEvent]:
        if not records:
            return []
        result = normalization.run(records)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, (list, tuple)):
            return list(result)
        events = getattr(result, "events", None)
        if events is not None:
            return list(events)
        return []

    @staticmethod
    def _classify_failure(
        provider_identity: str,
        result: AdapterResult[Any],
        *,
        retry_count: int,
    ) -> ProviderPullFailed:
        status = result.status
        if status == AdapterStatus.UNAUTHORIZED:
            code, msg = "provider_unauthorized", "provider authentication failed"
        elif status == AdapterStatus.PERMANENT_ERROR:
            code, msg = "provider_permanent_error", "provider permanent error"
        elif status == AdapterStatus.NOT_SUPPORTED:
            code, msg = "provider_pull_not_supported", "pull capability not supported"
        elif status == AdapterStatus.RATE_LIMITED:
            code, msg = "provider_rate_limited", "provider rate limit not cleared by retries"
        else:
            code, msg = "provider_pull_failed", "provider pull failed"
        detail = result.error_code or ""
        return _pull_failed(
            f"{msg} for {provider_identity} after {retry_count} retries"
            + (f": {detail}" if detail else ""),
            provider_identity=provider_identity,
            error_code=code,
            detail=detail or msg,
        )

    async def _fail_run(
        self,
        connection: Any,
        run_service: Any,
        sync_run: Optional[SyncRun],
        *,
        error_code: str,
        detail: str,
        retry_count: int = 0,
        rate_limit_events: int = 0,
        pages: int = 0,
    ) -> SyncRun | dict[str, Any]:
        """Close the ledger as failed, record the connection error, raise."""
        if sync_run is not None and run_service is not None:
            try:
                await run_service.complete_run(
                    sync_run,
                    status="failed",
                    safe_error_code=error_code,
                    safe_error_detail=detail[:500],
                    counts={
                        "pages_requested": pages,
                        "retry_count": retry_count,
                        "rate_limit_events": rate_limit_events,
                    },
                )
            except Exception as exc:  # pragma: no cover - best-effort
                self._warn(
                    f"provider sync-run close(failed) failed "
                    f"tenant={connection.tenant_id}: {exc}"
                )
        await self._record_connection_error(
            connection, error_code=error_code, detail=detail,
        )
        raise _pull_failed(
            f"provider sync failed for {connection.provider_identity}: {detail}",
            provider_identity=connection.provider_identity,
            error_code=error_code,
            detail=detail,
        )

    async def _record_connection_success(self, connection: Any, *, last_sync_at: str) -> None:
        """Record last_successful_sync_at in place + best-effort persist.

        Persists through the lazy ``_connections()`` resolver so the real
        orchestration path (``PullScheduler()`` with no injected repo, which is
        exactly what ``ConnectionOrchestrator.run_sync`` constructs) still writes
        the timestamp to the connection store — otherwise the health engine
        would read ``None`` forever after a successful sync.
        """
        try:
            connection.last_successful_sync_at = last_sync_at  # type: ignore[attr-defined]
            connection.updated_at = last_sync_at  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - read-only connection is fine
            pass
        try:
            await self._connections().upsert(connection)
        except Exception as exc:  # pragma: no cover - best-effort
            self._warn(
                f"provider connection success record failed "
                f"tenant={connection.tenant_id}: {exc}"
            )

    async def _record_connection_error(
        self, connection: Any, *, error_code: str, detail: str,
    ) -> None:
        """Best-effort in-place error counters.

        ``ProviderConnection`` (extra="forbid") has no error fields, so this is a
        no-op for the real model — error health signals live in the sync-run
        ledger (safe_error_code/safe_error_detail) and the health engine reads
        defaults of 0/None.
        """
        try:
            connection.error_count = int(getattr(connection, "error_count", 0)) + 1  # type: ignore[attr-defined]
            connection.last_error = detail[:500]  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - read-only / forbid model is fine
            pass

    def _warn(self, message: str) -> None:
        from shared.logger.logger import get_logger as _get_logger
        _get_logger("aether.provider_runtime.scheduler").warning(message)


def _pull_failed(
    message: str,
    *,
    provider_identity: str,
    error_code: str,
    detail: str,
) -> ProviderPullFailed:
    """Build a typed pull failure carrying Team D's ``details`` dict."""
    return ProviderPullFailed(
        message,
        details={
            "provider_identity": provider_identity,
            "error_code": error_code,
            "detail": detail,
        },
    )


__all__ = ["ProviderCursorRepository", "PullScheduler"]
