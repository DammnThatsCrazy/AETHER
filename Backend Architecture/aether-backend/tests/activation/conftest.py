"""Fixtures for the self-serve activation test suite.

Isolation contract
------------------
``repositories.repos.reset_in_memory_stores`` clears every table-backed
in-memory store (``tenant_activations``, ``api_keys``, ``bronze_sdk_events``,
…). It deliberately does **not** touch the billing fallback store, which lives
in its own module-level dict: ``shared.billing.stripe_repository._mem_accounts``
(plus its sibling webhook/invoice/overage dicts). Billing state is *derived*
read-only from that store, so a seeded Stripe account must not bleed between
tests. The autouse fixture below therefore resets both.

The registry cache (idempotency keys) is a process-level singleton that is not
reset here; tests that exercise the ingestion path use unique event ids so no
key collides across tests.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from shared.billing import stripe_repository
from services.activation.service import ActivationService


class _Tenant:
    """Stand-in for the auth-middleware tenant on ``request.state.tenant``.

    The activation routes and the canonical ingestion path read the tenant from
    ``request.state.tenant`` and call ``require_permission`` with plain string
    permissions (``Permissions.READ`` / ``Permissions.WRITE`` are ``"read"`` /
    ``"write"``). The tenant id is always taken from here — never from a body —
    which is exactly what the tenant-isolation tests rely on.
    """

    def __init__(self, tenant_id: str, permissions=None) -> None:
        self.tenant_id = tenant_id
        self.permissions = set(
            permissions or {"read", "write", "ingest", "analytics", "admin"}
        )

    def require_permission(self, permission) -> None:
        if permission not in self.permissions:
            raise AssertionError(f"missing permission {permission!r}")


def _build_request(tenant_id: str, permissions=None):
    """A minimal object with the surface ``ingest_batch`` reads.

    ``ingest_batch`` uses ``request.state.tenant``, ``getattr(request,
    "headers", {})`` and ``request.client``; nothing else. Server-context
    enrichment is flag-gated OFF in the local profile, so ``client=None`` and an
    empty header map are sufficient for a real in-process ingestion call.
    """
    tenant = _Tenant(tenant_id, permissions)
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        headers={},
        client=None,
    )


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset every in-memory store, including the billing fallback dicts."""
    reset_in_memory_stores()
    stripe_repository._reset_in_memory_for_tests()
    yield
    reset_in_memory_stores()
    stripe_repository._reset_in_memory_for_tests()


@pytest.fixture
def svc() -> ActivationService:
    return ActivationService()


@pytest.fixture
def make_request():
    """Factory: ``make_request(tenant_id[, permissions])`` -> fake Request."""
    return _build_request


@pytest.fixture
def onboard_with_keys():
    """Drive a tenant through plan -> billing -> sdk -> keys to waiting_for_event.

    Returns the ``create_sdk_keys`` result (``{"keys": [...], "state": ...}``),
    leaving the activation record parked at ``waiting_for_event`` — the point in
    the flow from which a first event proves first value.
    """
    async def _run(
        service: ActivationService,
        tenant_id: str,
        count: int = 1,
        plan_tier: str = "P1",
        platforms=("web",),
    ):
        await service.select_plan(tenant_id, plan_tier)
        await service.select_sdks(tenant_id, list(platforms))
        return await service.create_sdk_keys(
            tenant_id, count=count, label="test key"
        )

    return _run
