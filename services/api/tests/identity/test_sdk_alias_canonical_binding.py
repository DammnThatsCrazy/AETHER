"""The legacy SDK alias endpoint is a facade over canonical identify."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.sdk_identify_idempotency import reset_sdk_identify_idempotency_memory  # noqa: E402
from governance.consent.authority import ConsentReceiptRepository  # noqa: E402
from identity.identity.audit import IdentityAuditWriter  # noqa: E402
from identity.identity.conflicts import IdentityConflictManager  # noqa: E402
from identity.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from identity.identity.metrics import IdentityMetrics  # noqa: E402
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from identity.identity.resolver import IdentityResolutionService  # noqa: E402
from ingestion.sdk import lifecycle_routes  # noqa: E402


TENANT = "tenant_sdk_alias_binding"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_sdk_identify_idempotency_memory()


def _request(*, sites=None):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/alias",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=TENANT, site_ids=sites)},
    })


class _Producer:
    async def publish(self, _event):
        return None


def _enable_binding(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        anonymous_to_known_binding_enabled=True,
        sdk_late_binding_enabled=True,
        connector_backfill_enabled=True,
    ))


async def _grant(anonymous_id):
    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{anonymous_id}",
        tenant_id=TENANT,
        purpose="analytics",
        state="granted",
        anonymous_id=anonymous_id,
        mode="opt_in",
        metadata={"scope": "identity"},
    )


def _resolver():
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )


@pytest.mark.asyncio
async def test_alias_without_server_consent_does_not_claim_canonical_binding(monkeypatch):
    _enable_binding(monkeypatch)
    resolver = _resolver()
    monkeypatch.setattr("identity.identity.routes.get_identity_resolver", lambda: resolver)

    response = await lifecycle_routes.sdk_alias(
        lifecycle_routes.AliasRequest(
            previous_id="anon-no-consent", user_id="user-1", tenant_app_key="site-a",
        ),
        _request(),
        cache=None,
        producer=_Producer(),
    )

    assert response.aliased is False
    assert response.resolution_outcome == "blocked"
    assert resolver._repo._subjects._store == {}
    assert await lifecycle_routes.SourceIdentityRegistry(
        IdentityResolutionRepository()
    ).find_existing_source_identity(
        TENANT, source_namespace="aether-web:site-a", user_id="user-1"
    ) is None


@pytest.mark.asyncio
async def test_alias_with_server_consent_resolves_and_keeps_app_scoped_history(monkeypatch):
    _enable_binding(monkeypatch)
    await _grant("anon-approved")
    resolver = _resolver()
    monkeypatch.setattr("identity.identity.routes.get_identity_resolver", lambda: resolver)

    response = await lifecycle_routes.sdk_alias(
        lifecycle_routes.AliasRequest(
            previous_id="anon-approved", user_id="user-1", tenant_app_key="site-a",
        ),
        _request(),
        cache=None,
        producer=_Producer(),
    )

    assert response.aliased is True
    assert response.resolution_outcome == "create"
    assert response.source_identity_id is None
    aliases = await resolver._repo.get_aliases_for_entity(TENANT, response.canonical_entity_id)
    types = {row["alias_type"] for row in aliases}
    assert "user_id" in types
    assert "anonymous_id" in types
    anonymous_alias = next(row for row in aliases if row["alias_type"] == "anonymous_id")
    assert anonymous_alias["alias_value_hash"] != "anon-approved"


@pytest.mark.asyncio
async def test_alias_rejects_app_outside_authenticated_sdk_scope(monkeypatch):
    _enable_binding(monkeypatch)
    await _grant("anon-wrong-app")
    resolver = _resolver()
    monkeypatch.setattr("identity.identity.routes.get_identity_resolver", lambda: resolver)

    response = await lifecycle_routes.sdk_alias(
        lifecycle_routes.AliasRequest(
            previous_id="anon-wrong-app", user_id="user-1", tenant_app_key="attacker-site",
        ),
        _request(sites=["trusted-site"]),
        cache=None,
        producer=_Producer(),
    )

    assert response.aliased is False
    assert response.resolution_outcome == "blocked"
    assert resolver._repo._subjects._store == {}
