"""Deterministic deferred-attribution handoffs: resolve-once, replay, expiry,
and the uniform unmatched response (no handoff-state oracle, no probabilistic
matching — unmatched installs stay Direct / Unknown)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.traffic import deferred_attribution as module
from services.traffic.deferred_attribution import (
    DeferredAttributionRepository,
    DeferredHandoffCreate,
    DeferredHandoffResolve,
    create_deferred_handoff,
    resolve_deferred_handoff,
)
from shared.auth.auth import Role, TenantContext


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(module, "_pool", no_pool)
    module.reset_deferred_handoffs_for_tests()
    yield
    module.reset_deferred_handoffs_for_tests()


def _request(tenant_id: str = "tenant-a") -> SimpleNamespace:
    tenant = SimpleNamespace(tenant_id=tenant_id)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


EVIDENCE = {
    "source": "partner-landing",
    "medium": "qr",
    "source_class": "owned_referral",
    "placement": "conference-badge",
}


@pytest.mark.asyncio
async def test_create_persists_only_identifier_hash():
    repo = DeferredAttributionRepository()
    handoff = await repo.create(
        "tenant-a", identifier="HANDOFF-abc123", evidence=EVIDENCE
    )

    stored = next(iter(module._LOCAL_DEFERRED_HANDOFFS.values()))
    assert "HANDOFF-abc123" not in repr(stored)
    assert stored["identifier_hash"] != "HANDOFF-abc123"
    assert "identifier_hash" not in handoff
    assert handoff["status"] == "pending"
    assert handoff["evidence"]["source"] == "partner-landing"


@pytest.mark.asyncio
async def test_resolve_once_returns_evidence_then_uniform_false_on_replay():
    repo = DeferredAttributionRepository()
    await repo.create("tenant-a", identifier="HANDOFF-1", evidence=EVIDENCE, link_id="link-9")

    request = _request("tenant-a")
    first = await resolve_deferred_handoff(DeferredHandoffResolve(identifier="HANDOFF-1"), request)
    assert first["resolved"] is True
    assert first["evidence"]["entry_method"] == "verified_source_link"
    assert first["evidence"]["proof_level"] == "server_observed"
    assert first["evidence"]["source_class"] == "owned_referral"
    assert first["evidence"]["link_id"] == "link-9"

    replay = await resolve_deferred_handoff(DeferredHandoffResolve(identifier="HANDOFF-1"), request)
    assert replay == {"resolved": False}


@pytest.mark.asyncio
async def test_expired_and_unmatched_and_cross_tenant_are_indistinguishable():
    repo = DeferredAttributionRepository()
    await repo.create(
        "tenant-a",
        identifier="HANDOFF-expiring",
        evidence=EVIDENCE,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    # Force expiry without sleeping.
    record = next(iter(module._LOCAL_DEFERRED_HANDOFFS.values()))
    record["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    expired = await resolve_deferred_handoff(
        DeferredHandoffResolve(identifier="HANDOFF-expiring"), _request("tenant-a")
    )
    unmatched = await resolve_deferred_handoff(
        DeferredHandoffResolve(identifier="never-registered"), _request("tenant-a")
    )
    cross_tenant = await resolve_deferred_handoff(
        DeferredHandoffResolve(identifier="HANDOFF-expiring"), _request("tenant-b")
    )

    assert expired == unmatched == cross_tenant == {"resolved": False}


@pytest.mark.asyncio
async def test_expired_handoff_stays_unconsumed_and_unresolvable():
    repo = DeferredAttributionRepository()
    await repo.create("tenant-a", identifier="HANDOFF-2", evidence=EVIDENCE)
    record = next(iter(module._LOCAL_DEFERRED_HANDOFFS.values()))
    record["expires_at"] = datetime.now(timezone.utc) - timedelta(days=1)

    result = await repo.resolve_once("tenant-a", "HANDOFF-2")
    assert result is None
    assert record["consumed_at"] is None


@pytest.mark.asyncio
async def test_create_route_requires_write_capable_credential():
    viewer = TenantContext(tenant_id="tenant-a", role=Role.VIEWER, permissions=[])
    with pytest.raises(HTTPException) as exc:
        await module._require_deferred_handoff_write(viewer)
    assert exc.value.status_code == 403

    permitted = TenantContext(
        tenant_id="tenant-a", role=Role.VIEWER,
        permissions=["deferred_attribution:write"],
    )
    assert await module._require_deferred_handoff_write(permitted) is permitted
    editor = TenantContext(tenant_id="tenant-a", role=Role.EDITOR)
    assert await module._require_deferred_handoff_write(editor) is editor


@pytest.mark.asyncio
async def test_create_route_validates_evidence_and_duplicates():
    tenant = TenantContext(tenant_id="tenant-a", role=Role.EDITOR, user_id="op-1")

    with pytest.raises(HTTPException) as exc:
        await create_deferred_handoff(
            DeferredHandoffCreate(identifier="H-1", evidence={"unknown_field": "x"}),
            tenant,
        )
    assert exc.value.status_code == 400

    created = await create_deferred_handoff(
        DeferredHandoffCreate(identifier="H-1", evidence=EVIDENCE), tenant
    )
    assert created["handoff"]["status"] == "pending"

    with pytest.raises(HTTPException) as duplicate:
        await create_deferred_handoff(
            DeferredHandoffCreate(identifier="H-1", evidence=EVIDENCE), tenant
        )
    assert duplicate.value.status_code == 400


@pytest.mark.asyncio
async def test_evidence_is_sanitized_to_the_declared_allowlist():
    repo = DeferredAttributionRepository()
    handoff = await repo.create(
        "tenant-a",
        identifier="H-allow",
        evidence={
            "source": "landing",
            "entry_method": "web_referrer",   # not creator-assertable
            "proof_level": "cryptographic",   # not creator-assertable
            "arbitrary": "junk",
        },
    )
    assert handoff["evidence"] == {"source": "landing"}

    resolution = await repo.resolve_once("tenant-a", "H-allow")
    assert resolution is not None
    # entry_method / proof_level are stamped server-side at resolution and can
    # never be inflated by the handoff creator.
    assert resolution["evidence"]["entry_method"] == "verified_source_link"
    assert resolution["evidence"]["proof_level"] == "server_observed"


def test_main_registers_deferred_attribution_router() -> None:
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    main_source = (backend_root / "main.py").read_text(encoding="utf-8")
    assert (
        "from services.traffic.deferred_attribution import router as deferred_attribution_router"
        in main_source
    )
    assert "app.include_router(deferred_attribution_router)" in main_source


def test_router_exposes_the_contract_paths() -> None:
    route_methods = {
        (route.path, method)
        for route in module.router.routes
        for method in (route.methods or set())
    }
    assert ("/v1/attribution/deferred/handoffs", "POST") in route_methods
    assert ("/v1/attribution/deferred/resolve", "POST") in route_methods
