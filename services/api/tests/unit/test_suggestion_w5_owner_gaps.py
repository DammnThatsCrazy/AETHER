"""W5 owner-side gaps: reviewer identity, expiry, create idempotency, atomic transitions.

These run against the real in-memory SuggestionRepository so the conditional
writes are exercised, not mocked.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from pydantic import ValidationError

from intelligence.suggestions.models import (
    SuggestionActionRequest,
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
)
from intelligence.suggestions.repository import SuggestionRepository
from intelligence.suggestions.service import SuggestionService
from shared.common.common import BadRequestError, ConflictError


# The in-memory store is shared across repo instances, so each test gets its own tenant.
_TENANT = "tenant_a"


@pytest.fixture(autouse=True)
def _fresh_tenant():
    global _TENANT
    _TENANT = f"tenant_{uuid.uuid4().hex[:8]}"
    yield


def _tenant(user_id="user_real", tenant_id=None):
    tenant = MagicMock()
    tenant.tenant_id = tenant_id or _TENANT
    tenant.user_id = user_id
    return tenant


def _service():
    producer = MagicMock()
    producer.publish = AsyncMock()
    return SuggestionService(SuggestionRepository(), producer, MagicMock(), MagicMock())


def _create(**overrides):
    body = dict(
        tenant_id=_TENANT,
        subject=SuggestionSubject(kind="entity", id="e-1"),
        source=SuggestionSource.RULE,
        suggestion_class=SuggestionClass.DATA_QUALITY,
        title="t", summary="s", what="w", why="y", impact="i",
        confidence_score=0.8,
    )
    body.update(overrides)
    return SuggestionCreate(**body)


def _iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


async def _review_required(svc, **overrides):
    record = await svc.create_suggestion(_create(**overrides), _tenant())
    patched = dict(record)
    patched["status"] = SuggestionStatus.REVIEW_REQUIRED.value
    await svc._repo.update(record["id"], patched)
    return record["id"]


def test_reviewer_is_the_authenticated_principal_not_the_request_body():
    async def go():
        svc = _service()
        sid = await _review_required(svc)
        approved = await svc.approve_suggestion(
            sid, SuggestionActionRequest(actor_id="someone_else"), _tenant("user_real"),
        )
        assert approved["reviewed_by"] == "user_real"
        assert approved["audit_trail"][-1]["actor_id"] == "user_real"
    asyncio.run(go())


def test_expired_suggestion_cannot_be_approved_and_is_marked_expired():
    async def go():
        svc = _service()
        sid = await _review_required(svc, expires_at=_iso(timedelta(seconds=-5)))
        with pytest.raises(BadRequestError, match="expired"):
            await svc.approve_suggestion(sid, SuggestionActionRequest(), _tenant())
        stored = await svc._repo.get(sid, _TENANT)
        assert stored["status"] == SuggestionStatus.EXPIRED.value
    asyncio.run(go())


def test_unexpired_suggestion_still_approves():
    async def go():
        svc = _service()
        sid = await _review_required(svc, expires_at=_iso(timedelta(hours=1)))
        approved = await svc.approve_suggestion(sid, SuggestionActionRequest(), _tenant())
        assert approved["status"] == SuggestionStatus.APPROVED.value
    asyncio.run(go())


def test_approved_but_expired_suggestion_cannot_be_delivered():
    async def go():
        svc = _service()
        sid = await _review_required(svc, expires_at=_iso(timedelta(hours=1)))
        await svc.approve_suggestion(sid, SuggestionActionRequest(), _tenant())
        stored = await svc._repo.get(sid, _TENANT)
        stored["expires_at"] = _iso(timedelta(seconds=-5))
        await svc._repo.update(sid, stored)
        with pytest.raises(BadRequestError, match="expired"):
            await svc.deliver_suggestion(sid, _tenant())
        assert (await svc._repo.get(sid, _TENANT))["status"] == SuggestionStatus.EXPIRED.value
    asyncio.run(go())


def test_expires_at_must_be_a_timestamp():
    with pytest.raises(ValidationError):
        _create(expires_at="next tuesday")


def test_replayed_create_returns_the_original_without_a_duplicate():
    async def go():
        svc = _service()
        first = await svc.create_suggestion(_create(idempotency_key="k1"), _tenant())
        second = await svc.create_suggestion(_create(idempotency_key="k1"), _tenant())
        assert second["id"] == first["id"]
        assert len(await svc._repo.find_many(filters={"tenant_id": _TENANT}, limit=50)) == 1
    asyncio.run(go())


def test_same_key_with_different_content_is_a_conflict():
    async def go():
        svc = _service()
        await svc.create_suggestion(_create(idempotency_key="k1"), _tenant())
        with pytest.raises(ConflictError):
            await svc.create_suggestion(_create(idempotency_key="k1", title="changed"), _tenant())
    asyncio.run(go())


def test_idempotency_key_is_scoped_to_the_principal():
    async def go():
        svc = _service()
        a = await svc.create_suggestion(_create(idempotency_key="k1"), _tenant("user_a"))
        b = await svc.create_suggestion(_create(idempotency_key="k1"), _tenant("user_b"))
        assert a["id"] != b["id"]
    asyncio.run(go())


def test_concurrent_creates_with_one_key_produce_one_row():
    async def go():
        svc = _service()
        results = await asyncio.gather(*[
            svc.create_suggestion(_create(idempotency_key="race"), _tenant()) for _ in range(8)
        ])
        assert len({r["id"] for r in results}) == 1
        assert len(await svc._repo.find_many(filters={"tenant_id": _TENANT}, limit=50)) == 1
    asyncio.run(go())


def test_transition_is_compare_and_set():
    async def go():
        svc = _service()
        sid = await _review_required(svc)
        repo = svc._repo
        stale = await repo.get(sid, _TENANT)
        audit = {"id": "a1", "action": "x"}
        await repo.transition(sid, _TENANT, "review_required", "approved", audit)
        # A second writer that read the same row before the first write must lose.
        real_get = repo.get_or_fail
        repo.get_or_fail = AsyncMock(return_value=stale)
        with pytest.raises((ConflictError, BadRequestError)):
            await repo.transition(sid, _TENANT, "review_required", "rejected", audit)
        repo.get_or_fail = real_get
        assert (await repo.get(sid, _TENANT))["status"] == "approved"
    asyncio.run(go())


def test_concurrent_approvals_have_one_winner():
    async def go():
        svc = _service()
        sid = await _review_required(svc)
        results = await asyncio.gather(*[
            svc.approve_suggestion(sid, SuggestionActionRequest(), _tenant()) for _ in range(6)
        ], return_exceptions=True)
        wins = [r for r in results if isinstance(r, dict)]
        assert len(wins) == 1
        assert all(isinstance(r, (BadRequestError, ConflictError)) for r in results if not isinstance(r, dict))
        stored = await svc._repo.get(sid, _TENANT)
        approvals = [e for e in stored["audit_trail"] if e["to_status"] == "approved"]
        assert len(approvals) == 1
    asyncio.run(go())
