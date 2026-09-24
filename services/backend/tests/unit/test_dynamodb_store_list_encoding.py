"""Regression: ``DynamoDBStore`` list values survive DynamoDB's type system.

The staging API logged ``observability trace append failed: Float types are
not supported. Use Decimal types instead.`` on every request: the trace record
carries ``duration_ms`` (a float) and ``DynamoDBStore.append_list`` handed the
raw dict to ``update_item``, whose boto3 ``TypeSerializer`` rejects floats (and
would return numbers as ``Decimal`` on read).

``_SerializingTable`` runs every attribute value through boto3's real
``TypeSerializer`` / ``TypeDeserializer`` — the exact code path that raised —
so the test fails the way the service did.
"""

from __future__ import annotations

import asyncio

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

import shared.store as store_mod

_SER = TypeSerializer()
_DESER = TypeDeserializer()


class _SerializingTable:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        wire = {k: _SER.serialize(v) for k, v in ExpressionAttributeValues.items()}
        values = {k: _DESER.deserialize(v) for k, v in wire.items()}
        item = self.items.setdefault(Key["cache_key"], dict(Key))
        item["items"] = list(item.get("items", values[":empty"])) + list(values[":item"])
        return {}

    def get_item(self, *, Key, ProjectionExpression=None, ExpressionAttributeNames=None):
        item = self.items.get(Key["cache_key"])
        return {"Item": dict(item)} if item else {}


class _Resource:
    def __init__(self, table: _SerializingTable) -> None:
        self._table = table

    def Table(self, _name):  # noqa: N802 - boto3 API
        return self._table


class _Boto3:
    def __init__(self, table: _SerializingTable) -> None:
        self._table = table

    def resource(self, _service):
        return _Resource(self._table)


def _store(monkeypatch, table: _SerializingTable) -> store_mod.DynamoDBStore:
    monkeypatch.setattr(store_mod, "_boto3_store", _Boto3(table))
    return store_mod.DynamoDBStore("observability_traces", "AETHER-staging-cache")


def test_trace_with_float_duration_round_trips(monkeypatch):
    table = _SerializingTable()
    store = _store(monkeypatch, table)
    trace = {
        "request_id": "req-1",
        "service": "aether-backend",
        "endpoint": "/v1/batch",
        "duration_ms": 12.75,
        "status": 200,
        "error": None,
        "metadata": {"latency_ratio": 0.5, "tags": ["a", 1.5]},
        "timestamp": "2026-09-24T17:37:19.604646+00:00",
        "tenant_id": "tenant-a",
    }

    async def exercise():
        await store.append_list("traces:tenant-a", trace)
        await store.append_list("traces:tenant-a", {**trace, "request_id": "req-2"})
        return await store.get_list("traces:tenant-a")

    got = asyncio.run(exercise())

    assert got == [trace, {**trace, "request_id": "req-2"}]
    assert isinstance(got[0]["duration_ms"], float)
    assert isinstance(got[0]["status"], int)


def test_legacy_map_elements_are_still_readable(monkeypatch):
    table = _SerializingTable()
    store = _store(monkeypatch, table)
    # An element written by the old encoding (float-free native map).
    table.update_item(
        Key={"cache_key": store._list_key("traces:t")},
        UpdateExpression="",
        ExpressionAttributeNames={},
        ExpressionAttributeValues={":empty": [], ":item": [{"request_id": "old", "status": 200}]},
    )

    async def exercise():
        await store.append_list("traces:t", {"request_id": "new", "duration_ms": 1.5})
        return await store.get_list("traces:t")

    got = asyncio.run(exercise())

    assert got == [
        {"request_id": "old", "status": 200},
        {"request_id": "new", "duration_ms": 1.5},
    ]
    assert isinstance(got[0]["status"], int)


def test_get_list_limit_keeps_the_newest(monkeypatch):
    store = _store(monkeypatch, _SerializingTable())

    async def exercise():
        for i in range(5):
            await store.append_list("k", {"i": i, "x": i / 2})
        return await store.get_list("k", limit=2), await store.get_list("k", limit=0)

    newest, none = asyncio.run(exercise())
    assert newest == [{"i": 3, "x": 1.5}, {"i": 4, "x": 2.0}]
    assert none == []
