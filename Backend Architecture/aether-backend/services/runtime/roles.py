"""Aether Runtime — role helpers (PR 4 / FT-4).

``AETHER_ROLE`` selects which slice of the process runs. This module owns the
*pure* role logic used by both the FastAPI lifespan (``main.py``) and the
role entrypoint (``services/runtime/run_role.py``):

- :data:`WORKER_ROLES` — the worker classes split out of the request lifecycle.
- :data:`ALL_ROLES` — every valid ``AETHER_ROLE`` token (workers + ``api`` + ``all``).
- :func:`should_start_workers` / :func:`should_start_consumers` — lifespan gates.
- :data:`ROLE_TO_SPEC_NAMES` + :func:`specs_for_role` — map a role onto the
  supervised :class:`WorkerSpec` subset it owns.

Deliberately dependency-free (no settings/registry imports) so it is trivially
importable and unit-testable regardless of suite ordering.
"""

from __future__ import annotations

from typing import Iterable, TypeVar

# Worker roles: each names a class of supervised background workers that a
# dedicated process runs instead of the API. Order is irrelevant (a set).
WORKER_ROLES: frozenset[str] = frozenset(
    {
        "outbox-relay",
        "stream-worker",
        "identity-worker",
        "graph-writer",
        "measurement-worker",
        "semantic-worker",
        "materializer",
        "maintenance",
    }
)

# Every valid AETHER_ROLE token: the worker roles plus the pure API server and
# the single-process "all" default. Kept in sync with config.settings.RUNTIME_ROLES.
ALL_ROLES: frozenset[str] = WORKER_ROLES | {"api", "all"}

# Worker roles whose process also attaches the shared stream (Kafka) consumers.
# A pure "api" process attaches none; "all" attaches everything.
CONSUMER_ROLES: frozenset[str] = frozenset(
    {
        "stream-worker",
        "identity-worker",
        "graph-writer",
        "measurement-worker",
        "semantic-worker",
    }
)

# Map each worker role onto the supervised loop WorkerSpec names it owns. Stream
# consumers are independently and canonically owned by ``consumer_specs.py``;
# identity/graph/measurement therefore need no artificial loop spec here.
ROLE_TO_SPEC_NAMES: dict[str, frozenset[str]] = {
    "outbox-relay": frozenset({"notification_outbox", "event_outbox_relay"}),
    "stream-worker": frozenset({"event_replay", "dune_polling"}),
    "identity-worker": frozenset(),
    # The Kyber Graph projector consumes the graph mutation ledger into platform
    # topology. It is the first loop spec this role owns; the role was otherwise
    # consumer-attached only.
    "graph-writer": frozenset({"kyber_graph_projector"}),
    "measurement-worker": frozenset(),
    # Stream consumer is owned by consumer_specs.py; Phase B adds replay/reconciler
    # supervised loop specs here.
    "semantic-worker": frozenset(),
    "materializer": frozenset(
        {"export_expiry_sweep", "payment_rail_sync", "bronze_object_compaction"}
    ),
    "maintenance": frozenset(
        {
            "billing_overage_cron",
            "notification_sla",
            "retention_sweep",
            "delivery_worker",
            "webhook_inbox",
            "job_worker",
            "job_lease_sweeper",
            "job_scheduler",
            # Kyber workforce directory reconciliation. A single periodic loop,
            # so it rides the existing maintenance role rather than justifying a
            # dedicated runtime role and the deploy-profile/compose/Terraform
            # topology fan-out that would come with one.
            "kyber_directory_sync",
            # Kyber's short-lived tables (sessions, step-up grants, single-use
            # challenges) are plain JSONB rows the storage-plane retention
            # sweep cannot reach. Same role, same cadence, same master switch.
            "kyber_retention_sweep",
        }
    ),
}


def is_valid_role(role: str) -> bool:
    """Return True if ``role`` is a recognised AETHER_ROLE token."""
    return role in ALL_ROLES


def is_worker_role(role: str) -> bool:
    """Return True if ``role`` names a dedicated worker class (not api/all)."""
    return role in WORKER_ROLES


def should_start_workers(role: str) -> bool:
    """Return True when a process in ``role`` runs supervised workers.

    ``all`` runs everything and every worker role runs its own class, so both
    return True. Only the pure ``api`` server returns False.
    """
    return role != "api"


def should_start_consumers(role: str) -> bool:
    """Return True when a process in ``role`` attaches stream consumers.

    ``all`` and the stream-oriented worker roles attach the shared consumer; a
    pure ``api`` process and non-stream worker roles (outbox-relay, materializer,
    maintenance) do not.
    """
    return role == "all" or role in CONSUMER_ROLES


_S = TypeVar("_S")


def _spec_name(spec: _S) -> str:
    """Best-effort name accessor: WorkerSpec has ``.name``; strings pass through."""
    return getattr(spec, "name", spec)  # type: ignore[return-value]


def specs_for_role(role: str, specs: Iterable[_S]) -> list[_S]:
    """Filter ``specs`` (WorkerSpec objects or names) to those owned by ``role``.

    - ``all`` → every spec (unchanged order).
    - ``api`` → none.
    - a worker role → the specs whose name is in ROLE_TO_SPEC_NAMES[role].
    - anything else → none.
    """
    spec_list = list(specs)
    if role == "all":
        return spec_list
    if role == "api":
        return []
    wanted = ROLE_TO_SPEC_NAMES.get(role, frozenset())
    return [s for s in spec_list if _spec_name(s) in wanted]
