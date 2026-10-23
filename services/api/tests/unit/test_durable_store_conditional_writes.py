"""Conditional writes on ``DurableStore``: read-modify-write that never loses an update.

The commerce ledger (and any record updated by several API instances) needs a
write that fails when the record changed after it was read. The Redis and
DynamoDB tests run the store's real logic against small fakes that reproduce the
backends' contract: Redis ``WATCH``/``MULTI``/``EXEC`` and DynamoDB
``ConditionExpression`` with ``ConditionalCheckFailedException``. They do not
replace an integration run against the real services.
"""

from __future__ import annotations

import asyncio

import pytest
from botocore.exceptions import ClientError

import shared.store as store_mod
from shared.store import DurableStore, InMemoryStore, RedisStore, StoreConflictError, update_atomically


def _increment(current):
    return {"n": (current or {"n": 0})["n"] + 1}


async def _hammer(store: DurableStore, workers: int = 25) -> None:
    await asyncio.gather(
        *[store.atomic_update("counter", _increment, max_attempts=500) for _ in range(workers)]
    )
    assert (await store.get("counter"))["n"] == workers


# ---------------------------------------------------------------- in memory


class _YieldingMemoryStore(InMemoryStore):
    """Lets other writers run between the read and the conditional write."""

    async def get_versioned(self, key):
        result = await super().get_versioned(key)
        await asyncio.sleep(0)
        return result


@pytest.mark.asyncio
async def test_in_memory_rejects_a_stale_token():
    store = InMemoryStore("cas_stale")
    value, token = await store.get_versioned("k")
    assert value is None
    await store.set("k", {"n": 1})  # another writer gets in first
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False
    assert await store.get("k") == {"n": 1}


@pytest.mark.asyncio
async def test_in_memory_accepts_a_current_token_and_advances_it():
    store = InMemoryStore("cas_current")
    _, token = await store.get_versioned("k")
    assert await store.set_if_unchanged("k", {"n": 1}, token) is True
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False  # token is spent
    value, fresh = await store.get_versioned("k")
    assert value == {"n": 1}
    assert await store.set_if_unchanged("k", {"n": 2}, fresh) is True


@pytest.mark.asyncio
async def test_in_memory_delete_invalidates_outstanding_tokens():
    store = InMemoryStore("cas_delete")
    await store.set("k", {"n": 1})
    _, token = await store.get_versioned("k")
    await store.delete("k")
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False


@pytest.mark.asyncio
async def test_in_memory_write_without_ttl_clears_the_inherited_expiry():
    store = InMemoryStore("cas_ttl_clear")
    await store.set("k", {"n": 1}, ttl_seconds=100)
    _, token = await store.get_versioned("k")
    assert await store.set_if_unchanged("k", {"n": 2}, token) is True
    assert "k" not in store._expiry  # the new value no longer expires with the old one


@pytest.mark.asyncio
async def test_in_memory_expiry_invalidates_outstanding_tokens():
    import time

    store = InMemoryStore("cas_expiry")
    await store.set("k", {"n": 1}, ttl_seconds=100)
    value, token = await store.get_versioned("k")
    assert value == {"n": 1}
    store._expiry["k"] = time.time() - 1  # the TTL elapses after the read
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False
    assert await store.get("k") is None  # nothing was resurrected from the expired value


@pytest.mark.asyncio
async def test_in_memory_versioned_read_is_a_private_copy():
    store = InMemoryStore("cas_alias")
    await store.set("k", {"items": [1]})
    value, token = await store.get_versioned("k")
    value["items"].append(2)  # mutating the result must not touch the stored record
    assert await store.get("k") == {"items": [1]}
    assert await store.set_if_unchanged("k", {"items": [1, 3]}, token) is True


@pytest.mark.asyncio
async def test_atomic_update_loses_no_concurrent_updates():
    await _hammer(_YieldingMemoryStore("cas_hammer"))


@pytest.mark.asyncio
async def test_atomic_update_hands_the_mutator_a_private_copy():
    store = InMemoryStore("cas_copy")
    await store.set("k", {"items": [1]})
    seen = {}

    def mutate(current):
        seen["current"] = current
        current["items"].append(2)
        return current

    await store.atomic_update("k", mutate)
    assert seen["current"] == {"items": [1, 2]}
    assert await store.get("k") == {"items": [1, 2]}


@pytest.mark.asyncio
async def test_atomic_update_gives_up_after_bounded_attempts():
    class _AlwaysLoses(InMemoryStore):
        async def set_if_unchanged(self, key, value, token, ttl_seconds=0):
            return False

    store = _AlwaysLoses("cas_giveup")
    with pytest.raises(StoreConflictError):
        await store.atomic_update("k", _increment, max_attempts=3)
    assert await store.get("k") is None


@pytest.mark.asyncio
async def test_stores_without_conditional_writes_fall_back_to_a_per_key_lock():
    class _PlainStore(DurableStore):
        def __init__(self):
            self.rows = {}

        async def get(self, key):
            row = self.rows.get(key)
            await asyncio.sleep(0)
            return dict(row) if row is not None else None

        async def set(self, key, value, ttl_seconds=0):
            await asyncio.sleep(0)
            self.rows[key] = dict(value)

        async def delete(self, key):
            return self.rows.pop(key, None) is not None

        async def find(self, **filters):
            return []

        async def append_list(self, key, value):
            return None

        async def get_list(self, key, limit=100):
            return []

        async def count(self, **filters):
            return len(self.rows)

    await _hammer(_PlainStore())
    with pytest.raises(NotImplementedError):
        await _PlainStore().get_versioned("k")


# ------------------------------------------------------------------- redis


class _FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.versions: dict[str, int] = {}
        self.before_exec = None  # hook: a competing write between WATCH and EXEC

    def _write(self, key, value):
        self.data[key] = value
        self.versions[key] = self.versions.get(key, 0) + 1

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self._write(key, value)

    async def setex(self, key, _ttl, value):
        self._write(key, value)

    def pipeline(self, transaction=True):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.watched: dict[str, int] = {}
        self.ops: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def watch(self, key):
        self.watched[key] = self.redis.versions.get(key, 0)

    async def get(self, key):
        await asyncio.sleep(0)
        return self.redis.data.get(key)

    async def unwatch(self):
        self.watched.clear()

    def multi(self):
        return None

    def set(self, key, value):
        self.ops.append((key, value))
        return self

    def setex(self, key, _ttl, value):
        self.ops.append((key, value))
        return self

    async def execute(self):
        from redis.exceptions import WatchError

        if self.redis.before_exec:
            self.redis.before_exec()
        for key, version in self.watched.items():
            if self.redis.versions.get(key, 0) != version:
                raise WatchError()
        for key, value in self.ops:
            self.redis._write(key, value)
        return [True] * len(self.ops)


def _redis_store(fake: _FakeRedis) -> RedisStore:
    store = RedisStore("cas_redis", "redis://unused")
    store._init_attempted = True
    store._redis = fake
    return store


@pytest.mark.asyncio
async def test_redis_conditional_write_succeeds_when_unchanged():
    store = _redis_store(_FakeRedis())
    value, token = await store.get_versioned("k")
    assert (value, token) == (None, None)
    assert await store.set_if_unchanged("k", {"n": 1}, token) is True
    value, token = await store.get_versioned("k")
    assert value == {"n": 1}
    assert await store.set_if_unchanged("k", {"n": 2}, token, ttl_seconds=60) is True
    assert await store.get("k") == {"n": 2}


@pytest.mark.asyncio
async def test_redis_conditional_write_fails_when_the_value_changed_before_the_read():
    fake = _FakeRedis()
    store = _redis_store(fake)
    _, token = await store.get_versioned("k")
    await store.set("k", {"n": 9})
    assert await store.set_if_unchanged("k", {"n": 1}, token) is False
    assert await store.get("k") == {"n": 9}


@pytest.mark.asyncio
async def test_redis_conditional_write_fails_when_another_client_writes_before_exec():
    fake = _FakeRedis()
    store = _redis_store(fake)
    _, token = await store.get_versioned("k")
    # The value still matches the token at WATCH time, then a competing client
    # writes before EXEC: Redis aborts the transaction (WatchError).
    fake.before_exec = lambda: fake._write("aether:cas_redis:k", '{"n": 9}')
    assert await store.set_if_unchanged("k", {"n": 1}, token) is False
    assert await store.get("k") == {"n": 9}


@pytest.mark.asyncio
async def test_redis_atomic_update_loses_no_concurrent_updates():
    await _hammer(_redis_store(_FakeRedis()))


@pytest.mark.asyncio
async def test_redis_atomic_update_retries_after_a_same_value_rewrite_before_exec():
    """A rewrite of identical JSON (e.g. a TTL refresh) still aborts the transaction.

    ``atomic_update`` holds WATCH from the read, so it needs no payload comparison.
    """
    fake = _FakeRedis()
    store = _redis_store(fake)
    await store.set("k", {"n": 1})
    fired = []

    def rewrite_once():
        if not fired:
            fired.append(True)
            fake._write("aether:cas_redis:k", '{"n": 1}')  # same payload, new write

    fake.before_exec = rewrite_once
    result = await store.atomic_update("k", _increment)
    assert result == {"n": 2}
    assert fired == [True]  # the first attempt was aborted and retried
    assert await store.get("k") == {"n": 2}


@pytest.mark.asyncio
async def test_redis_atomic_update_gives_up_after_bounded_attempts():
    fake = _FakeRedis()
    store = _redis_store(fake)
    fake.before_exec = lambda: fake._write("aether:cas_redis:k", '{"n": 0}')  # always loses
    with pytest.raises(StoreConflictError):
        await store.atomic_update("k", _increment, max_attempts=3)


# ---------------------------------------------------------------- dynamodb


class _FakeDynamoTable:
    """Evaluates the conditional-put expressions ``DynamoDBStore`` builds."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.read_consistency: list[bool] = []

    def get_item(self, *, Key, ConsistentRead=False, **_):
        self.read_consistency.append(ConsistentRead)
        item = self.items.get(Key["cache_key"])
        return {"Item": dict(item)} if item else {}

    @staticmethod
    def _holds(existing, expression, names, values) -> bool:
        for part in expression.split(" AND "):
            part = part.strip()
            if part.startswith("attribute_not_exists("):
                attribute = names.get(part[21:-1], part[21:-1])
                if existing is not None and attribute in existing:
                    return False
            elif part.startswith("attribute_exists("):
                attribute = names.get(part[17:-1], part[17:-1])
                if existing is None or attribute not in existing:
                    return False
            else:
                left, right = (x.strip() for x in part.split("="))
                if existing is None or existing.get(names[left]) != values[right]:
                    return False
        return True

    def put_item(self, *, Item, ConditionExpression=None, ExpressionAttributeNames=None,
                 ExpressionAttributeValues=None):
        existing = self.items.get(Item["cache_key"])
        if ConditionExpression and not self._holds(
            existing, ConditionExpression,
            ExpressionAttributeNames or {}, ExpressionAttributeValues or {},
        ):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "failed"}},
                "PutItem",
            )
        self.items[Item["cache_key"]] = dict(Item)
        return {}


class _Boto3:
    def __init__(self, table):
        self._table = table

    def resource(self, _service):
        table = self._table

        class _Resource:
            def Table(self, _name):  # noqa: N802 - boto3 API
                return table

        return _Resource()


def _dynamo_store(monkeypatch, table: _FakeDynamoTable) -> store_mod.DynamoDBStore:
    monkeypatch.setattr(store_mod, "BOTO3_STORE_AVAILABLE", True)
    monkeypatch.setattr(store_mod, "_boto3_store", _Boto3(table))
    return store_mod.DynamoDBStore("cas_dynamo", "AETHER-staging-cache")


@pytest.mark.asyncio
async def test_dynamodb_creates_only_when_absent_and_then_matches_exact_content(monkeypatch):
    table = _FakeDynamoTable()
    store = _dynamo_store(monkeypatch, table)
    value, token = await store.get_versioned("k")
    assert (value, token) == (None, None)
    assert table.read_consistency == [True]  # the versioned read is strongly consistent
    assert await store.set_if_unchanged("k", {"n": 1}, token) is True
    # A second creator with the same stale "absent" token loses.
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False
    value, token = await store.get_versioned("k")
    assert value == {"n": 1}
    assert await store.set_if_unchanged("k", {"n": 2}, token) is True
    assert await store.set_if_unchanged("k", {"n": 3}, token) is False
    assert await store.get("k") == {"n": 2}


@pytest.mark.asyncio
async def test_dynamodb_replaces_an_expired_row_without_resurrecting_it(monkeypatch):
    table = _FakeDynamoTable()
    store = _dynamo_store(monkeypatch, table)
    await store.set("k", {"n": 1})
    table.items["aether:store:cas_dynamo:k"]["ttl"] = 1  # long expired
    value, token = await store.get_versioned("k")
    assert value is None
    assert await store.set_if_unchanged("k", {"n": 2}, token) is True
    assert await store.get("k") == {"n": 2}


@pytest.mark.asyncio
async def test_dynamodb_detects_a_same_content_rewrite_with_a_new_ttl(monkeypatch):
    """A refresh that stores identical JSON with a different TTL is still a change."""
    table = _FakeDynamoTable()
    store = _dynamo_store(monkeypatch, table)
    await store.set("k", {"n": 1}, ttl_seconds=3600)
    _, token = await store.get_versioned("k")
    await store.set("k", {"n": 1}, ttl_seconds=7200)  # same payload, refreshed TTL
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False
    assert await store.get("k") == {"n": 1}


@pytest.mark.asyncio
async def test_dynamodb_matches_rows_written_before_revisions_existed(monkeypatch):
    table = _FakeDynamoTable()
    store = _dynamo_store(monkeypatch, table)
    key = "aether:store:cas_dynamo:k"
    table.items[key] = {"cache_key": key, "val": '{"n": 1}', "ttl": 4102444800}  # no "rev"
    value, token = await store.get_versioned("k")
    assert value == {"n": 1}
    assert token[0] == "legacy"
    # TTL changed under a content-identical row: the legacy token must not match.
    table.items[key]["ttl"] = 4102448400
    assert await store.set_if_unchanged("k", {"n": 2}, token) is False
    value, token = await store.get_versioned("k")
    assert await store.set_if_unchanged("k", {"n": 2}, token) is True
    assert table.items[key]["rev"]  # rewritten rows carry a revision from now on


@pytest.mark.asyncio
async def test_dynamodb_propagates_unrelated_client_errors(monkeypatch):
    table = _FakeDynamoTable()
    store = _dynamo_store(monkeypatch, table)

    def boom(**_):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")

    table.put_item = boom
    with pytest.raises(ClientError):
        await store.set_if_unchanged("k", {"n": 1}, None)


@pytest.mark.asyncio
async def test_dynamodb_atomic_update_loses_no_concurrent_updates(monkeypatch):
    class _Yielding(store_mod.DynamoDBStore):
        async def get_versioned(self, key):
            result = await super().get_versioned(key)
            await asyncio.sleep(0)
            return result

    monkeypatch.setattr(store_mod, "BOTO3_STORE_AVAILABLE", True)
    monkeypatch.setattr(store_mod, "_boto3_store", _Boto3(_FakeDynamoTable()))
    await _hammer(_Yielding("cas_dynamo_hammer", "AETHER-staging-cache"))


@pytest.mark.asyncio
async def test_update_atomically_is_the_same_function_the_store_method_uses():
    store = InMemoryStore("cas_function")
    result = await update_atomically(store, "k", _increment)
    assert result == {"n": 1}
    assert await store.get("k") == {"n": 1}
