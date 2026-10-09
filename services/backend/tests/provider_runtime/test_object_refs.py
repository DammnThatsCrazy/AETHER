"""Durable, verified-account non-identity object mapping contracts."""

from __future__ import annotations

import ast
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from repositories.repos import reset_in_memory_stores
from services.provider_runtime.acquisition import ProviderAccountRecord, ProviderAccountRepository
from services.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
from services.provider_runtime.object_refs import (
    AccountEvidenceInvalid,
    ObjectAliasConflict,
    ProviderObjectRefRepository,
    SCHEMA_SQL,
    reset_object_ref_local_stores,
)
from services.provider_runtime import object_refs as object_ref_module
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.source_objects import SourceObjectRef


@pytest.fixture(autouse=True)
def _local_store(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_in_memory_stores()
    reset_object_ref_local_stores()
    yield
    reset_in_memory_stores()
    reset_object_ref_local_stores()


async def _verified_source(
    *,
    tenant_id: str = "tenant-a",
    connection_id: str = "conn-1",
    provider_identity: str = "shopify.admin.orders_read",
    realm: str = "live",
    immutable_account_id: str | None = "gid://shopify/Shop/123",
    selected: bool = True,
    verified: bool = True,
    object_id: str = "gid://shopify/Order/456",
) -> SourceObjectRef:
    selected_id = "shop:example.myshopify.com"
    await ProviderConnectionRepository().upsert(
        ProviderConnection(
            connection_id=connection_id,
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            state=ConnectionState.VERIFIED,
            selected_accounts=[selected_id] if selected else [],
            last_verified_at="2026-10-02T00:00:00+00:00" if verified else None,
        )
    )
    account_ref = f"{connection_id}:{selected_id}"
    await ProviderAccountRepository().upsert(
        ProviderAccountRecord(
            account_id=account_ref,
            tenant_id=tenant_id,
            connection_id=connection_id,
            provider_identity=provider_identity,
            external_id=immutable_account_id,
            metadata={"source_account_realm": realm},
        )
    )
    return SourceObjectRef(
        tenant_id=tenant_id,
        provider_identity=provider_identity,
        source_account_key=immutable_account_id or "gid://shopify/Shop/123",
        source_account_realm=realm,
        account_verification_ref=account_ref,
        source_object_type="order",
        source_object_id=object_id,
    )


@pytest.mark.asyncio
async def test_resolve_reuses_id_across_retries_and_verified_reconnect() -> None:
    source = await _verified_source()
    repo = ProviderObjectRefRepository()
    first = await repo.resolve(source)
    assert uuid.UUID(first).version == 4
    assert await repo.resolve(source) == first
    assert await repo.lookup(source) == first

    reconnect = await _verified_source(connection_id="conn-2")
    assert await repo.resolve(reconnect) == first
    assert await ProviderObjectRefRepository().lookup(reconnect) == first


@pytest.mark.asyncio
async def test_two_verified_capabilities_of_same_provider_share_object_mapping() -> None:
    first = await _verified_source()
    second = await _verified_source(
        connection_id="conn-products",
        provider_identity="shopify.admin.products_read",
    )
    repo = ProviderObjectRefRepository()
    assert await repo.resolve(first) == await repo.resolve(second)


@pytest.mark.asyncio
async def test_mapping_isolated_by_tenant_realm_account_and_object() -> None:
    repo = ProviderObjectRefRepository()
    first = await _verified_source()
    other_tenant = await _verified_source(tenant_id="tenant-b", connection_id="conn-b")
    other_realm = await _verified_source(realm="test", connection_id="conn-test")
    other_account = await _verified_source(
        immutable_account_id="gid://shopify/Shop/999", connection_id="conn-other"
    )
    other_object = first.model_copy(update={"source_object_id": "gid://shopify/Order/789"})
    identifiers = {
        await repo.resolve(first),
        await repo.resolve(other_tenant),
        await repo.resolve(other_realm),
        await repo.resolve(other_account),
        await repo.resolve(other_object),
    }
    assert len(identifiers) == 5


@pytest.mark.asyncio
async def test_concurrent_local_resolve_issues_one_id() -> None:
    source = await _verified_source()
    repos = [ProviderObjectRefRepository() for _ in range(12)]
    ids = await asyncio.gather(*(repo.resolve(source) for repo in repos))
    assert len(set(ids)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_overrides",
    [
        {"source_account_key": "unverified-account"},
        {"source_account_realm": "test"},
        {"tenant_id": "tenant-b"},
        {"provider_identity": "stripe.payments.payments_read"},
        {"account_verification_ref": "missing-account"},
    ],
)
async def test_mismatched_or_missing_account_evidence_fails_closed(
    source_overrides: dict[str, str],
) -> None:
    source = await _verified_source()
    with pytest.raises(AccountEvidenceInvalid):
        await ProviderObjectRefRepository().resolve(source.model_copy(update=source_overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence_overrides",
    [
        {"immutable_account_id": None},
        {"selected": False},
        {"verified": False},
    ],
)
async def test_unverified_discovery_or_connection_fails_closed(
    evidence_overrides: dict[str, object],
) -> None:
    source = await _verified_source(**evidence_overrides)
    with pytest.raises(AccountEvidenceInvalid):
        await ProviderObjectRefRepository().resolve(source)


@pytest.mark.asyncio
async def test_nonlocal_requires_existing_identity_hmac_key(monkeypatch) -> None:
    source = await _verified_source()
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.delenv("IDENTITY_HASH_KEY", raising=False)
    with pytest.raises(RuntimeError, match="IDENTITY_HASH_KEY"):
        await ProviderObjectRefRepository().resolve(source)


@pytest.mark.asyncio
async def test_local_database_mapping_also_requires_stable_hmac_key(monkeypatch) -> None:
    source = await _verified_source()
    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable/example")
    monkeypatch.delenv("IDENTITY_HASH_KEY", raising=False)
    with pytest.raises(RuntimeError, match="IDENTITY_HASH_KEY"):
        await ProviderObjectRefRepository().lookup(source)


@pytest.mark.asyncio
async def test_first_use_schema_creation_is_transactionally_serialized(monkeypatch) -> None:
    statements: list[str] = []
    transaction_open = False

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            nonlocal transaction_open
            transaction_open = True
            try:
                yield
            finally:
                transaction_open = False

        async def execute(self, query: str, *args):
            assert transaction_open
            statements.append(query)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    pool = Pool()

    async def get_test_pool():
        return pool

    monkeypatch.setattr(object_ref_module, "get_pool", get_test_pool)
    repository = ProviderObjectRefRepository()
    assert await repository._ensure() is pool
    assert "pg_advisory_xact_lock" in statements[0]
    assert statements[1] == SCHEMA_SQL
    assert not transaction_open


@pytest.mark.asyncio
async def test_alias_is_scoped_immutable_and_respects_validity() -> None:
    source = await _verified_source()
    other_order = source.model_copy(update={"source_object_id": "gid://shopify/Order/789"})
    other_tenant = await _verified_source(tenant_id="tenant-b", connection_id="conn-b")
    repo = ProviderObjectRefRepository()
    canonical_id = await repo.resolve(source)
    other_id = await repo.resolve(other_order)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    alias_id = await repo.add_alias(
        source.account,
        canonical_object_id=canonical_id,
        namespace="legacy_shopify",
        kind="order_id",
        value="legacy-123",
        reason="legacy_migration",
        evidence_ref="migration-audit-1",
        valid_from=start,
        valid_to=end,
    )
    assert alias_id.startswith("poalias_")
    assert (
        await repo.add_alias(
            source.account,
            canonical_object_id=canonical_id,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            reason="legacy_migration",
            evidence_ref="migration-audit-1",
            valid_from=start,
            valid_to=end,
        )
        == alias_id
    )
    assert (
        await repo.resolve_alias(
            source.account,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            at=start + timedelta(days=1),
        )
        == canonical_id
    )
    assert (
        await repo.resolve_alias(
            source.account,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            at=end,
        )
        is None
    )
    assert (
        await repo.resolve_alias(
            other_tenant.account,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            at=start + timedelta(days=1),
        )
        is None
    )
    with pytest.raises(ObjectAliasConflict):
        await repo.add_alias(
            source.account,
            canonical_object_id=other_id,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            reason="operator_correction",
            evidence_ref="audit-2",
        )
    with pytest.raises(ObjectAliasConflict):
        await repo.add_alias(
            other_tenant.account,
            canonical_object_id=canonical_id,
            namespace="legacy_shopify",
            kind="order_id",
            value="legacy-123",
            reason="legacy_migration",
            evidence_ref="audit-3",
        )


@pytest.mark.asyncio
async def test_sql_path_reuses_existing_concurrent_mapping_without_raw_ids() -> None:
    source = await _verified_source()
    expected = str(uuid.uuid4())

    class ConcurrentPool:
        def __init__(self):
            self.calls: list[tuple[str, tuple]] = []

        async def fetchrow(self, query: str, *args):
            self.calls.append((query, args))
            if query.startswith("INSERT"):
                return None
            return {"canonical_object_id": expected}

    fake = ConcurrentPool()
    repo = ProviderObjectRefRepository()
    repo._pool = fake
    repo._table_ensured = True
    assert await repo.resolve(source) == expected
    assert len(fake.calls) == 2
    bound = repr(fake.calls)
    assert source.source_account_key not in bound
    assert source.source_object_id not in bound
    assert source.account_verification_ref not in bound


@pytest.mark.asyncio
async def test_sql_path_retries_independent_uuid_collision(monkeypatch) -> None:
    source = await _verified_source()
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    candidates = iter((first_id, second_id))
    monkeypatch.setattr(object_ref_module, "_new_object_id", lambda: next(candidates))

    class CollisionPool:
        def __init__(self):
            self.inserts = 0

        async def fetchrow(self, query: str, *args):
            if query.startswith("INSERT"):
                self.inserts += 1
                return None if self.inserts == 1 else {"canonical_object_id": args[0]}
            return None

    fake = CollisionPool()
    repo = ProviderObjectRefRepository()
    repo._pool = fake
    repo._table_ensured = True
    assert await repo.resolve(source) == second_id
    assert fake.inserts == 2


def test_runtime_schema_matches_chained_alembic_migration() -> None:
    migration = Path(__file__).parents[2] / "alembic/versions/20261002_provider_object_refs.py"
    tree = ast.parse(migration.read_text())
    assignments = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        if target.id in {"SCHEMA_SQL", "revision", "down_revision"}
    }
    assert assignments["SCHEMA_SQL"] == SCHEMA_SQL
    assert assignments["revision"] == "20261002_provider_object_refs"
    assert assignments["down_revision"] == "20261002_tenant_connector_routes"
