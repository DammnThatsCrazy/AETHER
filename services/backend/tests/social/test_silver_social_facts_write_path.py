"""Social Silver write path — real forward writes for the six M3 projectors.

Before this work the six ``silver_social_*_facts`` tables the M3 Social Silver
projectors write had NO DDL and NO repository: against a real pool the generic
``SilverFactWriter`` path introspected ``information_schema``, found no columns,
logged ``silver_write_unknown_table`` and returned 0, so rows only ever lived in
the in-memory ``_local_tables`` fallback. This suite locks the new real forward
write path:

- integration: feed ``social_*_observed`` events through
  ``SilverDispatcher().project_with_outcome(...)`` →
  ``SilverFactWriter().persist(...)`` in local/no-pool mode and assert each row
  persists to the correct repository-backed in-memory table with the canonical
  domain columns (and does NOT fall through to the writer's generic
  ``_local_tables`` store);
- replay safety: re-persisting the same event stays first-write-wins, and a
  multi-record metric bundle fans out to one row per record with per-record
  idempotency keys;
- routing: monkeypatching each repository's ``upsert`` asserts the writer routes
  every one of the six tables to its named repository and never calls
  ``_persist_generic``;
- static DDL consistency: the Alembic migration (read, not executed) declares a
  column set that is exactly the repository column contract and a superset of
  every key the six projectors actually emit (minus the ephemeral ``surface`` /
  ``sequence_key`` envelope helpers that no silver fact table persists).

Runs hermetic in the local branch: ``get_pool`` is monkeypatched to ``None`` in
the modules under test regardless of the ambient ``AETHER_ENV`` (the same
technique the sibling backend repo suites use).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.silver.dispatcher import SilverDispatcher
from services.silver.writer import SilverFactWriter
from services.silver.repositories import social_facts as sf
from services.silver import writer as writer_module

_BACKEND = Path(__file__).resolve().parents[2]
_PROJECTORS_DIR = _BACKEND / "services" / "silver" / "projectors"
_MIGRATION_PATH = _BACKEND / "alembic" / "versions" / "20260904_social_silver_facts.py"

# event type -> (table, projector module filename)
_SOCIAL_TABLE_FILE = {
    "silver_social_identity_facts": "social_identity_projector.py",
    "silver_social_connection_facts": "social_connection_projector.py",
    "silver_social_interaction_facts": "social_interaction_projector.py",
    "silver_social_content_facts": "social_content_projector.py",
    "silver_social_community_facts": "social_community_projector.py",
    "silver_social_metric_facts": "social_metric_projector.py",
}


def _social_event(type_: str, *, message_id: str, props: dict) -> dict:
    """A Bronze social event carrying one provider record in ``properties``."""
    return {
        "type": type_,
        "messageId": message_id,
        "timestamp": "2026-09-01T00:00:00+00:00",
        "context": {
            "tenantId": "tenant-t1",
            "provider": {
                "provider": "x",
                "acquisition_mode": "poll",
                "provider_record_id": f"xr-{message_id}",
            },
        },
        "properties": props,
    }


@pytest.fixture(autouse=True)
def _local_no_pool_stores(monkeypatch: pytest.MonkeyPatch):
    """Force the in-memory branches of the writer + social repositories."""

    async def _no_pool():
        return None

    monkeypatch.setattr(sf, "get_pool", _no_pool)
    monkeypatch.setattr(writer_module, "get_pool", _no_pool)
    sf.reset_local_stores()
    writer_module.reset_local_tables()
    yield
    sf.reset_local_stores()
    writer_module.reset_local_tables()


async def _dispatch_and_persist(event: dict) -> None:
    outcome = await SilverDispatcher().project_with_outcome(event)
    await SilverFactWriter().persist(outcome.results)


# ── Integration: dispatcher → writer → repository local store ───────────────

_INTEGRATION_CASES: list[dict] = [
    {
        "type": "social_identity_observed",
        "table": "silver_social_identity_facts",
        "props": {
            "provider_account_id": "x-1",
            "handle": "alice",
            "display_name": "Alice",
            "account_type": "human",
            "verification_state": "provider_verified",
            "resolution_state": "resolved",
            "resolution_confidence": 0.95,
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "social_identity_id": "x:x-1",
            "provider_account_id": "x-1",
            "handle": "alice",
            "account_type": "human",
            "verification_state": "provider_verified",
            "resolution_confidence": 0.95,
        },
    },
    {
        "type": "social_connection_observed",
        "table": "silver_social_connection_facts",
        "props": {
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "follows",
            "directionality": "directed",
            "proof_level": "provider_observed",
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "source_social_identity_ref": "x:alice",
            "target_social_identity_ref": "x:bob",
            "connection_type": "follows",
            "directionality": "directed",
            "proof_level": "provider_observed",
        },
        # The connection projector emits a natural composite fact id (the reason
        # silver_social_connection_facts.fact_id is TEXT, not UUID).
        "fact_id_prefix": "x:",
    },
    {
        "type": "social_interaction_observed",
        "table": "silver_social_interaction_facts",
        "props": {
            "actor_social_identity_ref": "alice",
            "interaction_type": "like",
            "content_ref": "post-1",
            "occurred_at": "2026-09-01T00:00:00+00:00",
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "actor_social_identity_ref": "alice",
            "interaction_type": "like",
            "content_ref": "post-1",
        },
    },
    {
        "type": "social_content_observed",
        "table": "silver_social_content_facts",
        "props": {
            "author_social_identity_ref": "alice",
            "provider_content_id": "post-1",
            "content_type": "post",
            "content_hash": "abc123",
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "content_id": "x:post-1",
            "author_social_identity_ref": "x:alice",
            "provider_content_id": "post-1",
            "content_type": "post",
            "content_hash": "abc123",
        },
    },
    {
        "type": "social_community_membership_observed",
        "table": "silver_social_community_facts",
        "props": {
            "social_identity_ref": "alice",
            "community_ref": "comm-1",
            "membership_role": "member",
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "social_identity_ref": "x:alice",
            "community_ref": "x:comm-1",
            "membership_role": "member",
        },
    },
    {
        "type": "social_metric_observed",
        "table": "silver_social_metric_facts",
        "props": {
            "social_identity_ref": "alice",
            "metric_name": "follower_count",
            "value": 1234,
            "unit": "count",
            "status": "observed",
        },
        "expects": {
            "tenant_id": "tenant-t1",
            "social_identity_ref": "x:alice",
            "metric_name": "follower_count",
            "value": 1234,
            "unit": "count",
            "status": "observed",
        },
    },
]


def _case_id(case: dict) -> str:
    return case["table"].replace("silver_social_", "").replace("_facts", "")


@pytest.mark.parametrize("case", _INTEGRATION_CASES, ids=_case_id)
@pytest.mark.asyncio
async def test_social_event_persists_to_repo_table(case: dict) -> None:
    event_type = case["type"]
    table = case["table"]
    message_id = f"evt-{_case_id(case)}"
    await _dispatch_and_persist(
        _social_event(event_type, message_id=message_id, props=case["props"])
    )

    rows = sf.local_rows(table)
    assert len(rows) == 1, f"{table} should hold exactly one persisted row"
    row = rows[0]
    for key, value in case["expects"].items():
        assert row.get(key) == value, f"{table}.{key}: {row.get(key)!r} != {value!r}"

    # The six tables are special-cased — they must NOT land in the writer's
    # generic in-memory _local_tables (which has no DDL/columns behind it).
    assert table not in writer_module._local_tables
    # Repo defaults (the DB-side DEFAULTs on the migration) are always present.
    assert row.get("fact_id")
    assert row.get("received_at")
    assert row.get("privacy_class") == "behavioral"
    assert row.get("idempotency_key") == message_id  # single-record event
    assert row.get("source_event_id") == message_id
    assert row.get("occurred_at") == "2026-09-01T00:00:00+00:00"
    # The connection projector's natural fact id passes through the TEXT column.
    prefix = case.get("fact_id_prefix")
    if prefix:
        assert row["fact_id"].startswith(prefix), row["fact_id"]


@pytest.mark.parametrize("case", _INTEGRATION_CASES, ids=_case_id)
@pytest.mark.asyncio
async def test_social_event_replay_is_first_write_wins(case: dict) -> None:
    """Re-persisting the same Bronze event never duplicates a fact row."""
    event_type = case["type"]
    table = case["table"]
    message_id = f"evt-replay-{table}"
    event = _social_event(event_type, message_id=message_id, props=case["props"])

    for _ in range(3):
        await _dispatch_and_persist(event)

    assert len(sf.local_rows(table)) == 1


# ── Routing: writer dispatches each table to its named repository ───────────

@pytest.mark.asyncio
async def test_all_six_social_tables_route_to_named_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, list[dict]] = {t: [] for t in sf.SOCIAL_FACT_REPOSITORY_BY_TABLE}

    async def _record_upsert(self, row):
        calls[self.table].append(row)
        return row

    for table, repo_cls in sf.SOCIAL_FACT_REPOSITORY_BY_TABLE.items():
        monkeypatch.setattr(repo_cls, "upsert", _record_upsert)

    # Each integration case drives exactly one projector → one table.
    for case in _INTEGRATION_CASES:
        table = case["table"]
        message_id = f"evt-route-{table}"
        outcome = await SilverDispatcher().project_with_outcome(
            _social_event(case["type"], message_id=message_id, props=case["props"])
        )
        projected_rows = [r for r in outcome.results if r.table == table]
        assert len(projected_rows) == 1
        assert len(projected_rows[0].rows) == 1
        await SilverFactWriter().persist(outcome.results)

        assert len(calls[table]) == 1, (
            f"{table} should reach its repository upsert exactly once"
        )
        # The row landed under THIS table's repository channel and carries the
        # routed event — proving the writer picked the named repository.
        assert calls[table][0]["source_event_id"] == message_id


@pytest.mark.asyncio
async def test_social_tables_never_reach_generic_writer_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generic_calls: list[str] = []

    async def _spy_generic(table, rows):
        generic_calls.append(table)
        return len(rows)

    monkeypatch.setattr(SilverFactWriter, "_persist_generic", _spy_generic)

    for case in _INTEGRATION_CASES:
        await _dispatch_and_persist(
            _social_event(
                case["type"],
                message_id=f"evt-nogeneric-{case['table']}",
                props=case["props"],
            )
        )

    assert generic_calls == [], "the six social tables must never hit _persist_generic"


def test_writer_registry_agrees_with_social_repository_registry() -> None:
    """Two independent lists of the six tables must not drift."""
    assert sf.SOCIAL_FACT_REPOSITORY_BY_TABLE.keys() == set(
        writer_module._SOCIAL_FACT_TABLES
    )
    assert set(sf.SOCIAL_FACT_REPOSITORY_BY_TABLE) == set(_SOCIAL_TABLE_FILE)


@pytest.mark.asyncio
async def test_metric_bundle_fans_out_with_per_record_idempotency() -> None:
    """One multi-record metric event -> N rows, each with its own stable key."""
    event = _social_event(
        "social_metric_observed",
        message_id="evt-metric-bundle",
        props={
            "records": [
                {
                    "social_identity_ref": "alice",
                    "metric_name": "follower_count",
                    "value": 100,
                    "status": "observed",
                },
                {
                    "social_identity_ref": "alice",
                    "metric_name": "post_count",
                    "value": 7,
                    "status": "observed",
                },
            ]
        },
    )
    for _ in range(3):
        await _dispatch_and_persist(event)

    rows = sf.local_rows("silver_social_metric_facts")
    assert len(rows) == 2  # one row per metric, not per dispatch
    keys = {r["idempotency_key"] for r in rows}
    assert keys == {
        "evt-metric-bundle:follower_count",
        "evt-metric-bundle:post_count",
    }


@pytest.mark.asyncio
async def test_metric_honesty_null_value_never_becomes_zero() -> None:
    """An unavailable metric persists value=NULL + status, never a synthetic 0."""
    event = _social_event(
        "social_metric_observed",
        message_id="evt-metric-unavailable",
        props={
            "social_identity_ref": "alice",
            "metric_name": "private_engagement",
            "value": None,
            "status": "not_authorized",
        },
    )
    await _dispatch_and_persist(event)

    rows = sf.local_rows("silver_social_metric_facts")
    assert len(rows) == 1
    assert rows[0]["value"] is None
    assert rows[0]["status"] == "not_authorized"


# ── Static DDL-vs-projector-row-key consistency ─────────────────────────────

_COLUMN_LINE_SKIP_PREFIXES = (
    "CREATE", ")", "PRIMARY", "UNIQUE", "ON", "WHERE", "DROP", "REFERENCES",
    "CONSTRAINT", "FOREIGN",
)


def _column_names(sql_block: str) -> list[str]:
    """First identifier of each column-definition line in a SQL column block."""
    names: list[str] = []
    for line in sql_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        first = stripped.split(None, 1)[0]
        if first.startswith(_COLUMN_LINE_SKIP_PREFIXES):
            continue
        names.append(first)
    return names


def _migration_columns_by_table() -> dict[str, set[str]]:
    """AST-read the migration file: table -> set of declared column names.

    Parses the column blocks passed to ``_create_social_silver_table`` (the
    shared ``_SOCIAL_COMMON`` plus each table's own domain columns). Never
    executes the migration or imports Alembic.
    """
    tree = ast.parse(_MIGRATION_PATH.read_text(encoding="utf-8"))
    common_names: list[str] = []
    extra_by_table: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "_SOCIAL_COMMON"
                for t in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ):
            common_names = _column_names(str(node.value.value))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            for stmt in node.body:
                expr = stmt.value if isinstance(stmt, ast.Expr) else None
                if (
                    isinstance(expr, ast.Call)
                    and isinstance(expr.func, ast.Attribute)
                    and expr.func.attr == "execute"
                    and expr.args
                    and isinstance(expr.args[0], ast.Call)
                    and isinstance(expr.args[0].func, ast.Name)
                    and expr.args[0].func.id == "_create_social_silver_table"
                ):
                    inner = expr.args[0]
                    table = inner.args[0].value
                    if len(inner.args) > 1 and isinstance(inner.args[1], ast.Constant):
                        extra_by_table[table] = _column_names(str(inner.args[1].value))

    return {
        table: set(common_names) | set(extra_by_table[table])
        for table in extra_by_table
    }


def _return_dict_keys(source: str, method_name: str) -> set[str]:
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    for k in sub.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
    return keys


def _row_update_keys(source: str) -> set[str]:
    """String keys of ``row.update({...})`` literals (the projector row shape)."""
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "row"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            for k in node.args[0].keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _projector_emitted_keys(table: str) -> set[str]:
    base_src = (_PROJECTORS_DIR / "base.py").read_text(encoding="utf-8")
    social_base_src = (_PROJECTORS_DIR / "social_base.py").read_text(encoding="utf-8")
    proj_src = (
        _PROJECTORS_DIR / _SOCIAL_TABLE_FILE[table]
    ).read_text(encoding="utf-8")
    emitted = (
        _return_dict_keys(base_src, "_base_row")
        | _row_update_keys(social_base_src)
        | _row_update_keys(proj_src)
    )
    # Ephemeral envelope helpers BaseProjector puts on every row but no silver
    # fact table persists (incl. comms/touchpoint) — excluded from DDL coverage.
    emitted.discard("surface")
    emitted.discard("sequence_key")
    return emitted


@pytest.mark.parametrize("table", sorted(_SOCIAL_TABLE_FILE))
def test_migration_ddl_is_exactly_the_repo_column_contract(table: str) -> None:
    ddl = _migration_columns_by_table()[table]
    assert ddl == set(sf._TABLE_COLUMNS[table]), (
        f"{table}: DDL columns != repository column contract\n"
        f"  only in DDL:   {sorted(ddl - set(sf._TABLE_COLUMNS[table]))}\n"
        f"  only in repo:  {sorted(set(sf._TABLE_COLUMNS[table]) - ddl)}"
    )


@pytest.mark.parametrize("table", sorted(_SOCIAL_TABLE_FILE))
def test_projector_row_keys_are_covered_by_migration_ddl(table: str) -> None:
    """Every key the projector emits for a table exists as a DDL column."""
    ddl = _migration_columns_by_table()[table]
    missing = _projector_emitted_keys(table) - ddl
    assert not missing, f"{table}: DDL missing projector columns: {sorted(missing)}"
