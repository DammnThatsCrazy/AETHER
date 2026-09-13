"""Fixtures for the Kyber Mission aggregate tests.

Two jobs only:

* **Isolation** — every test runs against empty stores. The mission aggregate
  spreads its state across two backends: the JSONB ``BaseRepository`` in-memory
  stores (missions, monitoring conditions, exceptions, incidents, signals,
  access decisions/scopes) and the agent runtime's ``shared.store`` durable
  stores (objectives, plans, steps, worker runs, events, review batches). Both
  are cleared per test, in place, so module-level repository singletons keep
  pointing at the same — now empty — backing dicts.

* **A scoped operator** — a builder that assembles a real
  :class:`WorkforceSession` + :class:`AccessScope` + :class:`KyberAccessContext`
  for a tenant, the shape ``mission_routes._assert_mission_in_scope`` and
  ``MissionService._enforce_scope`` authorize against. ``set_providers`` /
  ``reset_providers`` are exercised so a test can drive
  ``require_kyber_access`` deterministically without lazily importing the real
  identity/device planes.
"""
from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Optional

import pytest

os.environ.setdefault("AETHER_ENV", "local")

import shared.store as shared_store
from repositories.repos import reset_in_memory_stores
from shared.common.common import utc_now

from services.kyber.access import dependencies as access_dependencies
from services.kyber.access.contracts import (
    AccessScope,
    WorkforcePrincipal,
    WorkforceSession,
)
from services.kyber.access.dependencies import AccessProviders, KyberAccessContext


# ── Store isolation ──────────────────────────────────────────────────────────


def _reset_shared_stores() -> None:
    """Clear the ``shared.store`` in-memory backing the agent runtime uses.

    ``reset_in_memory_stores`` only knows about ``repositories.repos``; the agent
    runtime persists through a separate ``DurableStore`` registry. Both must be
    emptied or an objective seeded by one test would compose into another test's
    mission view.
    """
    stores = getattr(shared_store, "_stores", {})
    for store in list(stores.values()):
        targets = [store]
        fallback = getattr(store, "_fallback", None)
        if fallback is not None:
            targets.append(fallback)
        for target in targets:
            for attr in ("_data", "_lists", "_expiry"):
                backing = getattr(target, attr, None)
                if isinstance(backing, dict):
                    backing.clear()


@pytest.fixture(autouse=True)
def isolated_stores():
    """Fresh stores before and after every test; forget any cached providers."""
    reset_in_memory_stores()
    _reset_shared_stores()
    access_dependencies.reset_providers()
    yield
    reset_in_memory_stores()
    _reset_shared_stores()
    access_dependencies.reset_providers()


# ── Scoped operator builders ─────────────────────────────────────────────────


def _future_iso(hours: int = 1) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat()


def build_workforce_session(
    *,
    operator_id: str = "op_kyber_test",
    device_id: str = "dev_kyber_test",
    environment: str = "local",
    session_id: Optional[str] = None,
) -> WorkforceSession:
    """A live, device-bound operator session (no real token behind it)."""
    session = WorkforceSession(
        token_hash=f"hash_{operator_id}",
        operator_id=operator_id,
        device_id=device_id,
        status="active",
        authentication_strength="device_bound",
        environment=environment,
        presence_expires_at=_future_iso(24),
        authority_expires_at=_future_iso(8),
        idle_expires_at=_future_iso(1),
    )
    if session_id is not None:
        session.session_id = session_id
    return session


def build_access_scope(
    *,
    tenant_id: str,
    session: WorkforceSession,
) -> AccessScope:
    """A durable, active scope granted for exactly one tenant."""
    return AccessScope(
        operator_id=session.operator_id,
        session_id=session.session_id,
        device_id=session.device_id,
        environment=session.environment,
        tenant_id=tenant_id,
        purpose="incident_response",
        reason="operator inspecting a mission under test",
        expires_at=_future_iso(1),
    )


def build_scoped_context(
    *,
    scope_tenant: Optional[str],
    operator_id: str = "op_kyber_test",
) -> KyberAccessContext:
    """A :class:`KyberAccessContext` as a route handler would read it.

    ``scope_tenant=None`` yields a session with no active tenant scope — the
    "workforce session without scope" case a per-mission read must refuse.
    """
    session = build_workforce_session(operator_id=operator_id)
    principal = WorkforcePrincipal(
        operator_id=operator_id,
        email="operator@olympus.test",
        employment_status="active",
        kyber_enabled=True,
    )
    scope = (
        build_access_scope(tenant_id=scope_tenant, session=session)
        if scope_tenant is not None
        else None
    )
    return KyberAccessContext(
        session=session,
        principal=principal,
        scope=scope,
        environment=session.environment,
        tenant_id=scope_tenant,
    )


@pytest.fixture
def make_scoped_context():
    """Factory fixture: build a scoped (or unscoped) operator context."""
    return build_scoped_context


class FakeRequest:
    """The minimal request surface the Kyber evaluator reads.

    A plain Aether tenant reaches a Kyber route with no workforce session — at
    most a tenant API key on the ``Authorization`` header, which carries no
    Kyber token prefix and is therefore invisible to ``read_session_token``.
    """

    def __init__(
        self,
        *,
        cookies: Optional[dict] = None,
        headers: Optional[dict] = None,
        state: Optional[Any] = None,
    ) -> None:
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.state = state if state is not None else SimpleNamespace()
        self.method = "GET"
        self.path_params: dict = {}
        self.query_params: dict = {}


@pytest.fixture
def install_empty_providers():
    """Install a deny-everything provider set (all providers ``None``).

    Used by the ``require_kyber_access`` denial test so the evaluator does not
    lazily import the real identity/device planes. ``reset_providers`` runs in
    the autouse teardown.
    """
    def _install() -> None:
        access_dependencies.set_providers(AccessProviders())

    return _install
