"""Reward rail matrix + sender dispatch — P5 invariants.

Pins the classification matrix, the sender indirection (outbox can dispatch
every deliverable rail, not just tenant_webhook), the bidirectional validator,
and internal_credit double-entry idempotency.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from decimal import Decimal

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def test_matrix_generator_is_deterministic():
    from services.rewards.rail_matrix import build_rail_matrix

    assert build_rail_matrix() == build_rail_matrix()
    m = build_rail_matrix()
    assert m["summary"]["total"] == 10
    assert m["summary"]["by_tier"]["intentionally_unsupported"] == 2


def test_bidirectional_validator_passes():
    import subprocess

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    # locate repo root that holds scripts/
    here = os.path.dirname(__file__)
    repo = here
    for _ in range(6):
        repo = os.path.dirname(repo)
        if os.path.exists(os.path.join(repo, "scripts", "release", "check_reward_rail_matrix.py")):
            break
    proc = subprocess.run(
        [sys.executable, os.path.join(repo, "scripts", "release", "check_reward_rail_matrix.py")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_configurable_deliverable_rail_has_a_sender():
    from services.rewards.rail_matrix import CONFIGURABLE_TIERS, RAIL_MATRIX
    from services.rewards.senders import has_sender

    for name, c in RAIL_MATRIX.items():
        if c.tier in CONFIGURABLE_TIERS and c.delivery_mode in ("sync_api", "internal_ledger"):
            assert has_sender(name), f"{name} deliverable but has no sender"


def test_intentionally_unsupported_have_no_sender():
    from services.rewards.senders import has_sender

    assert not has_sender("loyalty_points")
    assert not has_sender("coupon")


@pytest.mark.asyncio
async def test_internal_credit_sender_double_entry_and_idempotent():
    from services.rewards.credit_ledger import get_internal_credit_ledger
    from services.rewards.senders import InternalCreditSender

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    job = {
        "tenant_id": tenant, "action_id": "a1",
        "payload": {
            "recipient_id": "r1", "campaign_id": "c1",
            "amount": "7.25", "currency": "USD", "idempotency_key": "idem-x",
        },
    }
    r1 = await InternalCreditSender().send(job)
    assert r1.outcome == "success"
    r2 = await InternalCreditSender().send(job)  # replay
    assert r2.outcome == "success"
    bal = await get_internal_credit_ledger().get_balance(tenant, "r1", "USD")
    assert bal == Decimal("7.25")  # not doubled


@pytest.mark.asyncio
async def test_internal_credit_cross_tenant_idempotency_key_collision_is_scoped():
    """Two tenants replaying the SAME idempotency_key must not collide.

    Pins the fix for the row-id bug: the ledger row id used to be derived
    from ``idempotency_key`` alone, so if two tenants both posted a common
    key like "order-123", the second tenant's post would read back the
    FIRST tenant's ledger entry as an idempotent replay, report success, and
    never credit its own recipient. Row identity must be scoped per tenant.
    """
    from services.rewards.credit_ledger import InternalCreditLedger

    ledger = InternalCreditLedger()
    shared_key = "order-123"

    entry_a = await ledger.credit(
        tenant_id="tenant-a", recipient_id="alice", campaign_id="c1",
        amount=Decimal("10.00"), currency="USD", idempotency_key=shared_key,
    )
    entry_b = await ledger.credit(
        tenant_id="tenant-b", recipient_id="bob", campaign_id="c1",
        amount=Decimal("25.00"), currency="USD", idempotency_key=shared_key,
    )

    # Independent ledger rows...
    assert entry_a["id"] != entry_b["id"]
    # ...and each tenant's own recipient was actually credited.
    bal_a = await ledger.get_balance("tenant-a", "alice", "USD")
    bal_b = await ledger.get_balance("tenant-b", "bob", "USD")
    assert bal_a == Decimal("10.00")
    assert bal_b == Decimal("25.00")

    # Replaying tenant A's post again must still be a same-tenant no-op —
    # scoping the id must not have broken ordinary idempotency.
    replay_a = await ledger.credit(
        tenant_id="tenant-a", recipient_id="alice", campaign_id="c1",
        amount=Decimal("10.00"), currency="USD", idempotency_key=shared_key,
    )
    assert replay_a["id"] == entry_a["id"]
    assert await ledger.get_balance("tenant-a", "alice", "USD") == Decimal("10.00")


@pytest.mark.asyncio
async def test_internal_credit_replay_repairs_balance_after_crash_before_apply():
    """A crash between the ledger insert and the balance increment must be
    repaired by the next retry, applying the balance exactly once.

    Pins the fix for the non-atomic insert-then-balance-update bug: if the
    process/db died after the ledger row was durably inserted but before
    ``_apply_balance`` ran, the old code's retry found the existing
    idempotency entry and returned immediately — the ledger recorded a
    credit the balance permanently never reflected. The entry now carries a
    ``balance_applied`` marker; a replay that finds it still ``False``
    re-applies the balance before returning, and never applies it twice.
    """
    from services.rewards.credit_ledger import InternalCreditLedger

    ledger = InternalCreditLedger()
    real_apply_balance = ledger._apply_balance
    calls = {"n": 0}

    async def _flaky_apply_balance(tenant_id, recipient_id, currency, delta):
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the process/db dying right as the balance step runs,
            # *after* the ledger insert already committed.
            raise RuntimeError("simulated crash between ledger insert and balance apply")
        return await real_apply_balance(tenant_id, recipient_id, currency, delta)

    ledger._apply_balance = _flaky_apply_balance

    with pytest.raises(RuntimeError, match="simulated crash"):
        await ledger.credit(
            tenant_id="tenant-c", recipient_id="carol", campaign_id="c2",
            amount=Decimal("50.00"), currency="USD", idempotency_key="crash-key",
        )

    # The ledger row is durable, but the balance must not have moved yet.
    entry_id = ledger._entry_id("tenant-c", "crash-key")
    stored = await ledger._ledger.find_by_id(entry_id)
    assert stored is not None
    assert stored["balance_applied"] is False
    assert await ledger.get_balance("tenant-c", "carol", "USD") == Decimal("0")

    # Retry (e.g. a redelivered outbox job): same idempotency key. The
    # replay path must notice the balance was never applied and repair it.
    result = await ledger.credit(
        tenant_id="tenant-c", recipient_id="carol", campaign_id="c2",
        amount=Decimal("50.00"), currency="USD", idempotency_key="crash-key",
    )
    assert result["balance_applied"] is True
    assert await ledger.get_balance("tenant-c", "carol", "USD") == Decimal("50.00")

    # A further replay after the repair must not double-apply.
    await ledger.credit(
        tenant_id="tenant-c", recipient_id="carol", campaign_id="c2",
        amount=Decimal("50.00"), currency="USD", idempotency_key="crash-key",
    )
    assert await ledger.get_balance("tenant-c", "carol", "USD") == Decimal("50.00")
    assert calls["n"] == 2  # first attempt failed, retry succeeded, no third apply


@pytest.mark.asyncio
async def test_internal_credit_concurrent_postings_do_not_lose_balance_updates():
    """Concurrent credits to the same recipient balance must all land.

    ``_apply_balance`` is a read-modify-write; without per-row serialization
    two concurrent postings can both read the same starting balance and one
    increment clobbers the other. Every posting here uses a distinct
    idempotency key (these are genuinely different credits, not replays of
    one another), so all of them must be reflected in the final balance.
    """
    from services.rewards.credit_ledger import InternalCreditLedger

    ledger = InternalCreditLedger()

    async def _post(i: int) -> None:
        await ledger.credit(
            tenant_id="tenant-d", recipient_id="dave", campaign_id="c3",
            amount=Decimal("1.00"), currency="USD",
            idempotency_key=f"concurrent-{i}",
        )

    await asyncio.gather(*(_post(i) for i in range(25)))

    assert await ledger.get_balance("tenant-d", "dave", "USD") == Decimal("25.00")


@pytest.mark.asyncio
async def test_stripe_credit_sender_fail_closed_without_credential(monkeypatch):
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "staging")
    job = {
        "tenant_id": f"t-{uuid.uuid4().hex[:8]}",
        "payload": {
            "customer_ref": "cus_x", "amount": "5.00",
            "currency": "usd", "idempotency_key": "s-idem",
        },
        "provider_config": {},
    }
    result = await StripeCreditSender().send(job)
    assert result.outcome == "fatal"
    assert "credential" in (result.error or "").lower()


# ═══════════════════════════════════════════════════════════════════════════
# stripe_credit credential slot (BUG 1 regression)
# ═══════════════════════════════════════════════════════════════════════════


def test_stripe_credit_slot_resolves_in_slot_registry():
    """The credential API validates every client-set slot_name against the
    registry (unknown slot -> 400). Before this declaration existed,
    stripe_credit/server_api_key was unresolvable and every send() failed
    fatally regardless of whether a tenant had a Stripe key on file."""
    from services.providers.credentials.slot_registry import get_slot

    slot = get_slot("stripe_credit", "server_api_key")
    assert slot is not None
    assert slot.provider == "stripe_credit"
    assert slot.slot_name == "server_api_key"
    assert slot.domain == "rewards"
    assert slot.required is True


@pytest.mark.asyncio
async def test_stripe_credit_credential_round_trips_through_authority():
    """End-to-end: a tenant can now store+activate a stripe_credit credential
    and the sender resolves it (instead of always hitting the fatal
    no-credential path)."""
    from services.providers.credentials.authority import credential_authority
    from services.rewards.senders import StripeCreditSender

    # AETHER_ENV=local (set by the autouse fixture) still maps
    # credential_environment() -> "sandbox"; it only needs to stay "local" so
    # the in-memory repo fallback is used (no DATABASE_URL in this test run).
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    pending = await credential_authority.create_pending(
        tenant, "stripe_credit", "sandbox", "server_api_key", "sk_test_abc123",
        created_by="admin",
    )
    await credential_authority.activate(
        tenant, "stripe_credit", "sandbox", "server_api_key",
        credential_version=int(pending["credential_version"]), actor="admin",
    )
    resolved = await credential_authority.get_active_secret(
        tenant, "stripe_credit", "sandbox", "server_api_key"
    )
    assert resolved == "sk_test_abc123"

    job = {
        "tenant_id": tenant,
        "payload": {
            "customer_ref": "cus_x", "amount": "5.00",
            "currency": "usd", "idempotency_key": "s-idem-resolved",
        },
        "provider_config": {},
    }
    result = await StripeCreditSender().send(job)
    # No longer fails on credential resolution; local/test AETHER_ENV short-
    # circuits the actual Stripe network call to a deterministic stub.
    assert result.outcome == "success"
    assert result.external_id == "cbt_local_s-idem-resolved"


# ═══════════════════════════════════════════════════════════════════════════
# stripe_credit currency minor-unit conversion (BUG 2 regression)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stripe_credit_usd_still_scaled_by_100(monkeypatch):
    """USD (a standard 2-decimal currency) keeps the existing *100 behavior."""
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "local")
    result = await StripeCreditSender()._stripe_customer_balance_credit(
        "sk_test_x", "cus_x", Decimal("5.00"), "usd", "idem-usd"
    )
    assert result["amount"] == -500


@pytest.mark.asyncio
async def test_stripe_credit_jpy_not_scaled_by_100(monkeypatch):
    """JPY is zero-decimal: a reward of 100 must post as 100 minor units, not
    10,000 (which would be a 100x over-credit)."""
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "local")
    result = await StripeCreditSender()._stripe_customer_balance_credit(
        "sk_test_x", "cus_x", Decimal("100"), "jpy", "idem-jpy"
    )
    assert result["amount"] == -100


@pytest.mark.asyncio
async def test_stripe_credit_three_decimal_currency_scaled_by_1000(monkeypatch):
    """BHD is three-decimal: 5.125 BHD posts as 5125 minor units."""
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "local")
    result = await StripeCreditSender()._stripe_customer_balance_credit(
        "sk_test_x", "cus_x", Decimal("5.125"), "bhd", "idem-bhd"
    )
    assert result["amount"] == -5125


@pytest.mark.asyncio
async def test_stripe_credit_unknown_currency_rejected(monkeypatch):
    """A currency with no known Stripe minor-unit exponent is refused rather
    than silently defaulted to 2 decimals."""
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "local")
    with pytest.raises(ValueError, match="unsupported currency"):
        await StripeCreditSender()._stripe_customer_balance_credit(
            "sk_test_x", "cus_x", Decimal("10"), "xyz", "idem-unknown"
        )


@pytest.mark.asyncio
async def test_stripe_credit_send_rejects_unknown_currency_as_fatal(monkeypatch):
    """Through the public send() path, an unsupported currency is a fatal
    (non-retryable) SenderResult, not an uncaught exception or a silent
    mis-scaled charge."""
    from services.providers.credentials.authority import credential_authority
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "local")
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    pending = await credential_authority.create_pending(
        tenant, "stripe_credit", "sandbox", "server_api_key", "sk_test_abc123",
        created_by="admin",
    )
    await credential_authority.activate(
        tenant, "stripe_credit", "sandbox", "server_api_key",
        credential_version=int(pending["credential_version"]), actor="admin",
    )
    job = {
        "tenant_id": tenant,
        "payload": {
            "customer_ref": "cus_x", "amount": "10",
            "currency": "xyz", "idempotency_key": "idem-unknown-send",
        },
        "provider_config": {},
    }
    result = await StripeCreditSender().send(job)
    assert result.outcome == "fatal"
    assert "currency" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_outbox_enqueue_refuses_rail_without_sender():
    from services.rewards.delivery_outbox import RewardDeliveryOutbox

    outbox = RewardDeliveryOutbox()
    with pytest.raises(ValueError, match="no registered outbox sender"):
        await outbox.enqueue({"rail": "loyalty_points", "payload": {}}, {}, "t1")


@pytest.mark.asyncio
async def test_outbox_dispatches_internal_credit_end_to_end():
    from services.rewards.credit_ledger import get_internal_credit_ledger
    from services.rewards.delivery_outbox import RewardDeliveryOutbox

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    outbox = RewardDeliveryOutbox()
    action = {
        "id": "act-1", "rail": "internal_credit",
        "payload": {
            "recipient_id": "r9", "campaign_id": "c9", "amount": "3.00",
            "currency": "USD", "idempotency_key": f"e2e-{uuid.uuid4().hex[:8]}",
        },
    }
    await outbox.enqueue(action, {}, tenant)
    summary = await outbox.drain()
    assert summary["delivered"] >= 1
    bal = await get_internal_credit_ledger().get_balance(tenant, "r9", "USD")
    assert bal == Decimal("3.00")
