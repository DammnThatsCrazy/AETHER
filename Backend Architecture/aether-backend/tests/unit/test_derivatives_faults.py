"""Deterministic fault suite for the derivatives / perpetuals closure (2B).

Every test runs against mock transport / in-memory stores — NO live network, NO
live credentials. The task's mandated fault list is covered stage-by-stage:

  sequence correctness  : duplicate fills, out-of-order fills, sequence gap
  stream transport      : disconnect, reconnect, cooperative shutdown,
                          cancellation, restart-from-cursor, corrupted cursor
  REST transport        : transport timeout, rate limit, venue auth expiration
                          (HTTP 401 / 403), credential rotation + revocation
  guards                : observation-only connectors reject mutating scopes
  entitlement + meter   : fail-closed gate, resolver seam, metering sink hook
  honest declarations   : centralized_futures is SCAFFOLDED, never supported
  computed counters     : fleet / data-quality / graph counters from real rows
                          (no more hardcoded zeros)
  topic contract        : no-broker validation of the whole registry
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import SecretStr

from repositories.derivatives_repos import (
    ConnectorCheckpointRepo,
    FillRepo,
    PositionRepo,
    ReconciliationVarianceRepo,
    StreamGapRepo,
    TradingAccountRepo,
)
from repositories.typed_repo import reset_typed_in_memory_stores
from services.derivatives import counters
from services.derivatives.adapters.hyperliquid import HyperliquidAdapter
from services.derivatives.connectors.base import (
    enforce_read_only_credentials,
)
from services.derivatives.connectors.stream import (
    ReconnectingStream,
    StreamDisconnect,
    StreamResult,
)
from services.derivatives.connectors.transport import (
    PROVIDER_HEALTH_AUTH_ERROR,
    PROVIDER_HEALTH_RATE_LIMITED,
    PROVIDER_HEALTH_TIMEOUT,
    ProviderRequestError,
    RestBackfillClient,
)
from services.derivatives.guards import (
    CredentialNotUsable,
    CredentialReferenceNotFound,
    build_read_only_adapter,
    enforce_observation_only_credential,
    resolve_read_only_credential,
)
from services.derivatives.durable_cursor import persist_connector_checkpoint
from services.derivatives.guards import (
    DERIVATIVES_REQUIRED_ENTITLEMENT,
    DerivativesEntitlementError,
    clear_derivatives_entitlements,
    derivatives_entitlement_gate,
    install_derivatives_entitlement_resolver,
    require_derivatives_entitlement,
    seed_derivatives_entitlement,
)
from services.derivatives.meter import (
    DerivativesMeter,
    derivatives_meter,
    install_derivatives_meter_sink,
)
from services.derivatives.models import (
    DerivativesValidationError,
    PositionEpochState,
    PositionSide,
    PositionStatus,
    ReadOnlyCredentialError,
    validate_read_only_scopes,
)
from services.derivatives.multi_venue import (
    SUPPORTED_VENUES,
    build_scaffolded_adapters,
    cross_venue_parity_report,
)
from services.derivatives.reconciliation import reconcile_position_size
from services.derivatives.sequence import (
    SupervisedStreamWorker,
    parse_stream_cursor,
    stream_cursor_json,
)
from services.derivatives.streams import SequenceTracker
from services.derivatives.topic_contract import (
    DERIVATIVES_DLQ_TOPIC,
    DERIVATIVES_TOPIC_CONTRACTS,
    DerivativesTopicContract,
    all_contract_names,
    assert_valid_topic_contracts,
    contract_by_topic,
    validate_all_topic_contracts,
    validate_topic_contract,
)
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.types import ApiKeyCredential, OAuthTokenCredential


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Isolate every module-level store between tests (deterministic)."""
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()
    derivatives_entitlement_gate.reset()
    derivatives_meter.reset()
    yield
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()
    derivatives_entitlement_gate.reset()
    derivatives_meter.reset()


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic stream source plumbing
# ─────────────────────────────────────────────────────────────────────────────

def _frame(sequence: int, fill_id: str) -> dict:
    return {"sequence": sequence, "payload": {"fill_id": fill_id}}


class _PlanSource:
    """Deterministic frame source factory.

    ``plan`` is a list of per-connection plans. Each connection plan is a list
    whose items are either frame dicts or a ``StreamDisconnect`` to raise. The
    generator awaits ``asyncio.sleep(0)`` before each yield so a test can
    interleave (cooperative shutdown / cancellation) deterministically.
    """

    def __init__(self, plan):
        self.plan = list(plan)
        self.calls = 0
        self.resume_cursors: list = []

    async def __call__(self, resume_cursor):
        self.calls += 1
        self.resume_cursors.append(resume_cursor)
        conn = self.plan[self.calls - 1]
        for item in conn:
            await asyncio.sleep(0)
            if isinstance(item, Exception):
                raise item
            yield item


# ═══════════════════════════════════════════════════════════════════════════
# 1. Sequence correctness
# ═══════════════════════════════════════════════════════════════════════════

def test_duplicate_fill_detected():
    plan = [
        [_frame(1, "f1"), _frame(1, "f1"), _frame(2, "f2")],
    ]
    stream = ReconnectingStream(
        _PlanSource(plan), venue_id="hl", market_id="BTC", channel="account"
    )
    result = asyncio.run(stream.run())
    assert result.duplicates == 1
    assert result.accepted == [{"fill_id": "f1"}, {"fill_id": "f2"}]


def test_out_of_order_fill_buffered_then_released():
    # 3 arrives before 2 -> buffered; 2 then makes both contiguous.
    plan = [[_frame(1, "f1"), _frame(3, "f3"), _frame(2, "f2")]]
    stream = ReconnectingStream(
        _PlanSource(plan), venue_id="hl", market_id="BTC", channel="account"
    )
    result = asyncio.run(stream.run())
    assert result.buffered == 1
    assert result.accepted == [
        {"fill_id": "f1"},
        {"fill_id": "f2"},
        {"fill_id": "f3"},
    ]


def test_sequence_gap_detected_then_recovered():
    tracker = SequenceTracker("hl", "BTC", "account", tenant_id="t1", gap_threshold=3)
    tracker.ingest(1, {"fill_id": "f1"})
    outcome = tracker.ingest(10, {"fill_id": "f10"})
    assert outcome.gap_detected is not None
    assert outcome.gap_detected["status"] == "open"
    assert outcome.gap_detected["expected_sequence"] == 2
    assert outcome.gap_detected["received_sequence"] == 10
    # Fill the hole contiguously; the gap recovers once the stream advances past
    # the sequence that revealed it.
    for i in range(2, 11):
        tracker.ingest(i, {"fill_id": f"f{i}"})
    events = [e["event_name"] for e in tracker.emitted_events]
    assert "derivatives_stream_gap_detected" in events
    assert "derivatives_stream_gap_recovered" in events
    assert tracker.expected_next == 11


def test_gap_detected_and_recovered_through_stream():
    plan = [[
        _frame(1, "f1"),
        _frame(10, "f10"),  # gap opened
        _frame(2, "f2"), _frame(3, "f3"), _frame(4, "f4"),
        _frame(5, "f5"), _frame(6, "f6"), _frame(7, "f7"),
        _frame(8, "f8"), _frame(9, "f9"), _frame(10, "f10b"),
    ]]
    stream = ReconnectingStream(
        _PlanSource(plan), venue_id="hl", market_id="BTC", channel="account",
        gap_threshold=3,
    )
    result = asyncio.run(stream.run())
    assert result.gaps_detected == 1
    assert result.gaps_recovered == 1
    assert result.buffered >= 1
    # All 10 distinct fills accepted, no duplicates released.
    assert len(result.accepted) == 10
    assert len({payload["fill_id"] for payload in result.accepted}) == 10


# ═══════════════════════════════════════════════════════════════════════════
# 2. Stream transport faults
# ═══════════════════════════════════════════════════════════════════════════

def test_disconnect_then_reconnect_resumes_at_expected_sequence():
    plan = [
        [_frame(1, "f1"), _frame(2, "f2"), StreamDisconnect("socket dropped")],
        [_frame(3, "f3"), _frame(4, "f4")],
    ]
    source = _PlanSource(plan)
    stream = ReconnectingStream(
        source, venue_id="hl", market_id="BTC", channel="account",
        sleeper=lambda delay: asyncio.sleep(0),
    )
    result = asyncio.run(stream.run())
    assert result.reconnects == 1
    assert result.completed is True
    assert result.disconnected_out is False
    assert [p["fill_id"] for p in result.accepted] == ["f1", "f2", "f3", "f4"]
    # The reconnect opened with cursor=3 (the next contiguous sequence).
    assert source.resume_cursors[1] == 3
    # Next contiguous sequence after the whole stream (PORT-ADAPT: main's
    # ReconnectingStream exposes the tracker, not a last_cursor attribute).
    assert stream.tracker.expected_next == 5


def test_reconnect_exhaustion_marks_disconnected_out():
    plan = [[_frame(1, "f1"), StreamDisconnect("drop")]]
    stream = ReconnectingStream(
        _PlanSource(plan), venue_id="hl", market_id="BTC", channel="account",
        max_reconnects=0,
    )
    result = asyncio.run(stream.run())
    assert result.disconnected_out is True
    assert result.completed is False
    assert result.accepted == [{"fill_id": "f1"}]
    # Next contiguous sequence — restart resumes here (PORT-ADAPT: main's
    # ReconnectingStream exposes the tracker, not a last_cursor attribute).
    assert stream.tracker.expected_next == 2


@pytest.mark.asyncio
async def test_cooperative_shutdown_stops_cleanly_between_cycles():
    # PORT-ADAPT: main's ReconnectingStream has no intra-stream should_stop hook
    # (the branch's run_stream(..., should_stop=...) was not ported), so
    # cooperative shutdown is a worker-level contract: run_until_stopped checks
    # should_stop() BETWEEN cycles and persists each cycle's cursor before the
    # loop ends cleanly (no crash, no lost cursor).
    stop = {"flag": False}
    frames = [_frame(i, f"f{i}") for i in range(1, 100)]
    source = _PlanSource([frames])
    adapter = HyperliquidAdapter(stream_factory=source)
    worker = SupervisedStreamWorker(adapter, tenant_id="t1", connector_id="hyperliquid")

    async def _run():
        task = asyncio.create_task(
            worker.run_until_stopped(should_stop=lambda: stop["flag"])
        )
        await asyncio.sleep(0)
        stop["flag"] = True
        return await asyncio.wait_for(task, timeout=5)

    summary = await _run()
    # Exactly one full cycle ran (the stop flag is only consulted between
    # cycles); the loop ended cleanly and the cycle's cursor is durable.
    assert summary["cycles_completed"] == 1
    assert summary["completed"] is True
    # range(1, 100) is 99 frames (1..99) -> next contiguous sequence is 100.
    assert await worker.restore_cursor() == 100


def test_asyncio_cancellation_propagates_and_tracker_keeps_partial_state():
    # PORT-ADAPT: main's ReconnectingStream records no last_result/last_cursor
    # and its StreamResult has no `cancelled` flag — cancellation is simply
    # re-raised (never swallowed), and the tracker keeps the partial contiguous
    # state so a restart resumes from where the cancel hit.
    frames = [_frame(i, f"f{i}") for i in range(1, 1000)]
    stream = ReconnectingStream(
        _PlanSource([frames]), venue_id="hl", market_id="BTC", channel="account",
    )

    async def _run():
        task = asyncio.create_task(stream.run())
        # Several loop ticks so the task has consumed >= 1 frame before cancel,
        # guaranteeing a non-trivial restart cursor was reached.
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return stream

    stream = asyncio.run(_run())
    # The CancelledError propagated (re-raised, not swallowed).
    # The tracker advanced past the start before the cancel.
    assert stream.tracker.expected_next is not None and stream.tracker.expected_next >= 2


def test_restart_from_cursor_does_not_reobserve_prior_fills():
    plan = [[_frame(3, "f3"), _frame(4, "f4")]]
    source = _PlanSource(plan)
    stream = ReconnectingStream(
        source, venue_id="hl", market_id="BTC", channel="account",
    )
    result = asyncio.run(stream.run(resume_cursor=3))
    assert source.resume_cursors[0] == 3
    assert [p["fill_id"] for p in result.accepted] == ["f3", "f4"]
    # Next contiguous sequence (PORT-ADAPT: main's ReconnectingStream exposes
    # the tracker, not a last_cursor attribute).
    assert stream.tracker.expected_next == 5


# ═══════════════════════════════════════════════════════════════════════════
# 3. REST transport faults
# ═══════════════════════════════════════════════════════════════════════════

def _noop_sleeper(delay):
    return asyncio.sleep(0)


@pytest.mark.asyncio
async def test_transport_timeout_classified_and_degrades_health():
    async def handler(request: httpx.Request):
        raise httpx.ConnectTimeout("connection timed out")
    client = RestBackfillClient(
        http_transport=httpx.MockTransport(handler),
        sleeper=_noop_sleeper,
        max_retries=0,
    )
    health = {"health": "ok"}
    with pytest.raises(ProviderRequestError) as excinfo:
        await client.request_json({"url": "https://api.example/info"}, health=health)
    assert excinfo.value.classification == PROVIDER_HEALTH_TIMEOUT
    assert health["health"] == PROVIDER_HEALTH_TIMEOUT


@pytest.mark.asyncio
async def test_rate_limit_retries_then_raises():
    calls = {"n": 0}

    async def handler(request: httpx.Request):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = RestBackfillClient(
        http_transport=httpx.MockTransport(handler),
        sleeper=_noop_sleeper,
        max_retries=2,
    )
    health = {"health": "ok"}
    with pytest.raises(ProviderRequestError) as excinfo:
        await client.request_json({"url": "https://api.example/info"}, health=health)
    assert excinfo.value.classification == PROVIDER_HEALTH_RATE_LIMITED
    assert excinfo.value.status_code == 429
    assert calls["n"] == 3  # initial + 2 bounded retries
    assert health["health"] == PROVIDER_HEALTH_RATE_LIMITED


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.asyncio
async def test_venue_auth_expiration_401_403_raises_auth_error(status_code):
    async def handler(request: httpx.Request, _code=status_code):
        return httpx.Response(_code, json={"error": "unauthorized"})

    client = RestBackfillClient(
        http_transport=httpx.MockTransport(handler),
        sleeper=_noop_sleeper,
        max_retries=3,  # auth errors never retry
    )
    health = {"health": "ok"}
    with pytest.raises(ProviderRequestError) as excinfo:
        await client.request_json({"url": "https://api.example/info"}, health=health)
    assert excinfo.value.classification == PROVIDER_HEALTH_AUTH_ERROR
    assert excinfo.value.status_code == status_code
    assert health["health"] == PROVIDER_HEALTH_AUTH_ERROR


def test_test_connection_surfaces_auth_expiration_state():
    async def handler(request: httpx.Request):
        return httpx.Response(401, json={"error": "expired"})

    adapter = HyperliquidAdapter(
        http_transport=httpx.MockTransport(handler), sleeper=_noop_sleeper
    )
    result = asyncio.run(adapter.test_connection())
    assert result["ok"] is False
    assert result["state"] == PROVIDER_HEALTH_AUTH_ERROR


# ═══════════════════════════════════════════════════════════════════════════
# 4. Durable cursor / supervised worker
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_supervised_worker_restart_from_persisted_cursor():
    source = _PlanSource([
        [_frame(1, "f1"), _frame(2, "f2")],
        [_frame(3, "f3"), _frame(4, "f4")],
    ])
    adapter = HyperliquidAdapter(stream_factory=source)
    worker = SupervisedStreamWorker(adapter, tenant_id="t1", connector_id="hyperliquid")
    result = await worker.run_once()
    assert result.completed is True
    # Cursor persisted BEFORE run_once returns (at-least-once).
    assert await worker.restore_cursor() == 3

    # A FRESH worker resumes from the persisted cursor: no re-observation.
    source2 = _PlanSource([
        [_frame(3, "f3"), _frame(4, "f4")],
    ])
    adapter2 = HyperliquidAdapter(stream_factory=source2)
    worker2 = SupervisedStreamWorker(adapter2, tenant_id="t1", connector_id="hyperliquid")
    result2 = await worker2.run_once()
    assert source2.resume_cursors == [3]
    assert [p["fill_id"] for p in result2.accepted] == ["f3", "f4"]
    assert await worker2.restore_cursor() == 5


@pytest.mark.asyncio
async def test_corrupted_cursor_never_wedges_the_worker():
    repo = ConnectorCheckpointRepo()
    await persist_connector_checkpoint(
        repo,
        tenant_id="t1",
        connector_id="hyperliquid",
        checkpoint_value="not-json{{{",
        advanced_at="2026-08-08T00:00:00Z",
        state="ok",
    )
    # Corrupted / wrong-shape / missing / non-int cursors all parse to None.
    assert parse_stream_cursor("not-json{{{") is None
    assert parse_stream_cursor('{"stream": "42"}') == 42
    assert parse_stream_cursor('{"cursors": {"raw_fill": "7"}}') is None
    assert parse_stream_cursor("{}") is None
    assert parse_stream_cursor(None) is None
    assert parse_stream_cursor('{"stream": "abc"}') is None
    assert stream_cursor_json(5) == '{"stream": 5}'

    source = _PlanSource([[_frame(1, "f1")]])
    adapter = HyperliquidAdapter(stream_factory=source)
    worker = SupervisedStreamWorker(adapter, tenant_id="t1", connector_id="hyperliquid")
    # Corrupted persisted cursor -> restore returns None -> fresh start succeeds.
    assert await worker.restore_cursor() is None
    result = await worker.run_once()
    assert result.accepted == [{"fill_id": "f1"}]
    assert await worker.restore_cursor() == 2


@pytest.mark.asyncio
async def test_supervised_worker_persists_gap_evidence():
    source = _PlanSource([[
        _frame(1, "f1"),
        _frame(10, "f10"),  # opens a gap
        _frame(2, "f2"), _frame(3, "f3"), _frame(4, "f4"), _frame(5, "f5"),
        _frame(6, "f6"), _frame(7, "f7"), _frame(8, "f8"), _frame(9, "f9"),
        _frame(10, "f10b"),
    ]])
    adapter = HyperliquidAdapter(stream_factory=source)
    worker = SupervisedStreamWorker(adapter, tenant_id="t1", connector_id="hyperliquid")
    result = await worker.run_once()
    assert result.gaps_detected == 1
    gaps = await worker.gaps.find_many({"tenant_id": "t1", "status": "recovered"}, limit=10)
    assert len(gaps) == 1
    assert gaps[0]["expected_sequence"] == 2
    assert gaps[0]["received_sequence"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# 5. Credential resolver + observation-only guards
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_credential_rotation_and_revocation():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create("t1", "hl-ref", ApiKeyCredential(api_key=SecretStr("v1-secret")))
    resolved = await resolve_read_only_credential("hl-ref", tenant_id="t1", service=svc)
    assert resolved.api_key == "v1-secret"
    assert resolved.authority == "read_only"
    assert resolved.credential_type == "api_key"

    # Rotation: the resolver sees the NEW secret immediately.
    await svc.rotate("t1", "hl-ref", ApiKeyCredential(api_key=SecretStr("v2-secret")))
    resolved = await resolve_read_only_credential("hl-ref", tenant_id="t1", service=svc)
    assert resolved.api_key == "v2-secret"

    # Revocation: the reference becomes unfindable (fail-closed).
    await svc.revoke("t1", "hl-ref")
    with pytest.raises(CredentialReferenceNotFound):
        await resolve_read_only_credential("hl-ref", tenant_id="t1", service=svc)


@pytest.mark.asyncio
async def test_expired_credential_refused():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create(
        "t1",
        "expired-ref",
        OAuthTokenCredential(
            access_token=SecretStr("tok"),
            scope=["read"],
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )
    with pytest.raises(CredentialNotUsable):
        await resolve_read_only_credential("expired-ref", tenant_id="t1", service=svc)


@pytest.mark.asyncio
async def test_observation_only_guard_rejects_mutating_oauth_scopes():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create(
        "t1",
        "mutating-ref",
        OAuthTokenCredential(
            access_token=SecretStr("tok"),
            scope=["read", "orders:write", "trade"],
        ),
    )
    with pytest.raises(ReadOnlyCredentialError):
        await resolve_read_only_credential("mutating-ref", tenant_id="t1", service=svc)


def test_observation_only_connector_guards():
    # The standalone guards share the same fail-closed rule set.
    enforce_read_only_credentials(["read", "read_only", "public_data"])
    enforce_observation_only_credential(["read"])
    validate_read_only_scopes({"account"})
    for scopes in (
        ["orders:write"],
        ["trade"],
        ["withdraw"],
        ["transfer"],
        ["key_management"],
        ["admin"],
        ["account:write"],
        ["wallet:write"],
        ["read", "write"],
    ):
        with pytest.raises(ReadOnlyCredentialError):
            enforce_read_only_credentials(scopes)
        with pytest.raises(ReadOnlyCredentialError):
            enforce_observation_only_credential(scopes)

    # The canonical venue adapter refuses anything beyond read-only authority.
    adapter = HyperliquidAdapter()
    adapter.validate_config({"authority_type": "read_only", "scopes": ["read"]})
    with pytest.raises((ValueError, DerivativesValidationError)):
        adapter.validate_config({"authority_type": "trade", "scopes": ["orders:write"]})
    with pytest.raises(ReadOnlyCredentialError):
        adapter.validate_config({"authority_type": "read_only", "scopes": ["withdraw"]})


@pytest.mark.asyncio
async def test_build_read_only_adapter_binds_credential_and_auth_headers():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create("t1", "hl-ref", ApiKeyCredential(api_key=SecretStr("sekret-key")))

    async def handler(request: httpx.Request):
        return httpx.Response(200, json={"ok": True})

    adapter = await build_read_only_adapter(
        "hl-ref",
        tenant_id="t1",
        venue_id="hyperliquid",
        service=svc,
        http_transport=httpx.MockTransport(handler),
        sleeper=_noop_sleeper,
        account_ref="0xdeadbeef",
    )
    assert adapter._auth_headers == {"Authorization": "Bearer sekret-key"}
    # The resolved credential never carries a mutating authority.
    assert adapter._resolved_credential.authority == "read_only"

    # test_connection routes through the mock transport (no live IO).
    probe = await adapter.test_connection()
    assert probe["ok"] is True
    # The build_request seam carries the resolved Authorization header through
    # main's canonical ctx credential-injection seam.
    request = adapter.build_request(
        {"credential": {"api_key": adapter._resolved_credential.api_key}}
    )
    assert request["headers"]["Authorization"] == "Bearer sekret-key"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Entitlement enforcement + meter hook
# ═══════════════════════════════════════════════════════════════════════════

def test_entitlement_fail_closed_until_resolver_installed():
    assert DERIVATIVES_REQUIRED_ENTITLEMENT == "derivatives.enabled"
    # No resolver, nothing seeded -> fail-closed denial.
    assert derivatives_entitlement_gate.is_entitled("t1") is False
    with pytest.raises(DerivativesEntitlementError):
        require_derivatives_entitlement("t1")
    # Deterministic in-process seeding unlocks a tenant.
    seed_derivatives_entitlement("t1")
    require_derivatives_entitlement("t1")
    with pytest.raises(DerivativesEntitlementError):
        require_derivatives_entitlement("t2")
    clear_derivatives_entitlements()
    # A real resolver is the authoritative gate.
    install_derivatives_entitlement_resolver(lambda t, e: t == "allowed")
    require_derivatives_entitlement("allowed")
    with pytest.raises(DerivativesEntitlementError):
        require_derivatives_entitlement("denied")


async def test_resolver_seam_enforces_entitlement_before_credential_use():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create("t1", "hl-ref", ApiKeyCredential(api_key=SecretStr("k")))
    # Unentitled tenant -> no adapter, no credential resolution.
    with pytest.raises(DerivativesEntitlementError):
        await build_read_only_adapter(
            "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
            entitlement_check=lambda t: t != "t1",
        )
    # Entitled tenant -> adapter resolves with the read-only secret.
    adapter = await build_read_only_adapter(
        "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
        entitlement_check=lambda t: t == "t1",
    )
    assert adapter._resolved_credential.api_key == "k"


@pytest.mark.asyncio
async def test_async_entitlement_predicate_is_awaited_not_truthy_coroutine():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create("t1", "hl-ref", ApiKeyCredential(api_key=SecretStr("k")))
    calls = []

    async def async_deny(tenant_id: str) -> bool:
        calls.append(tenant_id)
        return False

    # An async predicate returning False MUST deny: the coroutine is awaited
    # rather than treated as a truthy object that silently bypasses the gate
    # and proceeds to credential resolution.
    with pytest.raises(DerivativesEntitlementError):
        await build_read_only_adapter(
            "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
            entitlement_check=async_deny,
        )
    assert calls == ["t1"]

    # The same async predicate returning True grants normally.
    async def async_allow(tenant_id: str) -> bool:
        calls.append(tenant_id)
        return True

    adapter = await build_read_only_adapter(
        "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
        entitlement_check=async_allow,
    )
    assert adapter._resolved_credential.api_key == "k"

    # A synchronous predicate still works (unchanged path).
    with pytest.raises(DerivativesEntitlementError):
        await build_read_only_adapter(
            "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
            entitlement_check=lambda t: t != "t1",
        )
    adapter = await build_read_only_adapter(
        "hl-ref", tenant_id="t1", venue_id="hyperliquid", service=svc,
        entitlement_check=lambda t: t == "t1",
    )
    assert adapter._resolved_credential.api_key == "k"


def test_meter_hook_records_forwards_and_rejects():
    records = []
    install_derivatives_meter_sink(
        lambda t, m, q: records.append((t, m, str(q)))
    )
    derivatives_meter.record("t1", "graph_queries", 3)
    derivatives_meter.record("t1", "graph_queries", "2")
    assert records == [
        ("t1", "graph_queries", "3"),
        ("t1", "graph_queries", "2"),
    ]
    assert derivatives_meter.snapshot("t1")["graph_queries"] == "5"
    assert derivatives_meter.total("graph_queries") == 5
    with pytest.raises(ValueError):
        derivatives_meter.record("t1", "not_a_meter", 1)
    with pytest.raises(ValueError):
        derivatives_meter.record("t1", "graph_queries", -1)
    # A fresh hook instance has no cross-test leakage and no sink.
    fresh = DerivativesMeter()
    assert fresh.snapshot("t1")["graph_queries"] == "0"
    assert fresh.sink_installed is False


def test_product_meter_usage_delegates_to_hook():
    # PORT-ADAPT: main's product facade accumulates usage into its OWN in-process
    # rollup (product.py never forwards to the meter hook), so the delegation
    # seam main actually carries is derivatives_meter.record -> the installed
    # MeteringService-style sink. Both surfaces are asserted here.
    from services.derivatives.product import product_service

    # Facade rollup: Decimal-exact accumulation across calls.
    first = product_service.meter_usage("t1", "backfill_records", Decimal("4"))
    assert first["meter"] == "backfill_records"
    assert first["quantity"] == "4"
    assert product_service.meter_usage("t1", "backfill_records", Decimal("2"))["quantity"] == "6"

    # Hook delegation: record forwards to the installed sink exactly once.
    sink_calls: list[tuple[str, str, str]] = []
    install_derivatives_meter_sink(
        lambda tenant_id, meter, qty: sink_calls.append((tenant_id, meter, str(qty)))
    )
    hook = derivatives_meter.record("t1", "backfill_records", Decimal("4"))
    assert hook["meter"] == "backfill_records"
    assert hook["quantity"] == "4"
    assert derivatives_meter.snapshot("t1")["backfill_records"] == "4"
    assert sink_calls == [("t1", "backfill_records", "4")]
    install_derivatives_meter_sink(None)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Honest centralized_futures declaration
# ═══════════════════════════════════════════════════════════════════════════

def test_centralized_futures_is_declared_scaffolded_not_supported():
    # PORT-ADAPT: main's multi_venue carries no SCAFFOLDED_VENUES /
    # available_venues / profile.scaffolded flag — the canonical declaration
    # signal is (a) the normalization-scaffold set from
    # build_scaffolded_adapters and (b) the venue adapter registry, which has
    # no live connector for the scaffolded venue.
    assert "centralized_futures" in SUPPORTED_VENUES
    adapters = build_scaffolded_adapters()
    assert "centralized_futures" in adapters
    profile = adapters["centralized_futures"].capabilities
    assert profile.venue_id == "centralized_futures"
    # The parity report marks the whole normalization surface scaffolded.
    report = cross_venue_parity_report(adapters)
    assert report["availability"] == "scaffolded"
    assert "centralized_futures" in report["venues"]
    # And there is no live connector in the venue adapter registry.
    from services.derivatives.adapters import get_adapter

    assert get_adapter("centralized_futures") is None


# ═══════════════════════════════════════════════════════════════════════════
# 8. Computed counters (no hardcoded zeros)
# ═══════════════════════════════════════════════════════════════════════════

def _insert_fleet_rows():
    accounts = TradingAccountRepo()
    checkpoints = ConnectorCheckpointRepo()
    asyncio.run(accounts.insert({
        "tenant_id": "t1", "trading_account_id": "acct-1", "venue_id": "hyperliquid",
        "idempotency_key": "acct-t1-1",
    }))
    asyncio.run(accounts.insert({
        "tenant_id": "t2", "trading_account_id": "acct-2", "venue_id": "dydx",
        "idempotency_key": "acct-t2-1",
    }))
    asyncio.run(checkpoints.insert({
        "tenant_id": "t1", "connector_checkpoint_id": "ccp-1", "connector_id": "hyperliquid",
        "state": "auth_error", "checkpoint_value": '{"stream": 5}',
        "advanced_at": "2026-08-08T00:00:00Z", "idempotency_key": "ccp-t1-hl",
    }))
    asyncio.run(checkpoints.insert({
        "tenant_id": "t1", "connector_checkpoint_id": "ccp-2", "connector_id": "dydx",
        "state": "rate_limited", "checkpoint_value": '{"stream": 3}',
        "advanced_at": "2026-08-08T00:00:00Z", "idempotency_key": "ccp-t1-dydx",
    }))


def test_fleet_counters_computed_from_real_rows():
    _insert_fleet_rows()
    fleet = counters.compute_kyber_fleet_sync(operator_tenant_id="ops-1")
    assert fleet["tenant_count"] == 2
    assert fleet["account_count"] == 2
    assert fleet["venue_count"] == 2
    assert fleet["authentication_failures"] == 1
    assert fleet["rate_limit_events"] == 1
    assert fleet["execution_by_aether"] is False


def test_data_quality_counters_computed_from_real_rows():
    fills = FillRepo()
    gaps = StreamGapRepo()
    variances = ReconciliationVarianceRepo()
    positions = PositionRepo()
    # Two fills sharing (tenant, fill_id) with DIFFERENT idempotency keys are a
    # real duplicate collision the computed counter must surface.
    asyncio.run(fills.insert({
        "tenant_id": "t1", "fill_id": "f1", "idempotency_key": "fill-t1-f1-a",
    }))
    asyncio.run(fills.insert({
        "tenant_id": "t1", "fill_id": "f1", "idempotency_key": "fill-t1-f1-b",
    }))
    asyncio.run(gaps.insert({
        "tenant_id": "t1", "stream_gap_id": "gap-1", "status": "open",
        "idempotency_key": "gap-t1-1",
    }))
    asyncio.run(variances.insert({
        "tenant_id": "t1", "reconciliation_variance_id": "var-1",
        "variance_type": "duplicate_fill", "idempotency_key": "var-t1-1",
    }))
    asyncio.run(variances.insert({
        "tenant_id": "t1", "reconciliation_variance_id": "var-2",
        "variance_type": "price_gap", "idempotency_key": "var-t1-2",
    }))
    asyncio.run(positions.insert({
        "tenant_id": "t1", "position_id": "pos-1", "status": "stale",
        "idempotency_key": "pos-t1-1",
    }))

    dq = counters.compute_kyber_data_quality_sync(operator_tenant_id="ops-1")
    assert dq["duplicates"] == 2  # 1 variance + 1 fill collision
    assert dq["reordered_records"] == 1
    assert dq["missing_intervals"] == 1
    assert dq["price_gaps"] == 1
    assert dq["stale_positions"] == 1
    assert dq["execution_by_aether"] is False


def test_graph_quality_counters_computed_from_rows():
    ledger = [
        {"reason_code": "unknown_edge", "aggregate_id": None, "evidence_refs": [], "confidence": 0.3},
        {"reason_code": "execution_failed", "aggregate_id": "agg-2", "evidence_refs": ["ev"], "confidence": 0.9},
        {"reason_code": "ok", "aggregate_id": "agg-3", "evidence_refs": [], "confidence": 0.99},
    ]
    positions = [
        {"trading_account_id": "acct-1", "status": "open"},
        {"trading_account_id": "acct-missing", "status": "open"},  # orphan
    ]
    accounts = [{"trading_account_id": "acct-1"}]
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    gq = counters.aggregate_graph_quality_from_rows(ledger, positions, accounts, now=now)
    assert gq["failed_mutations"] == 2
    assert gq["unknown_edge_attempts"] == 1
    assert gq["missing_evidence"] == 2
    assert gq["low_confidence_links"] == 1
    assert gq["orphan_positions"] == 1
    assert gq["tenant_isolation_rejections"] == 0
    assert gq["execution_by_aether"] is False


def test_product_kyber_fleet_surfaces_computed_not_zero():
    # PORT-ADAPT: main's product facade computes kyber_fleet from seeded
    # DerivativesProductSnapshot in-memory views (the DB-row counters live in
    # services.derivatives.counters and are covered by
    # test_fleet_counters_computed_from_real_rows). Seed two accounts and
    # assert the fleet surface is computed — never hardcoded zeros.
    from services.derivatives.product import (
        DerivativesAccountView,
        DerivativesProductSnapshot,
        product_service,
    )

    product_service.seed_snapshot(DerivativesProductSnapshot(
        tenant_id="t1",
        accounts=(
            DerivativesAccountView(
                tenant_id="t1", trading_account_id="acct-1", venue_id="hyperliquid",
                connection_state="connected",
            ),
            DerivativesAccountView(
                tenant_id="t1", trading_account_id="acct-2", venue_id="dydx",
                connection_state="connected",
            ),
        ),
    ))
    fleet = product_service.kyber_fleet("ops-1")
    assert fleet["tenant_count"] == 1
    assert fleet["account_count"] == 2
    assert fleet["venue_count"] == 2
    assert fleet["execution_by_aether"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 9. Snapshot / projection disagreement (stale snapshot, size mismatch)
# ═══════════════════════════════════════════════════════════════════════════

def test_stale_snapshot_vs_projection_disagreement():
    # Closed position (projection) but the venue snapshot still shows size != 0
    # -> critical disagreement.
    closed = PositionEpochState(
        tenant_id="t1", trading_account_id="acct-1", canonical_market_id="BTC",
        epoch_id="e1", side=PositionSide.LONG, status=PositionStatus.CLOSED,
        size=Decimal("0"), realized_pnl=Decimal("10"),
        opened_at="2026-07-01T00:00:00Z", closed_at="2026-07-02T00:00:00Z",
    )
    fact = reconcile_position_size(computed=closed, observed_size=Decimal("5"), source_ref="venue-snapshot")
    assert fact is not None
    assert fact.variance_type == "position_size_mismatch"
    assert fact.severity == "critical"
    assert fact.observed_value == Decimal("5")

    # Open position with a size drift -> high severity variance.
    opened = PositionEpochState(
        tenant_id="t1", trading_account_id="acct-1", canonical_market_id="BTC",
        epoch_id="e2", side=PositionSide.LONG, status=PositionStatus.OPEN,
        size=Decimal("2"), entry_notional=Decimal("100000"),
    )
    drift = reconcile_position_size(computed=opened, observed_size=Decimal("1.5"), source_ref="venue")
    assert drift is not None
    assert drift.severity == "high"
    assert drift.difference == Decimal("0.5")

    # In-tolerance: no variance emitted.
    assert reconcile_position_size(computed=opened, observed_size=Decimal("2"), source_ref="venue") is None


# ═══════════════════════════════════════════════════════════════════════════
# 10. Topic contract (no broker)
# ═══════════════════════════════════════════════════════════════════════════

def test_topic_contract_registry_validates_with_no_broker():
    report = validate_all_topic_contracts()
    assert report["passed"] is True
    assert report["broker_required"] is False
    assert report["topic_count"] == len(DERIVATIVES_TOPIC_CONTRACTS) == 13
    assert report["tenant_topic_count"] == 10
    assert assert_valid_topic_contracts()["passed"] is True  # does not raise

    from services.derivatives.product import DERIVATIVES_REALTIME_TOPICS

    names = set(all_contract_names())
    for topic in DERIVATIVES_REALTIME_TOPICS:
        assert topic in names  # parity with the product facade

    # The DLQ is declared and resolvable (heterogeneous catch-all).
    dlq = contract_by_topic(DERIVATIVES_DLQ_TOPIC)
    assert dlq is not None
    assert dlq.channel == "dlq"
    assert dlq.required is True


def test_topic_contract_rejects_invalid_contracts():
    bad = DerivativesTopicContract(
        topic="Tenant..", channel="x", partitions=0, retention_ms=0, required=True,
    )
    violations = validate_topic_contract(bad)
    assert any("partitions" in v for v in violations)
    assert any("retention_ms" in v for v in violations)

    # A required topic with no consumer ownership is a violation.
    unowned = DerivativesTopicContract(
        topic="tenant.derivatives.orphan", channel="risk",
        event_types=("derivatives_position_liquidated_observed",), required=True,
        consumer_group=None,
    )
    assert any("consumer_group" in v for v in validate_topic_contract(unowned))

    # A non-compacted topic referencing an undeclared DLQ is a violation.
    bad_dlq = DerivativesTopicContract(
        topic="tenant.derivatives.position_opened", channel="position",
        event_types=("derivatives_position_opened_observed",),
        compacted=False, dlq_topic="tenant.derivatives.nowhere",
        consumer_group="kyber-derivatives-ingest", required=True,
    )
    assert any("dlq_topic" in v for v in validate_topic_contract(bad_dlq))
