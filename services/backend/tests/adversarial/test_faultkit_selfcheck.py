"""Self-check of the shared fault-injection harness primitives.

Proves the harness itself behaves deterministically before any capability
suite depends on it:

  * ``FaultInjector`` modes (never / once / always / on_nth / for_first_n)
  * ``arm`` on sync and async methods (raises then delegates, restorable)
  * ``transport_handler`` / ``mock_transport`` raise the classified fault and
    classify against a production classifier
  * ``PlanSource`` yields frames / raises exceptions in order
  * ``FaultyStore`` injects faults on selected methods and delegates the rest
  * ``expect_fault`` enforces the "distinguishable from empty" invariant

This module must stay green whenever the harness is in use — a regression
here is a regression in every capability's adversarial coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parent
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    BROKER_UNAVAILABLE,
    DB_UNAVAILABLE,
    PROVIDER_AUTH_FAILURE,
    PROVIDER_MALFORMED,
    PROVIDER_RATE_LIMITED,
    PROVIDER_TIMEOUT,
    PROVIDER_UNREACHABLE,
    REDIS_UNAVAILABLE,
    WORKER_CRASH,
    FaultInjector,
    FaultyStore,
    PlanSource,
    arm,
    expect_fault,
    frame,
    make_fault,
    mock_transport,
    transport_handler,
)


# ── FaultInjector modes ──────────────────────────────────────────────────

def test_injector_never_raises():
    inj = FaultInjector(make_fault(WORKER_CRASH), mode="never")
    inj.maybe_raise()
    inj.maybe_raise()
    assert inj.calls == 2 and inj.raised == 0


def test_injector_once_then_passes():
    inj = FaultInjector(make_fault(WORKER_CRASH), mode="once")
    with pytest.raises(Exception) as ei:
        inj.maybe_raise()
    assert faultkit.classify(ei.value) == WORKER_CRASH
    inj.maybe_raise()  # passes through
    assert inj.calls == 2 and inj.raised == 1


def test_injector_always_raises():
    inj = FaultInjector(make_fault(DB_UNAVAILABLE), mode="always")
    for _ in range(3):
        with pytest.raises(Exception) as ei:
            inj.maybe_raise()
        assert faultkit.classify(ei.value) == DB_UNAVAILABLE


def test_injector_on_nth_is_selective():
    inj = FaultInjector(make_fault(BROKER_UNAVAILABLE), mode="on_nth", nth=3)
    inj.maybe_raise()
    inj.maybe_raise()
    with pytest.raises(Exception) as ei:
        inj.maybe_raise()
    assert faultkit.classify(ei.value) == BROKER_UNAVAILABLE
    inj.maybe_raise()
    assert inj.raised == 1


def test_injector_for_first_n_then_recovers():
    inj = FaultInjector(make_fault(REDIS_UNAVAILABLE), mode="for_first_n", nth=2)
    for _ in range(2):
        with pytest.raises(Exception):
            inj.maybe_raise()
    inj.maybe_raise()  # recovered
    assert inj.raised == 2


def test_unknown_fault_classification_rejected():
    with pytest.raises(ValueError):
        make_fault("not_a_real_fault")


# ── arm / arm_func ───────────────────────────────────────────────────────

class _Dummy:
    def __init__(self):
        self.calls = 0

    def sync_work(self, x: int) -> int:
        self.calls += 1
        return x * 2

    async def async_work(self, x: int) -> int:
        self.calls += 1
        return x + 1


def test_arm_sync_raises_once_then_delegates_and_restores():
    dummy = _Dummy()
    restore = arm(dummy, "sync_work", FaultInjector(make_fault(DB_UNAVAILABLE), mode="once"))
    with pytest.raises(Exception):
        dummy.sync_work(1)
    assert dummy.calls == 0  # the injected call never reached the body
    assert dummy.sync_work(3) == 6
    assert dummy.calls == 1
    restore()
    assert dummy.sync_work(4) == 8
    assert dummy.calls == 2


@pytest.mark.asyncio
async def test_arm_async_raises_and_delegates():
    dummy = _Dummy()
    restore = arm(dummy, "async_work", FaultInjector(make_fault(WORKER_CRASH), mode="once"))
    with pytest.raises(Exception):
        await dummy.async_work(1)
    assert await dummy.async_work(5) == 6
    assert dummy.calls == 1
    restore()
    assert await dummy.async_work(9) == 10


# ── transport_handler / mock_transport ───────────────────────────────────

@pytest.mark.asyncio
async def test_transport_timeout_classified():
    client = httpx.AsyncClient(transport=mock_transport(fault_kind=PROVIDER_TIMEOUT))
    try:
        with pytest.raises(httpx.ConnectTimeout):
            await client.get("https://provider.example/info")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transport_rate_limit_returns_429():
    client = httpx.AsyncClient(transport=mock_transport(fault_kind=PROVIDER_RATE_LIMITED))
    try:
        response = await client.get("https://provider.example/info")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "0"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_transport_auth_failure_status(status):
    client = httpx.AsyncClient(
        transport=mock_transport(fault_kind=PROVIDER_AUTH_FAILURE, status=status)
    )
    try:
        response = await client.get("https://provider.example/info")
        assert response.status_code == status
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transport_malformed_body():
    client = httpx.AsyncClient(transport=mock_transport(fault_kind=PROVIDER_MALFORMED))
    try:
        response = await client.get("https://provider.example/info")
        assert response.text == "not-json{{{"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transport_after_serves_healthy_then_fault():
    handler = transport_handler(PROVIDER_UNREACHABLE, after=1)
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        ok = await client.get("https://provider.example/info")
        assert ok.status_code == 200
        with pytest.raises(httpx.ConnectError):
            await client.get("https://provider.example/info")
    finally:
        await client.aclose()


# ── PlanSource ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_source_yields_frames_and_raises():
    source = PlanSource([
        frame(1, {"fill_id": "f1"}),
        frame(1, {"fill_id": "f1"}),  # duplicate
        RuntimeError("socket dropped"),
    ])
    got = []
    with pytest.raises(RuntimeError):
        async for item in source(3):
            got.append(item)
    assert [p["payload"]["fill_id"] for p in got] == ["f1", "f1"]
    assert source.resume_cursors == [3]


# ── FaultyStore ──────────────────────────────────────────────────────────

class _FakeStore:
    def __init__(self):
        self.data = {}
        self.get_calls = 0

    async def get(self, key):
        self.get_calls += 1
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value


@pytest.mark.asyncio
async def test_faulty_store_injects_on_selected_method_only():
    store = _FakeStore()
    proxy = FaultyStore(store, {"set": FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")})
    with pytest.raises(Exception):
        await proxy.set("k", {"v": 1})
    assert store.data == {}  # the write never landed
    await proxy.set("k", {"v": 1})
    assert store.data["k"] == {"v": 1}
    assert await proxy.get("k") == {"v": 1}  # unlisted method delegates cleanly


# ── expect_fault ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expect_fault_passes_when_fault_raises():
    async def _boom():
        raise make_fault(DB_UNAVAILABLE)

    exc = await expect_fault(_boom(), DB_UNAVAILABLE)
    assert faultkit.classify(exc) == DB_UNAVAILABLE


@pytest.mark.asyncio
async def test_expect_fault_fails_on_silent_success():
    async def _healthy():
        return "ok"

    with pytest.raises(AssertionError, match="expected fault"):
        await expect_fault(_healthy(), DB_UNAVAILABLE)
