"""A blast radius must be bounded, per-subject, and honest about its limits.

The dangerous answer this module can give is not a wrong number — it is a
*complete-looking* one. An operator asks "what does this touch?" before pausing
a connector or rolling back a release; a reach that stopped at a budget, or that
was assembled over nodes the walk could not read, and that is nevertheless
returned at full confidence, is read as "this change is safe".

So three properties are tested here:

*Partial is labelled partial.* Any missing input sets ``exposure_known: false``
and names what was absent. An unresolved anchor is a zero-confidence unknown,
never an empty reach.

*The walk is bounded and says which bound bound it.* Node budget, per-node edge
fan-out and depth are all hard. The node budget is the only one that makes the
walk *drop* something it saw, so it is the only one that sets ``truncated``; the
other two report through ``missing_inputs``. Both paths lower ``confidence``.

*There is no fleet rollup.*
``services/agent_access_intelligence/kyber_ops_routes.py`` records why: a blast
radius is a per-subject exposure answer whose honesty depends on every input for
that subject being present, so summing it over tenants "would produce a number no
operator can act on and would hide exactly the tenants whose inputs were
missing". The tests at the end assert the behaviour that comment describes still
holds — no fleet entry point, no tenant field on the D0 request body, and a
delegated subject without a named tenant reports the gap instead of aggregating.

Error classes are resolved at call time; see ``_raises_named``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-graph-test")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.kyber.graph import blast_radius as blast_radius_module  # noqa: E402
from services.kyber.graph.blast_radius import (  # noqa: E402
    MAX_DEPTH,
    MAX_EDGES_PER_NODE,
    MAX_NODES,
    KyberBlastRadiusService,
    node_key_for,
)
from services.kyber.graph.contracts import KyberGraphEdge, KyberGraphNode  # noqa: E402
from services.kyber.graph.repository import KyberGraphStore  # noqa: E402
from services.kyber.graph.routes import BlastRadiusRequest, review_blast_radius  # noqa: E402

ENV = "test"
_COMPLETE_CONFIDENCE = 0.9


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _node(store: KyberGraphStore, key: str, node_type: str, **kwargs: Any):
    return await store.upsert_node(
        KyberGraphNode(
            node_key=key,
            node_type=node_type,  # type: ignore[arg-type]
            environment=ENV,
            **kwargs,
        )
    )


async def _edge(store: KyberGraphStore, source: str, target: str, rel: str = "DEPENDS_ON"):
    return await store.upsert_edge(
        KyberGraphEdge(
            source_node_key=source,
            target_node_key=target,
            relationship_type=rel,  # type: ignore[arg-type]
            environment=ENV,
        )
    )


async def _chain(store: KyberGraphStore, length: int) -> str:
    """A linear ``DEPENDS_ON`` chain of services, returning the anchor key."""
    for index in range(length):
        await _node(store, f"service:s{index}", "Service")
    for index in range(length - 1):
        await _edge(store, f"service:s{index}", f"service:s{index + 1}")
    return "service:s0"


async def _raises_named(name: str, awaitable: Any) -> Exception:
    """Await something that must raise ``name``, matched at call time.

    Matched by class name because sibling suites in this directory purge
    ``shared.*`` from ``sys.modules``; an identity check against a class
    imported at module scope would stop matching once they run together.
    """
    try:
        result = await awaitable
    except Exception as exc:  # noqa: BLE001 - the class is checked here
        assert type(exc).__name__ == name, f"expected {name}, got {type(exc).__name__}: {exc}"
        return exc
    raise AssertionError(f"expected {name}, but the call returned {result!r}")


class BrokenStore:
    """A store whose reads fail. Absence of data and failure to read differ."""

    async def get_node(self, node_key: str, *, environment: Optional[str] = None):
        raise RuntimeError("graph store unreachable")

    async def edges_from(self, node_key: str, **_: Any):
        raise RuntimeError("graph store unreachable")

    async def edges_to(self, node_key: str, **_: Any):
        raise RuntimeError("graph store unreachable")


class EdgelessStore(KyberGraphStore):
    """A store missing the edge readers entirely — a partially-deployed backend."""

    edges_from = None  # type: ignore[assignment]
    edges_to = None  # type: ignore[assignment]


# ── 12. Missing inputs ───────────────────────────────────────────────────────


async def test_an_unresolved_anchor_is_unknown_reach_not_empty_reach():
    """A subject that does not resolve has an unknown blast radius.

    Returning empty lists at any confidence would read as "this change touches
    nothing", which is the single most dangerous wrong answer this surface can
    give.
    """
    store = KyberGraphStore()
    await _node(store, "service:api", "Service")
    service = KyberBlastRadiusService(store=store)

    result = await service.for_subject(subject_type="Service", subject_id="ghost", environment=ENV)

    assert result.exposure_known is False
    assert result.confidence == 0.0
    assert result.missing_inputs == ["kyber_graph_node:node_key=service:ghost"]
    assert result.affected_services == []
    assert result.affected_tenants == []
    assert result.customer_visible is False


async def test_an_edge_to_an_unreadable_node_is_a_gap_not_an_absence_of_reach():
    """A dangling edge names the node it could not read.

    What *was* found is still reported — the answer is a lower bound, and it is
    labelled as one rather than withheld.
    """
    store = KyberGraphStore()
    await _node(store, "service:api", "Service")
    await _node(store, "service:worker", "Service")
    await _edge(store, "service:api", "service:worker")
    # An edge whose target was never projected.
    await _edge(store, "service:api", "service:vanished")
    service = KyberBlastRadiusService(store=store)

    result = await service.for_subject(
        subject_type="Service", subject_id="api", environment=ENV
    )

    assert "kyber_graph_node:node_key=service:vanished" in result.missing_inputs
    assert result.exposure_known is False
    assert result.confidence < _COMPLETE_CONFIDENCE
    assert "service:worker" in result.affected_services


async def test_an_unavailable_store_reports_the_gap_rather_than_no_exposure():
    """No store means no answer, not a clean bill of health."""
    service = KyberBlastRadiusService(store=None)
    import services.kyber.graph.scoped_gateway as gateway_module

    gateway_module.set_store(None)
    gateway_module._store_probed = True
    try:
        result = await service.for_subject(subject_type="Service", subject_id="api")
    finally:
        gateway_module.reset_store()

    assert result.exposure_known is False
    assert result.confidence == 0.0
    assert result.missing_inputs == ["kyber_graph_store:unavailable"]
    assert result.affected_services == []


async def test_a_failing_store_read_is_reported_as_a_failure():
    """A lookup that raised is distinguishable from a node that is absent."""
    service = KyberBlastRadiusService(store=BrokenStore())
    result = await service.for_subject(
        subject_type="Service", subject_id="api", environment=ENV
    )

    assert result.exposure_known is False
    assert result.confidence == 0.0
    assert "kyber_graph_node:lookup_failed:service:api" in result.missing_inputs


async def test_a_store_without_edge_readers_names_what_it_could_not_read():
    """A partially-deployed backend must not read as a subject with no reach."""
    store = EdgelessStore()
    await _node(store, "service:api", "Service")
    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id="api", environment=ENV
    )

    assert result.exposure_known is False
    assert "kyber_graph_store:edges_from_unavailable" in result.missing_inputs
    assert "kyber_graph_store:edges_to_unavailable" in result.missing_inputs


async def test_a_complete_walk_is_the_only_thing_that_claims_to_be_complete():
    """The control: exposure_known can in fact be true, so the tests above bite."""
    store = KyberGraphStore()
    await _node(store, "service:api", "Service")
    await _node(store, "feature_surface:graph", "FeatureSurface")
    await _node(store, "tenant:acme", "Tenant", tenant_id="acme")
    await _edge(store, "service:api", "feature_surface:graph", rel="SERVED_BY")
    await _edge(store, "feature_surface:graph", "tenant:acme", rel="ENTITLED_TO")

    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id="api", environment=ENV, max_depth=MAX_DEPTH
    )

    assert result.missing_inputs == []
    assert result.truncated is False
    assert result.exposure_known is True
    assert result.confidence == _COMPLETE_CONFIDENCE
    assert result.affected_services == ["service:api"]
    assert result.affected_features == ["feature_surface:graph"]
    assert result.affected_tenants == ["acme"]
    assert result.customer_visible is True


async def test_non_propagating_edges_do_not_widen_the_reach():
    """An audit event hanging off a service is not something a change breaks."""
    store = KyberGraphStore()
    await _node(store, "service:api", "Service")
    await _node(store, "service:unrelated", "Service")
    await _edge(store, "service:api", "service:unrelated", rel="GOVERNED_BY")

    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id="api", environment=ENV
    )
    assert result.affected_services == ["service:api"]
    assert result.missing_inputs == []


# ── 13. Bounded traversal ────────────────────────────────────────────────────


async def test_the_node_budget_marks_the_result_truncated_and_lowers_confidence():
    """The node budget is the one bound that drops something the walk saw."""
    store = KyberGraphStore()
    await _node(store, "service:hub", "Service")
    for index in range(10):
        await _node(store, f"service:leaf{index}", "Service")
        await _edge(store, "service:hub", f"service:leaf{index}")

    bounded = KyberBlastRadiusService(store=store, max_nodes=4)
    result = await bounded.for_subject(
        subject_type="Service", subject_id="hub", environment=ENV
    )

    assert result.truncated is True
    assert result.exposure_known is False
    assert result.confidence < _COMPLETE_CONFIDENCE
    assert len(result.affected_services) <= 4

    # The same graph without the bound is complete, so the bound is what bound.
    unbounded = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id="hub", environment=ENV
    )
    assert unbounded.truncated is False
    assert len(unbounded.affected_services) == 11


async def test_a_cyclic_topology_terminates_and_is_charged_once():
    """Two services that each read the other's projection is real topology."""
    store = KyberGraphStore()
    await _node(store, "service:a", "Service")
    await _node(store, "service:b", "Service")
    await _edge(store, "service:a", "service:b")
    await _edge(store, "service:b", "service:a")

    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id="a", environment=ENV, max_depth=MAX_DEPTH
    )
    assert sorted(result.affected_services) == ["service:a", "service:b"]
    assert result.truncated is False


async def test_the_depth_bound_is_reported_and_lowers_confidence():
    """A walk that stopped at the depth ceiling is not a complete answer.

    Note the deliberate asymmetry with the node budget: reaching the depth
    ceiling does **not** set ``truncated``, because everything the walk saw is
    still reported — only the onward edges of the boundary nodes were never
    read. That is a missing input, and the code says so. ``exposure_known`` is
    false and ``confidence`` drops either way, which is the property an
    operator actually depends on.
    """
    store = KyberGraphStore()
    anchor = await _chain(store, MAX_DEPTH + 3)

    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Service", subject_id=anchor, environment=ENV, max_depth=MAX_DEPTH
    )

    assert f"kyber_graph_walk:depth_bound_reached:depth={MAX_DEPTH}" in result.missing_inputs
    assert result.exposure_known is False
    assert result.confidence < _COMPLETE_CONFIDENCE
    assert result.traversal_depth == MAX_DEPTH


async def test_a_requested_depth_beyond_the_ceiling_is_clamped_not_honoured():
    """``max_depth`` is a hard ceiling, not a default."""
    store = KyberGraphStore()
    anchor = await _chain(store, 12)
    service = KyberBlastRadiusService(store=store)

    result = await service.for_subject(
        subject_type="Service", subject_id=anchor, environment=ENV, max_depth=99
    )
    assert result.traversal_depth <= MAX_DEPTH
    # Depth 3 from s0 reaches s1..s3, so the far end of the chain is not in reach.
    assert "service:s11" not in result.affected_services
    assert result.exposure_known is False


async def test_a_hub_nodes_edge_fanout_is_bounded_and_reported():
    """One hub node cannot consume the whole walk, and the cut is named."""
    store = KyberGraphStore()
    await _node(store, "service:hub", "Service")
    fanout = MAX_EDGES_PER_NODE + 5
    for index in range(fanout):
        await _node(store, f"service:f{index}", "Service")
        await _edge(store, "service:hub", f"service:f{index}")

    service = KyberBlastRadiusService(store=store, max_nodes=MAX_NODES)
    result = await service.for_subject(
        subject_type="Service", subject_id="hub", environment=ENV, max_depth=1
    )

    assert "kyber_graph_edges:fanout_truncated:service:hub" in result.missing_inputs
    assert result.exposure_known is False
    assert result.confidence < _COMPLETE_CONFIDENCE
    # The fan-out was cut at the bound rather than pulled unbounded.
    assert len(result.affected_services) <= MAX_EDGES_PER_NODE + 1


async def test_the_module_ceilings_are_the_values_the_docstring_claims():
    """A ceiling raised without review would silently unbound every walk."""
    assert MAX_DEPTH == 3
    assert MAX_NODES == 400
    assert MAX_EDGES_PER_NODE == 200
    # The service clamps its constructor arguments to at least one, so a
    # zero or negative budget cannot disable the bound.
    tiny = KyberBlastRadiusService(max_depth=0, max_nodes=0)
    assert tiny.max_depth == 1
    assert tiny.max_nodes == 1


# ── 14. No cross-tenant aggregate ────────────────────────────────────────────


async def test_there_is_no_fleet_wide_blast_radius_entry_point():
    """Per subject, deliberately. There is no ``for_fleet``.

    ``kyber_ops_routes.py`` states the reason: summing exposure over tenants
    "would produce a number no operator can act on and would hide exactly the
    tenants whose inputs were missing".
    """
    for forbidden in ("for_fleet", "for_all_tenants", "for_tenants", "fleet_blast_radius"):
        assert not hasattr(blast_radius_module.kyber_blast_radius_service, forbidden), forbidden
        assert not hasattr(blast_radius_module, forbidden), forbidden
    entry_points = [
        name
        for name in dir(blast_radius_module.KyberBlastRadiusService)
        if not name.startswith("_")
    ]
    assert entry_points == ["for_subject"], (
        "the service has grown a second public entry point; if it aggregates "
        "across tenants the honesty argument in kyber_ops_routes.py no longer holds"
    )


async def test_the_d0_request_body_has_no_tenant_field():
    """A tenant on this D0 body would create an unscoped per-tenant read."""
    assert "tenant_id" not in BlastRadiusRequest.model_fields
    assert set(BlastRadiusRequest.model_fields) == {
        "subject_type",
        "subject_id",
        "environment",
        "max_depth",
    }
    assert BlastRadiusRequest.model_fields["max_depth"].metadata


async def test_a_delegated_subject_without_a_tenant_reports_the_gap():
    """An agent's reach is per tenant by construction; it is never summed.

    Without a named tenant the answer is the missing input, not an aggregate
    assembled across every tenant the agent was ever observed in.
    """
    store = KyberGraphStore()
    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Agent", subject_id="agent-42", environment=ENV
    )

    assert "blast_radius_tenant_id_required:subject=agent" in result.missing_inputs
    assert result.exposure_known is False
    assert result.affected_tenants == [], "no tenant may be inferred without one being named"
    assert result.affected_features == []


async def test_the_route_points_a_delegated_subject_at_the_tenant_scoped_surface():
    """The D0 route answers with a pointer, not with a cross-tenant total."""
    store = KyberGraphStore()
    import services.kyber.graph.scoped_gateway as gateway_module

    gateway_module.set_store(store)
    try:
        payload = await review_blast_radius(
            request=None,
            body=BlastRadiusRequest(subject_type="Agent", subject_id="agent-42"),
            context=None,
        )
    finally:
        gateway_module.reset_store()

    data = payload["data"]
    assert data["exposure_known"] is False
    assert data["affected_tenants"] == []
    assert data["delegated_surface"].startswith("GET /v1/capability/kyber/ops/blast-radius")
    assert "tenant_id=" in data["delegated_surface"]


async def test_the_agent_access_ops_route_still_requires_an_explicit_tenant():
    """The behaviour the ``kyber_ops_routes.py`` comment describes, executed.

    That comment is the reason this module has no fleet rollup, so if the ops
    route ever started answering without a tenant the justification would have
    quietly stopped being true.
    """
    from services.agent_access_intelligence.kyber_ops_routes import read_kyber_blast_radius

    exc = await _raises_named(
        "BadRequestError",
        read_kyber_blast_radius(request=None, tenant_id="   ", agent_id="agent-42"),
    )
    assert "tenant_id is required" in str(exc)


async def test_a_delegated_subject_is_not_charged_a_kyber_graph_anchor_it_never_had():
    """A delegated answer must not carry a gap for a node that cannot exist.

    Agent and capability subjects live in the agent-access plane's observed
    inventory, not in the Kyber Graph; there is no node key for them and none is
    expected. Reporting ``kyber_graph_node:node_key=agent-42`` as a missing input
    describes a gap that is not real, and pinning ``confidence`` at 0.0 for every
    delegated review makes the field carry no information on this surface — which
    is exactly how an operator learns to ignore it.

    This was a real defect, found by attacking the claim rather than reading the
    code: ``GRAPH_SUBJECT_PREFIXES`` has no ``agent``/``capability`` entry, so
    ``node_key_for`` returned the bare id and ``for_subject`` walked it anyway.
    ``for_subject`` now skips the graph walk entirely for a delegated subject and
    takes the answer from the plane that owns it.
    """
    store = KyberGraphStore()
    result = await KyberBlastRadiusService(store=store).for_subject(
        subject_type="Agent",
        subject_id="agent-42",
        environment=ENV,
        tenant_id="tenant_acme",
    )

    assert not any(
        item.startswith("kyber_graph_node:node_key=agent-42")
        for item in result.missing_inputs
    ), f"spurious Kyber Graph gap reported for a delegated subject: {result.missing_inputs}"
    assert result.confidence > 0.0


async def test_node_key_prefixing_never_invents_a_subject():
    """An unknown subject type is passed through, so it fails to resolve loudly."""
    assert node_key_for("Service", "api") == "service:api"
    assert node_key_for("Service", "service:api") == "service:api"
    # No prefix is known, so the raw id is used and the walk will report it as
    # an unresolved anchor rather than silently matching something else.
    assert node_key_for("NotAThing", "whatever") == "whatever"
