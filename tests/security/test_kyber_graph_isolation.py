"""The scoped tenant graph gateway must not be reachable outside its scope.

This suite attacks the headline claim of ``services/kyber/graph``: an operator
holding a live scope on tenant A reaches tenant A and nothing else. Every test
asserts the *denial reason* rather than merely that something was raised —
"it raised" is compatible with an unrelated crash, and a security property that
is only proven by a stack trace is not proven at all.

Three of the properties here are not the obvious ones and are the reason the
file exists:

*Truncation is a leak in the other direction.* A tenant read that silently caps
a global page and filters it afterwards reports "this tenant has no data" for a
tenant whose rows sort past the cap. ``test_scoped_read_returns_every_row...``
seeds more foreign vertices than the cap so the cap actually binds, and contrasts
the scoped read against the legacy scan-then-filter shape. The pre-existing
``tests/security/test_graph_tenant_isolation.py`` cannot catch this: it reads a
four-vertex fixture with ``limit=1000``, so its cap never binds.

*A refusal must not be an oracle.* An entity that does not exist and another
tenant's real entity have to be indistinguishable — same body, same store
traffic — or the route answers "does tenant B have entity X?" for free.

*Error classes are resolved at call time.* Sibling suites in this directory
purge ``shared.*`` from ``sys.modules`` (see ``test_graph_tenant_isolation.py``),
so a ``ForbiddenError`` imported here at module scope can be a *different class
object* than the one the gateway raises once the suites run together, and
``pytest.raises`` would then let a real refusal escape as an error. ``_denied``
below matches on the class name and the denial reason instead.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-graph-test")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.kyber.access.contracts import AccessScope  # noqa: E402
from services.kyber.access.disclosure import DisclosureLevel  # noqa: E402
from services.kyber.graph import scoped_gateway  # noqa: E402
from services.kyber.graph.contracts import (  # noqa: E402
    TENANT_SCOPED_NODE_TYPES,
    KyberGraphNode,
    KyberNodeType,
)
from services.kyber.graph.repository import KyberGraphStore  # noqa: E402
from services.kyber.graph.routes import read_tenant_entity_neighborhood  # noqa: E402
from services.kyber.graph.scoped_gateway import (  # noqa: E402
    EVIDENCE_CAPABILITY,
    MINIMUM_DISCLOSURE,
    TENANT_GRAPH_CAPABILITY,
    ScopedTenantGraphGateway,
)
from shared.common.common import utc_now  # noqa: E402

TENANT_A = "tenant_acme"
TENANT_B = "tenant_globex"
TENANT_C = "tenant_initech"
ENV = "test"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_stores():
    """Every test starts from an empty graph and an uninjected gateway."""
    reset_in_memory_stores()
    scoped_gateway.reset_store()
    scoped_gateway.reset_tenant_graph()
    yield
    scoped_gateway.reset_store()
    scoped_gateway.reset_tenant_graph()
    reset_in_memory_stores()


# ── Denial helper ────────────────────────────────────────────────────────────


async def _denied(awaitable: Any) -> str:
    """Await something that must refuse, returning its ``denial_reason``.

    The exception class is matched by *name*, resolved at call time. Importing
    ``ForbiddenError`` at module scope and using ``pytest.raises`` would bind a
    class object that a sibling suite's ``shared.*`` purge can replace, after
    which a genuine refusal would be reported as an unrelated error and the
    security assertion would silently stop being made.
    """
    try:
        result = await awaitable
    except Exception as exc:  # noqa: BLE001 - the class is checked below
        assert type(exc).__name__ == "ForbiddenError", (
            f"expected a Kyber ForbiddenError, got {type(exc).__name__}: {exc}"
        )
        reason = (getattr(exc, "details", None) or {}).get("denial_reason")
        assert reason, f"denial carried no denial_reason: {getattr(exc, 'details', None)!r}"
        return str(reason)
    raise AssertionError(
        f"expected a refusal, but the call returned a result: {result!r}"
    )


# ── Test doubles ─────────────────────────────────────────────────────────────


class FakeContext:
    """The attributes ``ScopedTenantGraphGateway`` reads off a Kyber context.

    Deliberately not a ``KyberAccessContext``: building one needs a live
    session, principal and device, none of which this gateway consults. Every
    field the gateway *does* read is present with the real semantics —
    ``masks_identifiers`` in particular is a method, as it is on the real
    context, because the gateway branches on it being callable.
    """

    def __init__(
        self,
        *,
        scope: Optional[AccessScope],
        capabilities: frozenset[str] = frozenset({TENANT_GRAPH_CAPABILITY}),
        disclosure: DisclosureLevel = DisclosureLevel.D3_TENANT_VISIBLE,
        tenant_id: Optional[str] = None,
        environment: str = ENV,
    ) -> None:
        self.scope = scope
        self.capabilities = capabilities
        self.granted_disclosure = disclosure
        #: What the *request* named. On the real context this is filled from
        #: the path/query/header, i.e. it is client-supplied.
        self.tenant_id = tenant_id
        self.environment = environment
        self.operator_id = "op_test"
        self.session_id = "sess_test"
        self.device_id = "dev_test"

    def masks_identifiers(self) -> bool:
        return self.granted_disclosure <= DisclosureLevel.D2_TENANT_MASKED


class CountingGraph:
    """A ``GraphClient`` wrapper that records the calls made through it.

    Used to prove the existence-oracle property structurally: two requests that
    must be indistinguishable have to issue the *same* backend calls, not just
    return the same body. A refusal path that skipped a lookup would be
    distinguishable by latency even with identical payloads.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    async def get_vertex(self, vertex_id: str):
        self.calls.append("get_vertex")
        return await self._inner.get_vertex(vertex_id)

    async def get_neighbors(self, vertex_id: str, direction: str = "out"):
        self.calls.append("get_neighbors")
        return await self._inner.get_neighbors(vertex_id, direction=direction)

    async def get_vertices_for_tenant(
        self, tenant_id: str, limit: int = 1000, *, vertex_type: Optional[str] = None
    ):
        self.calls.append("get_vertices_for_tenant")
        return await self._inner.get_vertices_for_tenant(
            tenant_id, limit, vertex_type=vertex_type
        )


def _graph():
    """A real ``GraphClient`` over the in-memory backend. No database."""
    from shared.graph.graph import GraphClient, _InMemoryGraphBackend

    client = GraphClient.__new__(GraphClient)
    client._backend = _InMemoryGraphBackend()
    client._mode = "local"
    return client


async def _add_vertex(graph: Any, tenant_id: str, label: str, vertex_type: str = "entity"):
    from shared.graph.graph import Vertex

    vertex = Vertex(vertex_type, str(uuid4()), {"tenantId": tenant_id, "label": label})
    await graph._backend.add_vertex(vertex)
    return vertex


async def _add_edge(graph: Any, source: Any, target: Any, tenant_id: str):
    from shared.graph.graph import Edge

    await graph._backend.add_edge(
        Edge("SIMILAR_TO", source.vertex_id, target.vertex_id, {"tenantId": tenant_id})
    )


def _scope(
    tenant_id: str,
    *,
    minutes: int = 30,
    status: str = "active",
) -> AccessScope:
    return AccessScope(
        operator_id="op_test",
        session_id="sess_test",
        device_id="dev_test",
        environment=ENV,
        tenant_id=tenant_id,
        purpose="incident_response",
        reason="investigating an ingestion backlog",
        status=status,  # type: ignore[arg-type]
        expires_at=(utc_now() + timedelta(minutes=minutes)).isoformat(),
    )


def _request(context: Optional[FakeContext]) -> Any:
    """A request carrying the context exactly where the real dependency puts it.

    The gateway reads it through ``current_kyber_context``, the declared seam,
    rather than through a patched module global — so a rename in the access
    plane breaks this suite instead of quietly making every read deny.
    """
    return SimpleNamespace(state=SimpleNamespace(kyber_context=context))


async def _seed(graph: Any, store: Optional[KyberGraphStore] = None) -> None:
    scoped_gateway.set_tenant_graph(graph)
    scoped_gateway.set_store(store if store is not None else KyberGraphStore())


# ── 1. Cross-tenant reads ────────────────────────────────────────────────────


async def test_scope_on_one_tenant_cannot_read_another_through_query():
    """A live scope on A asked for B is refused, not silently rescoped to A.

    Answering with A's data would make the audit trail lie about what was
    asked for, so the reason has to be a mismatch and not a successful read.
    """
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _add_vertex(graph, TENANT_B, "b-1")
    await _seed(graph)
    request = _request(FakeContext(scope=_scope(TENANT_A)))

    reason = await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(request, tenant_id=TENANT_B)
    )
    assert reason == "scope_tenant_mismatch"


async def test_scope_on_one_tenant_cannot_read_another_through_neighborhood():
    """The neighbourhood surface enforces the same step, with the same reason."""
    graph = _graph()
    foreign = await _add_vertex(graph, TENANT_B, "b-1")
    await _seed(graph)
    request = _request(FakeContext(scope=_scope(TENANT_A)))

    reason = await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.neighborhood(
            request, tenant_id=TENANT_B, vertex_id=foreign.vertex_id
        )
    )
    assert reason == "scope_tenant_mismatch"


async def test_a_scoped_read_reaches_the_tenant_the_scope_names():
    """The control: the gate is refusing the right thing, not everything."""
    graph = _graph()
    mine = await _add_vertex(graph, TENANT_A, "a-1")
    await _add_vertex(graph, TENANT_B, "b-1")
    await _seed(graph)
    request = _request(FakeContext(scope=_scope(TENANT_A)))

    result = await scoped_gateway.scoped_tenant_graph_gateway.query(
        request, tenant_id=TENANT_A
    )
    visible = result["tenantVisible"]
    assert visible["tenant_id"] == TENANT_A
    assert [v["vertex_id"] for v in visible["vertices"]] == [mine.vertex_id]


# ── 2. Expiry mid-session ────────────────────────────────────────────────────


async def test_a_scope_that_expires_mid_session_stops_graph_access():
    """Grant, read, expire, read again — the second read must refuse.

    The route dependency already checked the scope; this gateway re-checks it
    because a scope can expire between the authorization and the read, and
    because the gateway is reachable from callers that are not that route.
    """
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _seed(graph)

    scope = _scope(TENANT_A, minutes=30)
    context = FakeContext(scope=scope)
    request = _request(context)

    first = await scoped_gateway.scoped_tenant_graph_gateway.query(
        request, tenant_id=TENANT_A
    )
    assert first["tenantVisible"]["vertex_count"] == 1

    # The same scope object, now past its expiry. No sleeping and no clock
    # patching: expiry is data on the scope.
    context.scope = scope.model_copy(
        update={"expires_at": (utc_now() - timedelta(seconds=1)).isoformat()}
    )
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(request, tenant_id=TENANT_A)
    ) == "scope_expired"

    # Neighbourhood closes at the same moment.
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.neighborhood(
            request, tenant_id=TENANT_A, vertex_id="anything"
        )
    ) == "scope_expired"


async def test_a_revoked_or_exited_scope_is_refused_even_before_its_expiry():
    """Status is checked independently of the clock."""
    graph = _graph()
    await _seed(graph)
    for status in ("revoked", "exited", "expired"):
        context = FakeContext(scope=_scope(TENANT_A, status=status))
        reason = await _denied(
            scoped_gateway.scoped_tenant_graph_gateway.query(
                _request(context), tenant_id=TENANT_A
            )
        )
        assert reason == "scope_expired", status


async def test_a_missing_scope_denies_rather_than_reading_unscoped():
    graph = _graph()
    await _seed(graph)
    context = FakeContext(scope=None)
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id=TENANT_A)
    ) == "scope_missing"


# ── 3. Truncation ────────────────────────────────────────────────────────────


async def test_scoped_read_returns_every_row_of_its_own_tenant_under_a_binding_cap():
    """A noisy neighbour must not truncate this tenant's answer to nothing.

    The cap here *binds*: 40 foreign vertices are inserted before tenant A's 4,
    and the read budget is 5. A scan-then-filter implementation would fetch the
    first 5 rows — all foreign — and report tenant A as empty, which reads to an
    operator as "this tenant has no data" rather than "the query was wrong".
    The contrast against the legacy shape at the end of this test is the proof
    that the cap is genuinely binding and the assertion is not vacuous.
    """
    graph = _graph()
    for index in range(20):
        await _add_vertex(graph, TENANT_B, f"b-{index}")
    for index in range(20):
        await _add_vertex(graph, TENANT_C, f"c-{index}")
    mine = [await _add_vertex(graph, TENANT_A, f"a-{index}") for index in range(4)]
    await _seed(graph)

    gateway = ScopedTenantGraphGateway(max_results=5)
    request = _request(FakeContext(scope=_scope(TENANT_A)))
    result = await gateway.query(request, tenant_id=TENANT_A, limit=5)

    visible = result["tenantVisible"]
    assert visible["vertex_count"] == 4, "the scoped read lost rows to a foreign tenant's volume"
    assert {v["vertex_id"] for v in visible["vertices"]} == {v.vertex_id for v in mine}
    assert visible["truncated"] is False
    # Nothing foreign came back with them.
    assert all(v["properties"]["tenantId"] == TENANT_A for v in visible["vertices"])

    # The legacy shape this gateway exists to replace, run against the same
    # graph and the same cap. It returns fewer — that gap is the defect.
    legacy_page = await graph.get_all_vertices(limit=5)
    legacy = [v for v in legacy_page if v.properties.get("tenantId") == TENANT_A]
    assert len(legacy) < len(mine), (
        "the legacy scan-then-filter path did not truncate, so this test is not "
        "exercising the binding cap it claims to"
    )


async def test_truncation_of_the_tenants_own_rows_is_reported_not_hidden():
    """When the budget really does bind, the response says so.

    Detected by over-fetching one row, never inferred from a short page: a
    silently capped page and a genuinely small tenant are otherwise identical.
    """
    graph = _graph()
    for index in range(10):
        await _add_vertex(graph, TENANT_A, f"a-{index}")
    await _seed(graph)

    gateway = ScopedTenantGraphGateway(max_results=3)
    result = await gateway.query(
        _request(FakeContext(scope=_scope(TENANT_A))), tenant_id=TENANT_A, limit=3
    )
    assert result["tenantVisible"]["truncated"] is True
    assert result["tenantVisible"]["vertex_count"] == 3
    diagnostics = result["operatorDiagnostics"]
    assert "tenant_vertices:scan_truncated" in diagnostics["missing_inputs"]
    assert diagnostics["exposure_known"] is False


async def test_a_foreign_neighbour_cannot_consume_this_tenants_node_budget():
    """Foreign vertices are dropped before they are charged to the budget."""
    graph = _graph()
    anchor = await _add_vertex(graph, TENANT_A, "anchor")
    foreign = [await _add_vertex(graph, TENANT_B, f"b-{i}") for i in range(6)]
    mine = [await _add_vertex(graph, TENANT_A, f"a-{i}") for i in range(2)]
    for vertex in foreign + mine:
        await _add_edge(graph, anchor, vertex, TENANT_A)
    await _seed(graph)

    gateway = ScopedTenantGraphGateway(max_nodes=3)
    result = await gateway.neighborhood(
        _request(FakeContext(scope=_scope(TENANT_A))),
        tenant_id=TENANT_A,
        vertex_id=anchor.vertex_id,
    )
    visible = result["tenantVisible"]
    assert visible["found"] is True
    assert {v["vertex_id"] for v in visible["neighbors"]} == {v.vertex_id for v in mine}
    assert visible["truncated"] is False


# ── 4. Client-supplied identifiers ───────────────────────────────────────────


async def test_a_tenant_id_in_the_path_never_grants_authority():
    """The path parameter is compared against the scope, not trusted."""
    graph = _graph()
    await _add_vertex(graph, TENANT_B, "b-1")
    await _seed(graph)

    context = FakeContext(scope=_scope(TENANT_A), tenant_id=TENANT_A)
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id=TENANT_B)
    ) == "scope_tenant_mismatch"


async def test_a_tenant_id_carried_on_the_request_cannot_widen_the_scope():
    """A second, client-supplied naming of the tenant is also compared.

    A caller who passes the scoped tenant in the path and a different one in
    the body/query/header does not get either answer: the disagreement itself
    is the denial, because a request that names two tenants cannot be audited
    as having asked about one.
    """
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _seed(graph)

    context = FakeContext(scope=_scope(TENANT_A), tenant_id=TENANT_B)
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id=TENANT_A)
    ) == "scope_tenant_mismatch"


async def test_an_empty_tenant_id_does_not_widen_into_a_cross_tenant_read():
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _add_vertex(graph, TENANT_B, "b-1")
    await _seed(graph)
    context = FakeContext(scope=_scope(TENANT_A))
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id="  ")
    ) == "scope_missing"


async def test_an_unauthorized_request_denies_instead_of_reading():
    """No context and no capability are both refusals, with distinct reasons."""
    graph = _graph()
    await _seed(graph)
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(None), tenant_id=TENANT_A)
    ) == "no_kyber_context"

    context = FakeContext(scope=_scope(TENANT_A), capabilities=frozenset())
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id=TENANT_A)
    ) == "capability_missing"


async def test_an_unavailable_store_denies_rather_than_reporting_an_empty_tenant():
    """Infrastructure absence must not render as "this tenant has no data"."""
    graph = _graph()
    scoped_gateway.set_tenant_graph(graph)
    scoped_gateway.set_store(None)
    scoped_gateway._store_probed = True  # a probe that resolved to nothing
    context = FakeContext(scope=_scope(TENANT_A))
    assert await _denied(
        scoped_gateway.scoped_tenant_graph_gateway.query(_request(context), tenant_id=TENANT_A)
    ) == "graph_unavailable"


# ── 5. The existence oracle ──────────────────────────────────────────────────


async def test_the_neighborhood_route_is_not_a_cross_tenant_existence_oracle():
    """A nonexistent entity and another tenant's real entity look identical.

    Identical body, identical operator diagnostics apart from the timestamp,
    and identical store traffic. The last one matters: a path that skipped a
    lookup for one of the two cases would be distinguishable by latency even
    with byte-identical payloads, and that is enough to answer "does tenant B
    have entity X?" one probe at a time.
    """
    graph = _graph()
    foreign = await _add_vertex(graph, TENANT_B, "b-1")
    await _add_vertex(graph, TENANT_A, "a-1")
    counting = CountingGraph(graph)
    await _seed(counting)
    request = _request(FakeContext(scope=_scope(TENANT_A)))

    counting.calls.clear()
    absent = await read_tenant_entity_neighborhood(
        request, tenant_id=TENANT_A, vertex_id=f"vertex-that-does-not-exist-{uuid4()}",
        depth=1, context=request.state.kyber_context,
    )
    absent_calls = list(counting.calls)

    counting.calls.clear()
    others = await read_tenant_entity_neighborhood(
        request, tenant_id=TENANT_A, vertex_id=foreign.vertex_id,
        depth=1, context=request.state.kyber_context,
    )
    others_calls = list(counting.calls)

    absent_body = absent["data"]["tenantVisible"]
    others_body = others["data"]["tenantVisible"]
    assert absent_body["found"] is False
    assert absent_body == others_body, (
        "a foreign entity and an absent one are distinguishable in the response body"
    )
    assert absent_calls == others_calls == ["get_vertex"], (
        "the two cases issue different backend traffic and are therefore "
        "distinguishable by latency"
    )

    absent_diag = dict(absent["data"]["operatorDiagnostics"])
    others_diag = dict(others["data"]["operatorDiagnostics"])
    for diag in (absent_diag, others_diag):
        diag.pop("computed_at", None)
    assert absent_diag == others_diag


# ── 6. Tenant-scoped node types ──────────────────────────────────────────────


async def test_only_tenant_scoped_node_types_may_carry_a_tenant_id():
    """Every node type outside the declared set refuses a ``tenant_id``.

    Asserted over the whole vocabulary rather than one example, because the
    guard is a membership test against a set that will keep growing: a new node
    type added to the Literal without a decision about tenancy would otherwise
    slip through untested.
    """
    from typing import get_args

    store = KyberGraphStore()
    every_type = set(get_args(KyberNodeType))
    assert TENANT_SCOPED_NODE_TYPES <= every_type
    platform_types = sorted(every_type - TENANT_SCOPED_NODE_TYPES)
    assert platform_types, "the vocabulary must contain non-tenant-scoped types"

    for node_type in platform_types:
        node = KyberGraphNode(
            node_key=f"probe:{node_type}",
            node_type=node_type,  # type: ignore[arg-type]
            environment=ENV,
            tenant_id=TENANT_A,
        )
        try:
            await store.upsert_node(node)
        except Exception as exc:  # noqa: BLE001 - class checked by name, see _denied
            assert type(exc).__name__ == "BadRequestError", (
                f"{node_type}: expected a BadRequestError, got {type(exc).__name__}"
            )
            assert "tenant_id" in str(exc)
        else:
            raise AssertionError(
                f"{node_type} is not tenant-scoped but accepted a tenant_id — the "
                f"Kyber Graph would then be storing tenant data, not references to it"
            )
        assert not await store.find_nodes(node_type=node_type, limit=5)  # type: ignore[arg-type]

    # The declared tenant-scoped types are accepted, so the guard is a boundary
    # and not a blanket refusal.
    for node_type in sorted(TENANT_SCOPED_NODE_TYPES):
        stored = await store.upsert_node(
            KyberGraphNode(
                node_key=f"ok:{node_type}",
                node_type=node_type,  # type: ignore[arg-type]
                environment=ENV,
                tenant_id=TENANT_A,
            )
        )
        assert stored.tenant_id == TENANT_A


# ── 7. Disclosure ────────────────────────────────────────────────────────────


async def test_disclosure_below_the_masked_tenant_floor_is_denied():
    """D0 and D1 are aggregate levels; a tenant graph read is not an aggregate."""
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _seed(graph)

    for level in (DisclosureLevel.D0_PLATFORM_TOPOLOGY, DisclosureLevel.D1_FLEET_AGGREGATE):
        assert level < MINIMUM_DISCLOSURE
        context = FakeContext(scope=_scope(TENANT_A), disclosure=level)
        reason = await _denied(
            scoped_gateway.scoped_tenant_graph_gateway.query(
                _request(context), tenant_id=TENANT_A
            )
        )
        assert reason == "disclosure_exceeded", level


async def test_at_the_floor_the_read_is_allowed_but_identifiers_are_masked():
    """D2 is the floor: the read happens, and every identifier is masked.

    The masked value must not be reversible to the tenant id, and it must be
    stable so an operator can still correlate two appearances of one entity
    inside a single response.
    """
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    await _seed(graph)

    context = FakeContext(scope=_scope(TENANT_A), disclosure=MINIMUM_DISCLOSURE)
    result = await scoped_gateway.scoped_tenant_graph_gateway.query(
        _request(context), tenant_id=TENANT_A
    )
    visible = result["tenantVisible"]
    assert visible["tenant_id"] != TENANT_A
    assert visible["tenant_id"].startswith("masked:")
    vertex = visible["vertices"][0]
    assert vertex["properties"]["tenantId"].startswith("masked:")
    assert TENANT_A not in repr(visible)
    assert result["operatorDiagnostics"]["identifiers_masked"] is True
    assert result["operatorDiagnostics"]["granted_disclosure"] == "D2"


async def test_evidence_references_are_gated_on_their_own_capability():
    """Holding the graph capability does not disclose where evidence lives."""
    graph = _graph()
    await _add_vertex(graph, TENANT_A, "a-1")
    store = KyberGraphStore()
    await store.upsert_node(
        KyberGraphNode(
            node_key=f"tenant:{TENANT_A}",
            node_type="Tenant",
            environment=ENV,
            tenant_id=TENANT_A,
            evidence_reference="evidence://bundle/abc",
        )
    )
    await _seed(graph, store)

    without = await scoped_gateway.scoped_tenant_graph_gateway.query(
        _request(FakeContext(scope=_scope(TENANT_A))), tenant_id=TENANT_A
    )
    assert without["operatorDiagnostics"]["evidence_references"] == []
    assert without["operatorDiagnostics"]["evidence_disclosure_gated"] is True

    with_evidence = await scoped_gateway.scoped_tenant_graph_gateway.query(
        _request(
            FakeContext(
                scope=_scope(TENANT_A),
                capabilities=frozenset({TENANT_GRAPH_CAPABILITY, EVIDENCE_CAPABILITY}),
            )
        ),
        tenant_id=TENANT_A,
    )
    assert with_evidence["operatorDiagnostics"]["evidence_references"] == [
        "evidence://bundle/abc"
    ]
