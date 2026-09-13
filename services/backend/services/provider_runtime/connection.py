"""Connection orchestration — lifecycle operations guarded by the state machine.

:class:`ProviderConnection` is the repository record model for one
tenant↔provider connection. :class:`ProviderConnectionRepository` is a thin
:class:`~repositories.repos.BaseRepository` subclass (JSONB table
``provider_connections``). :class:`ConnectionOrchestrator` owns the lifecycle
operations and never performs a state move the
:class:`~shared.integration_contracts.lifecycle` transition table forbids.

Credential material never lives here — only a ``credential_ref`` produced by the
:class:`~services.provider_runtime.credential_broker.CredentialBroker`.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.lifecycle import ConnectionState, can_transition
from shared.integration_contracts.results import AdapterResult
from shared.credentials.types import StructuredCredential
from repositories.repos import BaseRepository

from services.provider_runtime.errors import (
    ConnectionStateViolation,
    PluginIncompatible,
    ProviderNotInstalled,
)
from services.provider_runtime.credential_broker import credential_broker


def _now_iso() -> str:
    """Current UTC time in ISO-8601 form (caller-supplied timestamps)."""
    return utc_now().isoformat()


def _connection_from_row(row: Optional[dict]) -> Optional[ProviderConnection]:
    """Build a model from a stored row, stripping the repo-injected ``id``.

    :class:`BaseRepository` injects an ``id`` key on insert; ``ProviderConnection``
    is ``extra="forbid"`` and has no ``id`` field, so the repo key must be dropped
    before validation.
    """
    if row is None:
        return None
    return ProviderConnection.model_validate({k: v for k, v in row.items() if k != "id"})


class ProviderConnection(BaseModel):
    """Repository record model for a tenant↔provider connection."""

    model_config = ConfigDict(extra="forbid")

    connection_id: str
    tenant_id: str
    provider_identity: str
    display_name: str = ""
    state: ConnectionState = ConnectionState.AVAILABLE
    credential_ref: str = ""
    selected_accounts: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""  # ISO-8601 UTC, caller-supplied
    updated_at: str = ""
    last_verified_at: Optional[str] = None
    last_successful_sync_at: Optional[str] = None


class ProviderConnectionRepository(BaseRepository):
    """Thin BaseRepository over ``provider_connections`` (JSONB)."""

    def __init__(self) -> None:
        super().__init__("provider_connections")

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[ProviderConnection]:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        return [_connection_from_row(r) for r in rows if _connection_from_row(r) is not None]

    async def find(self, connection_id: str) -> Optional[ProviderConnection]:
        row = await self.find_by_id(connection_id)
        return _connection_from_row(row)

    async def upsert(self, record: ProviderConnection) -> ProviderConnection:
        """Insert-or-update by ``connection_id``; returns the persisted model.

        ``created_at`` from an existing row is preserved on update (never moved
        to a later insert time).
        """
        existing = await self.find_by_id(record.connection_id)
        data = record.model_dump()
        if existing is not None:
            if not data.get("created_at") and existing.get("created_at"):
                data["created_at"] = existing["created_at"]
            await self.update(record.connection_id, data)
        else:
            await self.insert(record.connection_id, data)
        stored = await self.find_by_id(record.connection_id)
        assert stored is not None  # just inserted/updated
        return _connection_from_row(stored)  # type: ignore[return-value]


class ConnectionOrchestrator:
    """Lifecycle operations with ConnectionState transitions guarded by can_transition."""

    def __init__(self, *, connections=None, broker=None) -> None:
        self.connections = connections if connections is not None else ProviderConnectionRepository()
        self.broker = broker if broker is not None else credential_broker

    async def create_connection(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        display_name: str = "",
        config: dict | None = None,
    ) -> ProviderConnection:
        """Create a new connection in AVAILABLE state and persist it."""
        now = _now_iso()
        connection = ProviderConnection(
            connection_id=f"conn_{uuid.uuid4().hex}",
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            display_name=display_name,
            config=config or {},
            created_at=now,
            updated_at=now,
        )
        await self.connections.upsert(connection)
        return connection

    async def store_credential(
        self,
        connection: ProviderConnection,
        credential: StructuredCredential,
    ) -> ProviderConnection:
        """Store a structured credential behind a ref; advance to CREDENTIALS_RECEIVED.

        Ref = ``broker.provider_ref(tenant, provider_identity)``. The state move is
        only performed when the transition table allows it from the connection's
        current state (see seam note: ``CREDENTIAL_WAITING → CREDENTIALS_RECEIVED``
        is not a single legal hop; the legal path is via ``AVAILABLE``).
        """
        ref = self.broker.provider_ref(connection.tenant_id, connection.provider_identity)
        await self.broker.store(connection.tenant_id, ref, credential)
        connection.credential_ref = ref
        if can_transition(connection.state, ConnectionState.CREDENTIALS_RECEIVED):
            connection = self.transition(connection, ConnectionState.CREDENTIALS_RECEIVED)
        await self.connections.upsert(connection)
        return connection

    async def test_connection(
        self,
        connection: ProviderConnection,
        *,
        plugin: Any = None,
    ) -> AdapterResult[Any]:
        """Resolve the credential, build an AcquisitionContext, run plugin.auth().test.

        On success the connection advances toward VERIFIED (via legal
        transitions); on failure it advances toward FAILED. The plugin is
        supplied by the caller (loaded from Team C's registry); a missing plugin
        raises :class:`ProviderNotInstalled`.
        """
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}",
                details={"connection_id": connection.connection_id},
            )
        auth = plugin.auth()
        if auth is None:
            # The plugin is registered but does not implement the auth
            # capability — a typed incompatibility, never a raw AttributeError.
            raise PluginIncompatible(
                f"provider plugin for {connection.provider_identity} "
                "does not implement the auth capability",
                details={"connection_id": connection.connection_id},
            )
        credential = (
            await self.broker.resolve(connection.tenant_id, connection.credential_ref)
            if connection.credential_ref
            else None
        )
        context = AcquisitionContext(
            tenant_id=connection.tenant_id,
            provider_identity=connection.provider_identity,
            connection_id=connection.connection_id,
            account_id=connection.selected_accounts[0] if connection.selected_accounts else "",
            config=connection.config,
            credential=credential,
        )
        # Enter VERIFYING only when the machine allows it (a re-test of a
        # VERIFIED/VERIFYING connection proceeds in place).
        if can_transition(connection.state, ConnectionState.VERIFYING):
            connection = self.transition(connection, ConnectionState.VERIFYING)

        result = await auth.test(context)

        if result.success:
            if can_transition(connection.state, ConnectionState.VERIFIED):
                connection = self.transition(connection, ConnectionState.VERIFIED)
            # A successful live test is a verification at this instant, even
            # when the state is already VERIFIED (re-test) and does not move.
            connection.last_verified_at = _now_iso()
        elif not result.success and can_transition(connection.state, ConnectionState.FAILED):
            connection = self.transition(connection, ConnectionState.FAILED)
        await self.connections.upsert(connection)
        return result

    async def run_sync(self, connection: ProviderConnection, *, since: str | None = None):
        """Delegate a sync to Team E's PullScheduler.

        The scheduler is imported lazily inside the method to avoid the D↔E
        module cycle.
        """
        from services.provider_runtime.scheduler import PullScheduler  # type: ignore[import-not-found]

        scheduler = PullScheduler()
        return await scheduler.run(connection=connection, since=since)

    def transition(
        self,
        connection: ProviderConnection,
        target: ConnectionState,
    ) -> ProviderConnection:
        """Perform a guarded state move, raising ConnectionStateViolation if illegal."""
        if not can_transition(connection.state, target):
            raise ConnectionStateViolation(
                f"illegal connection state transition {connection.state.value} -> {target.value}",
                details={
                    "connection_id": connection.connection_id,
                    "from": connection.state.value,
                    "to": target.value,
                },
            )
        connection.state = target
        connection.updated_at = _now_iso()
        return connection


__all__ = [
    "ConnectionOrchestrator",
    "ProviderConnection",
    "ProviderConnectionRepository",
]
