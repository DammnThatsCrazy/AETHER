from __future__ import annotations

import base64
import uuid

import pytest

from actions.agent_correlation.keys import parse_keyring
from actions.agent_correlation.service import CorrelationService

SECRET_B64 = base64.urlsafe_b64encode(b"c" * 32).decode().rstrip("=")


class RecordingProjector:
    """Captures graph projections instead of writing to a graph."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def project(self, left, right, verdict, verdict_id):
        from actions.agent_correlation.projection import build_link_mutations

        mutations = build_link_mutations(left, right, verdict, verdict_id)
        self.calls.append((left, right, verdict, verdict_id, mutations))
        return {"graph_projection_status": "persisted", "graph_mutations_persisted": len(mutations)}


async def connect_verified_account(
    tenant_id: str,
    *,
    family: str = "shopify",
    account_key: str = "acme.myshopify.com",
    realm: str = "live",
    state: str = "connected",
    verified: bool = True,
) -> str:
    """Create a provider-runtime connection and selected account, as discovery would."""
    from connectors.provider_runtime.acquisition import ProviderAccountRecord, ProviderAccountRepository
    from connectors.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
    from shared.integration_contracts.lifecycle import ConnectionState

    connection_id = f"conn_{uuid.uuid4().hex[:10]}"
    selected = "acct_main"
    await ProviderConnectionRepository().upsert(ProviderConnection(
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_identity=f"{family}.admin.orders_read",
        state=ConnectionState(state),
        selected_accounts=[selected],
        last_verified_at="2026-11-14T00:00:00+00:00" if verified else None,
    ))
    account_id = f"{connection_id}:{selected}"
    await ProviderAccountRepository().upsert(ProviderAccountRecord(
        account_id=account_id,
        tenant_id=tenant_id,
        connection_id=connection_id,
        provider_identity=f"{family}.admin.orders_read",
        external_id=account_key,
        metadata={"source_account_realm": realm},
    ))
    return account_id


@pytest.fixture
def tenant_id() -> str:
    # In-memory repository stores are process-wide; a fresh tenant isolates tests.
    return f"tenant_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def keyring():
    return parse_keyring([f"k1:{SECRET_B64}"])


@pytest.fixture
def projector() -> RecordingProjector:
    return RecordingProjector()


@pytest.fixture
def service(keyring, projector) -> CorrelationService:
    svc = CorrelationService(keyring=keyring)
    svc.engine._projector = projector  # noqa: SLF001 - test seam
    return svc
