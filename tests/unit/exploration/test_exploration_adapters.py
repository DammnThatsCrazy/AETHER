"""Surface adapters — honest field support + real graph delegation."""
from __future__ import annotations

import pytest

from exploration_fakes import FakeGraphNode, FakeGraphResponse, context, fake_graph_runner

from shared.exploration.generated_fields import FILTER_FIELDS
from shared.exploration.generated_surfaces import SURFACE_CAPABILITIES
from services.exploration.adapters import available_surfaces, get_adapter
from services.exploration.adapters.base import AdapterContext
import services.exploration.adapters.graph as graph_adapter


def test_every_backed_surface_has_an_adapter():
    expected = {"graph", "profile360", "cluster360", "timeline", "geo", "campaign360"}
    assert available_surfaces() == frozenset(expected)


def test_deferred_surfaces_have_no_adapter():
    for surface in ("comparison_workbench", "journeys", "product_intelligence", "temporal_observatory"):
        assert get_adapter(surface) is None


@pytest.mark.parametrize("surface", sorted(available_surfaces()))
def test_supported_fields_match_registry_categories(surface):
    adapter = get_adapter(surface)
    caps = SURFACE_CAPABILITIES[surface]
    supported = adapter.supported_fields()
    # Every supported field's category is declared; no field outside the
    # surface's categories is claimed.
    for fid in supported:
        assert FILTER_FIELDS[fid]["category"] in caps["supported_field_categories"]
    # A field from an unsupported category is honestly reported as unsupported.
    unsupported_categories = set(FILTER_FIELDS[f]["category"] for f in FILTER_FIELDS) - set(
        caps["supported_field_categories"]
    )
    for fid, spec in FILTER_FIELDS.items():
        if spec["category"] in unsupported_categories:
            assert not adapter.supports_field(fid)


async def test_graph_adapter_delegates_and_reports_truncation(monkeypatch):
    nodes = [FakeGraphNode("e1"), FakeGraphNode("e2"), FakeGraphNode("e3")]
    resp = FakeGraphResponse(nodes, truncated=True, reason="node_budget", cursor="c2")
    monkeypatch.setattr(graph_adapter, "run_universal_graph_query", fake_graph_runner(resp))

    adapter = get_adapter("graph")
    ctx = AdapterContext(
        tenant_id="t1",
        context=context("graph", [{"field": "entity.id", "op": "eq", "value": "e1"}]),
        applied_filters=[],
        request=None, graph=None, cache=None, limit=2,
    )
    result = await adapter.execute(ctx)
    assert result.surface == "graph"
    assert result.backend == "operational_intelligence.graph_query"
    assert result.populated is True
    assert len(result.data["nodes"]) == 3
    assert result.truncation.truncated is True
    assert result.truncation.reason == "node_budget"
    assert result.cursor == "c2"


async def test_profile_adapter_projects_anchor(monkeypatch):
    nodes = [FakeGraphNode("anchor"), FakeGraphNode("rel1"), FakeGraphNode("rel2")]
    monkeypatch.setattr(
        graph_adapter, "run_universal_graph_query", fake_graph_runner(FakeGraphResponse(nodes))
    )
    adapter = get_adapter("profile360")
    ctx = AdapterContext(
        tenant_id="t1", context=context("profile360"), applied_filters=[],
    )
    result = await adapter.execute(ctx)
    assert result.data["anchor_id"] == "anchor"
    assert len(result.data["related"]) == 2


async def test_empty_graph_is_honest_empty(monkeypatch):
    monkeypatch.setattr(
        graph_adapter, "run_universal_graph_query", fake_graph_runner(FakeGraphResponse([]))
    )
    adapter = get_adapter("geo")
    ctx = AdapterContext(tenant_id="t1", context=context("geo"), applied_filters=[])
    result = await adapter.execute(ctx)
    assert result.populated is False
    assert result.data["countries"] == []
    assert result.truncation.truncated is False
