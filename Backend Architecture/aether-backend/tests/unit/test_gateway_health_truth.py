"""The gateway liveness body must never assert health it has not observed.

``/v1/health`` is the ECS container ``healthCheck`` command and the ALB target
group's health check path. That fixes two independent obligations, and these
tests pin both:

1. It stays a *liveness* predicate — 200 while the process can serve, even with
   every dependency down. A non-200 on degradation would have ECS kill live
   containers during a rollout and the service could never stabilise. The
   degraded/503 verdict belongs to ``/v1/ready``.
2. Its body reports only derived state. It used to emit a fixed map of nine
   ``"ok"`` strings that no code consulted, so a container whose database,
   cache, graph and event bus were all refusing connections still published
   nine healthy services. Every component state is now derived, and a signal
   the process cannot observe is reported unknown, never healthy.

The guard at the bottom fails if a bare ``"ok"`` literal is reintroduced into
the handler module.
"""

from __future__ import annotations

import ast
import sys
import types
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from services.gateway import component_status as cs
from services.gateway import routes as gateway_routes
from services.runtime.roles import WORKER_ROLES

ALL_DEPENDENCIES = ("database", "cache", "graph", "event_bus")


# ── fixtures / builders ──────────────────────────────────────────────────────


class _Registry:
    """Stands in for ResourceRegistry, returning a fixed dependency probe."""

    def __init__(self, health: dict[str, Any]) -> None:
        self._health = health

    async def health_check(self) -> dict[str, Any]:
        return self._health


class _Supervisor:
    """Stands in for WorkerSupervisor's per-role fold."""

    def __init__(self, by_role: dict[str, Any]) -> None:
        self._by_role = by_role

    def status_by_role(self) -> dict[str, Any]:
        return self._by_role


class _Metrics:
    """Stands in for the shared MetricsCollector snapshot."""

    def __init__(self, counters: dict[str, int], histograms: dict[str, Any]) -> None:
        self._snapshot = {"counters": counters, "histograms": histograms}

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot


def dependencies_all(status: str, error: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"status": status}
    if error is not None:
        entry["error"] = error
    return {name: dict(entry) for name in ALL_DEPENDENCIES}


def healthy_roles() -> dict[str, Any]:
    return {role: {"healthy": True, "workers": {}, "failed": []} for role in sorted(WORKER_ROLES)}


def _probe() -> dict[str, Any]:
    return {}


def build_app(*, mount: tuple[str, ...] | None = None, supervisor: Any = None) -> FastAPI:
    """An app serving the gateway plus one route per requested surface prefix."""
    app = FastAPI()
    app.include_router(gateway_routes.router)

    prefixes = mount
    if prefixes is None:
        prefixes = tuple(
            prefix for spec in cs.COMPONENTS for prefix in spec.route_prefixes
        )
    surfaces = APIRouter()
    for index, prefix in enumerate(prefixes):
        surfaces.add_api_route(f"{prefix}/__probe{index}", _probe, methods=["GET"])
    app.include_router(surfaces)

    app.state.worker_supervisor = supervisor
    return app


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch):
    """Factory returning a TestClient with the handler's collaborators stubbed."""

    def _make(
        *,
        dependency_health: dict[str, Any],
        mount: tuple[str, ...] | None = None,
        supervisor: Any = None,
        counters: dict[str, int] | None = None,
        histograms: dict[str, Any] | None = None,
    ) -> TestClient:
        monkeypatch.setattr(
            gateway_routes, "get_registry", lambda: _Registry(dependency_health)
        )
        monkeypatch.setattr(
            gateway_routes, "metrics", _Metrics(counters or {}, histograms or {})
        )
        return TestClient(build_app(mount=mount, supervisor=supervisor))

    return _make


@pytest.fixture
def fake_model_registry(monkeypatch: pytest.MonkeyPatch):
    """Install an importable ``common.model_registry`` for the inference signal."""

    def _install(models: list[Any]) -> None:
        package = types.ModuleType("common")
        module = types.ModuleType("common.model_registry")
        module.list_models = lambda: list(models)  # type: ignore[attr-defined]
        package.model_registry = module  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "common", package)
        monkeypatch.setitem(sys.modules, "common.model_registry", module)

    return _install


def component_statuses(body: dict[str, Any]) -> dict[str, str]:
    return {name: entry["status"] for name, entry in body["components"].items()}


def signal_statuses(body: dict[str, Any], component: str) -> dict[str, str]:
    return {
        name: signal["status"]
        for name, signal in body["components"][component]["signals"].items()
    }


# ── 1. liveness is preserved (no rollout deadlock) ───────────────────────────


def test_health_stays_200_with_every_dependency_down(gateway):
    """ECS/ALB use this path as a liveness probe; degradation must not kill the task."""
    client = gateway(dependency_health=dependencies_all("error", "ConnectionRefusedError"))
    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["probe"] == "liveness"
    assert body["readiness_probe"] == "/v1/ready"


def test_health_and_v1_health_are_the_same_liveness_predicate(gateway):
    client = gateway(dependency_health=dependencies_all("error"))
    assert client.get("/health").status_code == 200
    assert client.get("/v1/health").status_code == 200


# ── 2. the body stops asserting unobserved health ────────────────────────────


def test_no_component_claims_ok_when_every_dependency_is_down(gateway):
    """The exact regression: nine hardcoded "ok" strings with all backends dead."""
    client = gateway(dependency_health=dependencies_all("error", "ConnectionRefusedError"))
    body = client.get("/v1/health").json()

    statuses = component_statuses(body)
    assert set(statuses) == set(cs.COMPONENT_NAMES)
    assert cs.STATUS_OK not in statuses.values(), statuses
    assert set(statuses.values()) == {cs.STATUS_DOWN}
    assert body["status"] == "degraded"


def test_component_body_carries_no_bare_ok_string_without_a_backing_signal(gateway):
    """Every "ok" that appears anywhere in the body must name the signal behind it."""
    client = gateway(dependency_health=dependencies_all("error"))
    body = client.get("/v1/health").json()

    for name, entry in body["components"].items():
        for signal_name, signal in entry["signals"].items():
            if signal["status"] == cs.STATUS_OK:
                assert signal["detail"], f"{name}.{signal_name} claims ok with no detail"
                assert signal_name != cs.SIGNAL_DEPENDENCIES


def test_degraded_dependency_degrades_rather_than_downs_the_component(gateway):
    client = gateway(dependency_health=dependencies_all("degraded"), supervisor=_Supervisor(healthy_roles()))
    body = client.get("/v1/health").json()

    assert set(component_statuses(body).values()) == {cs.STATUS_DEGRADED}
    assert body["status"] == "degraded"


def test_healthy_process_reports_ok_from_positive_signals_only(gateway):
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    )
    body = client.get("/v1/health").json()

    statuses = component_statuses(body)
    assert statuses["ingestion"] == cs.STATUS_OK
    # Every ok component is backed by at least one affirmatively-ok signal.
    for name, entry in body["components"].items():
        if entry["status"] != cs.STATUS_OK:
            continue
        assert cs.STATUS_OK in signal_statuses(body, name).values()
    # Nothing this process could not observe is hidden.
    assert body["components"]["ingestion"]["unverified"] == [cs.SIGNAL_RECENT_WORK]


# ── 3. route activation is a real signal ─────────────────────────────────────


def test_unmounted_surface_reports_down_even_with_healthy_dependencies(gateway):
    """A router that failed to mount is not being served, whatever the backends say."""
    mounted = tuple(
        prefix
        for spec in cs.COMPONENTS
        if spec.name != "notification"
        for prefix in spec.route_prefixes
    )
    client = gateway(
        dependency_health=dependencies_all("ok"),
        mount=mounted,
        supervisor=_Supervisor(healthy_roles()),
    )
    body = client.get("/v1/health").json()

    assert component_statuses(body)["notification"] == cs.STATUS_DOWN
    assert signal_statuses(body, "notification")[cs.SIGNAL_ROUTES] == cs.STATUS_DOWN
    assert component_statuses(body)["ingestion"] == cs.STATUS_OK
    assert body["status"] == "degraded"


def test_route_collection_descends_into_included_routers():
    app = build_app()
    paths = cs.collect_route_paths(app)

    assert paths is not None
    assert "/v1/health" in paths
    for spec in cs.COMPONENTS:
        assert any(
            path.startswith(spec.route_prefixes[0]) for path in paths
        ), f"{spec.name} prefixes not discovered"


def test_unreachable_route_table_is_unknown_not_ok():
    report = cs.component_report(
        dependency_health=dependencies_all("ok"),
        route_paths=None,
        worker_view=cs.WorkerView(roles=healthy_roles(), reason="attached"),
        metrics_snapshot={},
    )
    routes_signal = report["ingestion"]["signals"][cs.SIGNAL_ROUTES]
    assert routes_signal["status"] == cs.STATUS_UNKNOWN
    assert cs.SIGNAL_ROUTES in report["ingestion"]["unverified"]


# ── 4. worker state is a real signal ─────────────────────────────────────────


def test_failed_worker_role_brings_its_components_down(gateway):
    roles = healthy_roles()
    roles["outbox-relay"] = {
        "healthy": False,
        "workers": {},
        "failed": ["notification_outbox"],
    }
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(roles),
    )
    body = client.get("/v1/health").json()

    statuses = component_statuses(body)
    assert statuses["notification"] == cs.STATUS_DOWN
    assert statuses["ingestion"] == cs.STATUS_DOWN
    assert signal_statuses(body, "notification")[cs.SIGNAL_WORKERS] == cs.STATUS_DOWN
    detail = body["components"]["notification"]["signals"][cs.SIGNAL_WORKERS]["detail"]
    assert "notification_outbox" in detail
    # A role this failure does not touch keeps its own verdict.
    assert statuses["analytics"] == cs.STATUS_OK


def test_absent_supervisor_is_unknown_never_ok(gateway):
    """An API-only process hosts no workers, so it cannot vouch for them."""
    client = gateway(dependency_health=dependencies_all("ok"), supervisor=None)
    body = client.get("/v1/health").json()

    workers = body["components"]["notification"]["signals"][cs.SIGNAL_WORKERS]
    assert workers["status"] == cs.STATUS_UNKNOWN
    assert "no worker supervisor in this process" in workers["detail"]
    assert cs.SIGNAL_WORKERS in body["components"]["notification"]["unverified"]


def test_unreadable_supervisor_reports_why_it_is_unknown():
    class _Broken:
        def status_by_role(self) -> dict[str, Any]:
            raise RuntimeError("supervisor lock poisoned")

    app = types.SimpleNamespace(state=types.SimpleNamespace(worker_supervisor=_Broken()))
    view = cs.collect_worker_view(app)

    assert view.roles is None
    assert "RuntimeError" in view.reason
    assert "no worker supervisor" not in view.reason


def test_unregistered_worker_role_is_unknown_not_ok():
    report = cs.component_report(
        dependency_health=dependencies_all("ok"),
        route_paths=("/v1/notifications/x",),
        worker_view=cs.WorkerView(roles={}, reason="attached"),
        metrics_snapshot={},
    )
    workers = report["notification"]["signals"][cs.SIGNAL_WORKERS]
    assert workers["status"] == cs.STATUS_UNKNOWN


def test_declared_worker_roles_are_canonical():
    """Component specs may only name roles services/runtime/roles.py owns."""
    for spec in cs.COMPONENTS:
        assert set(spec.worker_roles) <= WORKER_ROLES, spec.name


def test_component_spec_rejects_an_uncanonical_worker_role():
    with pytest.raises(ValueError, match="WORKER_ROLES"):
        cs.ComponentSpec(
            name="invented",
            route_prefixes=("/v1/invented",),
            dependencies=("database",),
            worker_roles=("no-such-worker",),
        )


# ── 5. dependency attribution is per component ───────────────────────────────


def test_only_components_that_use_a_dependency_react_to_it():
    """notification uses only the database; graph loss must not implicate it."""
    health = dependencies_all("ok")
    health["graph"] = {"status": "error", "error": "ConnectionRefusedError"}
    report = cs.component_report(
        dependency_health=health,
        route_paths=tuple(
            f"{prefix}/x" for spec in cs.COMPONENTS for prefix in spec.route_prefixes
        ),
        worker_view=cs.WorkerView(roles=healthy_roles(), reason="attached"),
        metrics_snapshot={},
    )

    assert report["identity"]["status"] == cs.STATUS_DOWN
    assert report["campaign"]["status"] == cs.STATUS_DOWN
    assert report["notification"]["status"] == cs.STATUS_OK
    assert report["analytics"]["status"] == cs.STATUS_OK


def test_missing_dependency_entry_is_unknown_not_ok():
    """A registry that stops reporting a backend must not read as healthy."""
    health = dependencies_all("ok")
    del health["database"]
    report = cs.component_report(
        dependency_health=health,
        route_paths=("/v1/notifications/x",),
        worker_view=cs.WorkerView(roles=healthy_roles(), reason="attached"),
        metrics_snapshot={},
    )

    dependencies = report["notification"]["signals"][cs.SIGNAL_DEPENDENCIES]
    assert dependencies["status"] == cs.STATUS_UNKNOWN
    assert dependencies["required"]["database"] == cs.STATUS_UNKNOWN


def test_unrecognised_dependency_status_is_unknown_not_ok():
    health = dependencies_all("ok")
    health["database"] = {"status": "probably fine"}
    report = cs.component_report(
        dependency_health=health,
        route_paths=("/v1/notifications/x",),
        worker_view=cs.WorkerView(roles=healthy_roles(), reason="attached"),
        metrics_snapshot={},
    )
    assert (
        report["notification"]["signals"][cs.SIGNAL_DEPENDENCIES]["status"]
        == cs.STATUS_UNKNOWN
    )


# ── 6. backlog, model readiness and recent work ──────────────────────────────


def test_backlog_defect_series_degrades_its_component(gateway):
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
        histograms={"agent_worker_runs_stuck": {"count": 4, "avg": 3.0}},
    )
    body = client.get("/v1/health").json()

    backlog = body["components"]["agent"]["signals"][cs.SIGNAL_BACKLOG]
    assert backlog["status"] == cs.STATUS_DEGRADED
    assert "agent_worker_runs_stuck" in backlog["detail"]
    assert component_statuses(body)["agent"] == cs.STATUS_DEGRADED


def test_backlog_within_budget_is_ok_and_absent_observations_are_unknown(gateway):
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
        histograms={
            "agent_worker_runs_stuck{tenant_id=t1}": {"count": 9, "avg": 0.0},
            "agent_workers_stale": {"count": 9, "avg": 0.0},
        },
    )
    observed = client.get("/v1/health").json()
    assert observed["components"]["agent"]["signals"][cs.SIGNAL_BACKLOG]["status"] == cs.STATUS_OK

    silent = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()
    backlog = silent["components"]["agent"]["signals"][cs.SIGNAL_BACKLOG]
    assert backlog["status"] == cs.STATUS_UNKNOWN
    assert cs.SIGNAL_BACKLOG in silent["components"]["agent"]["unverified"]


def test_model_registry_signal_tracks_the_canonical_registry(
    gateway, fake_model_registry, monkeypatch
):
    monkeypatch.setenv("ML_SERVING_URL", "http://ml-serving:8080")
    fake_model_registry(["churn", "ltv"])
    body = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()

    signal = body["components"]["ml_serving"]["signals"][cs.SIGNAL_MODEL_REGISTRY]
    assert signal["status"] == cs.STATUS_OK
    assert signal["models"] == 2


def test_empty_model_registry_downs_the_inference_surface(gateway, fake_model_registry, monkeypatch):
    monkeypatch.setenv("ML_SERVING_URL", "http://ml-serving:8080")
    fake_model_registry([])
    body = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()

    assert (
        body["components"]["ml_serving"]["signals"][cs.SIGNAL_MODEL_REGISTRY]["status"]
        == cs.STATUS_DOWN
    )
    assert component_statuses(body)["ml_serving"] == cs.STATUS_DOWN


def test_unconfigured_serving_endpoint_degrades_the_inference_surface(
    gateway, fake_model_registry, monkeypatch
):
    monkeypatch.delenv("ML_SERVING_URL", raising=False)
    fake_model_registry(["churn"])
    body = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()

    signal = body["components"]["ml_serving"]["signals"][cs.SIGNAL_MODEL_REGISTRY]
    assert signal["status"] == cs.STATUS_DEGRADED
    assert "ML_SERVING_URL" in signal["detail"]


def test_unimportable_model_registry_is_unknown_not_ok(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.model_registry", None)
    report = cs.component_report(
        dependency_health=dependencies_all("ok"),
        route_paths=("/v1/ml/predict",),
        worker_view=cs.WorkerView(roles=healthy_roles(), reason="attached"),
        metrics_snapshot={},
    )
    signal = report["ml_serving"]["signals"][cs.SIGNAL_MODEL_REGISTRY]
    assert signal["status"] == cs.STATUS_UNKNOWN
    assert cs.SIGNAL_MODEL_REGISTRY in report["ml_serving"]["unverified"]


def test_recent_work_is_derived_from_observed_counters(gateway):
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
        counters={
            "http_requests_total{method=POST,path=/v1/ingest/events}": 12,
            "events_ingested": 340,
            "http_requests_total{method=GET,path=/v1/analytics/overview}": 3,
        },
    )
    body = client.get("/v1/health").json()

    ingestion = body["components"]["ingestion"]["signals"][cs.SIGNAL_RECENT_WORK]
    assert ingestion["status"] == cs.STATUS_OK
    assert ingestion["requests"] == 12
    assert ingestion["operations"] == 340

    analytics = body["components"]["analytics"]["signals"][cs.SIGNAL_RECENT_WORK]
    assert analytics["requests"] == 3
    assert analytics["operations"] == 0

    idle = body["components"]["consent"]["signals"][cs.SIGNAL_RECENT_WORK]
    assert idle["status"] == cs.STATUS_UNKNOWN
    assert cs.SIGNAL_RECENT_WORK in body["components"]["consent"]["unverified"]


def test_idle_process_is_not_degraded_by_the_absence_of_work(gateway):
    """A container that has served nothing yet is not thereby broken."""
    body = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()

    assert body["status"] == "healthy"
    assert component_statuses(body)["consent"] == cs.STATUS_OK


# ── 7. roll-up rules ─────────────────────────────────────────────────────────


def test_unknown_signals_alone_never_produce_ok():
    report = cs.component_report(
        dependency_health={},
        route_paths=None,
        worker_view=cs.WorkerView(roles=None, reason="no worker supervisor in this process"),
        metrics_snapshot={},
    )
    for name, entry in report.items():
        assert entry["status"] == cs.STATUS_UNKNOWN, name
        assert entry["unverified"] == sorted(entry["signals"]), name
    assert cs.aggregate_status(report) == cs.STATUS_UNKNOWN


def test_worst_signal_wins_and_aggregate_follows():
    assert cs.aggregate_status({"a": {"status": cs.STATUS_OK}, "b": {"status": cs.STATUS_DOWN}}) == cs.STATUS_DOWN
    assert cs.aggregate_status({"a": {"status": cs.STATUS_OK}, "b": {"status": cs.STATUS_DEGRADED}}) == cs.STATUS_DEGRADED
    assert cs.aggregate_status({"a": {"status": cs.STATUS_OK}, "b": {"status": cs.STATUS_UNKNOWN}}) == cs.STATUS_OK
    assert cs.aggregate_status({}) == cs.STATUS_UNKNOWN


# ── 8. regression guard on the handler source ────────────────────────────────


def _handler_source() -> tuple[str, ast.Module]:
    path = gateway_routes.__file__
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    return source, ast.parse(source)


def test_handler_module_contains_no_bare_ok_string_literal():
    """Fails if a hardcoded "ok" is reintroduced into the gateway handler.

    The defect this suite exists for was a dict of nine ``"ok"`` literals that
    no signal backed. Component state must come from component_status.py, whose
    STATUS_OK constant is only ever returned alongside the signal that earned
    it, so the handler module itself needs no ``"ok"`` string at all.
    """
    source, tree = _handler_source()
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().lower() == "ok"
    ]
    assert not offenders, (
        f"bare \"ok\" literal(s) reintroduced at line(s) {offenders} of "
        f"{gateway_routes.__file__}; derive the value from "
        "services.gateway.component_status instead"
    )
    assert "component_status" in source


def test_handler_delegates_component_state_to_the_derived_report():
    """The handler must not rebuild a component map of its own."""
    _, tree = _handler_source()
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "health_check"
    )
    calls = {
        node.func.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "component_report" in calls
    assert "aggregate_status" in calls

    literal_component_maps = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value in cs.COMPONENT_NAMES
            for key in node.keys
            if key is not None
        )
    ]
    assert not literal_component_maps, (
        f"component states hardcoded in the handler at line(s) {literal_component_maps}"
    )


# ── 9. the contract the deployment already depends on ────────────────────────


def test_body_keeps_the_shape_the_staging_preflight_reads(gateway):
    """scripts/lib/preflight_http.py reads ``status`` and the ``dependencies`` map."""
    client = gateway(
        dependency_health=dependencies_all("ok"),
        supervisor=_Supervisor(healthy_roles()),
    )
    body = client.get("/v1/health").json()

    assert body["status"] == "healthy"
    assert set(body["dependencies"]) == set(ALL_DEPENDENCIES)
    assert all(
        isinstance(entry, dict) and "status" in entry
        for entry in body["dependencies"].values()
    )
    assert "timestamp" in body


def test_preflight_sees_degraded_when_a_component_is_down(gateway):
    """A surface that stopped being served must reach the promotion gate."""
    mounted = tuple(
        prefix
        for spec in cs.COMPONENTS
        if spec.name != "consent"
        for prefix in spec.route_prefixes
    )
    body = gateway(
        dependency_health=dependencies_all("ok"),
        mount=mounted,
        supervisor=_Supervisor(healthy_roles()),
    ).get("/v1/health").json()

    assert body["status"] == "degraded"
    assert component_statuses(body)["consent"] == cs.STATUS_DOWN
