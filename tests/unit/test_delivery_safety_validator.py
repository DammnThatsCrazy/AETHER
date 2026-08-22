"""Tests for scripts/release/validate_delivery_safety.py (M1b delivery-safety gate).

The validator must fail the build on five unsafe delivery patterns and must NOT
raise false positives on the legitimate pipeline uses. The patterns are proven
with small inline fixture strings (no files are written to the real tree), and a
whole-tree subprocess smoke test guards the gate itself.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import validate_delivery_safety as vds  # noqa: E402


def _patterns(rel_path: str, source: str) -> list[str]:
    return [v.pattern for v in vds.analyze(rel_path, source)]


# ── Pattern 1 — direct adapter dispatch outside the worker/router pipeline ──

def test_catches_direct_adapter_dispatch() -> None:
    src = """
from services.delivery.adapters.webhook import WebhookAdapter

async def send_slack_now(payload):
    # Bypasses the delivery worker / router pipeline entirely.
    return await WebhookAdapter().dispatch(payload, {"url": "https://example.com"})
"""
    assert "DIRECT_ADAPTER_DISPATCH" in _patterns("services/somewhere/routes.py", src)


def test_catches_registry_dispatch_outside_pipeline() -> None:
    src = """
from services.delivery.adapters.base import ProviderAdapterRegistry

async def send_now(channel, payload):
    adapter = ProviderAdapterRegistry.default().get_or_raise(channel)
    return await adapter.dispatch(payload=payload)
"""
    assert "DIRECT_ADAPTER_DISPATCH" in _patterns("services/somewhere/routes.py", src)


def test_allows_dispatch_inside_worker() -> None:
    src = """
from services.delivery.adapters.base import ProviderAdapterRegistry

class Worker:
    async def process(self, job):
        registry = ProviderAdapterRegistry.default()
        adapter = registry.get_or_raise(job["provider"])
        return await adapter.dispatch(payload=job["payload"])
"""
    assert "DIRECT_ADAPTER_DISPATCH" not in _patterns("services/delivery/worker.py", src)


def test_allows_internal_adapter_delegation() -> None:
    src = """
from services.delivery.adapters.webhook import WebhookAdapter
from services.delivery.adapters.base import AdapterReceipt

async def dispatch(self, payload, provider_config, *, credential, idempotency_key):
    receipt = await WebhookAdapter().dispatch(payload, provider_config)
    return AdapterReceipt(external_id=f"mkt:{receipt.external_id}", raw_response={}, http_status=200)
"""
    assert "DIRECT_ADAPTER_DISPATCH" not in _patterns("services/delivery/adapters/marketing.py", src)


# ── Pattern 2 — fire-and-forget task scheduling on delivery-critical work ──

def test_catches_bare_create_task() -> None:
    src = """
import asyncio

async def notify_critical():
    asyncio.create_task(send_notification())  # dropped at shutdown, no handle kept
"""
    assert "FIRE_AND_FORGET_TASK" in _patterns("services/notification_intelligence/x.py", src)


def test_catches_stored_but_never_awaited_task() -> None:
    src = """
import asyncio

class Worker:
    async def start(self):
        self._task = asyncio.create_task(self._poll())  # stored but never awaited/cancelled

    async def _poll(self):
        while True:
            await asyncio.sleep(1)
"""
    assert "FIRE_AND_FORGET_TASK" in _patterns("services/delivery/worker.py", src)


def test_allows_stored_and_awaited_worker_task() -> None:
    src = """
import asyncio

class Worker:
    async def start(self):
        self._task = asyncio.create_task(self._poll_loop(), name="delivery-worker")

    async def stop(self):
        self._task.cancel()
        await self._task
"""
    assert "FIRE_AND_FORGET_TASK" not in _patterns("services/delivery/worker.py", src)


def test_allows_tasks_collected_then_gathered() -> None:
    src = """
import asyncio

async def route(notifications):
    tasks = [asyncio.create_task(deliver(n)) for n in notifications]
    return await asyncio.gather(*tasks, return_exceptions=True)
"""
    assert "FIRE_AND_FORGET_TASK" not in _patterns("services/notification_intelligence/delivery_router.py", src)


def test_allows_append_then_gather() -> None:
    src = """
import asyncio

async def route(notifications):
    tasks = []
    for notification in notifications:
        tasks.append(asyncio.create_task(deliver(notification)))
    return await asyncio.gather(*tasks)
"""
    assert "FIRE_AND_FORGET_TASK" not in _patterns("services/notification_intelligence/delivery_router.py", src)


def test_allows_inline_await() -> None:
    src = """
import asyncio

async def send():
    await asyncio.create_task(post_message())
"""
    assert "FIRE_AND_FORGET_TASK" not in _patterns("services/notification_intelligence/x.py", src)


# ── Pattern 3 — unconfigured router (success without any config reference) ──

def test_catches_unconfigured_success() -> None:
    src = """
async def deliver(self, notification, config, credentials):
    # Never reads channel/recipient/destination configuration, yet claims success.
    return DeliveryResult(success=True, channel_type="slack", message_ref="ts-1")
"""
    assert "UNCONFIGURED_ROUTER" in _patterns("services/notification_intelligence/channel_gateway.py", src)


def test_allows_config_backed_success() -> None:
    src = """
async def deliver(self, notification, config, credentials):
    channel = config.get("channel_id") or "#aether-ops"
    status, body = await self._post(channel, notification)
    ok = bool(body.get("ok"))
    return DeliveryResult(success=ok, channel_type="slack")
"""
    assert "UNCONFIGURED_ROUTER" not in _patterns("services/notification_intelligence/channel_gateway.py", src)


# ── Pattern 4 — success with zero channels / recipients contacted ──

def test_catches_zero_channel_success() -> None:
    src = """
async def deliver(self, notification, channels):
    if not channels:
        return DeliveryResult(success=True, channel_type="slack")
    return DeliveryResult(success=True, channel_type="slack")
"""
    assert "ZERO_CHANNEL_SUCCESS" in _patterns("services/notification_intelligence/delivery_router.py", src)


def test_allows_zero_channel_failure() -> None:
    src = """
async def route(self, notification):
    channels = await self._load_channels(notification.tenant_id)
    if not channels:
        return []  # unknown stays unknown — no false success
    results = await asyncio.gather(*[self._deliver_one(notification, ch) for ch in channels])
    return results
"""
    assert "ZERO_CHANNEL_SUCCESS" not in _patterns("services/notification_intelligence/delivery_router.py", src)


def test_allows_empty_guard_raising() -> None:
    src = """
async def deliver(self, notification, recipients):
    if not recipients:
        raise RuntimeError("no recipients configured")
    return DeliveryResult(success=True, channel_type="email")
"""
    assert "ZERO_CHANNEL_SUCCESS" not in _patterns("services/notification_intelligence/x.py", src)


# ── Pattern 5 — simulated / provider-shaped fake receipts without env guard ──

def test_catches_literal_sim_receipt() -> None:
    src = """
def _simulate_receipt(self):
    return AdapterReceipt(external_id="sim-abc123", raw_response={}, http_status=200)
"""
    assert "SIMULATED_PROVIDER_RECEIPT" in _patterns("services/delivery/adapters/x.py", src)


def test_catches_local_fake_receipt_without_env_guard() -> None:
    src = """
def _local_fake_receipt(self, recipient):
    return AdapterReceipt(
        external_id="email-local-abc@fake.local",
        raw_response={"fake": True},
        http_status=202,
    )
"""
    assert "SIMULATED_PROVIDER_RECEIPT" in _patterns("services/delivery/adapters/email.py", src)


def test_allows_env_guarded_fake() -> None:
    src = """
def _fake_receipt(self, recipient):
    if not self._fake_allowed():
        raise ConfigurationError("no credential configured")
    return AdapterReceipt(
        external_id=f"{self.adapter_name}-local-{uuid.uuid4().hex}",
        raw_response={"fake": True, "env": settings.env.value},
        http_status=202,
    )
"""
    assert "SIMULATED_PROVIDER_RECEIPT" not in _patterns("services/delivery/adapters/_notification_base.py", src)


# ── Clean fixture ──

def test_clean_fixture_passes_all_patterns() -> None:
    src = """
\"\"\"Clean delivery worker — nothing unsafe.\"\"\"
import asyncio

from services.delivery.adapters.base import ProviderAdapterRegistry

class Worker:
    async def start(self):
        self._registry = ProviderAdapterRegistry.default()
        self._task = asyncio.create_task(self._poll_loop(), name="delivery-worker")

    async def stop(self):
        self._task.cancel()
        await self._task

    async def _poll_loop(self):
        while True:
            jobs = await self._lease_jobs()
            if not jobs:
                await asyncio.sleep(1)
                continue
            await asyncio.gather(*[self._process(job) for job in jobs])

    async def _process(self, job):
        adapter = self._registry.get_or_raise(job["provider"])
        return await adapter.dispatch(payload=job["payload"])
"""
    assert _patterns("services/delivery/worker.py", src) == []


# ── Whole-tree gate ──

def test_whole_tree_gate_passes() -> None:
    """The gate itself must pass on the current delivery path (exit 0)."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/release/validate_delivery_safety.py")],
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
