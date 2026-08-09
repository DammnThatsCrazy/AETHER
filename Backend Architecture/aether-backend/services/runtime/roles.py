"""Aether Runtime — role helpers (PR 4 / FT-4).

``AETHER_ROLE`` selects which slice of the process runs. This module owns the
*pure* role logic used by both the FastAPI lifespan (``main.py``) and the
role entrypoint (``services/runtime/run_role.py``):

- :data:`WORKER_ROLES` — the worker classes split out of the request lifecycle.
- :data:`EXECUTION_GROUPS` — consolidated *deployment* tokens that co-host
  several logical worker roles inside one process (cost-driven packing).
- :data:`ALL_ROLES` — every valid ``AETHER_ROLE`` token (workers + ``api`` +
  ``all`` + the execution groups).
- :func:`should_start_workers` / :func:`should_start_consumers` — lifespan gates.
- :data:`ROLE_TO_SPEC_NAMES` + :func:`specs_for_role` — map a role onto the
  supervised :class:`WorkerSpec` subset it owns.
- :func:`roles_in` / :func:`owning_role` — the two directions of the
  deployment-token ⇄ logical-role mapping that keeps a consolidated process
  per-role observable.
- :data:`RELEASE_CRITICAL_ROLES` + :data:`ROLE_CAPABILITIES` — the single
  declaration of which role failures block a release and which capability each
  role delivers, consumed by both readiness surfaces.

Deliberately dependency-free (no settings/registry imports) so it is trivially
importable and unit-testable regardless of suite ordering.

``scripts/release/check_delivery_topology.py`` AST-parses this module rather
than importing it, so ``WORKER_ROLES`` must stay a literal ``frozenset({...})``
call and ``ALL_ROLES`` a top-level annotated assignment.
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

# Execution groups: deployment tokens that co-host several *logical* worker
# roles in one process. They are a packing decision, not a new kind of work —
# every member role keeps its own queue, consumer group, DLQ, retry policy,
# metrics label and independent failure/restart behaviour; only the process
# boundary is shared. ``production-lean`` trades 8 dedicated worker tasks for
# one "lean-worker" task without collapsing the logical topology, which is why
# this maps to a *set* of roles rather than to a merged pseudo-role.
#
# Distinct from "all": "all" is the local single-process default and is
# explicitly rejected by Settings in staging/production, whereas an execution
# group is a deployable token with real per-role isolation behind it.
EXECUTION_GROUPS: dict[str, frozenset[str]] = {
    "lean-worker": WORKER_ROLES,
}

# Every valid AETHER_ROLE token: the worker roles plus the pure API server, the
# single-process "all" default, and the execution groups. Kept in sync with
# config.settings.RUNTIME_ROLES.
ALL_ROLES: frozenset[str] = WORKER_ROLES | {"api", "all"} | frozenset(EXECUTION_GROUPS)

# Release-critical worker roles: the roles whose loss makes a release unsafe to
# complete rather than merely degraded, so a failure here fails the global
# readiness probe (services/gateway/readiness.py) and the worker process's own
# readiness surface (services/runtime/run_role.py).
#
# The dividing line is *recoverability*, not importance. A role is critical when
# its outage destroys work or breaks an at-least-once guarantee that catching up
# later cannot repair:
#
# - outbox-relay      — the at-least-once delivery path. Nothing else drains
#                       event_outbox / notification_outbox, so a stopped relay
#                       silently accumulates undelivered obligations.
# - stream-worker     — owns event replay and the ingestion stream. Its queues
#                       expire on the broker's retention, so backlog becomes
#                       permanent event loss rather than delayed processing.
# - identity-worker   — identity resolution sits on the same expiring ingestion
#                       queues; unresolved events cannot be re-derived once the
#                       source message is gone.
# - graph-writer      — projects the graph mutation ledger. The ledger is the
#                       only ordered record of topology change; a gap in the
#                       projection is not detectable from the projected state.
#
# The remaining roles degrade a capability while their work stays durably
# recorded and replayable (measurement restatement, semantic enrichment,
# materialisation, scheduled maintenance), so they must not block a rollout.
RELEASE_CRITICAL_ROLES: frozenset[str] = frozenset(
    {
        "outbox-relay",
        "stream-worker",
        "identity-worker",
        "graph-writer",
    }
)

# The platform capability each worker role delivers. Readiness reports per
# capability rather than per role because a capability is what a caller loses
# when the role stops: "semantic-enrichment unavailable" is actionable to a
# consumer of the API, "semantic-worker failed" is not.
ROLE_CAPABILITIES: dict[str, str] = {
    "outbox-relay": "event-delivery",
    "stream-worker": "stream-ingestion",
    "identity-worker": "identity-resolution",
    "graph-writer": "graph-projection",
    "measurement-worker": "measurement-restatement",
    "semantic-worker": "semantic-enrichment",
    "materializer": "materialization",
    "maintenance": "scheduled-maintenance",
}

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
    # Provider-truth polling ingestion rides the stream worker alongside the
    # Dune poller: these loops pull external provider/chain state into the
    # canonical observation spine, they are not materialization/reconciliation.
    "stream-worker": frozenset(
        {
            "event_replay",
            "dune_polling",
            "stablecoin_provider_polling",
            "interop_scan",
        }
    ),
    "identity-worker": frozenset(),
    # The Kyber Graph projector consumes the graph mutation ledger into platform
    # topology, and the card-linked graph outbox projects card-linked ingestion
    # through the same mutation gateway. Both are graph projection sinks, so
    # both are owned here.
    "graph-writer": frozenset({"kyber_graph_projector", "card_linked_graph_outbox"}),
    "measurement-worker": frozenset(),
    # Stream consumer is owned by consumer_specs.py; Phase B adds replay/reconciler
    # supervised loop specs here.
    "semantic-worker": frozenset(),
    # Materialization / reconciliation / repair loops: the payment-rail
    # observability cluster (sync, canonical repair, derived-condition alert
    # eval, settlement reconciliation), storage-plane compaction, the
    # derivatives venue reconciliation sweep, x402 settlement reconciliation,
    # and the shared dead-letter requeue sweeper.
    "materializer": frozenset(
        {
            "export_expiry_sweep",
            "payment_rail_sync",
            "payment_canonical_repair",
            "payment_alert_eval",
            "bronze_object_compaction",
            "derivatives_venue_sweep",
            "x402_reconciliation",
            "settlement_reconciliation",
            "dead_letter_sweeper",
        }
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
            # Correlates loose incident signals and merges same-release
            # incidents. One periodic loop, so it rides maintenance like the two
            # above rather than justifying a runtime role of its own. Not
            # graph-writer: it reads no ledger.
            "kyber_incident_correlation",
            # Durable reward-delivery outbox drain: same maintenance posture as
            # delivery_worker / webhook_inbox — a drain loop that idles when the
            # rewards job table is empty, owned by no execution surface.
            "reward_delivery_outbox",
            # Credential-authority expiry/overlap sweep: tombstones rotation
            # overlaps whose bounded window expired. A sweep, so it rides
            # maintenance like retention_sweep.
            "credential_expiry_sweep",
            # Capability-readiness revalidation: periodically revalidates that
            # declared platform capabilities are still ready and marks stale
            # ones down. A readiness staleness sweep, so it rides maintenance.
            "readiness_revalidation",
            # Reward budget reservation release + claim reconciliation +
            # receipt evidence: reward lifecycle maintenance loops (expired
            # reservations, claim-state drift, durable receipt-evidence retry)
            # with no execution surface of their own.
            "reward_reservation_release",
            "reward_claim_reconciliation",
            "reward_receipt_evidence",
        }
    ),
}


# Reverse index: supervised spec name → the single worker role that owns it.
# Built once at import so ``owning_role`` is an O(1) lookup on the hot path
# (every spec is stamped with its owner at boot and on every restart log line).
# A spec claimed by two roles would be a topology bug, so the last writer would
# hide it — assert single ownership while building instead.
def _build_spec_owner_index() -> dict[str, str]:
    # A function (not a module-level loop) so no loop variables leak into the
    # module namespace this file deliberately keeps small and inspectable.
    index: dict[str, str] = {}
    for role, spec_names in ROLE_TO_SPEC_NAMES.items():
        for spec_name in spec_names:
            if spec_name in index:  # pragma: no cover — topology guard
                raise ValueError(
                    f"spec {spec_name!r} is claimed by both "
                    f"{index[spec_name]!r} and {role!r}"
                )
            index[spec_name] = role
    return index


_SPEC_NAME_TO_ROLE: dict[str, str] = _build_spec_owner_index()


def _assert_role_metadata_complete() -> None:
    """Fail at import if criticality/capability declarations drift from the roles.

    Readiness reads both maps to decide whether a failure blocks a rollout, so a
    role added to WORKER_ROLES without an entry here would silently become
    non-critical and capability-less — exactly the "absent signal read as
    healthy" failure the probe exists to prevent.
    """
    unknown = RELEASE_CRITICAL_ROLES - WORKER_ROLES
    if unknown:  # pragma: no cover — topology guard
        raise ValueError(
            f"RELEASE_CRITICAL_ROLES names non-worker role(s): {sorted(unknown)}"
        )
    missing = WORKER_ROLES - set(ROLE_CAPABILITIES)
    extra = set(ROLE_CAPABILITIES) - WORKER_ROLES
    if missing or extra:  # pragma: no cover — topology guard
        raise ValueError(
            "ROLE_CAPABILITIES must cover exactly WORKER_ROLES "
            f"(missing={sorted(missing)}, unknown={sorted(extra)})"
        )


_assert_role_metadata_complete()


def is_valid_role(role: str) -> bool:
    """Return True if ``role`` is a recognised AETHER_ROLE token."""
    return role in ALL_ROLES


def is_release_critical(role: str) -> bool:
    """Return True when a failure of ``role`` must block a release.

    Unknown roles are not critical: an unattributed supervised worker degrades a
    capability nobody declared, and treating it as release-blocking would let any
    stray spec veto every rollout.
    """
    return role in RELEASE_CRITICAL_ROLES


def capability_for(role: str) -> str:
    """Return the platform capability ``role`` delivers.

    Roles outside :data:`WORKER_ROLES` (an unattributed supervised worker) get a
    namespaced fallback so their state is still reportable rather than dropped.
    """
    return ROLE_CAPABILITIES.get(role) or f"worker:{role}"


def is_worker_role(role: str) -> bool:
    """Return True if ``role`` names a dedicated worker class (not api/all)."""
    return role in WORKER_ROLES


def is_execution_group(role: str) -> bool:
    """Return True if ``role`` names a consolidated execution group."""
    return role in EXECUTION_GROUPS


def roles_in(role: str) -> frozenset[str]:
    """Expand an AETHER_ROLE token into the logical worker roles it runs.

    - a plain worker role → just itself (dedicated deployment).
    - an execution group  → its member roles (consolidated deployment).
    - ``all``             → every worker role (local single-process default).
    - ``api`` / unknown   → empty (the pure HTTP server runs no worker role).

    This is the single expansion point every other consolidation-aware helper
    routes through, so dedicated and consolidated deployments cannot drift.
    """
    if role in EXECUTION_GROUPS:
        return EXECUTION_GROUPS[role]
    if role == "all":
        return WORKER_ROLES
    if role in WORKER_ROLES:
        return frozenset({role})
    return frozenset()


def owning_role(spec_name: str) -> str | None:
    """Return the worker role that owns supervised spec ``spec_name``.

    Reverse lookup through :data:`ROLE_TO_SPEC_NAMES`. Returns None for a spec
    no role claims, so callers can label it explicitly rather than silently
    attributing it to the deployment token it happens to be running under.
    """
    return _SPEC_NAME_TO_ROLE.get(spec_name)


def should_start_workers(role: str) -> bool:
    """Return True when a process in ``role`` runs supervised workers.

    ``all`` runs everything, every worker role runs its own class, and an
    execution group runs its members' classes, so all three return True. Only
    the pure ``api`` server returns False.
    """
    return role != "api"


def should_start_consumers(role: str) -> bool:
    """Return True when a process in ``role`` attaches stream consumers.

    ``all`` and the stream-oriented worker roles attach consumers; a pure
    ``api`` process and non-stream worker roles (outbox-relay, materializer,
    maintenance) do not. An execution group attaches consumers when *any*
    member role is consumer-attached — the group hosts each member's consumer
    independently, so one stream member is enough to need the machinery.
    """
    return bool(roles_in(role) & CONSUMER_ROLES)


_S = TypeVar("_S")


def _spec_name(spec: _S) -> str:
    """Best-effort name accessor: WorkerSpec has ``.name``; strings pass through."""
    return getattr(spec, "name", spec)  # type: ignore[return-value]


def specs_for_role(role: str, specs: Iterable[_S]) -> list[_S]:
    """Filter ``specs`` (WorkerSpec objects or names) to those owned by ``role``.

    - ``all`` → every spec (unchanged order).
    - ``api`` → none.
    - a worker role → the specs whose name is in ROLE_TO_SPEC_NAMES[role].
    - an execution group → the union over its member roles, in ``specs`` order.
    - anything else → none.
    """
    spec_list = list(specs)
    if role == "all":
        # "all" is the local single-process aggregate: return every spec,
        # including any ROLE_TO_SPEC_NAMES does not yet claim, so a newly added
        # spec can never silently vanish from local/dev before it is given a
        # role owner. Deployable tokens go through the union path below, where
        # an unclaimed spec *should* be visibly missing.
        return spec_list
    wanted: set[str] = set()
    for member in roles_in(role):
        wanted |= ROLE_TO_SPEC_NAMES.get(member, frozenset())
    return [s for s in spec_list if _spec_name(s) in wanted]
