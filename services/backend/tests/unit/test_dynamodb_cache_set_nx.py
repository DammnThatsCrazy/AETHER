"""DynamoDB cache backend parity for atomic claims.

Ingestion deduplicates retried events through ``cache.set_nx``. The DynamoDB
backend used by the lean staging/production profiles lacked the method, the
AttributeError was treated as a successful claim, and every retry was accepted
again instead of being reported as a duplicate.
"""

from __future__ import annotations

import asyncio
import inspect
import time

import pytest

from shared.cache import cache as cache_module


class _ConditionalCheckFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _Throttled(Exception):
    response = {"Error": {"Code": "ProvisionedThroughputExceededException"}}


class _FakeTable:
    """Evaluates the exact condition set_nx sends to DynamoDB."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.fail_with: Exception | None = None

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None,
                 ExpressionAttributeValues=None):
        if self.fail_with is not None:
            raise self.fail_with
        assert ConditionExpression == "attribute_not_exists(cache_key) OR #t < :now"
        assert ExpressionAttributeNames == {"#t": "ttl"}
        existing = self.items.get(Item["cache_key"])
        now = ExpressionAttributeValues[":now"]
        if existing is not None and not ("ttl" in existing and existing["ttl"] < now):
            raise _ConditionalCheckFailed()
        self.items[Item["cache_key"]] = dict(Item)


def _backend(table: _FakeTable):
    backend = cache_module._DynamoDBBackend.__new__(cache_module._DynamoDBBackend)
    backend._table_name = "AETHER-staging-cache"
    backend._table = table
    return backend


def test_set_nx_claims_once_and_reports_later_claims_as_taken():
    table = _FakeTable()
    backend = _backend(table)

    assert asyncio.run(backend.set_nx("aether:idempotency:e1", "1", ttl=60)) is True
    assert asyncio.run(backend.set_nx("aether:idempotency:e1", "1", ttl=60)) is False
    assert table.items["aether:idempotency:e1"]["ttl"] >= int(time.time()) + 59


def test_set_nx_reclaims_an_expired_item_dynamodb_has_not_swept_yet():
    table = _FakeTable()
    table.items["k"] = {"cache_key": "k", "val": "1", "ttl": int(time.time()) - 5}

    assert asyncio.run(_backend(table).set_nx("k", "1", ttl=60)) is True


def test_set_nx_propagates_errors_other_than_a_failed_condition():
    table = _FakeTable()
    table.fail_with = _Throttled()

    with pytest.raises(_Throttled):
        asyncio.run(_backend(table).set_nx("k", "1", ttl=60))


def test_dynamodb_backend_implements_every_redis_backend_operation():
    def public(cls):
        return {
            name for name, value in vars(cls).items()
            if not name.startswith("_") and inspect.isfunction(value)
        }

    missing = public(cache_module._RedisBackend) - public(cache_module._DynamoDBBackend)
    assert not missing, f"DynamoDB cache backend is missing {sorted(missing)}"
