"""Route flag-gating + handler roundtrips (handlers called directly, fake request)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError, NotFoundError

import services.product_catalog.routes as pc_routes
from services.product_catalog.models import CatalogNode, MappingRule


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def _enable(monkeypatch, enabled: bool = True) -> None:
    monkeypatch.setattr(
        pc_routes,
        "settings",
        SimpleNamespace(product_intelligence=SimpleNamespace(catalog_enabled=enabled)),
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


class TestFlagGating:
    async def test_every_handler_404s_when_flag_off(self, monkeypatch):
        _enable(monkeypatch, enabled=False)
        request = _request()
        with pytest.raises(NotFoundError):
            await pc_routes.list_nodes(request, kind=None, status=None, limit=100, offset=0)
        with pytest.raises(NotFoundError):
            await pc_routes.get_node(request, "any")
        with pytest.raises(NotFoundError):
            await pc_routes.upsert_node(request, CatalogNode(kind="feature", stable_id="f", display_name="F"))
        with pytest.raises(NotFoundError):
            await pc_routes.list_mapping_rules(request, match_kind=None, limit=100, offset=0)
        with pytest.raises(NotFoundError):
            await pc_routes.list_proposals(request, status=None, limit=100, offset=0)
        with pytest.raises(NotFoundError):
            await pc_routes.validate_manifest_route(
                request, pc_routes.ManifestValidateIn(manifest={})
            )

    async def test_flag_off_message_masks_the_feature(self, monkeypatch):
        _enable(monkeypatch, enabled=False)
        with pytest.raises(NotFoundError, match="product catalog \\(feature not enabled\\)"):
            await pc_routes.list_nodes(_request(), kind=None, status=None, limit=100, offset=0)


class TestPermissions:
    async def test_read_endpoint_requires_read(self, monkeypatch):
        _enable(monkeypatch)
        with pytest.raises(ForbiddenError):
            await pc_routes.list_nodes(_request(permissions=[]), kind=None, status=None, limit=100, offset=0)

    async def test_write_endpoint_requires_write(self, monkeypatch):
        _enable(monkeypatch)
        node = CatalogNode(kind="feature", stable_id="f", display_name="F")
        with pytest.raises(ForbiddenError):
            await pc_routes.upsert_node(_request(permissions=["read"]), node)

    async def test_payload_tenant_mismatch_is_forbidden(self, monkeypatch):
        _enable(monkeypatch)
        node = CatalogNode(kind="feature", stable_id="f", display_name="F", tenant_id="other")
        with pytest.raises(ForbiddenError, match="tenant_id does not match"):
            await pc_routes.upsert_node(_request(tenant_id="t1"), node)


class TestHandlerRoundtrip:
    async def test_node_post_then_get_then_list(self, monkeypatch):
        _enable(monkeypatch)
        request = _request()
        created = await pc_routes.upsert_node(
            request, CatalogNode(kind="feature", stable_id="one-click", display_name="One-Click"),
        )
        assert created.data["node"]["tenant_id"] == "t1"

        fetched = await pc_routes.get_node(request, "one-click")
        assert fetched.data["node"]["display_name"] == "One-Click"

        listed = await pc_routes.list_nodes(request, kind=None, status=None, limit=100, offset=0)
        assert [n["stable_id"] for n in listed.data["nodes"]] == ["one-click"]

        # Another tenant sees nothing (isolation through the route path).
        other = await pc_routes.list_nodes(_request(tenant_id="t2"), kind=None, status=None, limit=100, offset=0)
        assert other.data["nodes"] == []
        with pytest.raises(NotFoundError):
            await pc_routes.get_node(_request(tenant_id="t2"), "one-click")

    async def test_mapping_rule_roundtrip(self, monkeypatch):
        _enable(monkeypatch)
        request = _request()
        rule = MappingRule(
            rule_id="r-1", match_kind="event_name", match_value="order_completed",
            precedence_class="tenant_catalog", target_feature_id="one-click",
        )
        created = await pc_routes.upsert_mapping_rule(request, rule)
        assert created.data["rule"]["tenant_id"] == "t1"
        listed = await pc_routes.list_mapping_rules(request, match_kind="event_name", limit=100, offset=0)
        assert [r["rule_id"] for r in listed.data["rules"]] == ["r-1"]

    async def test_manifest_validate_reports_errors_without_persisting(self, monkeypatch):
        _enable(monkeypatch)
        request = _request()
        bad = pc_routes.ManifestValidateIn(manifest={"product": {"stable_id": "p"}})
        response = await pc_routes.validate_manifest_route(request, bad)
        assert response.data["valid"] is False
        assert response.data["errors"]
        assert response.data["diff"] is None
        assert (await pc_routes.list_nodes(request, kind=None, status=None, limit=100, offset=0)).data["nodes"] == []

    async def test_manifest_validate_dry_run_diff(self, monkeypatch):
        _enable(monkeypatch)
        request = _request()
        manifest = {
            "product": {"stable_id": "p", "display_name": "P"},
            "features": [{"stable_id": "f", "display_name": "F"}],
        }
        response = await pc_routes.validate_manifest_route(
            request, pc_routes.ManifestValidateIn(manifest=manifest),
        )
        assert response.data["valid"] is True
        assert response.data["diff"]["added"] == ["f", "p"]
        # Dry-run only: nothing was written.
        assert (await pc_routes.list_nodes(request, kind=None, status=None, limit=100, offset=0)).data["nodes"] == []
