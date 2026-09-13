"""Acquisition coordination — account discovery and selection.

:class:`ProviderAccountRecord` is the repository record model for one discovered
provider account. :class:`ProviderAccountRepository` is a thin
:class:`~repositories.repos.BaseRepository` subclass (JSONB table
``provider_accounts``). :class:`AcquisitionCoordinator` drives the account
capability adapter (Team C plugin's ``account()``) against the
:class:`~shared.integration_contracts.acquisition.AcquisitionContext` seam and
persists discovery results.

Account persistence keys are namespaced by connection
(``{connection_id}:{provider_account_id}``) so the same provider-side account id
on two connections never collides.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now
from shared.integration_contracts.acquisition import (
    AcquisitionContext,
    ProviderAccount,
)
from shared.integration_contracts.lifecycle import ConnectionState, can_transition
from shared.integration_contracts.results import AdapterResult
from repositories.repos import BaseRepository

from services.provider_runtime.connection import ProviderConnection
from services.provider_runtime.errors import PluginIncompatible, ProviderNotInstalled


def _now_iso() -> str:
    """Current UTC time in ISO-8601 form (caller-supplied timestamps)."""
    return utc_now().isoformat()


def _account_from_row(row: Optional[dict]) -> Optional[ProviderAccountRecord]:
    """Build a model from a stored row, stripping repo-injected keys.

    :class:`BaseRepository` injects ``id`` and ``updated_at`` on insert/update;
    :class:`ProviderAccountRecord` is ``extra="forbid"`` and has neither field,
    so both keys must be dropped before validation.
    """
    if row is None:
        return None
    return ProviderAccountRecord.model_validate(
        {k: v for k, v in row.items() if k not in ("id", "updated_at")}
    )


class ProviderAccountRecord(BaseModel):
    """Repository record model for a discovered provider account."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    tenant_id: str
    connection_id: str
    provider_identity: str
    display_name: str = ""
    external_id: Optional[str] = None
    currency: Optional[str] = None
    region: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class ProviderAccountRepository(BaseRepository):
    """Thin BaseRepository over ``provider_accounts`` (JSONB)."""

    def __init__(self) -> None:
        super().__init__("provider_accounts")

    async def find(self, account_id: str) -> Optional[ProviderAccountRecord]:
        row = await self.find_by_id(account_id)
        return _account_from_row(row)

    async def list_for_connection(
        self, connection_id: str, *, limit: int = 200
    ) -> list[ProviderAccountRecord]:
        rows = await self.find_many(filters={"connection_id": connection_id}, limit=limit)
        return [
            record
            for r in rows
            if (record := _account_from_row(r)) is not None
        ]

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 200
    ) -> list[ProviderAccountRecord]:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        return [
            record
            for r in rows
            if (record := _account_from_row(r)) is not None
        ]

    async def upsert(self, record: ProviderAccountRecord) -> ProviderAccountRecord:
        """Insert-or-update by ``account_id``; returns the persisted model."""
        existing = await self.find_by_id(record.account_id)
        data = record.model_dump()
        if existing is not None:
            if not data.get("created_at") and existing.get("created_at"):
                data["created_at"] = existing["created_at"]
            await self.update(record.account_id, data)
        else:
            await self.insert(record.account_id, data)
        stored = await self.find_by_id(record.account_id)
        assert stored is not None  # just inserted/updated
        return _account_from_row(stored)  # type: ignore[return-value]


def _build_context(
    connection: ProviderConnection,
    *,
    account_id: str = "",
    credential: Any = None,
) -> AcquisitionContext:
    """Build the acquisition context from a connection's scoping."""
    return AcquisitionContext(
        tenant_id=connection.tenant_id,
        provider_identity=connection.provider_identity,
        connection_id=connection.connection_id,
        account_id=account_id,
        config=connection.config,
        credential=credential,
    )


class AcquisitionCoordinator:
    """Drives account discovery/selection for a provider plugin."""

    def __init__(self, *, accounts=None) -> None:
        self.accounts = accounts if accounts is not None else ProviderAccountRepository()

    async def discover_accounts(
        self,
        connection: ProviderConnection,
        *,
        plugin: Any = None,
        credential: Any = None,
    ) -> AdapterResult[list[ProviderAccount]]:
        """Run ``plugin.account().discover_accounts(ctx)`` and persist results.

        On success, every discovered :class:`ProviderAccount` is persisted as a
        :class:`ProviderAccountRecord` keyed by ``{connection_id}:{account_id}``.
        The adapter result is returned unchanged (success/failure classification
        stays with the adapter).
        """
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}",
                details={"connection_id": connection.connection_id},
            )
        account = plugin.account()
        if account is None:
            # Registered plugin without the account capability — typed
            # incompatibility, never a raw AttributeError.
            raise PluginIncompatible(
                f"provider plugin for {connection.provider_identity} "
                "does not implement the account capability",
                details={"connection_id": connection.connection_id},
            )
        context = _build_context(connection, credential=credential)
        result = await account.discover_accounts(context)
        if result.success and result.data:
            for account in result.data:
                await self.accounts.upsert(
                    ProviderAccountRecord(
                        account_id=f"{connection.connection_id}:{account.account_id}",
                        tenant_id=connection.tenant_id,
                        connection_id=connection.connection_id,
                        provider_identity=connection.provider_identity,
                        display_name=account.display_name,
                        external_id=account.external_id,
                        currency=account.currency,
                        region=account.region,
                        metadata=account.metadata,
                        created_at=_now_iso(),
                    )
                )
        return result

    async def select_account(
        self,
        connection: ProviderConnection,
        *,
        account_id: str,
        plugin: Any = None,
        credential: Any = None,
    ) -> ProviderConnection:
        """Run ``plugin.account().select_account(ctx, account_id=...)``.

        On success the account is appended to ``selected_accounts`` and the
        connection advances ``ACCOUNT_SELECTION_REQUIRED → next`` (legal
        transition only). The mutated connection is returned; persistence is the
        caller's responsibility (the coordinator owns no connection repo).
        """
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}",
                details={"connection_id": connection.connection_id},
            )
        account = plugin.account()
        if account is None:
            # Registered plugin without the account capability — typed
            # incompatibility, never a raw AttributeError.
            raise PluginIncompatible(
                f"provider plugin for {connection.provider_identity} "
                "does not implement the account capability",
                details={"connection_id": connection.connection_id},
            )
        context = _build_context(connection, account_id=account_id, credential=credential)
        result = await account.select_account(context, account_id=account_id)
        if not result.success:
            return connection
        if account_id not in connection.selected_accounts:
            connection.selected_accounts.append(account_id)
        # ACCOUNT_SELECTION_REQUIRED advances toward CONNECTED via the machine.
        if (
            connection.state == ConnectionState.ACCOUNT_SELECTION_REQUIRED
            and can_transition(connection.state, ConnectionState.INITIAL_SYNC_PENDING)
        ):
            connection.state = ConnectionState.INITIAL_SYNC_PENDING
            connection.updated_at = _now_iso()
        elif can_transition(connection.state, ConnectionState.ACCOUNT_SELECTION_REQUIRED):
            connection.state = ConnectionState.ACCOUNT_SELECTION_REQUIRED
            connection.updated_at = _now_iso()
        return connection


__all__ = [
    "AcquisitionCoordinator",
    "ProviderAccountRecord",
    "ProviderAccountRepository",
]
