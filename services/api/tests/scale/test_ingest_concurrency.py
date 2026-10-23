"""Scale-readiness proofs on the real SDK ingestion spine (``ingest_batch``).

Load tests measure latency; these prove the properties that must hold *while*
the system is loaded: events are attributed to exactly one tenant, a duplicate
under concurrency is accepted once, and a transient failure never strands a
retry. They drive the production handler in-process with concurrent batches, so
a regression in claim ordering, tenant scoping or release-on-failure fails here
before any staging load run can show it.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from config.settings import Environment
from governance.security import audit_ledger as audit_module
from governance.security.request_context import bind_current_request
from ingestion.ingestion import batch
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import Permissions, Role, TenantContext
from shared.common.common import ServiceUnavailableError


class _Cache:
    """Shared claim store. ``set_nx`` yields so concurrent batches interleave."""

    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:  # noqa: ARG002 - matches CacheClient
        await asyncio.sleep(0)
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def get(self, key: str):
        await asyncio.sleep(0)
        return "1" if key in self.keys else None

    async def delete(self, key: str) -> None:
        self.keys.discard(key)


class _Producer:
    def __init__(self, fail_first: int = 0) -> None:
        self.published: list = []
        self._fail_remaining = fail_first

    async def publish_batch(self, events) -> None:
        await asyncio.sleep(0)
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise RuntimeError("bus unavailable")
        self.published.extend(events)


@pytest.fixture(autouse=True)
def _ingest_env(monkeypatch):
    reset_in_memory_stores()
    audit_module._TENANT_TAIL.clear()
    audit_module._TENANT_SEQ.clear()
    cache = _Cache()
    # The handler's own settings object: config.settings can be reloaded by other
    # tests, leaving a separately imported reference pointing at another copy.
    settings = batch.settings
    monkeypatch.setattr(settings, "env", Environment.LOCAL)
    monkeypatch.setattr(settings, "ingestion_v2", replace(
        settings.ingestion_v2, enabled=False, canary_tenants=frozenset(),
    ))
    monkeypatch.setattr(settings, "ingress_gateway", replace(
        settings.ingress_gateway, enabled=False,
    ))
    monkeypatch.setattr(batch, "get_registry", lambda: SimpleNamespace(cache=cache))
    yield cache
    reset_in_memory_stores()
    audit_module._TENANT_TAIL.clear()
    audit_module._TENANT_SEQ.clear()


def _request(tenant_id: str, request_id: str) -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/v1/batch",
        "headers": [(b"x-correlation-id", request_id.encode())],
        "server": ("test", 80), "client": ("127.0.0.1", 12345),
    })
    request.state.tenant = TenantContext(
        tenant_id=tenant_id, user_id=f"user-{tenant_id}", role=Role.ADMIN,
        permissions=[Permissions.WRITE],
    )
    request.state.request_id = request_id
    request.state.context = SimpleNamespace(tenant_id=tenant_id, correlation_id=request_id)
    return request


def _body(event_ids: list[str], session: str = "s1") -> batch.BatchRequest:
    return batch.BatchRequest(
        batch=[
            batch.BaseEvent(
                id=event_id, type="track", timestamp="2026-10-12T12:00:00+00:00",
                sessionId=session, anonymousId=f"anon-{session}", properties={"event": "opened"},
            )
            for event_id in event_ids
        ],
        sentAt="2026-10-12T12:00:01+00:00",
    )


async def _send(tenant_id: str, event_ids: list[str], producer, tag: str = "r") -> dict:
    request = _request(tenant_id, f"req-{tenant_id}-{tag}")
    bind_current_request(request)
    try:
        return await batch.ingest_batch(request, _body(event_ids), producer)
    finally:
        bind_current_request(None)


async def _bronze_event_ids(tenant_id: str) -> list[str]:
    rows = await BronzeRepository("sdk_events").find_many(
        filters={"tenant_id": tenant_id}, limit=5000,
    )
    return sorted(row["payload"]["event_id"] for row in rows)


# ── Tenant isolation while loaded ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_multi_tenant_ingest_never_cross_attributes():
    producer = _Producer()
    tenants = [f"tenant-{i}" for i in range(8)]
    sent: dict[str, list[str]] = {t: [] for t in tenants}
    jobs = []
    for tenant in tenants:
        for b in range(5):
            ids = [f"{tenant}-b{b}-e{e}" for e in range(10)]
            sent[tenant].extend(ids)
            jobs.append(_send(tenant, ids, producer, tag=f"b{b}"))
    responses = await asyncio.gather(*jobs)

    assert all(r["accepted"] == 10 and r["rejected"] == 0 for r in responses)
    for tenant in tenants:
        assert await _bronze_event_ids(tenant) == sorted(sent[tenant]), (
            f"{tenant} must hold exactly its own events"
        )
    assert len(producer.published) == len(tenants) * 50


@pytest.mark.asyncio
async def test_same_event_id_in_different_tenants_is_independent():
    """An event id is only unique within a tenant: tenant B reusing tenant A's id
    must neither be treated as a duplicate nor read or overwrite A's record."""
    producer = _Producer()
    tenants = [f"tenant-{i}" for i in range(6)]
    responses = await asyncio.gather(*[_send(t, ["shared-id"], producer) for t in tenants])
    assert [r["accepted"] for r in responses] == [1] * len(tenants)
    assert [r["duplicates"] for r in responses] == [0] * len(tenants)
    for tenant in tenants:
        assert await _bronze_event_ids(tenant) == ["shared-id"]


# ── Idempotency while loaded ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_identical_batches_are_accepted_exactly_once():
    producer = _Producer()
    responses = await asyncio.gather(
        *[_send("tenant-dup", ["evt-once"], producer, tag=str(i)) for i in range(25)]
    )
    assert sum(r["accepted"] for r in responses) == 1
    assert sum(r["duplicates"] for r in responses) == 24
    assert len(producer.published) == 1, "a duplicate must never be re-published"


@pytest.mark.asyncio
async def test_bronze_holds_one_row_per_event_under_concurrent_duplicates():
    producer = _Producer()
    await asyncio.gather(
        *[_send("tenant-dup", ["evt-a", "evt-b"], producer, tag=str(i)) for i in range(15)]
    )
    assert await _bronze_event_ids("tenant-dup") == ["evt-a", "evt-b"]


@pytest.mark.asyncio
async def test_overlapping_batches_split_the_events_with_no_loss_or_double_count():
    producer = _Producer()
    universe = [f"evt-{i:02d}" for i in range(20)]
    # Eleven concurrent batches each carrying a sliding, overlapping window.
    windows = [universe[i:i + 10] for i in range(11)]  # covers evt-00 .. evt-19
    responses = await asyncio.gather(
        *[_send("tenant-overlap", w, producer, tag=str(i)) for i, w in enumerate(windows)]
    )
    assert sum(r["accepted"] for r in responses) == len(universe)
    published_ids = sorted(e.payload["event_id"] for e in producer.published)
    assert published_ids == universe, "every event published exactly once, none lost"
    assert await _bronze_event_ids("tenant-overlap") == universe


# ── Retry safety ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_failure_releases_the_claim_so_a_retry_is_accepted():
    producer = _Producer(fail_first=1)
    with pytest.raises(ServiceUnavailableError):
        await _send("tenant-retry", ["evt-retry"], producer, tag="first")
    assert producer.published == []

    retried = await _send("tenant-retry", ["evt-retry"], producer, tag="retry")
    assert retried["accepted"] == 1 and retried["duplicates"] == 0
    assert [e.payload["event_id"] for e in producer.published] == ["evt-retry"]
    assert await _bronze_event_ids("tenant-retry") == ["evt-retry"], (
        "the failed attempt's Bronze write must not become a second row"
    )


@pytest.mark.asyncio
async def test_concurrent_retries_after_an_outage_publish_exactly_once():
    producer = _Producer(fail_first=3)
    results = await asyncio.gather(
        *[_send("tenant-storm", ["evt-storm"], producer, tag=str(i)) for i in range(10)],
        return_exceptions=True,
    )
    # Nothing is silently dropped: each request either got an answer or was told to retry.
    assert all(isinstance(r, (ServiceUnavailableError, dict)) for r in results)

    # A client that keeps retrying on 503 converges, and the event is published once.
    for attempt in range(10):
        if producer.published:
            break
        try:
            await _send("tenant-storm", ["evt-storm"], producer, tag=f"again-{attempt}")
        except ServiceUnavailableError:
            continue
    published = [e.payload["event_id"] for e in producer.published]
    assert published == ["evt-storm"], "converged on exactly one publish"
    assert await _bronze_event_ids("tenant-storm") == ["evt-storm"]


# ── Declared degradation: what happens when the claim store is down ──────────

class _BrokenCache(_Cache):
    async def set_nx(self, key, value, ttl):  # noqa: ARG002
        raise ConnectionError("claim store unavailable")


@pytest.mark.asyncio
async def test_claim_store_outage_fails_open_for_events_but_closed_for_identify(monkeypatch):
    """Availability over dedupe for ordinary events; identify mutates identity
    claims, so it is refused (and nothing is half-published) rather than admitted
    without its only duplicate guard."""
    monkeypatch.setattr(batch, "get_registry", lambda: SimpleNamespace(cache=_BrokenCache()))
    producer = _Producer()

    ok = await _send("tenant-outage", ["evt-open"], producer)
    assert ok["accepted"] == 1 and [e.payload["event_id"] for e in producer.published] == ["evt-open"]

    request = _request("tenant-outage", "req-identify")
    identify = batch.BatchRequest(
        batch=[batch.BaseEvent(
            id="evt-identify", type="identify", timestamp="2026-10-12T12:00:00+00:00",
            sessionId="s1", anonymousId="anon-s1", userId="user-1", properties={},
        )],
        sentAt="2026-10-12T12:00:01+00:00",
    )
    bind_current_request(request)
    try:
        with pytest.raises(ServiceUnavailableError):
            await batch.ingest_batch(request, identify, producer)
    finally:
        bind_current_request(None)
    assert [e.payload["event_id"] for e in producer.published] == ["evt-open"], (
        "a refused identify must not have published anything"
    )
