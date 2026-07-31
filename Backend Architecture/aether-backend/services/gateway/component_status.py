"""Aether Gateway — per-component runtime status.

The gateway publishes one status per product surface the API process exposes.
Every status here is *derived* from state this process can actually observe:

- ``routes``          — the surface's paths are present in the live ASGI router
                        table. A surface whose router failed to mount is not
                        being served, whatever the rest of the process is doing.
- ``dependencies``    — the backing dependencies the surface's code actually
                        uses (``database`` / ``cache`` / ``graph`` /
                        ``event_bus``), resolved against the resource registry's
                        own probe results.
- ``workers``         — the supervised worker roles the surface's asynchronous
                        half runs under, read from the WorkerSupervisor's
                        per-role fold. An API-only process hosts no supervisor,
                        so it reports the roles as unobserved rather than well.
- ``backlog``         — in-process backlog/defect gauges the surface publishes.
                        Only series whose non-zero value is unambiguously a
                        defect carry a verdict; everything else stays an
                        observation, so no invented threshold decides health.
- ``model_registry``  — for the inference surface: the canonical model registry
                        is importable and non-empty in this process, and the
                        serving endpoint is explicitly configured.
- ``recent_work``     — requests served under the surface's prefixes plus the
                        surface's own success counters, since process start.

Status vocabulary: :data:`STATUS_OK`, :data:`STATUS_DEGRADED`,
:data:`STATUS_DOWN`, :data:`STATUS_UNKNOWN`.

The single rule the whole module obeys: **an unobserved signal is never
health**. ``STATUS_UNKNOWN`` never rolls up into ``STATUS_OK``, and a component
reports ``STATUS_OK`` only when at least one signal is affirmatively ok and none
is worse. Signals that could not be observed are listed per component under
``unverified`` so a reader can never mistake silence for attestation.

This module is a pure function of the state handed to it. It performs no I/O
and opens no connections, which is what makes it safe to call from the liveness
handler on every container health check.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from services.runtime.roles import WORKER_ROLES

# ── status vocabulary ────────────────────────────────────────────────────────

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

# Signal keys, so callers (notably the readiness probe) can address a specific
# signal without string-matching on prose.
SIGNAL_ROUTES = "routes"
SIGNAL_DEPENDENCIES = "dependencies"
SIGNAL_WORKERS = "workers"
SIGNAL_BACKLOG = "backlog"
SIGNAL_MODEL_REGISTRY = "model_registry"
SIGNAL_RECENT_WORK = "recent_work"

# ResourceRegistry.health_check() vocabulary → this module's vocabulary.
_REGISTRY_STATUS = {
    "ok": STATUS_OK,
    "degraded": STATUS_DEGRADED,
    "error": STATUS_DOWN,
}


# ── component specification ──────────────────────────────────────────────────


@dataclass(frozen=True)
class BacklogSeries:
    """A backlog/defect gauge whose non-zero value is itself the defect.

    ``max_mean`` is the largest mean-since-process-start this process tolerates
    before the surface is reported degraded. Only series with an unambiguous
    zero budget are declared, so no threshold here is a guess.
    """

    name: str
    max_mean: float


@dataclass(frozen=True)
class ComponentSpec:
    """What a product surface is made of, in terms this process can observe."""

    name: str
    # Path prefixes the surface's routers mount under.
    route_prefixes: tuple[str, ...]
    # Registry dependency keys the surface's code actually uses.
    dependencies: tuple[str, ...]
    # Supervised worker roles that run the surface's asynchronous half.
    worker_roles: tuple[str, ...] = ()
    # Backlog/defect gauges the surface publishes into the shared collector.
    backlog: tuple[BacklogSeries, ...] = ()
    # Counter names the surface increments on completed work.
    work_counters: tuple[str, ...] = ()
    # Whether the surface's readiness includes the canonical model registry.
    model_backed: bool = False

    def __post_init__(self) -> None:
        unknown_roles = sorted(set(self.worker_roles) - WORKER_ROLES)
        if unknown_roles:
            raise ValueError(
                f"component {self.name!r} declares worker roles that are not in "
                f"services.runtime.roles.WORKER_ROLES: {unknown_roles}"
            )


# The surfaces the API process exposes. ``dependencies`` mirrors the providers
# each service package imports; ``worker_roles`` names the roles from
# services/runtime/roles.py that own the surface's background half.
COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        name="ingestion",
        route_prefixes=("/v1/ingest", "/v1/batch"),
        dependencies=("database", "cache", "event_bus"),
        worker_roles=("stream-worker", "outbox-relay"),
        work_counters=(
            "events_ingested",
            "event_ingested",
            "api_feeds_ingested",
            "ingestion_batch_received_total",
            "ingestion_v2_batch_received_total",
            "ingestion_silver_written_total",
        ),
    ),
    ComponentSpec(
        name="identity",
        route_prefixes=("/v1/identity",),
        dependencies=("database", "cache", "graph", "event_bus"),
        worker_roles=("identity-worker",),
        work_counters=(
            "identity_resolve_success_total",
            "identity_link_total",
            "identity_merge_total",
            "identity_graph_edge_write_total",
        ),
    ),
    ComponentSpec(
        name="analytics",
        route_prefixes=("/v1/analytics",),
        dependencies=("database", "cache"),
        worker_roles=("measurement-worker", "materializer"),
        work_counters=(
            "analytics_events_read",
            "analytics_exports_created",
            "analytics_commerce_kpi_computed",
        ),
    ),
    ComponentSpec(
        name="ml_serving",
        route_prefixes=("/v1/ml",),
        dependencies=("cache", "event_bus"),
        work_counters=("ml_predictions", "ml_batch_predictions", "feature_store_hit"),
        model_backed=True,
    ),
    ComponentSpec(
        name="agent",
        route_prefixes=("/v1/agent",),
        dependencies=("database", "cache", "graph", "event_bus"),
        backlog=(
            # A run the bridge has lost track of, and a controller that stopped
            # heart-beating, are defects at any count — no threshold to invent.
            BacklogSeries("agent_worker_runs_stuck", 0.0),
            BacklogSeries("agent_workers_stale", 0.0),
        ),
        work_counters=(
            "agent_controller_heartbeats",
            "agent_tasks_submitted",
            "agent_worker_runs_queued",
            "agent_decisions_recorded",
        ),
    ),
    ComponentSpec(
        name="campaign",
        route_prefixes=(
            "/v1/campaigns",
            "/v1/campaign-sources",
            "/v1/campaign-quality",
            "/v1/mapping-review",
        ),
        dependencies=("database", "graph", "event_bus"),
        worker_roles=("measurement-worker",),
        work_counters=(
            "campaigns_read",
            "campaigns_created",
            "campaign_attribution_computed",
            "campaign_touchpoints_recorded",
        ),
    ),
    ComponentSpec(
        name="consent",
        route_prefixes=("/v1/consent", "/v1/audit"),
        dependencies=("database", "event_bus"),
        # retention_sweep enforces the consent-driven erasure schedule.
        worker_roles=("maintenance",),
    ),
    ComponentSpec(
        name="notification",
        route_prefixes=("/v1/notifications",),
        dependencies=("database",),
        # notification_outbox relays, notification_sla and delivery_worker send.
        worker_roles=("outbox-relay", "maintenance"),
    ),
    ComponentSpec(
        name="admin",
        route_prefixes=("/v1/admin",),
        dependencies=("database", "cache", "event_bus"),
        # billing_overage_cron and webhook_inbox back the admin surface.
        worker_roles=("maintenance",),
        work_counters=(
            "stripe_webhook_processed",
            "billing_plan_changes",
            "billing_subscriptions_canceled",
        ),
    ),
)

COMPONENT_NAMES: tuple[str, ...] = tuple(spec.name for spec in COMPONENTS)


# ── supervisor view ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkerView:
    """The per-role worker fold, plus why it is absent when it is.

    ``roles`` is ``None`` whenever this process cannot speak for the workers —
    either it hosts no supervisor (a pure ``api`` role) or the supervisor could
    not be read. ``reason`` carries which, so the emitted detail never claims
    the wrong cause.
    """

    roles: Optional[Mapping[str, Any]]
    reason: str


def collect_worker_view(app: Any) -> WorkerView:
    """Read ``app.state.worker_supervisor`` into a :class:`WorkerView`."""
    supervisor = getattr(getattr(app, "state", None), "worker_supervisor", None)
    if supervisor is None:
        return WorkerView(
            roles=None,
            reason="no worker supervisor in this process; worker roles run in dedicated processes",
        )
    try:
        return WorkerView(roles=dict(supervisor.status_by_role()), reason="worker supervisor attached")
    except Exception as exc:
        return WorkerView(roles=None, reason=f"worker supervisor unreadable: {type(exc).__name__}")


def _walk_routes(
    routes: Iterable[Any],
    prefix: str,
    seen: set[int],
) -> Iterable[str]:
    """Yield every mounted path under ``routes``, descending into sub-routers.

    Starlette exposes leaf routes with a ``path``; FastAPI defers ``include_router``
    into a wrapper holding the included router plus the prefix it was mounted
    under; and ``Mount`` nests a whole routing table beneath its own path. All
    three are walked, so the collected table is the paths the process actually
    serves rather than whatever one framework version happens to flatten.
    """
    for route in routes:
        marker = id(route)
        if marker in seen:
            continue
        seen.add(marker)

        path = getattr(route, "path", None)
        nested = getattr(route, "routes", None)
        if isinstance(path, str):
            yield prefix + path
            if nested:
                yield from _walk_routes(nested, prefix + path, seen)
            continue

        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            mounted_at = prefix + (getattr(context, "prefix", "") or "")
            yield from _walk_routes(getattr(included, "routes", ()) or (), mounted_at, seen)
            continue

        if nested:
            yield from _walk_routes(nested, prefix, seen)


def collect_route_paths(app: Any) -> Optional[tuple[str, ...]]:
    """Read the live router table's paths, or ``None`` when unreachable."""
    routes = getattr(app, "routes", None)
    if routes is None:
        return None
    return tuple(_walk_routes(routes, "", set()))


# ── metric readers ───────────────────────────────────────────────────────────

_PATH_LABEL = re.compile(r"(?:^|[{,])path=([^,}]*)")


def _series_base(key: str) -> str:
    """``name{a=1,b=2}`` → ``name``; an unlabelled key passes through."""
    brace = key.find("{")
    return key if brace < 0 else key[:brace]


def _request_counts_by_path(counters: Mapping[str, Any]) -> dict[str, int]:
    """Fold the request-lifecycle counter into requests-served per path."""
    served: dict[str, int] = {}
    for key, value in counters.items():
        if _series_base(key) != "http_requests_total":
            continue
        match = _PATH_LABEL.search(key)
        if match is None:
            continue
        try:
            served[match.group(1)] = served.get(match.group(1), 0) + int(value)
        except (TypeError, ValueError):
            continue
    return served


def _counter_totals(counters: Mapping[str, Any]) -> dict[str, int]:
    """Sum every labelled variant of each counter back to its base name."""
    totals: dict[str, int] = {}
    for key, value in counters.items():
        base = _series_base(key)
        try:
            totals[base] = totals.get(base, 0) + int(value)
        except (TypeError, ValueError):
            continue
    return totals


def _observed_means(histograms: Mapping[str, Any]) -> dict[str, list[float]]:
    """Collect each gauge/histogram base name's observed means."""
    means: dict[str, list[float]] = {}
    for key, entry in histograms.items():
        if not isinstance(entry, Mapping):
            continue
        try:
            count = int(entry.get("count", 0))
            mean = float(entry.get("avg", 0.0))
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        means.setdefault(_series_base(key), []).append(mean)
    return means


# ── roll-up ──────────────────────────────────────────────────────────────────


def _roll_up_signal(statuses: Iterable[str]) -> str:
    """Worst-of, where ``unknown`` outranks ``ok``.

    Used *within* one signal: a signal that could not fully observe its inputs
    does not get to claim ok on the strength of the inputs it did observe.
    """
    seen = list(statuses)
    if not seen:
        return STATUS_UNKNOWN
    for status in (STATUS_DOWN, STATUS_DEGRADED, STATUS_UNKNOWN):
        if status in seen:
            return status
    return STATUS_OK


def _roll_up_component(statuses: Iterable[str]) -> str:
    """Worst-of across a component's signals.

    ``unknown`` is not fatal here — a freshly started container has genuinely
    served no work yet — but it can never *produce* an ok either: a component
    with no affirmatively-ok signal reports ``unknown``. The unobserved signals
    stay enumerated under ``unverified``.
    """
    seen = list(statuses)
    for status in (STATUS_DOWN, STATUS_DEGRADED):
        if status in seen:
            return status
    return STATUS_OK if STATUS_OK in seen else STATUS_UNKNOWN


def _signal(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "detail": detail, **extra}


# ── signal builders ──────────────────────────────────────────────────────────


def _routes_signal(spec: ComponentSpec, route_paths: Optional[Sequence[str]]) -> dict[str, Any]:
    prefixes = list(spec.route_prefixes)
    if route_paths is None:
        return _signal(
            STATUS_UNKNOWN,
            "router table not reachable from this handler",
            prefixes=prefixes,
        )
    mounted = sum(
        1 for path in route_paths if any(path.startswith(prefix) for prefix in spec.route_prefixes)
    )
    if mounted:
        return _signal(
            STATUS_OK,
            f"{mounted} routes mounted under {', '.join(prefixes)}",
            prefixes=prefixes,
            mounted=mounted,
        )
    return _signal(
        STATUS_DOWN,
        f"no routes mounted under {', '.join(prefixes)}; this surface is not being served",
        prefixes=prefixes,
        mounted=0,
    )


def _dependencies_signal(spec: ComponentSpec, dependency_health: Mapping[str, Any]) -> dict[str, Any]:
    per_dependency: dict[str, str] = {}
    for dependency in spec.dependencies:
        entry = dependency_health.get(dependency) if isinstance(dependency_health, Mapping) else None
        if not isinstance(entry, Mapping):
            per_dependency[dependency] = STATUS_UNKNOWN
            continue
        per_dependency[dependency] = _REGISTRY_STATUS.get(entry.get("status"), STATUS_UNKNOWN)

    status = _roll_up_signal(per_dependency.values())
    impaired = sorted(name for name, value in per_dependency.items() if value != STATUS_OK)
    detail = (
        f"{len(per_dependency)} required dependencies healthy"
        if not impaired
        else f"impaired dependencies: {', '.join(impaired)}"
    )
    return _signal(status, detail, required=per_dependency)


def _workers_signal(spec: ComponentSpec, worker_view: WorkerView) -> dict[str, Any]:
    roles = list(spec.worker_roles)
    if worker_view.roles is None:
        return _signal(
            STATUS_UNKNOWN,
            f"{worker_view.reason}; cannot attest to {', '.join(roles)}",
            roles=roles,
        )

    per_role: dict[str, str] = {}
    failed: dict[str, list[str]] = {}
    for role in spec.worker_roles:
        entry = worker_view.roles.get(role)
        if not isinstance(entry, Mapping):
            per_role[role] = STATUS_UNKNOWN
            continue
        if entry.get("healthy"):
            per_role[role] = STATUS_OK
            continue
        per_role[role] = STATUS_DOWN
        failed[role] = sorted(str(name) for name in (entry.get("failed") or []))

    status = _roll_up_signal(per_role.values())
    if failed:
        detail = "; ".join(f"{role}: {', '.join(names)} failed" for role, names in sorted(failed.items()))
    elif status == STATUS_UNKNOWN:
        unobserved = sorted(role for role, value in per_role.items() if value == STATUS_UNKNOWN)
        detail = f"roles not registered with this supervisor: {', '.join(unobserved)}"
    else:
        detail = f"all workers running for {', '.join(roles)}"
    return _signal(status, detail, roles=per_role)


def _backlog_signal(spec: ComponentSpec, histograms: Mapping[str, Any]) -> dict[str, Any]:
    means = _observed_means(histograms)
    per_series: dict[str, str] = {}
    breached: list[str] = []
    for series in spec.backlog:
        observed = means.get(series.name)
        if not observed:
            per_series[series.name] = STATUS_UNKNOWN
            continue
        worst = max(observed)
        if worst > series.max_mean:
            per_series[series.name] = STATUS_DEGRADED
            breached.append(f"{series.name}={worst:.3g} (budget {series.max_mean:.3g})")
        else:
            per_series[series.name] = STATUS_OK

    status = _roll_up_signal(per_series.values())
    if breached:
        detail = "backlog over budget: " + "; ".join(breached)
    elif status == STATUS_UNKNOWN:
        detail = "no backlog observations published in this process"
    else:
        detail = f"{len(per_series)} backlog series within budget"
    return _signal(status, detail, series=per_series)


def _model_registry_signal() -> dict[str, Any]:
    try:
        from common.model_registry import list_models
    except Exception as exc:
        return _signal(
            STATUS_UNKNOWN,
            f"canonical model registry not importable in this process: {type(exc).__name__}",
        )

    try:
        models = list(list_models())
    except Exception as exc:
        return _signal(
            STATUS_UNKNOWN,
            f"canonical model registry unreadable: {type(exc).__name__}",
        )

    if not models:
        return _signal(STATUS_DOWN, "canonical model registry resolved but declares no models")

    serving_url = os.getenv("ML_SERVING_URL", "")
    if not serving_url:
        return _signal(
            STATUS_DEGRADED,
            f"{len(models)} models resolvable but ML_SERVING_URL is unset",
            models=len(models),
        )
    return _signal(
        STATUS_OK,
        f"{len(models)} models resolvable and serving endpoint configured",
        models=len(models),
    )


def _recent_work_signal(
    spec: ComponentSpec,
    requests_by_path: Mapping[str, int],
    counter_totals: Mapping[str, int],
) -> dict[str, Any]:
    requests = sum(
        count
        for path, count in requests_by_path.items()
        if any(path.startswith(prefix) for prefix in spec.route_prefixes)
    )
    operations = sum(counter_totals.get(name, 0) for name in spec.work_counters)
    if requests or operations:
        return _signal(
            STATUS_OK,
            f"{requests} requests served and {operations} domain operations since process start",
            requests=requests,
            operations=operations,
        )
    return _signal(
        STATUS_UNKNOWN,
        "no requests or domain operations recorded since process start",
        requests=0,
        operations=0,
    )


# ── report ───────────────────────────────────────────────────────────────────


def component_report(
    *,
    dependency_health: Mapping[str, Any],
    route_paths: Optional[Sequence[str]],
    worker_view: WorkerView,
    metrics_snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Derive every component's status from the observed state handed in.

    Interface for other gateway probes (``/v1/ready`` included): the return is
    ``{component_name: {"status", "signals", "unverified"}}`` where ``status``
    is one of :data:`STATUS_OK`, :data:`STATUS_DEGRADED`, :data:`STATUS_DOWN`,
    :data:`STATUS_UNKNOWN`; ``signals`` maps a ``SIGNAL_*`` key to
    ``{"status", "detail", ...}``; and ``unverified`` lists the signal keys that
    could not be observed. Pure — no I/O, no connections, no mutation.
    """
    counters = metrics_snapshot.get("counters") if isinstance(metrics_snapshot, Mapping) else None
    histograms = metrics_snapshot.get("histograms") if isinstance(metrics_snapshot, Mapping) else None
    counters = counters if isinstance(counters, Mapping) else {}
    histograms = histograms if isinstance(histograms, Mapping) else {}

    requests_by_path = _request_counts_by_path(counters)
    counter_totals = _counter_totals(counters)

    report: dict[str, dict[str, Any]] = {}
    for spec in COMPONENTS:
        signals: dict[str, dict[str, Any]] = {
            SIGNAL_ROUTES: _routes_signal(spec, route_paths),
            SIGNAL_DEPENDENCIES: _dependencies_signal(spec, dependency_health),
            SIGNAL_RECENT_WORK: _recent_work_signal(spec, requests_by_path, counter_totals),
        }
        if spec.worker_roles:
            signals[SIGNAL_WORKERS] = _workers_signal(spec, worker_view)
        if spec.backlog:
            signals[SIGNAL_BACKLOG] = _backlog_signal(spec, histograms)
        if spec.model_backed:
            signals[SIGNAL_MODEL_REGISTRY] = _model_registry_signal()

        report[spec.name] = {
            "status": _roll_up_component(signal["status"] for signal in signals.values()),
            "signals": signals,
            "unverified": sorted(
                name for name, signal in signals.items() if signal["status"] == STATUS_UNKNOWN
            ),
        }
    return report


def aggregate_status(report: Mapping[str, Mapping[str, Any]]) -> str:
    """Worst component status across ``report``, using the component roll-up."""
    return _roll_up_component(
        entry.get("status", STATUS_UNKNOWN) for entry in report.values()
    )
