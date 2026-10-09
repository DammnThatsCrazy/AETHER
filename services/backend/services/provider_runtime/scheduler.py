"""Pull scheduler — runs provider syncs through the provider-neutral runtime.

Mirrors the canonical ordering of ``ConnectorService.sync()``:

    open SyncRun ledger → pull().fetch → raw store → normalize → bridge →
    advance cursor → complete_run → meter

Zero returned records is a SUCCESS **only when the provider actually returned
none**; a provider failure marks the sync run failed with a typed error and is
never a silent empty success. Raw persistence, normalization, event persistence,
and cursor advancement fail closed. The sync-run ledger is best-effort.

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
import hashlib
import inspect
import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from services.comms.sync_runs import SyncRun, SyncRunService
from services.integrations.connectors.base import now_iso
from services.provider_runtime.connection import SYNC_ELIGIBLE_STATES
from services.provider_runtime.errors import (
    ConnectionStateViolation,
    ProviderNotInstalled,
    ProviderPullFailed,
)
from services.responsiveness.service import get_responsiveness_service
from services.provider_runtime.metering import meter as _default_meter
from services.provider_runtime.rate_limit import RateLimitCoordinator
from services.provider_runtime.retry import RetryCoordinator
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import AetherEvent, ReadBatch
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.results import AdapterResult, AdapterStatus
from shared.integration_contracts.streams import StreamDescriptor

_MAX_REQUESTED_STREAM_IDS = 32
_MAX_REQUESTED_STREAM_ID_LENGTH = 128


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_account_id(connection: Any) -> str:
    """First selected account (Team D's ProviderConnection shape)."""
    selected = getattr(connection, "selected_accounts", None) or []
    return str(selected[0]) if selected else ""


class ProviderCursorRepository(BaseRepository):
    """Durable cursor position, with an additive account/stream scoped key.

    The three-part key remains readable for existing v1 connections. New
    account/stream callers must supply both dimensions and get an isolated v2
    cursor; no implicit migration of the old cursor is performed.
    """

    def __init__(self) -> None:
        super().__init__("provider_cursors")

    @staticmethod
    def _cursor_id(
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        account_id: Optional[str] = None,
        stream_id: Optional[str] = None,
    ) -> str:
        if account_id is None and stream_id is None:
            return f"{tenant_id}:{connection_id}:{provider_identity}"
        if account_id is None or not stream_id:
            raise ValueError("account_id and stream_id are both required for a scoped cursor")
        material = json.dumps(
            [tenant_id, connection_id, provider_identity, account_id, stream_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "v2:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def get_cursor(
        self,
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        *,
        account_id: Optional[str] = None,
        stream_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        return await self.find_by_id(
            self._cursor_id(tenant_id, connection_id, provider_identity, account_id, stream_id)
        )

    async def set_cursor(
        self,
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        cursor_value: str,
        event_count: int = 0,
        *,
        account_id: Optional[str] = None,
        stream_id: Optional[str] = None,
    ) -> dict[str, Any]:
        cursor_id = self._cursor_id(
            tenant_id, connection_id, provider_identity, account_id, stream_id
        )
        now = _now_iso()
        return await self.insert(
            cursor_id,
            {
                "cursor_id": cursor_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "provider_identity": provider_identity,
                "account_id": account_id,
                "stream_id": stream_id,
                "cursor_value": cursor_value,
                "last_synced_at": now,
                "last_event_count": event_count,
                "updated_at": now,
            },
        )


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
        accounts: Any = None,
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
        self.accounts = accounts
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

    def _accounts(self) -> Any:
        if self.accounts is None:
            from services.provider_runtime.acquisition import ProviderAccountRepository

            self.accounts = ProviderAccountRepository()
        return self.accounts

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
        stream_id: Optional[str] = None,
        stream_ids: Optional[list[str]] = None,
    ) -> SyncRun | dict[str, Any]:
        """D↔E-compatible alias — Team D's ``ConnectionOrchestrator`` calls
        ``PullScheduler().run(connection=..., since=...)``."""
        return await self.run_sync(
            connection,
            since=since,
            stream_id=stream_id,
            stream_ids=stream_ids,
        )

    async def run_sync(
        self,
        connection: Any,
        *,
        since: Optional[str] = None,
        stream_id: Optional[str] = None,
        stream_ids: Optional[list[str]] = None,
        _stream_descriptor: Optional[StreamDescriptor] = None,
        _selected_account_id: Optional[str] = None,
    ) -> SyncRun | dict[str, Any]:
        """connection: ProviderConnection (Team D).

        Ordering mirrors ConnectorService.sync(). Returns the SyncRun returned
        by SyncRunService.complete_run (its real type), or a dict summary if the
        ledger was unavailable (best-effort ledger, never a sync gate).
        """
        self._require_sync_eligible(connection)
        tenant_id = connection.tenant_id
        connection_id = connection.connection_id
        provider_identity = connection.provider_identity

        requested_stream_ids = list(stream_ids or ())
        if stream_id is not None:
            if requested_stream_ids:
                return await self._fail_run(
                    connection,
                    self.sync_runs or SyncRunService(),
                    None,
                    error_code="provider_stream_selection_invalid",
                    detail="use either stream_id or stream_ids, not both",
                )
            requested_stream_ids = [stream_id]
        selection_error: Optional[tuple[str, str]] = None
        if len(requested_stream_ids) > _MAX_REQUESTED_STREAM_IDS:
            selection_error = (
                "provider_stream_selection_too_large",
                f"at most {_MAX_REQUESTED_STREAM_IDS} stream IDs may be selected",
            )
        elif any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > _MAX_REQUESTED_STREAM_ID_LENGTH
            for value in requested_stream_ids
        ):
            selection_error = (
                "provider_stream_selection_invalid",
                "stream IDs must be non-empty and at most 128 characters",
            )
        elif len(set(requested_stream_ids)) != len(requested_stream_ids):
            selection_error = (
                "provider_stream_selection_duplicate",
                "stream_ids must not contain duplicates",
            )
        if selection_error is not None:
            error_code, detail = selection_error
            return await self._fail_run(
                connection,
                self.sync_runs or SyncRunService(),
                None,
                error_code=error_code,
                detail=detail,
            )

        # Resolve the plugin once. A missing plugin is a hard error — there is
        # nothing honest we can sync against.
        plugin = self._resolve_plugin(provider_identity)

        # Manifests with no declared streams retain the v1 capability-level
        # path below. Explicit stream manifests use isolated per-account,
        # per-stream cursors and adapter contexts.
        if _stream_descriptor is None:
            manifest_fn = getattr(plugin, "manifest", None)
            manifest = manifest_fn() if callable(manifest_fn) else None
            declared_streams = tuple(getattr(manifest, "streams", ()) or ())
            if declared_streams:
                return await self._run_declared_streams(
                    connection,
                    manifest=manifest,
                    streams=declared_streams,
                    since=since,
                    requested_stream_ids=tuple(requested_stream_ids),
                )
            if requested_stream_ids:
                return await self._fail_run(
                    connection,
                    None,
                    None,
                    error_code="provider_stream_not_found",
                    detail="provider manifest does not declare streams",
                )

        pull = plugin.pull() if plugin is not None else None
        if pull is None:
            detail = f"provider {provider_identity} does not implement the pull capability"
            return await self._fail_run(
                connection,
                None,
                None,
                error_code="provider_pull_not_supported",
                detail=detail,
            )

        # Stream manifests fan out into nested per-account/per-stream calls.
        # Their outer dispatcher owns the single initial-sync transition.
        lifecycle_started = _stream_descriptor is not None

        scoped_stream_id = _stream_descriptor.stream_id if _stream_descriptor else None
        account_id = (
            _selected_account_id
            if _selected_account_id is not None
            else _connection_account_id(connection)
        )

        # Open a durable sync-run ledger entry BEFORE provider work (mirror
        # ConnectorService.sync §12.4). Best-effort: never a sync gate.
        run_service = self.sync_runs or SyncRunService()
        sync_run: Optional[SyncRun] = None
        prev_cursor: Optional[dict[str, Any]] = None
        try:
            if _stream_descriptor is None:
                prev_cursor = await self.cursors.get_cursor(
                    tenant_id, connection_id, provider_identity
                )
            else:
                prev_cursor = await self.cursors.get_cursor(
                    tenant_id,
                    connection_id,
                    provider_identity,
                    account_id=account_id,
                    stream_id=scoped_stream_id,
                )
            sync_run = await run_service.open_run(
                tenant_id=tenant_id,
                connector_instance_id=connection_id,
                provider=provider_identity,
                provider_account_id=_connection_account_id(connection),
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
        config = dict(getattr(connection, "config", None) or {})
        if (
            provider_identity == "shopify.admin.orders_read"
            and str(config.get("orders_api") or "rest").lower() == "graphql"
        ):
            selected_id = account_id
            selected = (
                await self._accounts().find(f"{connection_id}:{selected_id}")
                if selected_id
                else None
            )
            if (
                selected is None
                or selected.account_id != f"{connection_id}:{selected_id}"
                or selected.tenant_id != tenant_id
                or selected.connection_id != connection_id
                or selected.provider_identity != provider_identity
                or not selected.external_id
                or selected.external_id != selected.metadata.get("shop_gid")
                or selected.metadata.get("source_account_realm")
                != config.get("source_account_realm")
                or config.get("source_account_realm") not in ("live", "test")
                or not getattr(connection, "last_verified_at", None)
            ):
                return await self._fail_run(
                    connection,
                    run_service,
                    sync_run,
                    error_code="provider_account_unverified",
                    detail="Selected Shopify GraphQL shop identity is not verified",
                )
            # This value is inserted only from the tenant-scoped persisted
            # account. It is never trusted from connection config or user input.
            config["_verified_shop_gid"] = selected.external_id
        context = AcquisitionContext(
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            connection_id=connection_id,
            account_id=account_id,
            stream_id=scoped_stream_id,
            config=config,
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
        _first_sample_emitted = False
        _sync_started_at = datetime.now(timezone.utc).isoformat()

        try:
            if _stream_descriptor is None:
                lifecycle_started = True
                await self._record_connection_sync_started(connection)
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
                    pull,
                    context,
                    cursor,
                    tenant_id=tenant_id,
                    provider_identity=provider_identity,
                    connection_id=connection_id,
                )
                retry_count += page_retries
                rate_limit_events += page_rate_limits
                if result.status != AdapterStatus.OK:
                    terminal = self._classify_failure(
                        provider_identity,
                        result,
                        retry_count=retry_count,
                    )
                    break
                batch = self._batch_of(result)
                records = list(batch.records or [])
                if _stream_descriptor is not None:
                    try:
                        records = self._bind_stream_raw_records(
                            records,
                            tenant_id=tenant_id,
                            provider_identity=provider_identity,
                            connection_id=connection_id,
                            account_id=account_id,
                            stream_id=scoped_stream_id or "",
                        )
                    except ValueError as exc:
                        raise _pull_failed(
                            "provider returned a raw record outside its stream scope",
                            provider_identity=provider_identity,
                            error_code="provider_raw_scope_mismatch",
                            detail=str(exc),
                        ) from exc
                else:
                    try:
                        records = self._bind_streamless_raw_records(
                            records,
                            tenant_id=tenant_id,
                            provider_identity=provider_identity,
                            connection_id=connection_id,
                            account_id=account_id,
                        )
                    except ValueError as exc:
                        raise _pull_failed(
                            "provider returned a raw record outside its selected account scope",
                            provider_identity=provider_identity,
                            error_code="provider_raw_scope_mismatch",
                            detail=str(exc),
                        ) from exc
                records_received += len(records)

                # Persist before normalization. Never advance a cursor past a
                # page whose raw or canonical events were not durably accepted.
                try:
                    persisted = await self._raw_store().ingest(records, tenant_id=tenant_id)
                    if len(persisted) != len(records):
                        raise ValueError("raw store returned an incomplete page")
                except Exception as exc:
                    raise _pull_failed(
                        f"provider raw persistence failed for {provider_identity}",
                        provider_identity=provider_identity,
                        error_code="provider_raw_persist_failed",
                        detail=type(exc).__name__,
                    ) from exc
                persisted_records = []
                for persisted_record, _was_new in persisted:
                    if _stream_descriptor is not None:
                        if not self._raw_record_matches_stream_scope(
                            persisted_record,
                            tenant_id=tenant_id,
                            provider_identity=provider_identity,
                            connection_id=connection_id,
                            account_id=account_id,
                            stream_id=scoped_stream_id or "",
                        ):
                            raise _pull_failed(
                                "raw store returned a record outside its stream scope",
                                provider_identity=provider_identity,
                                error_code="provider_raw_scope_mismatch",
                                detail="persisted raw record scope does not match selected account and stream",
                            )
                    elif (
                        persisted_record.tenant_id != tenant_id
                        or persisted_record.provider_identity != provider_identity
                        or persisted_record.connection_id != connection_id
                        or persisted_record.account_id != account_id
                    ):
                        raise _pull_failed(
                            "provider raw persistence returned a record outside sync scope",
                            provider_identity=provider_identity,
                            error_code="provider_raw_persist_failed",
                            detail="raw store returned a record outside selected account scope",
                        )
                    persisted_records.append(persisted_record)
                if persisted and sync_run is not None:
                    try:
                        from services.identity.provider_evidence import (
                            capture_durable_provider_customer_evidence,
                        )

                        await capture_durable_provider_customer_evidence(
                            persisted_records,
                            persisted,
                            tenant_id=tenant_id,
                            connection_id=connection_id,
                            account_id=account_id,
                            lifecycle_type="provider_sync_run",
                            lifecycle_id=sync_run.sync_run_id,
                        )
                    except Exception as exc:  # evidence failure is observable, never candidate-visible
                        self._warn(
                            f"provider identity evidence capture failed tenant={tenant_id} "
                            f"provider={provider_identity}: {type(exc).__name__}"
                        )
                try:
                    events = await self._normalize_records(normalization, persisted_records)
                except Exception as exc:
                    raise _pull_failed(
                        f"provider normalization failed for {provider_identity}",
                        provider_identity=provider_identity,
                        error_code="provider_normalization_failed",
                        detail=type(exc).__name__,
                    ) from exc
                if events:
                    try:
                        accepted = await self._bridge().ingest_events(tenant_id, events)
                    except Exception as exc:
                        raise _pull_failed(
                            f"provider event persistence failed for {provider_identity}",
                            provider_identity=provider_identity,
                            error_code="provider_event_persist_failed",
                            detail=type(exc).__name__,
                        ) from exc
                    events_published += accepted

                # Responsiveness spine: first-sample milestone (progressive provider sync).
                if not _first_sample_emitted and events:
                    _first_sample_emitted = True
                    try:
                        await get_responsiveness_service().update_provider_sync_state(
                            tenant_id=tenant_id,
                            provider_id=provider_identity,
                            connection_id=connection_id,
                            status="sampling",
                            connected_at=_sync_started_at,
                            first_sample_record_at=datetime.now(timezone.utc).isoformat(),
                            records_sampled=len(events),
                            records_discovered=records_received,
                            progress_percent=min(100.0, (page / max(1, self.MAX_PAGES)) * 100),
                        )
                    except Exception:
                        pass

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
                f"provider pull raised tenant={tenant_id} provider={provider_identity}: {exc!r}"
            )
            terminal = _pull_failed(
                f"provider pull raised for {provider_identity}",
                provider_identity=provider_identity,
                error_code="provider_pull_failed",
                detail=str(exc)[:500],
            )

        if terminal is not None:
            return await self._fail_run(
                connection,
                run_service,
                sync_run,
                error_code=terminal.details.get("error_code") or "provider_pull_failed",
                detail=terminal.details.get("detail") or str(terminal),
                retry_count=retry_count,
                rate_limit_events=rate_limit_events,
                pages=page,
                lifecycle_started=lifecycle_started,
            )

        # Success: advance cursor, close the ledger with honest counts, record
        # the connection's last_successful_sync_at, and meter.
        try:
            if _stream_descriptor is None:
                await self.cursors.set_cursor(
                    tenant_id,
                    connection_id,
                    provider_identity,
                    cursor_value=last_cursor or "",
                    event_count=records_received,
                )
            else:
                await self.cursors.set_cursor(
                    tenant_id,
                    connection_id,
                    provider_identity,
                    cursor_value=last_cursor or "",
                    event_count=records_received,
                    account_id=account_id,
                    stream_id=scoped_stream_id,
                )
        except Exception as exc:
            return await self._fail_run(
                connection,
                run_service,
                sync_run,
                error_code="provider_cursor_persist_failed",
                detail=type(exc).__name__,
                retry_count=retry_count,
                rate_limit_events=rate_limit_events,
                pages=page,
                lifecycle_started=lifecycle_started,
            )

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
        if (
            sync_run is not None
            and completed is not None
            and getattr(completed, "status", None) == "completed"
        ):
            try:
                from services.identity.provider_evidence_anchors import (
                    ProviderIdentityEvidenceAnchorRepository,
                )

                await ProviderIdentityEvidenceAnchorRepository().finish_lifecycle(
                    tenant_id=tenant_id,
                    lifecycle_type="provider_sync_run",
                    lifecycle_id=sync_run.sync_run_id,
                    status="completed",
                )
            except Exception as exc:
                self._warn(
                    f"provider evidence lifecycle completion failed tenant={tenant_id}: "
                    f"{type(exc).__name__}"
                )
        if _stream_descriptor is None:
            await self._record_connection_success(connection, last_sync_at=now_iso())
        await self.meter(
            tenant_id,
            "provider.sync.completed",
            connection_id,
            "provider_runtime",
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

    async def _run_declared_streams(
        self,
        connection: Any,
        *,
        manifest: Any,
        streams: tuple[Any, ...],
        since: Optional[str],
        requested_stream_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Dispatch declared pull streams across the connection's accounts."""
        provider_identity = connection.provider_identity
        run_service = self.sync_runs or SyncRunService()
        if requested_stream_ids:
            selected_streams = []
            for requested_stream_id in requested_stream_ids:
                selected = next(
                    (stream for stream in streams if stream.stream_id == requested_stream_id),
                    None,
                )
                if selected is None:
                    return await self._fail_run(
                        connection,
                        run_service,
                        None,
                        error_code="provider_stream_not_found",
                        detail="requested stream is not declared by the provider manifest",
                    )
                if "pull" not in selected.acquisition_modes:
                    return await self._fail_run(
                        connection,
                        run_service,
                        None,
                        error_code="provider_stream_not_pullable",
                        detail="requested stream does not declare pull acquisition",
                    )
                if not self._stream_is_enabled(selected, connection, manifest):
                    return await self._fail_run(
                        connection,
                        run_service,
                        None,
                        error_code="provider_stream_inactive",
                        detail="requested stream is not enabled by the connection configuration",
                    )
                selected_streams.append(selected)
        else:
            selected_streams = [
                stream
                for stream in streams
                if "pull" in stream.acquisition_modes
                and self._stream_is_enabled(stream, connection, manifest)
            ]
            if not selected_streams:
                return {
                    "provider_identity": provider_identity,
                    "connection_id": connection.connection_id,
                    "status": "skipped",
                    "reason": "no_active_pull_streams",
                    "stream_runs": [],
                }

        configured_accounts = list(getattr(connection, "selected_accounts", None) or [])
        account_ids = list(dict.fromkeys(str(account_id) for account_id in configured_accounts))
        accounts_spec = getattr(manifest, "accounts", None)
        if not account_ids:
            if bool(getattr(accounts_spec, "selection_required", False)):
                return await self._fail_run(
                    connection,
                    run_service,
                    None,
                    error_code="provider_account_selection_required",
                    detail="a selected provider account is required for stream sync",
                )
            account_ids = [""]

        try:
            await self._record_connection_sync_started(connection)
        except (Exception, asyncio.CancelledError):
            await self._record_connection_sync_failure(connection)
            raise
        results: list[dict[str, Any]] = []
        for account_id in account_ids:
            for stream in selected_streams:
                try:
                    result = await self.run_sync(
                        connection,
                        since=since,
                        _stream_descriptor=stream,
                        _selected_account_id=account_id,
                    )
                except (Exception, asyncio.CancelledError):
                    await self._record_connection_sync_failure(connection)
                    raise
                results.append(
                    {
                        "account_id": account_id,
                        "stream_id": stream.stream_id,
                        "result": result,
                    }
                )
        await self._record_connection_success(connection, last_sync_at=now_iso())
        return {
            "provider_identity": provider_identity,
            "connection_id": connection.connection_id,
            "status": "completed",
            "stream_runs": results,
        }

    def _require_sync_eligible(self, connection: Any) -> None:
        state = self._state_value(connection)
        if state not in SYNC_ELIGIBLE_STATES:
            raise ConnectionStateViolation(
                f"provider sync is not allowed while connection is {state}",
                details={
                    "connection_id": getattr(connection, "connection_id", ""),
                    "state": state,
                    "eligible_states": sorted(SYNC_ELIGIBLE_STATES),
                },
            )

    @staticmethod
    def _state_value(connection: Any) -> str:
        state = getattr(connection, "state", None)
        return str(getattr(state, "value", state))

    def _transition_connection(self, connection: Any, target: ConnectionState) -> bool:
        current = ConnectionState(self._state_value(connection))
        if current == target:
            return False
        from services.provider_runtime.connection import ConnectionOrchestrator

        ConnectionOrchestrator(connections=self._connections()).transition(connection, target)
        return True

    async def _record_connection_sync_started(self, connection: Any) -> None:
        """Persist INITIAL_SYNC_RUNNING before the first provider request."""
        state = self._state_value(connection)
        transitioned = False
        if state == ConnectionState.SYNC_FAILED.value and not getattr(
            connection, "last_successful_sync_at", None
        ):
            transitioned = self._transition_connection(
                connection, ConnectionState.INITIAL_SYNC_PENDING
            )
            transitioned = (
                self._transition_connection(connection, ConnectionState.INITIAL_SYNC_RUNNING)
                or transitioned
            )
        elif state == ConnectionState.INITIAL_SYNC_PENDING.value:
            transitioned = self._transition_connection(
                connection, ConnectionState.INITIAL_SYNC_RUNNING
            )
        if transitioned:
            await self._connections().upsert(connection)

    @staticmethod
    def _stream_is_enabled(
        stream: StreamDescriptor,
        connection: Any,
        manifest: Any,
    ) -> bool:
        if stream.enabled_by_default:
            return True
        field = stream.activation_config_field
        expected = stream.activation_config_value
        if field is None or expected is None:
            return False
        config = getattr(connection, "config", None) or {}
        if field in config:
            actual = config[field]
        else:
            configuration = getattr(manifest, "configuration", None)
            config_fields = getattr(configuration, "fields", ()) or ()
            declared_field = next(
                (item for item in config_fields if getattr(item, "name", None) == field),
                None,
            )
            actual = getattr(declared_field, "default_value", None)
        return actual == expected

    @staticmethod
    def _raw_record_matches_stream_scope(
        record: Any,
        *,
        tenant_id: str,
        provider_identity: str,
        connection_id: str,
        account_id: str,
        stream_id: str,
    ) -> bool:
        return all(
            (
                getattr(record, "tenant_id", None) == tenant_id,
                getattr(record, "provider_identity", None) == provider_identity,
                getattr(record, "connection_id", None) == connection_id,
                getattr(record, "account_id", None) == account_id,
                getattr(record, "stream_id", None) == stream_id,
            )
        )

    @classmethod
    def _bind_stream_raw_records(
        cls,
        records: list[Any],
        *,
        tenant_id: str,
        provider_identity: str,
        connection_id: str,
        account_id: str,
        stream_id: str,
    ) -> list[Any]:
        """Bind absent scope fields and reject any provider-supplied mismatch."""
        bound: list[Any] = []
        for record in records:
            if getattr(record, "provider_identity", None) != provider_identity:
                raise ValueError("raw record provider_identity does not match the active provider")
            expected_scope = {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "account_id": account_id,
                "stream_id": stream_id,
            }
            updates: dict[str, str] = {}
            for field, expected in expected_scope.items():
                actual = getattr(record, field, None)
                if actual not in (None, "", expected):
                    raise ValueError(f"raw record {field} does not match the active stream scope")
                if actual != expected:
                    updates[field] = expected
            bound.append(record.model_copy(update=updates) if updates else record)
        return bound

    @staticmethod
    def _bind_streamless_raw_records(
        records: list[Any],
        *,
        tenant_id: str,
        provider_identity: str,
        connection_id: str,
        account_id: str,
    ) -> list[Any]:
        """Bind absent v1 scope fields and reject raw records outside the selected account."""
        expected_scope = {
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "account_id": account_id,
        }
        bound: list[Any] = []
        for record in records:
            if getattr(record, "provider_identity", None) != provider_identity:
                raise ValueError("raw record provider_identity does not match the active provider")
            updates: dict[str, str] = {}
            for field, expected in expected_scope.items():
                actual = getattr(record, field, None)
                if actual not in (None, "", expected):
                    raise ValueError(
                        f"raw record {field} does not match the selected account scope"
                    )
                if actual != expected:
                    updates[field] = expected
            bound.append(record.model_copy(update=updates) if updates else record)
        return bound

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
                connection.tenant_id,
                credential_ref,
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
            if result.status in (
                AdapterStatus.RETRYABLE_ERROR,
                AdapterStatus.RATE_LIMITED,
            ) and self.retry.should_retry(result.status, attempt=attempt):
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
        self,
        normalization: Any,
        records: list[Any],
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
        lifecycle_started: bool = False,
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
                    f"provider sync-run close(failed) failed tenant={connection.tenant_id}: {exc}"
                )
            else:
                try:
                    from services.identity.provider_evidence_anchors import (
                        ProviderIdentityEvidenceAnchorRepository,
                    )

                    await ProviderIdentityEvidenceAnchorRepository().finish_lifecycle(
                        tenant_id=connection.tenant_id,
                        lifecycle_type="provider_sync_run",
                        lifecycle_id=sync_run.sync_run_id,
                        status="failed",
                    )
                except Exception as exc:
                    self._warn(
                        f"provider evidence failure transition failed "
                        f"tenant={connection.tenant_id}: {type(exc).__name__}"
                    )
        if lifecycle_started:
            await self._record_connection_sync_failure(connection)
        await self._record_connection_error(connection, error_code=error_code, detail=detail)
        raise _pull_failed(
            f"provider sync failed for {connection.provider_identity}: {detail}",
            provider_identity=connection.provider_identity,
            error_code=error_code,
            detail=detail,
        )

    async def _record_connection_success(self, connection: Any, *, last_sync_at: str) -> None:
        """Record CONNECTED and last_successful_sync_at in place + best-effort persist.

        Persists through the lazy ``_connections()`` resolver so the real
        orchestration path (``PullScheduler()`` with no injected repo, which is
        exactly what ``ConnectionOrchestrator.run_sync`` constructs) still writes
        the timestamp to the connection store — otherwise the health engine
        would read ``None`` forever after a successful sync.
        """
        state = self._state_value(connection)
        if state in {
            ConnectionState.INITIAL_SYNC_RUNNING.value,
            ConnectionState.DEGRADED.value,
            ConnectionState.SYNC_FAILED.value,
        }:
            self._transition_connection(connection, ConnectionState.CONNECTED)
        connection.last_successful_sync_at = last_sync_at
        connection.updated_at = last_sync_at
        try:
            await self._connections().upsert(connection)
        except Exception as exc:  # pragma: no cover - best-effort
            self._warn(
                f"provider connection success record failed tenant={connection.tenant_id}: {exc}"
            )

    async def _record_connection_sync_failure(self, connection: Any) -> None:
        """Move an active sync lifecycle to SYNC_FAILED and persist best-effort."""
        state = self._state_value(connection)
        if state not in {
            ConnectionState.INITIAL_SYNC_RUNNING.value,
            ConnectionState.CONNECTED.value,
            ConnectionState.DEGRADED.value,
        }:
            return
        try:
            self._transition_connection(connection, ConnectionState.SYNC_FAILED)
            await self._connections().upsert(connection)
        except Exception as exc:  # preserve the original provider failure
            self._warn(
                f"provider connection failure state record failed tenant={connection.tenant_id}: {exc}"
            )

    async def _record_connection_error(
        self,
        connection: Any,
        *,
        error_code: str,
        detail: str,
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


__all__ = ["ProviderCursorRepository", "PullScheduler", "SYNC_ELIGIBLE_STATES"]
