"""Regression: the generic Silver writer binds values by the COLUMN's type.

The lean-worker logged, for consented canonical SDK events:

* ``silver_write_failed table=silver_identity_evidence_facts error=invalid
  input for query argument $8: '2026-…+00:00' (expected a datetime.date or
  datetime.datetime instance, got 'str')`` — ``occurred_at`` (timestamptz)
  received the envelope's ISO-8601 string;
* ``silver_write_failed table=canonical_conversions error=invalid input for
  query argument $27: [] (expected str, got list)`` — ``product_ids`` (jsonb)
  received a Python list, because only ``payload``/``provenance``/
  ``properties`` were JSON-encoded, by *name*.

The writer now introspects each column's ``data_type`` and coerces at the
boundary. ``_StrictConn`` enforces asyncpg's binary-codec rules for the types
these tables use, so the tests fail exactly the way Postgres did.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

import services.silver.writer as writer_mod
from services.silver.projectors.base import ProjectionResult
from services.silver.projectors.conversion_projector import ConversionProjector
from services.silver.projectors.identity_evidence_projector import (
    IdentityEvidenceProjector,
)
from services.silver.writer import SilverFactWriter

_SILVER_COMMON = {
    "fact_id": "uuid",
    "tenant_id": "text",
    "source_event_id": "uuid",
    "source_event_type": "text",
    "actor_id": "text",
    "user_id": "text",
    "anonymous_id": "text",
    "org_id": "text",
    "occurred_at": "timestamp with time zone",
    "received_at": "timestamp with time zone",
    "consent_snapshot_id": "text",
    "privacy_class": "text",
    "idempotency_key": "text",
    "payload": "jsonb",
    "created_at": "timestamp with time zone",
}

# alembic/versions/20260622_silver_fact_tables.py + 20260622_measurement_core.py
_SCHEMAS: dict[str, dict[str, str]] = {
    "silver_identity_evidence_facts": {
        **_SILVER_COMMON,
        "event_kind": "text",
        "identity_method": "text",
        "mfa_type": "text",
        "device_id": "text",
        "confidence": "numeric",
        "linked_actor_id": "text",
    },
    "canonical_conversions": {
        "conversion_id": "uuid",
        "tenant_id": "text",
        "conversion_type": "text",
        "conversion_name": "text",
        "profile_id": "text",
        "order_id": "text",
        "gross_value": "numeric",
        "discount_value": "numeric",
        "tax_value": "numeric",
        "shipping_value": "numeric",
        "refund_value": "numeric",
        "currency": "text",
        "normalized_currency": "text",
        "exchange_rate": "numeric",
        "quantity": "integer",
        "product_ids": "jsonb",
        "line_items": "jsonb",
        "occurred_at": "timestamp with time zone",
        "observed_at": "timestamp with time zone",
        "confirmed_at": "timestamp with time zone",
        "conversion_status": "text",
        "conversion_source": "text",
        "authority_rank": "integer",
        "deduplication_key": "text",
        "attribution_eligible": "boolean",
        "provenance": "jsonb",
        "evidence_ids": "jsonb",
        "source_event_id": "text",
        "schema_version": "integer",
    },
}

_ACCEPTS: dict[str, tuple[type, ...]] = {
    "text": (str,),
    "uuid": (str,),
    "jsonb": (str,),  # no jsonb codec registered: asyncpg wants JSON text
    "timestamp with time zone": (datetime,),
    "numeric": (Decimal, str, int, float),  # asyncpg parses numeric text
    "integer": (int,),
    "boolean": (bool,),
}


class _StrictConn:
    def __init__(self, inserts: list[tuple[str, dict[str, Any]]]) -> None:
        self.inserts = inserts

    async def fetch(self, query: str, table: str) -> list[dict[str, str]]:
        assert "information_schema.columns" in query
        return [
            {"column_name": c, "data_type": t} for c, t in _SCHEMAS.get(table, {}).items()
        ]

    async def execute(self, query: str, *values: Any) -> str:
        table = query.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
        cols = [c.strip() for c in query.split("(", 1)[1].split(")", 1)[0].split(",")]
        schema = _SCHEMAS[table]
        for position, (col, value) in enumerate(zip(cols, values), start=1):
            if value is None:
                continue
            accepted = _ACCEPTS[schema[col]]
            if schema[col] == "integer" and isinstance(value, bool):
                accepted = ()
            if not isinstance(value, accepted):
                raise TypeError(
                    f"invalid input for query argument ${position}: {value!r} "
                    f"(expected {accepted}, got {type(value).__name__!r})"
                )
        self.inserts.append((table, dict(zip(cols, values))))
        return "INSERT 0 1"


class _Acquire:
    def __init__(self, conn: _StrictConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _StrictConn:
        return self.conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _StrictPool:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []

    def acquire(self) -> _Acquire:
        return _Acquire(_StrictConn(self.inserts))


@pytest.fixture
def strict_pool(monkeypatch):
    pool = _StrictPool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(writer_mod, "get_pool", _get_pool)
    monkeypatch.setattr(writer_mod, "_column_cache", {})
    errors: list[str] = []
    monkeypatch.setattr(
        writer_mod.logger, "error", lambda msg, *a, **k: errors.append(msg % a)
    )
    pool.errors = errors
    return pool


def _canonical_event(event_type: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "messageId": "3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01",
        "id": "3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01",
        "type": event_type,
        "timestamp": "2026-09-24T16:56:43.593515+00:00",
        "userId": "user_1",
        "anonymousId": "anon_1",
        "tenantId": "tenant_1",
        "properties": properties,
        "context": {"tenantId": "tenant_1", "surface": "web"},
    }


@pytest.mark.asyncio
async def test_identity_evidence_occurred_at_is_bound_as_datetime(strict_pool):
    result = IdentityEvidenceProjector().project(
        _canonical_event("signup_completed", {"method": "email", "confidence": 0.9})
    )

    written = await SilverFactWriter().persist([result])

    assert strict_pool.errors == []
    assert written == 1
    table, row = strict_pool.inserts[0]
    assert table == "silver_identity_evidence_facts"
    assert row["occurred_at"] == datetime(
        2026, 9, 24, 16, 56, 43, 593515, tzinfo=timezone.utc
    )
    assert row["confidence"] == Decimal("0.9")
    assert json.loads(row["payload"]) == {"method": "email", "confidence": 0.9}


@pytest.mark.asyncio
async def test_canonical_conversion_json_lists_are_json_encoded(strict_pool):
    result = ConversionProjector().project(
        _canonical_event("signup_completed", {"revenue": 42.5})
    )

    written = await SilverFactWriter().persist([result])

    assert strict_pool.errors == []
    assert written == 1
    _, row = strict_pool.inserts[0]
    assert row["product_ids"] == "[]"
    assert row["line_items"] == "[]"
    assert json.loads(row["evidence_ids"]) == ["3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01"]
    assert row["gross_value"] == Decimal("42.5")
    assert row["exchange_rate"] == Decimal("1.0")
    assert isinstance(row["occurred_at"], datetime)
    assert isinstance(row["observed_at"], datetime)


@pytest.mark.asyncio
async def test_unrepresentable_value_fails_loudly_and_names_the_column(strict_pool):
    bad = ProjectionResult(
        table="silver_identity_evidence_facts",
        rows=[{
            "tenant_id": "tenant_1",
            "source_event_id": "3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01",
            "source_event_type": "signup_completed",
            "occurred_at": "not-a-timestamp",
            "event_kind": "signup_completed",
        }],
    )

    written = await SilverFactWriter().persist([bad])

    assert written == 0
    assert strict_pool.inserts == []
    assert len(strict_pool.errors) == 1
    assert "silver_identity_evidence_facts.occurred_at" in strict_pool.errors[0]


@pytest.mark.parametrize(
    ("data_type", "value", "expected"),
    [
        ("timestamp with time zone", "2026-09-24T16:56:43Z",
         datetime(2026, 9, 24, 16, 56, 43, tzinfo=timezone.utc)),
        ("timestamp with time zone", "2026-09-24T16:56:43",
         datetime(2026, 9, 24, 16, 56, 43, tzinfo=timezone.utc)),
        ("jsonb", ["a", "b"], '["a", "b"]'),
        ("jsonb", {"k": 1}, '{"k": 1}'),
        ("jsonb", "scalar", '"scalar"'),
        ("numeric", 0.1, Decimal("0.1")),
        ("numeric", "12.50", Decimal("12.50")),
        ("integer", "3", 3),
        ("integer", 2.0, 2),
        ("boolean", "true", True),
        ("boolean", "false", False),
        ("text", ["x", "y"], '["x", "y"]'),
        ("text", 7, "7"),
        ("uuid", "3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01",
         "3f1e1c1a-6b8e-4c1e-9f3e-2d8a1b7c9e01"),
        ("ARRAY", ["a"], ["a"]),
        ("jsonb", None, None),
    ],
)
def test_coerce_value_matches_column_type(data_type, value, expected):
    assert writer_mod._coerce_value("t", "c", data_type, value) == expected


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        ("timestamp with time zone", 1727196000),
        ("integer", "1.5"),
        ("numeric", True),
        ("boolean", "maybe"),
    ],
)
def test_coerce_value_rejects_unrepresentable_values(data_type, value):
    with pytest.raises(ValueError, match=r"t\.c"):
        writer_mod._coerce_value("t", "c", data_type, value)
