"""Ledger-driven projector for the Kyber Graph.

The graph is a *projection*, not a second source of truth. Its input is the
append-only ``graph_mutation_ledger``, and everything about this module follows
from that:

**Per tenant.** ``GraphMutationLedgerRepository.list_records`` reads one
tenant's ledger, and offsets are stored per ``(projection, tenant)``. That is
not an accident of the read API — it is what keeps one tenant's poison row from
stalling the fleet. :meth:`KyberGraphProjector.project_all` isolates each tenant
so a failure is recorded against that tenant and the rest still advance.

**At least once, never at most once.** The offset advances only after a batch is
fully applied. A crash mid-batch therefore re-processes rows, which is safe
because :class:`~services.kyber.graph.repository.KyberGraphStore` upserts on
natural keys. The inverse — advancing first — would skip rows on a crash, and a
projection with a silent hole reads as "nothing happened there" forever.

**Topology and references only.** For each ledger row the projector upserts the
``Tenant`` node, its ``TenantGraph``, the ``GraphDomain`` the mutation touched,
and the ``OWNS_GRAPH`` / ``CONTAINS_DOMAIN`` edges between them. The row's
``payload`` is deliberately never read. Copying payload contents into node
properties would turn this table into a second, unscoped copy of tenant data —
the exact boundary violation the Kyber Graph exists to avoid — and it would do
so invisibly, because the resulting rows would look like ordinary topology.

**Freshness is reported, not assumed.** Lag is measured from the newest consumed
row's ``recorded_at``, and a failing tenant keeps its ``last_error`` and
``consecutive_failures`` on its offset row. A projection that is silently 6
hours behind is worse than one that is visibly down: the first still answers
questions.

**Platform topology rides the same loop, on its own cadence.** The ledger only
ever produces ``Tenant`` / ``TenantGraph`` / ``GraphDomain`` nodes, so a process
that projected *only* the ledger left every node type the D0 platform surface
queries (``Service``, ``WorkerRole``, ``FeatureSurface``, …) unwritten — the
route answered "success" with an empty graph forever.
:func:`~services.kyber.graph.topology.sync_topology` fills those in, and
:meth:`KyberGraphProjector.project_all` calls it. It runs on the *first* sweep
after boot and then at most once per
:data:`KYBER_GRAPH_TOPOLOGY_SYNC_INTERVAL_S` (default one hour), because
topology derives from the runtime role tables and the capability registry —
deploy-time inputs. Syncing it on every 60-second ledger sweep would rewrite an
unchanged inventory sixty times an hour; syncing it only at startup would leave
a long-lived process asserting the topology of a build it is no longer running.
A failed sync never advances the "last synced" mark, so it retries on the next
sweep rather than waiting out the interval, and it never stops ledger
projection: the two inputs are independent and one being broken must not hide
the other.

**The projector reports its own ill health to the operator queue.** A stalled or
repeatedly failing projection, an exhausted fetch window, a topology sync that
failed, and any topology gap that is *not* one of the four permanently
underivable inputs each raise a Kyber operational exception (see
``services/kyber/ops/exceptions.py``). A frozen projection that still answers
queries is precisely the failure an operator has to be told about, and a log
line is not telling anyone.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
from services.kyber.graph.contracts import KyberGraphEdge, KyberGraphNode
from services.kyber.graph.repository import KyberGraphStore, kyber_graph_store
from services.kyber.graph.topology import UNDERIVABLE_INPUTS, sync_topology
from shared.common.common import parse_iso, utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.kyber.graph.projector")

#: Offset row key. Changing this restarts the projection from zero, which is
#: safe (upserts converge) but re-reads every tenant's ledger.
PROJECTION_NAME = "kyber_graph"

#: Backstop on the read window. ``list_records`` takes ``since_offset``, so the
#: resume point lives in the query and a sweep reads ``limit`` rows however long
#: the ledger has grown.
#:
#: This ceiling remains for a ledger implementation that ignores the argument.
#: Before ``since_offset`` existed, resumption over-fetched from the head and
#: dropped consumed rows client-side, so the window needed to reach one fresh row
#: grew with the ledger and a consumer past it stopped making progress
#: permanently — while still reporting healthy empty batches. ``fetch_window_
#: exhausted`` in the result is what distinguishes that stall from "caught up",
#: and it is now unreachable in normal operation rather than merely unlikely.
_MAX_LEDGER_FETCH = 20_000

_DEFAULT_INTERVAL_SECONDS = 60
_MIN_INTERVAL_SECONDS = 5

#: Platform topology derives from deploy-time inputs (the runtime role tables
#: and the surface capability registry), so it is synced far less often than the
#: ledger is swept. One hour is short enough that a rolling deploy's new
#: topology is visible within one hour of the last process restarting, and long
#: enough that a 60-second ledger loop is not rewriting an unchanged inventory
#: sixty times an hour.
_DEFAULT_TOPOLOGY_INTERVAL_SECONDS = 3600
_MIN_TOPOLOGY_INTERVAL_SECONDS = 60

#: Consecutive failed batches for one tenant before the projector raises an
#: operational exception. One failure is a blip worth a metric; three in a row
#: is a projection that is not coming back on its own, and the graph it serves
#: is now answering from a frozen snapshot.
PROJECTION_STALL_FAILURE_THRESHOLD = 3

#: Topology gaps :func:`sync_topology` reports on *every* run because no
#: repository source can close them. They belong in the sweep report and on a
#: gauge; raising an exception for them would put four permanent rows in the
#: operator queue, which is how a queue stops being read.
KNOWN_TOPOLOGY_GAPS: frozenset[str] = frozenset(name for name, _ in UNDERIVABLE_INPUTS)

#: Where projector-health signals say they came from.
SIGNAL_SOURCE = "kyber_graph_projector"

#: The runtime role this loop runs under. Matches the ``service:graph-writer``
#: node ``sync_topology`` derives, so a projector exception and the platform
#: graph name the same component.
SIGNAL_SERVICE = "graph-writer"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"kyber graph projector: {name}={raw!r} is not an int; using {default}")
        return default


def interval_seconds() -> int:
    """How often the supervised worker projects."""
    return max(
        _MIN_INTERVAL_SECONDS,
        _env_int("KYBER_GRAPH_PROJECTOR_INTERVAL_S", _DEFAULT_INTERVAL_SECONDS),
    )


def topology_interval_seconds() -> int:
    """How often a sweep re-derives platform topology.

    Deliberately independent of :func:`interval_seconds`: the ledger cadence is
    set by how stale a tenant's graph may be, the topology cadence by how stale
    the *deploy* inventory may be. Tying them would make one of the two wrong.
    """
    return max(
        _MIN_TOPOLOGY_INTERVAL_SECONDS,
        _env_int("KYBER_GRAPH_TOPOLOGY_SYNC_INTERVAL_S", _DEFAULT_TOPOLOGY_INTERVAL_SECONDS),
    )


class KyberGraphProjector:
    """Consumes the graph mutation ledger into Kyber Graph topology.

    Both the store and the ledger repository are injectable so the projector can
    be driven against fakes; the clock is injectable so lag and timestamps are
    assertable without sleeping.
    """

    def __init__(
        self,
        *,
        store: Optional[KyberGraphStore] = None,
        ledger: Optional[GraphMutationLedgerRepository] = None,
        clock: Optional[Callable[[], datetime]] = None,
        environment: Optional[str] = None,
    ) -> None:
        self.store = store or kyber_graph_store
        self.ledger = ledger or GraphMutationLedgerRepository()
        self._clock = clock or utc_now
        # Every projected node carries an environment: PostgreSQL treats NULLs
        # as distinct in a unique index, so an environment-less node would not
        # be deduped by ux_kyber_graph_nodes_key.
        self.environment = environment or os.getenv("AETHER_ENV", "local")
        # When topology last converged. ``None`` means "never in this process",
        # which is what makes the first sweep after boot always sync.
        self._last_topology_sync_at: Optional[datetime] = None

    # ── Clock ────────────────────────────────────────────────────────────────

    def _now(self) -> datetime:
        return self._clock()

    # ── Reporting the projector's own health ─────────────────────────────────

    async def _report(
        self,
        *,
        signal_type: str,
        title: str,
        dedupe_key: str,
        severity: str,
        probable_cause: str,
        recommended_action: str,
        payload: dict[str, Any],
        tenant_id: Optional[str] = None,
        data_integrity_exposure: bool = False,
    ) -> None:
        """Push one projector-health condition into the Kyber exception queue.

        This is a *cross-package* call (``graph`` → ``ops``), so it uses the
        function-level import shape declared in ``services/kyber/seams.py``: the
        ops plane is a separate deployment slice and may legitimately be absent.
        Absence is logged at error level and counted — never swallowed. A
        projector that cannot report its own stall is exactly the silent failure
        this call exists to prevent, so the *inability to report* has to be as
        visible as the condition would have been.

        Never raises. Callers are on the projection path, and a reporting fault
        must not become a projection fault.
        """
        try:
            from services.kyber.ops.contracts import IncidentSignal
            from services.kyber.ops.exceptions import report_operational_signal
        except ImportError as exc:
            logger.error(
                f"kyber graph projector: ops exception plane unavailable, "
                f"{signal_type} for tenant={tenant_id} not reported: {exc}"
            )
            metrics.increment(
                "kyber_graph_projector_signal_dropped_total",
                labels={"reason": "ops_plane_unavailable", "signal_type": signal_type},
            )
            return

        try:
            await report_operational_signal(
                IncidentSignal(
                    source=SIGNAL_SOURCE,
                    signal_type=signal_type,
                    service=SIGNAL_SERVICE,
                    tenant_id=tenant_id,
                    error_signature=signal_type,
                    observed_at=self._now().isoformat(),
                    payload={"environment": self.environment, **payload},
                ),
                title=title,
                dedupe_key=dedupe_key,
                severity=severity,
                probable_cause=probable_cause,
                recommended_action=recommended_action,
                data_integrity_exposure=data_integrity_exposure,
            )
        except Exception as exc:  # noqa: BLE001 - reporting must not break projection
            logger.error(
                f"kyber graph projector: failed to raise {signal_type} "
                f"for tenant={tenant_id}: {exc}"
            )
            metrics.increment(
                "kyber_graph_projector_signal_dropped_total",
                labels={"reason": "raise_failed", "signal_type": signal_type},
            )

    # ── One tenant ───────────────────────────────────────────────────────────

    async def project_tenant(self, tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
        """Project one tenant's unconsumed ledger rows.

        Resumes from the durable offset and advances it only after the whole
        batch applied. On failure the offset is left where it was and the error
        is recorded on the offset row, so the next run re-processes the same
        range instead of skipping it.
        """
        offset = await self.store.offset_for(PROJECTION_NAME, tenant_id)
        start = int(offset.last_offset or 0)

        try:
            fetched = await self._fetch(tenant_id, start, limit)
            fresh = [row for row in fetched if _row_offset(row) > start]
            fresh.sort(key=_row_offset)
            fresh = fresh[:limit]
            projected = await self._apply(tenant_id, fresh)
        except Exception as exc:  # noqa: BLE001 - a bad tenant must not stall the fleet
            metrics.increment(
                "kyber_graph_projection_failures_total",
                labels={"projection": PROJECTION_NAME},
            )
            failed = offset.model_copy(
                update={
                    # last_offset is deliberately untouched: at-least-once.
                    "last_run_at": self._now().isoformat(),
                    "last_error": f"{type(exc).__name__}: {exc}"[:1000],
                    "consecutive_failures": int(offset.consecutive_failures or 0) + 1,
                }
            )
            await self.store.save_offset(failed)
            logger.error(f"kyber graph projection failed for tenant={tenant_id}: {exc}")
            if int(failed.consecutive_failures or 0) >= PROJECTION_STALL_FAILURE_THRESHOLD:
                # The offset has not moved for three runs. The graph still
                # answers — from a snapshot that is now provably behind.
                await self._report(
                    signal_type="kyber_graph_projection_stalled",
                    title=f"Kyber Graph projection stalled for tenant {tenant_id}",
                    dedupe_key=f"kyber_graph_projection_stalled:{self.environment}:{tenant_id}",
                    severity="high",
                    probable_cause=str(failed.last_error or ""),
                    recommended_action=(
                        "Inspect the tenant's graph_mutation_ledger rows at offset "
                        f"{start} and the projection offset row for "
                        f"{PROJECTION_NAME}/{tenant_id}."
                    ),
                    payload={
                        "projection": PROJECTION_NAME,
                        "consecutive_failures": failed.consecutive_failures,
                        "last_offset": start,
                        "last_error": failed.last_error,
                    },
                    tenant_id=tenant_id,
                    # The graph keeps serving stale topology as if it were
                    # current, which is a correctness claim it can no longer make.
                    data_integrity_exposure=True,
                )
            return {
                "projection": PROJECTION_NAME,
                "tenant_id": tenant_id,
                "ok": False,
                "rows_processed": 0,
                "nodes_upserted": 0,
                "edges_upserted": 0,
                "from_offset": start,
                "last_offset": start,
                "lag_seconds": None,
                "error": failed.last_error,
                "consecutive_failures": failed.consecutive_failures,
                "fetch_window_exhausted": False,
            }

        highest = max([_row_offset(row) for row in fresh], default=start)
        advanced = offset.model_copy(
            update={
                "last_offset": max(start, highest),
                "last_run_at": self._now().isoformat(),
                "last_error": None,
                "consecutive_failures": 0,
            }
        )
        await self.store.save_offset(advanced)

        lag = self._emit_lag(fresh)
        # A full read window containing nothing new means the resume window
        # (see _MAX_LEDGER_FETCH) could not reach unconsumed rows. Nothing
        # failed, but no progress was made either, and a caller must be able to
        # tell that apart from "caught up".
        window_exhausted = not fresh and len(fetched) >= _MAX_LEDGER_FETCH
        result = {
            "projection": PROJECTION_NAME,
            "tenant_id": tenant_id,
            "ok": True,
            "rows_processed": len(fresh),
            "nodes_upserted": projected["nodes"],
            "edges_upserted": projected["edges"],
            "rows_without_domain": projected["rows_without_domain"],
            "from_offset": start,
            "last_offset": advanced.last_offset,
            "lag_seconds": lag,
            "error": None,
            "consecutive_failures": 0,
            "fetch_window_exhausted": window_exhausted,
        }
        if result["rows_processed"]:
            logger.info(
                f"kyber graph projection tenant={tenant_id} rows={len(fresh)} "
                f"nodes={projected['nodes']} edges={projected['edges']} "
                f"offset={start}->{advanced.last_offset}"
            )
        if window_exhausted:
            # Structural, not transient: no amount of retrying reaches an
            # unconsumed row through a window this full, so it is reported the
            # first time rather than after a failure count.
            await self._report(
                signal_type="kyber_graph_projection_window_exhausted",
                title=f"Kyber Graph projection cannot reach new rows for tenant {tenant_id}",
                dedupe_key=(
                    f"kyber_graph_projection_window_exhausted:{self.environment}:{tenant_id}"
                ),
                severity="high",
                probable_cause=(
                    "The ledger read returned a full window containing no rows "
                    "above the stored offset, so the batch made no progress."
                ),
                recommended_action=(
                    "Check that GraphMutationLedgerRepository.list_records honours "
                    "since_offset; without it the resume window cannot reach the "
                    "ledger head."
                ),
                payload={
                    "projection": PROJECTION_NAME,
                    "last_offset": start,
                    "fetch_window": _MAX_LEDGER_FETCH,
                },
                tenant_id=tenant_id,
                data_integrity_exposure=True,
            )
        return result

    async def _fetch(self, tenant_id: str, start: int, limit: int) -> list[dict[str, Any]]:
        """Read the next ``limit`` unconsumed rows of the tenant's ledger.

        ``since_offset`` pushes the resume point into the query, so the window
        is ``limit`` rows regardless of how long the ledger has grown. The
        client-side ``_MAX_LEDGER_FETCH`` ceiling stays as a backstop for a
        ledger implementation that ignores the argument: if one ever does, the
        batch reports ``fetch_window_exhausted`` instead of quietly making no
        progress forever.
        """
        window = min(max(limit, 1), _MAX_LEDGER_FETCH)
        return await self.ledger.list_records(
            tenant_id, aggregate_id=None, limit=window, since_offset=start
        )

    async def _apply(
        self, tenant_id: str, rows: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Upsert the topology implied by ``rows``.

        Rows are collapsed to distinct nodes and edges first — a 500-row batch
        touching one tenant implies one ``Tenant`` node, not 500 writes — keeping
        the newest provenance for each key so the batch's own ordering cannot
        regress ``source_offset``.
        """
        nodes: dict[str, KyberGraphNode] = {}
        edges: dict[str, KyberGraphEdge] = {}
        rows_without_domain = 0

        for row in rows:
            row_offset = _row_offset(row)
            event_id = row.get("source_event_id") or row.get("mutation_id")
            # NOTE: row["payload"] is never read. The graph stores references
            # into tenant data, never the data.
            tenant_key = f"tenant:{tenant_id}"
            graph_key = f"tenant_graph:{tenant_id}"

            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=tenant_key,
                    node_type="Tenant",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=tenant_id,
                    properties={"derived_from": "graph_mutation_ledger"},
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=graph_key,
                    node_type="TenantGraph",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=f"{tenant_id} graph",
                    properties={"derived_from": "graph_mutation_ledger"},
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_edge(
                edges,
                KyberGraphEdge(
                    source_node_key=tenant_key,
                    target_node_key=graph_key,
                    relationship_type="OWNS_GRAPH",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )

            domain = row.get("aggregate_type")
            if not domain:
                # An unclassified mutation is counted, not guessed at: inventing
                # a domain would put a node in the graph that no contract backs.
                rows_without_domain += 1
                continue
            domain_key = f"graph_domain:{tenant_id}:{domain}"
            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=domain_key,
                    node_type="GraphDomain",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=str(domain),
                    properties={
                        "aggregate_type": str(domain),
                        "derived_from": "graph_mutation_ledger",
                    },
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_edge(
                edges,
                KyberGraphEdge(
                    source_node_key=graph_key,
                    target_node_key=domain_key,
                    relationship_type="CONTAINS_DOMAIN",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )

        for node in nodes.values():
            await self.store.upsert_node(node)
        for edge in edges.values():
            await self.store.upsert_edge(edge)

        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "rows_without_domain": rows_without_domain,
        }

    def _emit_lag(self, rows: list[dict[str, Any]]) -> Optional[float]:
        """Projection lag from the newest consumed row, in seconds."""
        newest: Optional[datetime] = None
        for row in rows:
            recorded = row.get("recorded_at")
            if not recorded:
                continue
            try:
                parsed = parse_iso(str(recorded))
            except (TypeError, ValueError):
                continue
            if parsed is not None and (newest is None or parsed > newest):
                newest = parsed
        if newest is None:
            return None
        lag = max(0.0, (self._now() - newest).total_seconds())
        metrics.gauge(
            "kyber_graph_projection_lag_seconds",
            lag,
            labels={"projection": PROJECTION_NAME},
        )
        return lag

    # ── Platform topology ────────────────────────────────────────────────────

    def _topology_due(self) -> bool:
        """Whether topology should be re-derived on this sweep.

        ``None`` (never synced in this process) is always due, so a freshly
        booted process populates the platform node types the D0 route queries
        before it does anything else.
        """
        if self._last_topology_sync_at is None:
            return True
        elapsed = (self._now() - self._last_topology_sync_at).total_seconds()
        return elapsed >= topology_interval_seconds()

    async def sync_platform_topology(self, *, force: bool = False) -> dict[str, Any]:
        """Converge derived platform topology, at most once per interval.

        ``sync_topology`` is idempotent by construction (every node carries a
        stable natural key), so a repeat is a convergence, not an accumulation —
        which is what makes an interval a free choice rather than a correctness
        constraint.

        Returns the sync report with ``ok`` and ``ran`` added, and never raises:
        the ledger projection in :meth:`project_all` has an entirely separate
        input and must not be taken down by a broken role table or an unreadable
        capability registry. A failure leaves ``_last_topology_sync_at``
        untouched, so the next sweep retries instead of waiting out the interval.
        """
        if not force and not self._topology_due():
            return {"ok": True, "ran": False, "reason": "not_due", "missing_inputs": []}

        try:
            report = await sync_topology(self.store, environment=self.environment)
        except Exception as exc:  # noqa: BLE001 - topology must not stall the ledger
            metrics.increment(
                "kyber_graph_topology_sync_failures_total",
                labels={"environment": self.environment},
            )
            logger.error(f"kyber graph topology sync failed: {exc}")
            await self._report(
                signal_type="kyber_graph_topology_sync_failed",
                title="Kyber Graph platform topology sync failed",
                dedupe_key=f"kyber_graph_topology_sync_failed:{self.environment}",
                severity="high",
                probable_cause=f"{type(exc).__name__}: {exc}"[:1000],
                recommended_action=(
                    "The D0 platform graph route reads Service / WorkerRole / "
                    "FeatureSurface nodes; until this sync succeeds it answers "
                    "from whatever the last successful sync wrote."
                ),
                payload={"error": f"{type(exc).__name__}: {exc}"[:1000]},
                data_integrity_exposure=True,
            )
            return {
                "ok": False,
                "ran": True,
                "error": f"{type(exc).__name__}: {exc}"[:1000],
                "missing_inputs": [],
            }

        self._last_topology_sync_at = self._now()
        missing = [str(name) for name in (report.get("missing_inputs") or [])]
        metrics.gauge(
            "kyber_graph_topology_nodes",
            float(report.get("nodes_upserted") or 0),
            labels={"environment": self.environment},
        )
        metrics.gauge(
            "kyber_graph_topology_missing_inputs",
            float(len(missing)),
            labels={"environment": self.environment},
        )

        # The four permanently underivable inputs are a documented property of
        # the derivation, not an incident. Anything else in the list is a source
        # that was expected to be readable and was not.
        unexpected = [name for name in missing if name not in KNOWN_TOPOLOGY_GAPS]
        if unexpected:
            await self._report(
                signal_type="kyber_graph_topology_missing_inputs",
                title="Kyber Graph platform topology is missing a derivable input",
                dedupe_key=(
                    f"kyber_graph_topology_missing_inputs:{self.environment}:"
                    f"{','.join(sorted(unexpected))}"
                ),
                severity="medium",
                probable_cause=(
                    "sync_topology reported inputs it could normally derive as "
                    f"missing: {', '.join(sorted(unexpected))}"
                ),
                recommended_action=(
                    "The platform graph will answer without these nodes rather "
                    "than reporting an error, so blast-radius answers computed "
                    "from it are incomplete until the source is readable again."
                ),
                payload={"missing_inputs": sorted(unexpected), "known_gaps": sorted(missing)},
            )

        return {"ok": True, "ran": True, "unexpected_missing_inputs": unexpected, **report}

    # ── The fleet ────────────────────────────────────────────────────────────

    async def project_all(
        self, *, tenant_ids: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Project every known tenant, isolating failures per tenant.

        When ``tenant_ids`` is omitted the roster is derived from tenants this
        projection already knows: existing offset rows plus ``Tenant`` nodes. A
        tenant that has never been projected and is not passed in is reported as
        a ``missing_inputs`` gap — the ledger read is per tenant, so a roster is
        a genuine input this module does not own and must not fabricate.

        Platform topology is converged first (see
        :meth:`sync_platform_topology`). It is deliberately *not* conditional on
        the ledger sweep succeeding and the ledger sweep is not conditional on
        it: the two read different inputs, and a deployment where one is broken
        must still get the other. Its report — counts and, critically, its own
        ``missing_inputs`` — is returned whole under ``topology`` and lifted to
        the top level as ``topology_missing_inputs`` so a caller reading only
        the summary still sees what the topology is not producing. It is kept
        separate from ``missing_inputs`` because that key means "an input *this
        sweep* needed and did not have", and topology's four permanent gaps
        would otherwise make every healthy sweep read as degraded.
        """
        topology = await self.sync_platform_topology()
        targets = list(tenant_ids) if tenant_ids is not None else await self._known_tenants()
        results: list[dict[str, Any]] = []
        for tenant_id in targets:
            try:
                results.append(await self.project_tenant(tenant_id))
            except Exception as exc:  # noqa: BLE001 - isolate one tenant's failure
                metrics.increment(
                    "kyber_graph_projection_failures_total",
                    labels={"projection": PROJECTION_NAME},
                )
                logger.error(f"kyber graph projection crashed for tenant={tenant_id}: {exc}")
                results.append(
                    {
                        "projection": PROJECTION_NAME,
                        "tenant_id": tenant_id,
                        "ok": False,
                        "rows_processed": 0,
                        "nodes_upserted": 0,
                        "edges_upserted": 0,
                        "error": f"{type(exc).__name__}: {exc}"[:1000],
                    }
                )

        missing: list[str] = []
        if not targets:
            missing.append("tenant_ids")
        # Reported beside — not merged into — ``missing_inputs``. That key means
        # "an input *this sweep* needed and did not have"; topology's gaps are a
        # standing property of the derivation, and folding four permanent
        # entries into it would make the ledger sweep look permanently degraded.
        topology_missing = [str(name) for name in (topology.get("missing_inputs") or [])]
        return {
            "projection": PROJECTION_NAME,
            "environment": self.environment,
            "tenants": len(targets),
            "ok_tenants": sum(1 for r in results if r.get("ok")),
            "failed_tenants": sum(1 for r in results if not r.get("ok")),
            "rows_processed": sum(int(r.get("rows_processed") or 0) for r in results),
            "nodes_upserted": sum(int(r.get("nodes_upserted") or 0) for r in results),
            "edges_upserted": sum(int(r.get("edges_upserted") or 0) for r in results),
            "missing_inputs": missing,
            "topology": topology,
            "topology_ok": bool(topology.get("ok")),
            "topology_missing_inputs": topology_missing,
            "results": results,
            "computed_at": self._now().isoformat(),
        }

    async def _known_tenants(self) -> list[str]:
        """Tenants this projection has seen: offset rows plus ``Tenant`` nodes."""
        known: set[str] = set()
        for offset in await self.store.list_offsets(PROJECTION_NAME):
            if offset.tenant_id:
                known.add(offset.tenant_id)
        for node in await self.store.find_nodes(
            node_type="Tenant", environment=self.environment, limit=1000
        ):
            if node.tenant_id:
                known.add(node.tenant_id)
        return sorted(known)


#: Process-wide projector.
kyber_graph_projector = KyberGraphProjector()


class KyberGraphProjectorWorker:
    """Long-running projection loop for a supervised runtime role."""

    def __init__(self, projector: Optional[KyberGraphProjector] = None) -> None:
        self.projector = projector or kyber_graph_projector
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("kyber graph projector worker started")
        while self._running:
            try:
                sweep = await self.projector.project_all()
                topology = sweep.get("topology") or {}
                # The sweep's own honest report about what it did not produce.
                # Logged only when topology actually ran, so the skipped-because-
                # not-due case does not repeat an unchanged list every minute.
                if topology.get("ran"):
                    logger.info(
                        f"kyber graph sweep: topology_ok={sweep.get('topology_ok')} "
                        f"topology_nodes={topology.get('nodes_upserted', 0)} "
                        f"topology_missing_inputs={sweep.get('topology_missing_inputs')} "
                        f"missing_inputs={sweep.get('missing_inputs')}"
                    )
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                logger.error(f"kyber graph projection sweep failed: {exc}")
                metrics.increment(
                    "kyber_graph_projection_failures_total",
                    labels={"projection": PROJECTION_NAME},
                )
            await asyncio.sleep(interval_seconds())

    def stop(self) -> None:  # pragma: no cover - shutdown path
        self._running = False


def build_kyber_graph_projector_coro() -> Coroutine:
    """Zero-arg factory: a fresh supervised Kyber Graph projection coroutine.

    Same shape as ``services.kyber.retention.build_kyber_retention_coro`` so the
    runtime supervisor registers it as an ordinary ``WorkerSpec`` factory
    without a special case.
    """
    return KyberGraphProjectorWorker().run_forever()


def _row_offset(row: dict[str, Any]) -> int:
    """A ledger row's position, defaulting to 0 when the backend omits it."""
    try:
        return int(row.get("ledger_offset") or 0)
    except (TypeError, ValueError):
        return 0


def _keep_node(acc: dict[str, KyberGraphNode], node: KyberGraphNode) -> None:
    """Keep the newest provenance for a node key inside one batch."""
    current = acc.get(node.node_key)
    if current is None or (node.source_offset or 0) >= (current.source_offset or 0):
        acc[node.node_key] = node


def _keep_edge(acc: dict[str, KyberGraphEdge], edge: KyberGraphEdge) -> None:
    """Keep the newest provenance for an edge key inside one batch."""
    current = acc.get(edge.idempotency_key)
    if current is None or (edge.source_offset or 0) >= (current.source_offset or 0):
        acc[edge.idempotency_key] = edge


__all__ = [
    "KNOWN_TOPOLOGY_GAPS",
    "PROJECTION_NAME",
    "PROJECTION_STALL_FAILURE_THRESHOLD",
    "SIGNAL_SERVICE",
    "SIGNAL_SOURCE",
    "KyberGraphProjector",
    "KyberGraphProjectorWorker",
    "build_kyber_graph_projector_coro",
    "interval_seconds",
    "kyber_graph_projector",
    "topology_interval_seconds",
]
