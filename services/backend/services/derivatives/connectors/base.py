"""Derivatives connector interface shared by venue adapters and imports."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from services.derivatives.models import BronzeObservation, NormalizedFillFact, validate_read_only_scopes


@dataclass(frozen=True)
class DerivativesConnectorCheckpoint:
    tenant_id: str
    connector_id: str
    checkpoint_value: str
    advanced_at: str


@dataclass(frozen=True)
class DerivativesConnectorHealth:
    connector_id: str
    state: str
    snapshot_lag_seconds: int | None = None
    stream_lag_seconds: int | None = None
    last_error: str | None = None


class DerivativesConnector(ABC):
    """Read-only derivatives connector contract.

    Implementations may fetch public market data and authorized private-account
    observations, but must never expose trade submission, transfer, withdrawal,
    key-management, or account-mutation methods.
    """

    provider: str

    @abstractmethod
    async def describe_venue(self) -> Mapping[str, Any]: ...

    @abstractmethod
    async def test_connection(self, scopes: Iterable[str]) -> DerivativesConnectorHealth: ...

    @abstractmethod
    async def fetch_markets(self, *, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]: ...

    @abstractmethod
    async def fetch_account_snapshot(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]: ...

    @abstractmethod
    async def fetch_fills(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]: ...

    @abstractmethod
    async def subscribe_account_stream(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> AsyncIterator[BronzeObservation]: ...

    @abstractmethod
    def normalize(self, observation: BronzeObservation) -> list[NormalizedFillFact]: ...

    @abstractmethod
    def checkpoint(self, observations: list[BronzeObservation]) -> DerivativesConnectorCheckpoint | None: ...


def enforce_read_only_credentials(scopes: Iterable[str]) -> None:
    validate_read_only_scopes(list(scopes))
