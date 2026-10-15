"""Focused tests for the opt-in public marketplace catalog observer."""
from __future__ import annotations

import dataclasses
import json
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from actions.agent_marketplace.catalog import (  # noqa: E402
    MarketplaceCatalogParseError,
    MarketplaceCatalogRepository,
    PublicMarketplaceCatalogObserver,
    parse_public_marketplace_catalog,
)
from actions.agent_marketplace.lineage import (  # noqa: E402
    build_public_marketplace_listing_mutations,
)
from actions.agent_marketplace.projection import (  # noqa: E402
    AgentMarketplaceGraphOutboxRepository,
    AgentMarketplaceGraphProjectionOutbox,
)
from config.settings import settings  # noqa: E402
from shared.graph.graph import Edge, Vertex  # noqa: E402
from shared.store import InMemoryStore  # noqa: E402


def _html(items: list[dict]) -> str:
    document = {
        "@context": "https://schema.org",
        "@graph": [{"@type": "ItemList", "itemListElement": items}],
    }
    return (
        '<html><script type="application/ld+json">'
        + json.dumps(document)
        + "</script></html>"
    )


def _item(slug: str, name: str, position: int) -> dict:
    return {
        "position": position,
        "item": {
            "@type": "Thing",
            "name": name,
            "url": f"https://x.ai/bot/marketplace/bots/{slug}",
        },
    }


def _repo() -> MarketplaceCatalogRepository:
    return MarketplaceCatalogRepository(
        InMemoryStore(f"marketplace-catalog-test-{uuid.uuid4().hex}")
    )


def _separate_projection_stores(monkeypatch, catalog_module, projection_module, name: str):
    catalog_store = InMemoryStore(f"{name}-catalog-{uuid.uuid4().hex}")
    outbox_store = InMemoryStore(f"{name}-outbox-{uuid.uuid4().hex}")
    monkeypatch.setattr(catalog_module, "get_store", lambda _store_name: catalog_store)
    monkeypatch.setattr(projection_module, "get_store", lambda _store_name: outbox_store)
    return catalog_store, outbox_store


def test_parser_keeps_only_bounded_public_listing_facts():
    html = _html([_item("support-helper", "Support Helper", 1)])

    listings = parse_public_marketplace_catalog(html)

    assert len(listings) == 1
    assert listings[0]["listing_ref"] == "support-helper"
    assert listings[0]["name"] == "Support Helper"
    assert listings[0]["source_position"] == 1
    assert listings[0]["assertion"] == "public_source_observed"
    assert set(listings[0]) == {
        "source_namespace", "listing_ref", "name", "source_url",
        "source_position", "content_hash", "assertion",
    }


@pytest.mark.parametrize("url", [
    "https://example.test/bot/marketplace/bots/lookalike",
    "https://x.ai/bot/marketplace/bots/tracked?source=other",
])
def test_parser_fails_closed_on_unrecognized_listing_urls(url: str):
    html = _html([{"item": {"name": "Unsupported", "url": url}}])

    with pytest.raises(MarketplaceCatalogParseError):
        parse_public_marketplace_catalog(html)


def test_parser_fails_closed_when_public_catalog_exceeds_safe_limit():
    items = [_item(f"helper-{index}", f"Helper {index}", index + 1) for index in range(251)]

    with pytest.raises(MarketplaceCatalogParseError, match="safe listing limit"):
        parse_public_marketplace_catalog(_html(items))


def test_parser_fails_closed_when_source_catalog_shape_disappears():
    with pytest.raises(MarketplaceCatalogParseError):
        parse_public_marketplace_catalog("<html><body>No JSON-LD</body></html>")


@pytest.mark.asyncio
async def test_observer_uses_conditional_get_and_preserves_first_seen(monkeypatch):
    repo = _repo()
    body = _html([_item("support-helper", "Support Helper", 1)]).encode()
    calls: list[dict[str, str]] = []

    async def fetcher(headers: dict[str, str]):
        calls.append(headers)
        if len(calls) == 1:
            return 200, body, {"etag": '"catalog-v1"'}
        return 304, b"", {"etag": '"catalog-v1"'}

    monkeypatch_settings = dataclasses.replace(
        settings.external_agent_telemetry, graph_enabled=False,
    )
    monkeypatch.setattr(settings, "external_agent_telemetry", monkeypatch_settings)
    observer = PublicMarketplaceCatalogObserver(repo, fetcher=fetcher)
    first = await observer.observe_once()
    rows = await repo.list_listings()
    second = await observer.observe_once()
    refreshed = await repo.list_listings()
    status = await repo.status()

    assert first["status"] == "available"
    assert first["listing_count"] == 1
    assert second["status"] == "not_modified"
    assert calls[1]["If-None-Match"] == '"catalog-v1"'
    assert rows[0]["first_seen_at"] == refreshed[0]["first_seen_at"]
    assert status["source_status"] == "available"
    assert status["listing_count"] == 1


@pytest.mark.asyncio
async def test_catalog_removal_is_recorded_as_absence_without_erasing_history():
    repo = _repo()
    now = "2026-10-10T12:00:00+00:00"
    first = parse_public_marketplace_catalog(_html([_item("support-helper", "Support Helper", 1)]))
    await repo.snapshot(first, observed_at=now, etag=None, last_modified=None)
    changed = await repo.snapshot([], observed_at="2026-10-10T13:00:00+00:00", etag=None, last_modified=None)
    rows = await repo.list_projection_rows()

    assert len(changed) == 1
    assert rows[0]["listing_status"] == "not_currently_listed"
    assert rows[0]["first_seen_at"] == now
    assert rows[0]["last_seen_at"] == now


@pytest.mark.asyncio
async def test_catalog_observations_are_append_only_and_cursor_pages_transitions():
    repo = _repo()
    await repo.snapshot(
        parse_public_marketplace_catalog(_html([_item("support-helper", "Support Helper", 1)])),
        observed_at="2026-10-10T12:00:00+00:00",
        etag=None,
        last_modified=None,
    )
    await repo.snapshot(
        parse_public_marketplace_catalog(_html([_item("support-helper", "Support Helper v2", 1)])),
        observed_at="2026-10-10T13:00:00+00:00",
        etag=None,
        last_modified=None,
    )
    await repo.snapshot(
        [],
        observed_at="2026-10-10T14:00:00+00:00",
        etag=None,
        last_modified=None,
    )

    observations = []
    cursor = None
    while True:
        page, next_cursor, truncated = await repo.list_projection_observations(
            limit=1, cursor=cursor,
        )
        observations.extend(page)
        if not truncated:
            assert next_cursor is None
            break
        assert next_cursor
        cursor = next_cursor

    assert len(observations) == 3
    assert {row["listing_status"] for row in observations} == {
        "listed", "not_currently_listed",
    }
    assert {row.get("name") for row in observations} >= {
        "Support Helper", "Support Helper v2",
    }


@pytest.mark.asyncio
async def test_catalog_projection_pages_use_bounded_store_reads():
    class BoundedStore(InMemoryStore):
        async def find(self, **filters):
            raise AssertionError("projection paging must not load the full store")

    store = BoundedStore(f"marketplace-bounded-page-{uuid.uuid4().hex}")
    repo = MarketplaceCatalogRepository(store)
    for index in range(5):
        await store.set(f"observation:{index:04d}", {
            "id": f"observation:{index:04d}",
            "record_type": "listing_observation",
            "source_namespace": "xai_marketplace",
            "listing_ref": f"helper-{index}",
        })
    await store.set("listing:current", {
        "id": "listing:current", "record_type": "listing",
        "source_namespace": "xai_marketplace",
    })

    cursor = None
    seen = []
    while True:
        page, next_cursor, truncated = await repo.list_projection_observations(
            limit=2, cursor=cursor,
        )
        assert len(page) <= 2
        seen.extend(row["listing_ref"] for row in page)
        if not truncated:
            assert next_cursor is None
            break
        assert next_cursor
        cursor = next_cursor

    assert seen == [f"helper-{index}" for index in range(5)]


def test_public_catalog_graph_versions_are_platform_scoped_source_evidence():
    listing = parse_public_marketplace_catalog(
        _html([_item("support-helper", "Support Helper", 1)])
    )[0]
    listing.update({
        "listing_status": "listed",
        "last_observed_catalog_at": "2026-10-10T12:00:00+00:00",
    })
    changed = {**listing, "listing_status": "not_currently_listed"}
    current_mutations = build_public_marketplace_listing_mutations(listing)
    changed_mutations = build_public_marketplace_listing_mutations(changed)

    assert len(current_mutations) == len(changed_mutations) == 3
    vertices = [item for item in current_mutations if isinstance(item, Vertex)]
    edges = [item for item in current_mutations if isinstance(item, Edge)]
    assert all(vertex.properties["tenant_id"] == "platform" for vertex in vertices)
    assert vertices[1].properties["assertion"] == "public_source_observed"
    assert vertices[1].properties["listing_ref"] == "support-helper"
    assert edges[0].properties["listing_status"] == "listed"
    assert current_mutations[1].vertex_id != changed_mutations[1].vertex_id
    assert build_public_marketplace_listing_mutations({"listing_ref": "raw-only"}) == []


@pytest.mark.asyncio
async def test_platform_catalog_projection_reconciliation_repairs_missing_rows(monkeypatch):
    import actions.agent_marketplace.catalog as catalog_module
    import actions.agent_marketplace.projection as projection_module

    catalog_store, _outbox_store = _separate_projection_stores(
        monkeypatch, catalog_module, projection_module, "marketplace-projection-recovery",
    )
    repository = MarketplaceCatalogRepository()
    listing = parse_public_marketplace_catalog(
        _html([_item("support-helper", "Support Helper", 1)])
    )
    await repository.snapshot(
        listing,
        observed_at="2026-10-10T12:00:00+00:00",
        etag=None,
        last_modified=None,
    )
    projection = AgentMarketplaceGraphProjectionOutbox(
        repo=AgentMarketplaceGraphOutboxRepository(),
    )

    before = await projection.reconcile("platform", limit=10)
    repaired = await projection.repair(
        "platform", enqueue_missing=True, replay_dead_letters=False, limit=10,
    )
    after = await projection.reconcile("platform", limit=10)

    assert before["missing_outbox_rows"] == 3
    assert repaired["enqueued_missing"] == 3
    assert after["missing_outbox_rows"] == 0


@pytest.mark.asyncio
async def test_platform_repair_pages_older_catalog_transitions(monkeypatch):
    import actions.agent_marketplace.catalog as catalog_module
    import actions.agent_marketplace.projection as projection_module

    catalog_store, _outbox_store = _separate_projection_stores(
        monkeypatch, catalog_module, projection_module, "marketplace-projection-history",
    )
    repository = MarketplaceCatalogRepository()
    for index, name in enumerate(("Support Helper", "Support Helper v2", "Support Helper v3")):
        await repository.snapshot(
            parse_public_marketplace_catalog(_html([_item("support-helper", name, 1)])),
            observed_at=f"2026-10-10T{12 + index:02d}:00:00+00:00",
            etag=None,
            last_modified=None,
        )
    projection = AgentMarketplaceGraphProjectionOutbox(
        repo=AgentMarketplaceGraphOutboxRepository(),
    )

    first = await projection.reconcile("platform", limit=1)
    repaired_first = await projection.repair(
        "platform", enqueue_missing=True, replay_dead_letters=False, limit=1,
    )
    repaired_second = await projection.repair(
        "platform", enqueue_missing=True, replay_dead_letters=False, limit=1,
        cursor=first["source_next_cursor"],
    )
    repaired_third = await projection.repair(
        "platform", enqueue_missing=True, replay_dead_letters=False, limit=1,
        cursor=repaired_second["source_next_cursor"],
    )
    final = await projection.reconcile("platform", limit=10)

    assert first["source_scan_truncated"] is True
    assert first["source_next_cursor"]
    assert repaired_first["source_scan_truncated"] is True
    assert repaired_second["source_scan_truncated"] is True
    assert repaired_third["source_scan_truncated"] is False
    assert final["missing_outbox_rows"] == 0
    assert final["scan_pages_exhausted"] is True


@pytest.mark.asyncio
async def test_reconcile_reports_truncated_outbox_scan(monkeypatch):
    import actions.agent_marketplace.catalog as catalog_module
    import actions.agent_marketplace.projection as projection_module

    catalog_store, _outbox_store = _separate_projection_stores(
        monkeypatch, catalog_module, projection_module, "marketplace-outbox-bound",
    )
    repository = MarketplaceCatalogRepository()
    for index in range(5):
        await repository.snapshot(
            parse_public_marketplace_catalog(
                _html([_item(f"support-helper-{index}", f"Support Helper {index}", index + 1)])
            ),
            observed_at=f"2026-10-10T{12 + index:02d}:00:00+00:00",
            etag=None,
            last_modified=None,
        )
    projection = AgentMarketplaceGraphProjectionOutbox(
        repo=AgentMarketplaceGraphOutboxRepository(),
    )
    await projection.repair("platform", enqueue_missing=True, replay_dead_letters=False, limit=10)

    report = await projection.reconcile("platform", limit=1)

    assert report["outbox_rows"] == 10
    assert report["outbox_scan_truncated"] is True
    assert report["scan_pages_exhausted"] is False


@pytest.mark.asyncio
async def test_read_route_requires_agent_manage_and_returns_only_source_metadata(monkeypatch):
    import actions.agent.deployment_routes as routes_module
    import actions.agent_marketplace.catalog as catalog_module

    store = InMemoryStore(f"marketplace-route-test-{uuid.uuid4().hex}")
    monkeypatch.setattr(catalog_module, "get_store", lambda _name: store)
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(
            settings.external_agent_telemetry,
            registry_enabled=False,
            marketplace_catalog_enabled=True,
        ),
    )
    await MarketplaceCatalogRepository().snapshot(
        parse_public_marketplace_catalog(_html([_item("support-helper", "Support Helper", 1)])),
        observed_at="2026-10-10T12:00:00+00:00",
        etag=None,
        last_modified=None,
    )

    class Tenant:
        tenant_id = "tenant-route-test"

        def __init__(self):
            self.permissions: list[str] = []

        def require_permission(self, permission: str):
            self.permissions.append(permission)

    tenant = Tenant()
    request = type("RequestStub", (), {
        "state": type("RequestState", (), {"tenant": tenant})(),
    })()
    response = await routes_module.public_marketplace_catalog(request, limit=100)

    assert tenant.permissions == ["agent:manage"]
    assert response["data"]["source_status"] == "available"
    assert response["data"]["listings"][0]["source_url"].endswith("support-helper")
    assert "description" not in response["data"]["listings"][0]
