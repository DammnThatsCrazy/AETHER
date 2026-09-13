"""DB-free tests for the Data Exchange Plane M3 saved import-mapping surface.

Covers the ``data_exchange_saved_mappings`` repository and the
``/v1/data-exchange/import-mappings`` router without any Postgres: the
repository's in-memory fallback is exercised with ``get_pool`` pinned to None,
mirroring the M1 ``test_storage_migration.py`` DB-free pattern.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from repositories.data_artifacts import reset_data_artifact_in_memory_store  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.data_exchange.contracts import ImportMappingContract  # noqa: E402
from services.data_exchange.saved_mappings import (  # noqa: E402
    SCHEMA_SQL,
    SavedImportMappingRepository,
    SavedMappingCreateBody,
    create_saved_mapping,
    delete_saved_mapping,
    get_data_exchange_saved_mappings_repository,
    get_saved_mapping,
    list_saved_mappings,
    reset_saved_mapping_in_memory_store,
    router,
)
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    monkeypatch.setattr("services.data_exchange.saved_mappings.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    reset_saved_mapping_in_memory_store()
    reset_in_memory_stores()
    yield
    reset_data_artifact_in_memory_store()
    reset_saved_mapping_in_memory_store()
    reset_in_memory_stores()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _contract(
    import_id: str = "imp_env_1",
    version: int = 1,
    *,
    tenant_id: str = TENANT_A,
    fields: list[dict] | None = None,
) -> ImportMappingContract:
    return ImportMappingContract(
        import_id=import_id,
        tenant_id=tenant_id,
        version=version,
        fields=fields
        or [
            {
                "source_column": "email",
                "primitive": "identifier",
                "target_field": "value",
                "transform": "none",
            }
        ],
        identity_policy={"match_keys": ["email"]},
        temporal_policy={},
        currency_policy={},
        geographic_policy={},
        consent_policy={},
        unknown_field_policy="error",
        created_by=None,
        created_at=_now(),
    )


# ── SCHEMA_SQL ──────────────────────────────────────────────────────────────


def test_schema_sql_defines_table_and_tenant_indexes() -> None:
    assert "CREATE TABLE IF NOT EXISTS data_exchange_saved_mappings" in SCHEMA_SQL
    assert "identity_policy JSONB NOT NULL DEFAULT '{}'::jsonb" in SCHEMA_SQL
    assert "fields JSONB NOT NULL DEFAULT '[]'::jsonb" in SCHEMA_SQL
    assert "ix_data_exchange_saved_mappings_tenant_name" in SCHEMA_SQL


# ── repository ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_crud_is_tenant_scoped() -> None:
    repo = SavedImportMappingRepository()
    row = await repo.create(TENANT_A, name="People import", contract=_contract())
    mapping_id = row["mapping_id"]
    assert mapping_id.startswith("demap_")
    assert row["version"] == 1
    assert row["name"] == "People import"
    assert row["unknown_field_policy"] == "error"

    got = await repo.get(TENANT_A, mapping_id)
    assert got["mapping_id"] == mapping_id
    assert got["identity_policy"]["match_keys"] == ["email"]
    assert got["fields"][0]["source_column"] == "email"

    # Cross-tenant reads fail closed.
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_B, mapping_id)

    # list is tenant-scoped and newest-first.
    await repo.create(TENANT_B, name="Other", contract=_contract(tenant_id=TENANT_B))
    await repo.create(TENANT_A, name="Second", contract=_contract(import_id="imp_env_2"))
    names = [r["name"] for r in await repo.list_for_tenant(TENANT_A)]
    assert names == ["Second", "People import"]

    # delete is tenant-scoped.
    assert await repo.delete(TENANT_B, mapping_id) is False
    assert await repo.delete(TENANT_A, mapping_id) is True
    with pytest.raises(NotFoundError):
        await repo.get(TENANT_A, mapping_id)


@pytest.mark.asyncio
async def test_repo_validates_inputs() -> None:
    repo = SavedImportMappingRepository()
    # blank display name
    with pytest.raises(BadRequestError):
        await repo.create(TENANT_A, name="", contract=_contract())
    # blank import_id is refused at the repo guard
    with pytest.raises(BadRequestError):
        await repo.create(
            TENANT_A,
            name="bad import",
            contract=_contract().model_copy(update={"import_id": ""}),
        )
    # ``version``/``unknown_field_policy`` are constrained by the pydantic
    # contract itself (ValidationError before the repo sees them), so those
    # repo guards are only reachable through non-pydantic entry points and are
    # not exercised here.


@pytest.mark.asyncio
async def test_repo_getter_singleton() -> None:
    assert get_data_exchange_saved_mappings_repository() is (
        get_data_exchange_saved_mappings_repository()
    )


# ── router surface ──────────────────────────────────────────────────────────


class _Tenant:
    def __init__(self, tenant_id: str, can: bool = True) -> None:
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self._can = can

    def require_permission(self, permission: str) -> None:
        if not self._can:
            from shared.common.common import ForbiddenError

            raise ForbiddenError(f"missing permission {permission!r}")

    def require_any_permission(self, *perms: str) -> None:
        if not self._can:
            from shared.common.common import ForbiddenError

            raise ForbiddenError(f"missing one of: {', '.join(perms)}")


class _Request:
    def __init__(self, tenant: _Tenant) -> None:
        self.state = SimpleNamespace(tenant=tenant, request_id="req-1")


def test_router_prefix_and_tags() -> None:
    assert router.prefix == "/v1/data-exchange/import-mappings"
    methods_by_path: dict[str, set[str]] = {}
    for r in router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or [])
    assert methods_by_path["/v1/data-exchange/import-mappings"] == {"GET", "POST"}
    assert methods_by_path["/v1/data-exchange/import-mappings/{mapping_id}"] == {
        "GET",
        "DELETE",
    }


@pytest.mark.asyncio
async def test_create_and_fetch_route_flow() -> None:
    req = _Request(_Tenant(TENANT_A))
    body = SavedMappingCreateBody(
        **_contract().model_dump(mode="json"),
        name="People import",
    )
    created = await create_saved_mapping(body=body, request=req)
    assert created["import_id"] == "imp_env_1"
    assert created["version"] == 1
    assert created["mapping_id"].startswith("demap_")

    got = await get_saved_mapping(created["mapping_id"], request=req)
    assert got["name"] == "People import"

    # Query defaults are injected explicitly (direct handler calls, no FastAPI DI).
    listing = await list_saved_mappings(request=req, limit=50, offset=0, import_id=None)
    assert listing["count"] == 1
    assert listing["mappings"][0]["mapping_id"] == created["mapping_id"]


@pytest.mark.asyncio
async def test_delete_route_flow() -> None:
    req = _Request(_Tenant(TENANT_A))
    body = SavedMappingCreateBody(
        **_contract().model_dump(mode="json"),
        name="To delete",
    )
    created = await create_saved_mapping(body=body, request=req)
    deleted = await delete_saved_mapping(created["mapping_id"], request=req)
    assert deleted == {"deleted": True, "mapping_id": created["mapping_id"]}
    with pytest.raises(NotFoundError):
        await get_saved_mapping(created["mapping_id"], request=req)


@pytest.mark.asyncio
async def test_cross_tenant_body_is_refused() -> None:
    req = _Request(_Tenant(TENANT_A))
    body = SavedMappingCreateBody(
        **_contract(tenant_id=TENANT_B).model_dump(mode="json"),
        name="Cross tenant",
    )
    from shared.common.common import ForbiddenError

    with pytest.raises(ForbiddenError):
        await create_saved_mapping(body=body, request=req)


# ── Postgres-branch regressions (command-status DELETE) ─────────────────────


class _FakePool:
    """Minimal asyncpg-like pool: enough to exercise the repo's Postgres branch.

    ``execute`` returns the command-status *string* asyncpg yields (``"DELETE 1"``),
    which has no ``.rowcount`` attribute — exactly the Postgres path the old code
    mishandled.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def execute(self, sql: str, *args: Any) -> str:  # noqa: ANN401
        head = sql.lstrip().upper()
        if head.startswith("CREATE"):
            return "CREATE TABLE"
        if head.startswith("DELETE"):
            tenant_id, mapping_id = args
            row = self._store.get(mapping_id)
            if row is not None and row.get("tenant_id") == tenant_id:
                del self._store[mapping_id]
                return "DELETE 1"
            return "DELETE 0"
        return "OK"

    async def fetchrow(self, sql: str, *args: Any) -> None:  # noqa: ANN401
        return None

    async def fetch(self, sql: str, *args: Any) -> list:  # noqa: ANN401
        return []


@pytest.mark.asyncio
async def test_delete_parses_postgres_command_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the Postgres branch ``delete`` must reflect the real DELETE count.

    ``pool.execute`` returns a command-status string, not a ``.rowcount``
    attribute; the old ``bool(getattr(result, "rowcount", 1))`` was always True,
    so deleting a missing/cross-tenant mapping returned 200 instead of 404.
    """
    fake = _FakePool()

    async def _pool() -> _FakePool:
        return fake

    monkeypatch.setattr("services.data_exchange.saved_mappings.get_pool", _pool)
    repo = SavedImportMappingRepository()
    fake._store["demap_pg"] = {"tenant_id": TENANT_A, "name": "seeded"}
    # First delete matches → command status "DELETE 1" → True.
    assert await repo.delete(TENANT_A, "demap_pg") is True
    # Now absent → "DELETE 0" → False, so the route can 404.
    assert await repo.delete(TENANT_A, "demap_pg") is False
    assert await repo.delete(TENANT_B, "demap_absent") is False


@pytest.mark.asyncio
async def test_delete_route_404s_on_missing_mapping_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing/cross-tenant DELETE returns 404 on the Postgres branch too.

    Proves the route now raises NotFoundError when the DELETE matched nothing —
    previously it returned ``{"deleted": true}`` (200) under Postgres while the
    in-memory fallback returned 404.  A FRESH repo is bound to the route so the
    module singleton never caches the fake pool across tests.
    """
    fake = _FakePool()
    fresh = SavedImportMappingRepository()

    async def _pool() -> _FakePool:
        return fake

    monkeypatch.setattr("services.data_exchange.saved_mappings.get_pool", _pool)
    monkeypatch.setattr(
        "services.data_exchange.saved_mappings.get_data_exchange_saved_mappings_repository",
        lambda: fresh,
    )
    req = _Request(_Tenant(TENANT_A))
    with pytest.raises(NotFoundError):
        await delete_saved_mapping("demap_missing", request=req)


@pytest.mark.asyncio
async def test_list_route_with_import_filter_honors_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The import_id-filtered list honors the caller's limit/offset.

    Regression for the route silently dropping the page and capping the feed at
    the repo default of 50 when ``import_id`` was provided.  A fresh repo keeps
    this test on the in-memory branch regardless of prior pool-state pollution.
    """
    monkeypatch.setattr(
        "services.data_exchange.saved_mappings.get_data_exchange_saved_mappings_repository",
        lambda: SavedImportMappingRepository(),
    )
    req = _Request(_Tenant(TENANT_A))
    for i in range(3):
        body = SavedMappingCreateBody(
            **_contract(import_id="imp_pag", version=1).model_dump(mode="json"),
            name=f"page {i}",
        )
        await create_saved_mapping(body=body, request=req)
    page = await list_saved_mappings(request=req, limit=2, offset=0, import_id="imp_pag")
    assert page["count"] == 2
    assert len(page["mappings"]) == 2
