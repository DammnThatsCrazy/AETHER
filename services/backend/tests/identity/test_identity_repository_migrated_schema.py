"""Regression: identity resolution against the MIGRATED identity schema.

The staging API logged ``Unexpected identity resolution error: column "data"
of relation "identity_signal_observations" does not exist`` for every event:
the ``IdentityResolutionRepository`` stores were default (JSONB-bag)
``BaseRepository`` subclasses, but ``20260612_identity_resolution_tables``
creates the identity tables with NAMED columns and a ``payload`` JSONB — no
``data`` column — so resolution aborted at its first write.

The schema below is not hand-copied: it is produced by running the real
migrations' ``upgrade()`` against a recording ``op`` and parsing the DDL they
emit. ``_MigratedPool`` then enforces what Postgres + asyncpg enforce for the
SQL ``BaseRepository`` generates: referenced columns must exist, ``NOT NULL``
columns without a default must be bound, ``timestamptz`` parameters must be
datetimes, json/jsonb parameters must be JSON text, text parameters must be
``str``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytest

import repositories.repos as repos
from services.identity.models import EdgeType, ConfidenceTier, IdentitySignalType
from services.identity.repository import IdentityResolutionRepository

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATIONS = (
    "20260612_identity_resolution_tables",
    "20260619_identity_suppression",
    "20260715_identity_merge_correctness",
    "20260924_identity_observation_entity_nullable",
)

_TYPE_MAP = {
    "TEXT": "text",
    "TIMESTAMPTZ": "timestamp with time zone",
    "JSONB": "jsonb",
    "DOUBLE PRECISION": "double precision",
    "BOOLEAN": "boolean",
    "INTEGER": "integer",
}


@dataclass
class _Col:
    data_type: str
    not_null: bool
    default: Optional[str]


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(str(sql))


def _migrated_schema() -> dict[str, dict[str, _Col]]:
    recorder = _RecordingOp()
    for name in _MIGRATIONS:
        path = _VERSIONS / f"{name}.py"
        if not path.exists():
            continue  # pre-fix tree: the relaxing migration does not exist yet
        spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = recorder
        module.upgrade()
    schema: dict[str, dict[str, _Col]] = {}
    for sql in recorder.statements:
        create = re.search(
            r"CREATE TABLE IF NOT EXISTS (\w+) \((.*)\)\s*$", sql, re.S
        )
        if create:
            cols: dict[str, _Col] = {}
            for line in create.group(2).splitlines():
                line = line.strip().rstrip(",")
                m = re.match(
                    r"(\w+) (TEXT|TIMESTAMPTZ|JSONB|DOUBLE PRECISION|BOOLEAN|INTEGER)(.*)$",
                    line,
                )
                if not m:
                    continue
                rest = m.group(3)
                default = re.search(r"DEFAULT (.+?)(?: NOT NULL)?$", rest)
                cols[m.group(1)] = _Col(
                    _TYPE_MAP[m.group(2)],
                    "NOT NULL" in rest or "PRIMARY KEY" in rest,
                    default.group(1) if default else None,
                )
            schema[create.group(1)] = cols
            continue
        add = re.search(
            r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) (TEXT|JSONB)", sql
        )
        if add:
            schema[add.group(1)][add.group(2)] = _Col(_TYPE_MAP[add.group(3)], False, None)
            continue
        drop_nn = re.search(
            r"ALTER TABLE (\w+)\s+ALTER COLUMN (\w+) DROP NOT NULL", sql
        )
        if drop_nn:
            schema[drop_nn.group(1)][drop_nn.group(2)].not_null = False
    return schema


class _UndefinedColumn(Exception):
    pass


class _NotNullViolation(Exception):
    pass


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _Conn:
    def __init__(self, pool: "_MigratedPool") -> None:
        self.pool = pool

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, query: str, *args: Any) -> str:
        return await self.pool.execute(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert "to_regclass" in query
        return args[0] in self.pool.schema


class _Acquire:
    def __init__(self, pool: "_MigratedPool") -> None:
        self.conn = _Conn(pool)

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


class _MigratedPool:
    """Tiny interpreter for the SQL shapes BaseRepository emits."""

    def __init__(self, schema: dict[str, dict[str, _Col]]) -> None:
        self.schema = schema
        self.rows: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in schema}

    def acquire(self) -> _Acquire:
        return _Acquire(self)

    # ── helpers ────────────────────────────────────────────────────────────
    def _columns(self, table: str) -> dict[str, _Col]:
        if table not in self.schema:
            raise _UndefinedColumn(f'relation "{table}" does not exist')
        return self.schema[table]

    def _require(self, table: str, col: str) -> _Col:
        cols = self._columns(table)
        if col not in cols:
            raise _UndefinedColumn(
                f'column "{col}" of relation "{table}" does not exist'
            )
        return cols[col]

    def _check_bind(self, table: str, col: str, value: Any) -> Any:
        spec = self._require(table, col)
        if value is None:
            if spec.not_null:
                raise _NotNullViolation(
                    f'null value in column "{col}" of relation "{table}" '
                    "violates not-null constraint"
                )
            return None
        ok = {
            "text": (str,),
            "timestamp with time zone": (datetime,),
            "jsonb": (str,),
            "double precision": (float, int),
            "boolean": (bool,),
            "integer": (int,),
        }[spec.data_type]
        if not isinstance(value, ok) or (
            spec.data_type in ("double precision", "integer") and isinstance(value, bool)
        ):
            raise TypeError(
                f"invalid input for {table}.{col}: {value!r} "
                f"(expected {spec.data_type}, got {type(value).__name__})"
            )
        if spec.data_type == "jsonb":
            json.loads(value)  # asyncpg sends it as jsonb text; must be valid
        return value

    def _default(self, spec: _Col) -> Any:
        if spec.default is None:
            return None
        if spec.default.startswith("now()"):
            return datetime.now().astimezone()
        literal = re.match(r"'(.*)'(?:::jsonb)?$", spec.default)
        if literal:
            return literal.group(1)
        try:
            return float(spec.default)
        except ValueError:
            return spec.default

    def _matches(self, table: str, row: dict[str, Any], where: str, args: tuple) -> bool:
        for cond in [c.strip() for c in where.split(" AND ")]:
            if cond in ("1=1", ""):
                continue
            m = re.fullmatch(r"(\w+)->>'(\w+)' = \$(\d+)", cond)
            if m:
                self._require(table, m.group(1))
                bag = json.loads(row.get(m.group(1)) or "{}")
                if _json_text(bag.get(m.group(2))) != args[int(m.group(3)) - 1]:
                    return False
                continue
            m = re.fullmatch(r"(\w+)->>'(\w+)' IS NULL", cond)
            if m:
                self._require(table, m.group(1))
                if json.loads(row.get(m.group(1)) or "{}").get(m.group(2)) is not None:
                    return False
                continue
            m = re.fullmatch(r"(\w+) = \$(\d+)", cond)
            if m:
                self._require(table, m.group(1))
                if _json_text(row.get(m.group(1))) != _json_text(args[int(m.group(2)) - 1]):
                    return False
                continue
            m = re.fullmatch(r"(\w+) IS NULL", cond)
            if m:
                self._require(table, m.group(1))
                if row.get(m.group(1)) is not None:
                    return False
                continue
            raise AssertionError(f"unsupported predicate {cond!r}")
        return True

    # ── asyncpg surface ────────────────────────────────────────────────────
    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "information_schema.columns" in query:
            return [
                {
                    "column_name": name,
                    "data_type": spec.data_type,
                    "is_nullable": "NO" if spec.not_null else "YES",
                    "column_default": spec.default,
                }
                for name, spec in self.schema.get(args[0], {}).items()
            ]
        m = re.search(
            r"SELECT (\*|data) FROM (\w+)\s+WHERE (.*?)\s+ORDER BY (\w+) (\w+)\s+LIMIT",
            query, re.S,
        )
        assert m, query
        select, table, where, order, _direction = m.groups()
        self._require(table, select if select != "*" else "id")
        self._require(table, order)
        return [
            dict(r) for r in self.rows[table].values()
            if self._matches(table, r, where, args)
        ]

    async def fetchrow(self, query: str, *args: Any) -> Optional[dict[str, Any]]:
        m = re.search(r"SELECT (\*|data) FROM (\w+) WHERE id = \$1", query)
        if m:
            if m.group(1) != "*":
                self._require(m.group(2), m.group(1))
            row = self.rows[m.group(2)].get(args[0])
            return dict(row) if row else None
        m = re.search(r"SELECT COUNT\(\*\) as cnt FROM (\w+) WHERE (.*)$", query, re.S)
        assert m, query
        table, where = m.groups()
        return {"cnt": sum(1 for r in self.rows[table].values()
                           if self._matches(table, r, where.strip(), args))}

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip()
        if q.startswith("SELECT pg_advisory") or q.startswith("CREATE INDEX"):
            return "OK"
        created = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", q)
        if created:
            # BaseRepository's runtime JSONB-bag bootstrap for tables no
            # migration owns (e.g. identity_decision_evidence).
            if created.group(1) not in self.schema:
                self.schema[created.group(1)] = {
                    "id": _Col("text", True, None),
                    "data": _Col("jsonb", True, "'{}'"),
                    "tenant_id": _Col("text", False, None),
                    "created_at": _Col("timestamp with time zone", False, "now()"),
                    "updated_at": _Col("timestamp with time zone", False, "now()"),
                }
                self.rows[created.group(1)] = {}
            return "CREATE TABLE"
        m = re.match(r"INSERT INTO (\w+) \(([^)]*)\)", q)
        if m:
            table = m.group(1)
            cols = [c.strip() for c in m.group(2).split(",")]
            row = {c: self._check_bind(table, c, v) for c, v in zip(cols, args)}
            for name, spec in self._columns(table).items():
                if name not in row:
                    row[name] = self._default(spec)
                    if row[name] is None and spec.not_null:
                        raise _NotNullViolation(
                            f'null value in column "{name}" of relation "{table}" '
                            "violates not-null constraint"
                        )
            self.rows[table][row["id"]] = row
            return "INSERT 0 1"
        m = re.match(r"UPDATE (\w+) SET (.*) WHERE id = \$(\d+)$", q, re.S)
        if m:
            table = m.group(1)
            row_id = args[int(m.group(3)) - 1]
            row = self.rows[table][row_id]
            for col, idx in re.findall(r"(\w+) = \$(\d+)", m.group(2)):
                row[col] = self._check_bind(table, col, args[int(idx) - 1])
            return "UPDATE 1"
        raise AssertionError(f"unsupported statement {q[:80]!r}")


@pytest.fixture
def migrated_pool(monkeypatch):
    pool = _MigratedPool(_migrated_schema())

    async def _get_pool():
        return pool

    monkeypatch.setattr(repos, "get_pool", _get_pool)
    monkeypatch.setattr(repos, "_EXPLICIT_COLUMN_TYPES", {}, raising=False)
    monkeypatch.setattr(repos, "_EXPLICIT_DEFAULTED_NOT_NULL", {}, raising=False)
    return pool


def test_schema_comes_from_the_real_migrations():
    schema = _migrated_schema()
    assert "data" not in schema["identity_signal_observations"]
    assert schema["identity_signal_observations"]["payload"].data_type == "jsonb"
    assert "merged_into_entity_id" in schema["identity_subjects"]


@pytest.mark.asyncio
async def test_observation_is_persisted_before_resolution_and_linked_after(migrated_pool):
    repo = IdentityResolutionRepository()
    tenant, event = "t-obs", str(uuid.uuid4())

    obs = await repo.create_signal_observation(
        tenant_id=tenant,
        source_event_id=event,
        source_platform="web",
        source_sdk="aether-web",
        signal_type=IdentitySignalType.ANONYMOUS_ID,
        signal_value_hash="h-anon",
        raw_value_redacted="an***",
        observed_at="2026-09-24T17:29:39.337750+00:00",
        consent_snapshot={"analytics": True},
        context={"source": "sdk"},
    )
    stored = migrated_pool.rows["identity_signal_observations"][obs["id"]]
    assert stored["canonical_entity_id"] is None
    assert stored["signal_hash"] == "h-anon"
    assert json.loads(stored["payload"]) == {
        "source_platform": "web",
        "source_sdk": "aether-web",
        "raw_value_redacted": "an***",
        "consent_snapshot": {"analytics": True},
        "context": {"source": "sdk"},
    }

    linked = await repo.set_observations_canonical_entity(tenant, event, "ent-1")
    assert linked == 1

    (row,) = await repo.get_observations_for_entity(tenant, "ent-1")
    assert row["canonical_entity_id"] == "ent-1"
    assert row["signal_value_hash"] == row["signal_hash"] == "h-anon"
    assert row["source_platform"] == "web"
    assert row["context"] == {"source": "sdk"}
    assert "payload" not in row


@pytest.mark.asyncio
async def test_alias_subject_edge_and_cluster_round_trip(migrated_pool):
    repo = IdentityResolutionRepository()
    tenant = "t-rt"

    subject = await repo.create_subject(tenant, "ent-a", metadata={"k": "v"})
    assert (await repo.get_subject_by_canonical_entity_id(tenant, "ent-a"))["metadata"] == {"k": "v"}
    await repo.mark_subject_merged_by_canonical_id(tenant, "ent-a", "ent-b")
    assert await repo.resolve_surviving_canonical_entity_id(tenant, "ent-a") == "ent-b"
    assert subject["id"] in migrated_pool.rows["identity_subjects"]

    alias = await repo.upsert_alias(
        tenant_id=tenant, canonical_entity_id="ent-b",
        alias_type=IdentitySignalType.USER_ID, alias_value_hash="h-user",
        source=None, source_platform="web",
    )
    assert migrated_pool.rows["identity_aliases"][alias["id"]]["alias_hash"] == "h-user"
    assert migrated_pool.rows["identity_aliases"][alias["id"]]["source"] == "sdk"  # column default
    assert await repo.find_entities_by_alias(tenant, IdentitySignalType.USER_ID, "h-user") == ["ent-b"]
    # Idempotent re-upsert updates the same row through the explicit columns.
    again = await repo.upsert_alias(
        tenant_id=tenant, canonical_entity_id="ent-b",
        alias_type=IdentitySignalType.USER_ID, alias_value_hash="h-user",
    )
    assert again["id"] == alias["id"]

    edge = await repo.create_identity_edge(
        tenant, "ent-a", "ent-b", EdgeType.SAME_AS, 0.9,
        ConfidenceTier.DETERMINISTIC, ["user_id_match"], ["e1"],
    )
    stored_edge = migrated_pool.rows["identity_edges"][edge["id"]]
    assert (stored_edge["from_entity_id"], stored_edge["to_entity_id"]) == ("ent-a", "ent-b")
    (graph_edge,) = await repo.get_entity_graph(tenant, "ent-b")
    assert graph_edge["source_entity_id"] == "ent-a"
    assert graph_edge["reason_codes"] == ["user_id_match"]
    assert graph_edge["source_event_ids"] == ["e1"]
    await repo.revoke_identity_edge(edge["id"])
    assert isinstance(migrated_pool.rows["identity_edges"][edge["id"]]["revoked_at"], datetime)

    cluster = await repo.upsert_cluster(tenant, "ent-b", 0.8, ["r1"])
    assert migrated_pool.rows["identity_clusters_v2"][cluster["id"]]["cluster_status"] == "active"
    bumped = await repo.upsert_cluster(tenant, "ent-b", 0.95, ["r1", "r2"])
    assert bumped["cluster_version"] == 2
    assert (await repo.get_identity_health(tenant))["total_clusters"] == 1


@pytest.mark.asyncio
async def test_suppression_rules_use_the_migrated_columns(migrated_pool):
    repo = IdentityResolutionRepository()
    tenant = "t-sup"

    assert await repo.check_suppression(tenant, "email_hash", "h1") is False
    rule = await repo.create_suppression_rule(
        tenant, "h1", "email_hash", reason="dsar", created_by="op"
    )
    assert "updated_at" not in migrated_pool.rows["identity_suppression_rules"][rule["id"]]
    assert await repo.check_suppression(tenant, "email_hash", "h1") is True
    await repo.revoke_suppression_rule(tenant, rule["id"])
    assert await repo.check_suppression(tenant, "email_hash", "h1") is False


@pytest.mark.asyncio
async def test_resolver_resolves_an_sdk_event_end_to_end(migrated_pool):
    from services.identity.audit import IdentityAuditWriter
    from services.identity.conflicts import IdentityConflictManager
    from services.identity.graph_writer import IdentityGraphWriter
    from services.identity.metrics import IdentityMetrics
    from services.identity.resolver import IdentityResolutionService

    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    event_id = str(uuid.uuid4())
    decision = await resolver.resolve_event(
        {
            "event_id": event_id,
            "tenant_id": "t-res",
            "user_id": "user_e2e",
            "anonymous_id": "anon_e2e",
            "session_id": "sess_e2e",
            "properties": {},
            "context": {},
        },
        "t-res",
    )

    assert "internal_error" not in decision.reason_codes
    assert decision.canonical_entity_id
    observations = list(migrated_pool.rows["identity_signal_observations"].values())
    # user_id + anonymous_id + session_id, each linked to the resolved entity.
    assert len(observations) == 3
    assert {o["canonical_entity_id"] for o in observations} == {
        decision.canonical_entity_id
    }
    (subject,) = migrated_pool.rows["identity_subjects"].values()
    assert subject["canonical_entity_id"] == decision.canonical_entity_id
    assert decision.audit_id in migrated_pool.rows["identity_resolution_audit"]
