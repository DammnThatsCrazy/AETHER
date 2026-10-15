"""``20261015_tenant_owned_row_keys`` on a seeded database, run twice.

Needs PostgreSQL (``REPOSITORY_TEST_DATABASE_URL`` or ``DATABASE_URL``). The
migration runs inside a throwaway schema in a transaction that is rolled back,
so the shared database is untouched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest

PG_URL = os.getenv("REPOSITORY_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "20261015_tenant_owned_row_keys.py"
)

_JSONB_TABLE = """
    CREATE TABLE {name} (
        id TEXT PRIMARY KEY, data JSONB NOT NULL DEFAULT '{{}}', tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())
"""


def _load_migration():
    spec = importlib.util.spec_from_file_location("tenant_owned_row_keys", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    if not PG_URL:
        pytest.skip("REPOSITORY_TEST_DATABASE_URL not set")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    url = PG_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql://", "postgresql+psycopg2://", 1,
    )
    engine = sqlalchemy.create_engine(url)
    schema = f"mig_{uuid.uuid4().hex[:10]}"
    with engine.connect() as connection:
        connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        connection.exec_driver_sql(f"SET search_path TO {schema}")
        try:
            yield connection
        finally:
            connection.rollback()  # never committed: the schema goes with it
    engine.dispose()


def _put(conn, table: str, row_id: str, data: dict, tenant: str | None) -> None:
    conn.exec_driver_sql(
        f"INSERT INTO {table} (id, data, tenant_id) VALUES (%(id)s, %(data)s::jsonb, %(tenant)s)",
        {"id": row_id, "data": json.dumps({"id": row_id, **data}), "tenant": tenant},
    )


def _rows(conn, table: str) -> dict[str, tuple[str | None, dict]]:
    result = conn.exec_driver_sql(f"SELECT id, tenant_id, data FROM {table}")
    return {r[0]: (r[1], r[2]) for r in result}


def _seed(conn) -> None:
    for table in ("entities", "event_envelopes", "behavior_profiles", "journey_chains",
                  "commerce_facilitators", "commerce_resources", "web3_chains", "users"):
        conn.exec_driver_sql(_JSONB_TABLE.format(name=table))
    conn.exec_driver_sql("""
        CREATE TABLE graph_vertices (
            vertex_id TEXT PRIMARY KEY, vertex_type TEXT NOT NULL, tenant_id TEXT,
            properties JSONB NOT NULL DEFAULT '{}', created_at TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW())
    """)

    # JSON-only tenants; a row naming none; a row whose spellings disagree.
    _put(conn, "entities", "e-json", {"tenant_id": "ta"}, "")
    _put(conn, "entities", "e-none", {"display_name": "orphan"}, None)
    _put(conn, "entities", "e-split", {"tenant_id": "ta", "tenantId": "tb"}, "")
    _put(conn, "users", "u-1", {"tenant_id": "ta"}, "")
    _put(conn, "event_envelopes", "evt-1", {"tenantId": "ta", "payload": {"k": "a"}}, "")
    _put(conn, "event_envelopes", "evt-unowned", {"payload": {}}, "")

    _put(conn, "behavior_profiles", "user-1", {"entity_id": "user-1", "tenant_id": "ta"}, "ta")
    _put(conn, "behavior_profiles", "user-2", {"entity_id": "user-2", "tenant_id": "tb"}, "ta")
    _put(conn, "journey_chains", "chain:user-1",
         {"entity_id": "user-1", "tenant_id": "ta", "chain_id": "chain:user-1"}, "ta")

    _put(conn, "commerce_facilitators", "fac_circle_v2",
         {"facilitator_id": "fac_circle_v2", "tenant_id": "ta"}, "ta")
    _put(conn, "commerce_facilitators", "fac_local_aether",
         {"facilitator_id": "fac_local_aether", "tenant_id": "tb"}, "ta")
    _put(conn, "commerce_facilitators", "tb:fac_circle_v2",
         {"facilitator_id": "fac_circle_v2", "tenant_id": "tb"}, "tb")
    _put(conn, "commerce_resources", "demo-uuid",
         {"resource_id": "demo-uuid", "tenant_id": "ta", "data_origin": "synthetic_seed"}, "ta")

    _put(conn, "web3_chains", "ethereum", {"chain_id": "ethereum", "source": "seed"}, None)
    _put(conn, "web3_chains", "custom", {"chain_id": "custom", "source": "provider"}, None)

    for vid, tenant in (("chain:eip155:1", "public"), ("card_program:redotpay", "ta"),
                        ("user:1", "ta")):
        conn.exec_driver_sql(
            "INSERT INTO graph_vertices (vertex_id, vertex_type, tenant_id, properties) "
            "VALUES (%(v)s, 'X', %(t)s, %(p)s::jsonb)",
            {"v": vid, "t": tenant, "p": json.dumps({"tenant_id": tenant})},
        )


def _upgrade(conn) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = _load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def test_migration_rekeys_and_backfills_idempotently(conn):
    _seed(conn)
    _upgrade(conn)
    first = {t: _rows(conn, t) for t in (
        "entities", "users", "event_envelopes", "behavior_profiles", "journey_chains",
        "commerce_facilitators", "commerce_resources", "web3_chains",
    )}
    _upgrade(conn)
    second = {t: _rows(conn, t) for t in first}
    assert first == second

    entities = first["entities"]
    assert entities["e-json"][0] == "ta"
    assert entities["e-none"][0] is None
    assert entities["e-split"][0] == ""
    assert first["users"]["u-1"][0] == ""  # global table: untouched

    envelopes = first["event_envelopes"]
    assert set(envelopes) == {"ta:evt-1", "evt-unowned"}
    tenant, data = envelopes["ta:evt-1"]
    assert tenant == "ta" and data["envelope_id"] == "evt-1" and data["id"] == "ta:evt-1"

    profiles = first["behavior_profiles"]
    assert set(profiles) == {"ta:user-1"}  # contaminated user-2 row removed
    assert profiles["ta:user-1"][1]["id"] == "ta:user-1"
    chains = first["journey_chains"]
    assert set(chains) == {"ta:user-1"}
    assert chains["ta:user-1"][1]["chain_id"] == "journey_chain:ta:user-1"

    facilitators = first["commerce_facilitators"]
    assert set(facilitators) == {"ta:fac_circle_v2", "tb:fac_local_aether", "tb:fac_circle_v2"}
    assert facilitators["tb:fac_local_aether"][0] == "tb"
    assert set(first["commerce_resources"]) == {"demo-uuid"}

    chains_registry = first["web3_chains"]
    assert chains_registry["ethereum"][0] == "system"
    assert chains_registry["ethereum"][1]["tenant_id"] == "system"
    assert chains_registry["custom"][0] is None

    vertices = {
        r[0]: (r[1], r[2])
        for r in conn.exec_driver_sql("SELECT vertex_id, tenant_id, properties FROM graph_vertices")
    }
    for vid in ("chain:eip155:1", "card_program:redotpay"):
        tenant, props = vertices[vid]
        assert tenant == "platform"
        assert props["tenantId"] == props["tenant_id"] == "platform"
    assert vertices["user:1"][0] == "ta"


def test_migration_tolerates_missing_runtime_tables(conn):
    _upgrade(conn)
    _upgrade(conn)
