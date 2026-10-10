"""Durable claim and SDK route retry behavior for identify requests."""

from __future__ import annotations

import asyncio
import ast
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.sdk_identify_idempotency import (  # noqa: E402
    SDK_IDENTIFY_IDEMPOTENCY_DDL,
    SDKIdentifyIdempotencyRepository,
    reset_sdk_identify_idempotency_memory,
)
from shared.common.common import utc_now  # noqa: E402
from identity.identity.models import MergeDecision  # noqa: E402
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from identity.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from ingestion.sdk import lifecycle_routes  # noqa: E402


TENANT = "tenant_sdk_identify_idempotency"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_sdk_identify_idempotency_memory()


def _request():
    return Request({
        "type": "http", "method": "POST", "path": "/sdk/identify",
        "headers": [], "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=TENANT)},
    })


def _body(key: str, *, anon="anon-idem", traits=None):
    return lifecycle_routes.IdentifyRequest(
        tenant_app_key="site", user_id="user", anonymous_id=anon,
        traits=traits, idempotency_key=key,
    )


class _Resolver:
    def __init__(self, *, pause=False):
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not pause:
            self.release.set()

    async def resolve_event(self, event, tenant_id):
        self.calls.append((event, tenant_id))
        self.entered.set()
        await self.release.wait()
        return SimpleNamespace(
            decision=MergeDecision("create"), canonical_entity_id="canonical-user",
            confidence=0.9, reason_codes=[],
        )


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _configure(monkeypatch, resolver):
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr("identity.identity.routes.get_identity_resolver", lambda: resolver)


async def _grant_receipt(anonymous_id: str):
    from governance.consent.authority import ConsentReceiptRepository

    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{anonymous_id}",
        tenant_id=TENANT,
        purpose="analytics",
        state="granted",
        anonymous_id=anonymous_id,
        mode="opt_in",
        metadata={"scope": "identity"},
    )


@pytest.mark.asyncio
async def test_repository_claim_is_single_winner_replayable_and_payload_bound():
    repo_a = SDKIdentifyIdempotencyRepository()
    repo_b = SDKIdentifyIdempotencyRepository()
    outcomes = await asyncio.gather(*[
        (repo_a if i % 2 else repo_b).claim(TENANT, "same-key", "fingerprint")
        for i in range(12)
    ])
    assert sum(result["status"] == "claimed" for result in outcomes) == 1
    assert sum(result["status"] == "in_progress" for result in outcomes) == 11
    winner = next(result for result in outcomes if result["status"] == "claimed")
    safe_result = {"resolution_outcome": "create", "canonical_entity_id": "canonical-user"}
    assert await repo_a.complete(TENANT, "same-key", winner["claim_token"], safe_result)
    replay = await repo_b.claim(TENANT, "same-key", "fingerprint")
    assert replay == {"status": "replay", "response": safe_result}
    assert (await repo_b.claim(TENANT, "same-key", "different"))["status"] == "conflict"


@pytest.mark.asyncio
async def test_route_replay_does_not_repeat_resolver_or_publication(monkeypatch):
    await _grant_receipt("anon-idem")
    resolver = _Resolver()
    producer = _Producer()
    _configure(monkeypatch, resolver)
    key = uuid.uuid4().hex
    body = _body(key, traits={"email": "pii@example.com"})

    first = await lifecycle_routes.sdk_identify(body, _request(), cache=None, producer=producer)
    replay = await lifecycle_routes.sdk_identify(body, _request(), cache=None, producer=producer)

    assert first.idempotency_status == "completed"
    assert replay.idempotency_status == "replayed"
    assert replay.canonical_entity_id == first.canonical_entity_id
    assert replay.user_id == body.user_id
    assert len(resolver.calls) == 1
    assert len(producer.events) == 1
    # The repository outcome contains no caller identifiers or trait values.
    from repositories.sdk_identify_idempotency import _MEM_ROWS
    row = _MEM_ROWS[(TENANT, key)]
    assert "user_id" not in row["response"]
    assert "anonymous_id" not in row["response"]
    assert "pii@example.com" not in repr(row["response"])


@pytest.mark.asyncio
async def test_route_rejects_changed_payload_and_keeps_concurrent_retry_pending(monkeypatch):
    await _grant_receipt("anon-idem")
    resolver = _Resolver(pause=True)
    producer = _Producer()
    _configure(monkeypatch, resolver)
    key = uuid.uuid4().hex

    first_task = asyncio.create_task(
        lifecycle_routes.sdk_identify(_body(key), _request(), cache=None, producer=producer)
    )
    await resolver.entered.wait()
    concurrent = await lifecycle_routes.sdk_identify(
        _body(key), _request(), cache=None, producer=producer
    )
    assert concurrent.idempotency_status == "in_progress"
    assert concurrent.canonical_entity_id is None
    with pytest.raises(HTTPException) as exc:
        await lifecycle_routes.sdk_identify(
            _body(key, anon="different-anonymous-id"), _request(), cache=None, producer=producer
        )
    assert exc.value.status_code == 409
    resolver.release.set()
    await first_task
    assert len(resolver.calls) == 1
    assert len(producer.events) == 1


@pytest.mark.asyncio
async def test_crash_pending_claim_is_not_stolen_by_new_repository_instance():
    repo_a = SDKIdentifyIdempotencyRepository()
    repo_b = SDKIdentifyIdempotencyRepository()
    claim = await repo_a.claim(TENANT, "crashed-request", "same")
    assert claim["status"] == "claimed"
    # Simulates process restart: a fresh repository instance sees durable state.
    assert (await repo_b.claim(TENANT, "crashed-request", "same"))["status"] == "in_progress"
    assert (await repo_b.claim(TENANT, "crashed-request", "changed"))["status"] == "conflict"


@pytest.mark.asyncio
async def test_old_pending_claim_is_reported_stale_without_reexecution():
    repo = SDKIdentifyIdempotencyRepository()
    await repo.claim(TENANT, "old-request", "same")
    from repositories.sdk_identify_idempotency import _MEM_ROWS
    _MEM_ROWS[(TENANT, "old-request")]["updated_at"] = utc_now() - timedelta(minutes=16)
    assert (await repo.claim(TENANT, "old-request", "same"))["status"] == "stale"


@pytest.mark.asyncio
async def test_route_returns_stale_without_running_identity_side_effects(monkeypatch):
    from repositories.sdk_identify_idempotency import _MEM_ROWS

    key = uuid.uuid4().hex
    fingerprint_payload = _body(key).dict(exclude={"idempotency_key"})
    import hashlib
    import json
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    await SDKIdentifyIdempotencyRepository().claim(TENANT, key, fingerprint)
    _MEM_ROWS[(TENANT, key)]["updated_at"] = utc_now() - timedelta(minutes=16)

    class _MustNotRun:
        async def resolve_event(self, *_args):
            raise AssertionError("stale identify request must not reach resolver")

    _configure(monkeypatch, _MustNotRun())
    response = await lifecycle_routes.sdk_identify(_body(key), _request(), cache=None, producer=None)
    assert response.idempotency_status == "stale"
    assert response.canonical_entity_id is None
    assert response.reason_codes == ["idempotent_request_stale_reconciliation_required"]


def test_identify_request_requires_caller_idempotency_key():
    with pytest.raises(ValidationError):
        lifecycle_routes.IdentifyRequest(tenant_app_key="site", user_id="user")


def test_migration_ddl_matches_repository_ddl():
    migration = Path(__file__).parents[2] / "alembic" / "versions" / "20260927_sdk_identify_idempotency.py"
    tree = ast.parse(migration.read_text())
    value = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SDK_IDENTIFY_IDEMPOTENCY_DDL" for target in node.targets)
    )
    assert value == SDK_IDENTIFY_IDEMPOTENCY_DDL
