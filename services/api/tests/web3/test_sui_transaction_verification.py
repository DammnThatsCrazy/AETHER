"""Sui SDK transaction evidence uses the registered Sui GraphQL source."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph.onchain import rpc_gateway
from graph.onchain.rpc_gateway import RPCGateway, SUI_TRANSACTION_QUERY
from graph.web3.registries import ChainRegistry, Web3ObservationRepository
from graph.web3.transaction_verification import SDKTransactionVerifier, TransactionVerification
from graph.web3 import routes as web3_routes
from repositories.repos import AnalyticsRepository, reset_in_memory_stores
from shared.auth.auth import Role, TenantContext
from shared.decorators import register_error_handlers


MAINNET_CHAIN_IDENTIFIER = "35834a8a"
MAINNET_CHAIN_IDENTIFIER_BASE58 = "4btiuiMPvEENsttpZC7CZ53DruC3MAgfznDbASZ7DR6S"
SUI_DIGEST = "6FkqU7MkDgT7QyZVbQfTzL6oYkUjF3vY6MK2LPC5Rf3x"
SUI_SENDER = "0x" + ("0" * 63) + "1"


@pytest.fixture(autouse=True)
def _reset_repositories():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


class FakeSuiRPC:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str]] = []

    async def execute_sui_transaction(self, *, tenant_id: str, chain_id: str, digest: str):
        self.calls.append((tenant_id, chain_id, digest))
        return self.response


async def _registered_sui_chain() -> ChainRegistry:
    chains = ChainRegistry()
    await chains.register({
        "chain_id": "sui",
        "aliases": ["sui:mainnet"],
        "canonical_name": "Sui",
        "vm_family": "movevm",
        "sui_chain_identifier": MAINNET_CHAIN_IDENTIFIER,
    })
    return chains


def _transaction(*, digest: str = SUI_DIGEST, status: str = "SUCCESS") -> dict[str, Any]:
    return {
        "digest": digest,
        "sender": {"address": SUI_SENDER},
        "effects": {
            "status": status,
            "checkpoint": {"sequenceNumber": "42"},
        },
    }


def test_verification_record_ids_preserve_case_sensitive_base58_digests():
    upper = SDKTransactionVerifier.record_id("tenant-a", "sui:mainnet", "AbC")
    lower = SDKTransactionVerifier.record_id("tenant-a", "sui:mainnet", "aBc")
    assert upper != lower
    assert SDKTransactionVerifier.record_id("tenant-a", "ethereum", "0xABCD") == (
        SDKTransactionVerifier.record_id("tenant-a", "ethereum", "0xabcd")
    )


@pytest.mark.asyncio
async def test_verifies_sui_graphql_evidence_without_promoting_settlement():
    chains = await _registered_sui_chain()
    rpc = FakeSuiRPC({
        "chain_identifier": MAINNET_CHAIN_IDENTIFIER_BASE58,
        "transaction": _transaction(),
    })
    observations = Web3ObservationRepository()
    verifier = SDKTransactionVerifier(rpc=rpc, chains=chains, observations=observations)

    result = await verifier.verify(
        tenant_id="tenant-a",
        chain_id="sui:mainnet",
        transaction_hash=SUI_DIGEST,
        vm_family="movevm",
        source_observation={"source_event_id": "sdk-event-1", "from_address": "0x1"},
    )

    assert result.status == "finalized"
    assert result.execution_status == "succeeded"
    assert result.confirmations == 0  # Sui finality is checkpoint based.
    assert result.evidence["checkpoint_sequence"] == 42
    assert rpc.calls == [("tenant-a", "sui:mainnet", SUI_DIGEST)]
    stored = await observations.for_tenant("tenant-a").find_by_id(
        verifier.record_id("tenant-a", "sui:mainnet", SUI_DIGEST)
    )
    assert stored["settlement_status"] == "unverified_by_this_check"
    assert stored["graph_projection"] is False


@pytest.mark.asyncio
async def test_sui_chain_identifier_mismatch_does_not_verify_execution():
    chains = await _registered_sui_chain()
    verifier = SDKTransactionVerifier(
        rpc=FakeSuiRPC({
            "chain_identifier": "wrong-network-id",
            "transaction": _transaction(),
        }),
        chains=chains,
    )

    result = await verifier.verify(
        tenant_id="tenant-a", chain_id="sui:mainnet", transaction_hash=SUI_DIGEST,
        vm_family="movevm", source_observation={},
    )

    assert result.status == "mismatch"
    assert result.evidence["mismatch"] == "chain_identifier"


@pytest.mark.asyncio
async def test_sui_failed_execution_is_finalized_but_not_successful():
    chains = await _registered_sui_chain()
    verifier = SDKTransactionVerifier(
        rpc=FakeSuiRPC({
            "chain_identifier": MAINNET_CHAIN_IDENTIFIER,
            "transaction": _transaction(status="FAILURE"),
        }),
        chains=chains,
    )

    result = await verifier.verify(
        tenant_id="tenant-a", chain_id="sui:mainnet", transaction_hash=SUI_DIGEST,
        vm_family="movevm", source_observation={},
    )

    assert result.status == "finalized"
    assert result.execution_status == "failed"


@pytest.mark.asyncio
async def test_sui_graphql_gateway_requeries_until_the_digest_is_visible(monkeypatch):
    gateway = RPCGateway(endpoint="https://provider.example/graphql", api_key="tenant-key")
    calls: list[tuple[str, str]] = []

    async def fake_execute(*, chain_id: str, digest: str):
        calls.append((chain_id, digest))
        return {"chain_identifier": MAINNET_CHAIN_IDENTIFIER, "transaction": None}

    monkeypatch.setattr(gateway, "_execute_sui_graphql", fake_execute)

    result = await gateway.execute_sui_transaction(
        tenant_id="tenant-a", chain_id="sui:mainnet", digest=SUI_DIGEST,
    )
    again = await gateway.execute_sui_transaction(
        tenant_id="tenant-a", chain_id="sui:mainnet", digest=SUI_DIGEST,
    )

    assert result == again
    assert calls == [("sui:mainnet", SUI_DIGEST), ("sui:mainnet", SUI_DIGEST)]
    assert "chainIdentifier" in SUI_TRANSACTION_QUERY
    assert "transaction(digest: $digest)" in SUI_TRANSACTION_QUERY
    with pytest.raises(ValueError, match="sui:<network>"):
        await gateway.execute_sui_transaction(
            tenant_id="tenant-a", chain_id="sui", digest=SUI_DIGEST,
        )


@pytest.mark.asyncio
async def test_sui_graphql_http_request_preserves_read_only_query(monkeypatch):
    requests: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {
                "chainIdentifier": MAINNET_CHAIN_IDENTIFIER,
                "transaction": _transaction(),
            }}

    class FakeClient:
        def __init__(self, *, timeout: float):
            assert timeout == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(rpc_gateway.httpx, "AsyncClient", FakeClient)
    gateway = RPCGateway(endpoint="https://provider.example/graphql", api_key="tenant-key")

    result = await gateway._execute_sui_graphql(chain_id="sui:mainnet", digest=SUI_DIGEST)

    assert result["chain_identifier"] == MAINNET_CHAIN_IDENTIFIER
    assert requests[0]["json"] == {
        "query": SUI_TRANSACTION_QUERY,
        "variables": {"digest": SUI_DIGEST},
    }
    assert requests[0]["headers"]["x-api-key"] == "tenant-key"


def test_sui_verify_route_accepts_namespaced_chain_alias(monkeypatch):
    chains = web3_routes.chain_reg
    import asyncio

    asyncio.run(chains.register({
        "chain_id": "sui",
        "aliases": ["sui:mainnet"],
        "canonical_name": "Sui",
        "vm_family": "movevm",
        "sui_chain_identifier": MAINNET_CHAIN_IDENTIFIER,
    }))

    async def fake_query_silver(self, table, filters, limit=100):
        assert table == "silver_web3_transaction_facts"
        assert filters["chain_id"] == "sui:mainnet"
        return [{"source_event_type": "transaction", "tx_hash": SUI_DIGEST}]

    class FakeVerifier:
        call: dict[str, Any] | None = None

        async def verify(self, **kwargs):
            self.call = kwargs
            return TransactionVerification(
                tenant_id=kwargs["tenant_id"], chain_id=kwargs["chain_id"],
                transaction_hash=kwargs["transaction_hash"], vm_family=kwargs["vm_family"],
                status="mismatch", execution_status="unknown", confirmations=0,
                source_event_id=None, evidence={"mismatch": "test"},
            )

    verifier = FakeVerifier()
    monkeypatch.setattr(AnalyticsRepository, "query_silver", fake_query_silver)
    monkeypatch.setattr(web3_routes, "transaction_verifier", verifier)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(web3_routes.router)

    @app.middleware("http")
    async def bind_tenant(request, call_next):
        request.state.tenant = TenantContext(tenant_id="tenant-a", role=Role.ADMIN, permissions=[])
        request.state.tenant_id = "tenant-a"
        return await call_next(request)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/web3/transactions/verify",
        json={"chain_id": "sui:mainnet", "transaction_hash": SUI_DIGEST},
    )

    assert response.status_code == 200
    assert verifier.call["chain_id"] == "sui:mainnet"
    assert verifier.call["vm_family"] == "movevm"
    assert response.json()["settlement_status"] == "not_assessed"
