"""Repository ↔ graph identity-edge reconciliation.

The identity subsystem keeps SAME_AS edges in two places:

* the durable **repository** edge store (``IdentityResolutionRepository`` /
  ``_IdentityEdgeStore``) — the source of truth, and
* the **graph backend** (``GraphClient`` → Neptune in prod, in-memory locally)
  which the graph writer mirrors edges into best-effort.

Because the graph mirror is best-effort (a failed ``add_edge`` / ``revoke_edge``
is logged, not retried), the two can drift: an edge can live in the repo but be
missing/revoked in the graph, or linger in the graph after the repo revoked it.
This module diffs the two and reports that drift. Its separate Kyber-only repair
operation defaults to dry-run and applies repo-authoritative fixes only after a
durable, idempotency-keyed intent record is written.

Design notes
------------
* Tenant-scoped end to end. Graph edges are matched on their ``tenant_id``
  property, repo edges on the row's ``tenant_id``; cross-tenant edges are never
  compared or surfaced.
* SAME_AS only — this is the identity-sameness relation. Other edge types
  (observed_as, campaign, wallet, …) are out of scope.
* Directional: the graph mirror always writes ``source → target`` (see
  ``IdentityGraphWriter._write_edge``), so edges are keyed by the ordered
  ``(source_entity_id, target_entity_id)`` pair.
* Never raises on a single-edge mismatch: per-vertex graph reads and per-row
  parsing are defensive, so one malformed edge cannot fail the whole run.
* Every run is persisted to a ``get_store``-backed table
  (``identity_graph_reconciliation_runs``) matching the repo's convention for
  non-atomic operational records (no alembic migration).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.store import get_store

from .models import EdgeType
from .repository import IdentityResolutionRepository

logger = get_logger("aether.identity.graph_reconciliation")

RUN_STORE_NAME = "identity_graph_reconciliation_runs"
REPAIR_STORE_NAME = "identity_graph_repair_runs"

# Bounded scan sizes so an "all" run can never fan out unboundedly.
_DEFAULT_EDGE_SCAN = 500
_DEFAULT_ENTITY_SCAN = 500

_SAME_AS = EdgeType.SAME_AS.value

# Drift types
DRIFT_MISSING_IN_GRAPH = "missing_in_graph"
DRIFT_MISSING_IN_REPO = "missing_in_repo"


def _run_store():
    """The durable store for reconciliation run records (Redis or in-memory)."""
    return get_store(RUN_STORE_NAME)


def _repair_store():
    """Durable, idempotency-keyed repair run records."""
    return get_store(REPAIR_STORE_NAME)


def _pair(row: dict) -> Optional[tuple[str, str]]:
    src = row.get("source_entity_id")
    tgt = row.get("target_entity_id")
    if not src or not tgt:
        return None
    return (str(src), str(tgt))


async def _collect_repo_edges(
    repo: IdentityResolutionRepository,
    tenant_id: str,
    entity_ids: Optional[list[str]],
    limit: int,
) -> tuple[dict[tuple[str, str], dict], set[str]]:
    """Return {(source, target): edge_row} of non-revoked SAME_AS repo edges,
    plus the set of source vertices to probe in the graph.
    """
    raw_rows: list[dict] = []
    if entity_ids:
        seen_ids: set[str] = set()
        for eid in entity_ids:
            try:
                rows = await repo.get_entity_graph(tenant_id, eid)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("repo edge read for %s skipped: %s", eid, exc)
                continue
            for row in rows:
                rid = row.get("id", "")
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                raw_rows.append(row)
    else:
        try:
            raw_rows = await repo.list_identity_edges(tenant_id, limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("list_identity_edges failed for %s: %s", tenant_id, exc)
            raw_rows = []

    pairs: dict[tuple[str, str], dict] = {}
    for row in raw_rows:
        if row.get("edge_type") != _SAME_AS:
            continue
        if row.get("revoked_at"):
            continue
        if str(row.get("tenant_id")) != str(tenant_id):
            continue
        key = _pair(row)
        if key is None:
            continue
        pairs.setdefault(key, row)

    source_ids = {k[0] for k in pairs}
    if entity_ids:
        source_ids |= {str(e) for e in entity_ids}
    return pairs, source_ids


async def _collect_graph_edges(
    graph: Any,
    tenant_id: str,
    source_ids: set[str],
) -> dict[tuple[str, str], Any]:
    """Return {(from, to): edge} of non-revoked SAME_AS graph edges out of the
    given source vertices, matched on the ``tenant_id`` edge property.
    """
    graph_pairs: dict[tuple[str, str], Any] = {}
    if graph is None:
        return graph_pairs
    for vid in source_ids:
        try:
            edges = await graph.get_edges(
                vid,
                edge_type=_SAME_AS,
                direction="out",
                include_revoked=False,
            )
        except Exception as exc:  # pragma: no cover - defensive per-vertex
            logger.debug("graph edge read for %s skipped: %s", vid, exc)
            continue
        for edge in edges or []:
            props = getattr(edge, "properties", {}) or {}
            if str(props.get("tenant_id")) != str(tenant_id):
                continue
            frm = getattr(edge, "from_vertex_id", None)
            to = getattr(edge, "to_vertex_id", None)
            if not frm or not to:
                continue
            graph_pairs[(str(frm), str(to))] = edge
    return graph_pairs


async def reconcile_identity_edges(
    tenant_id: str,
    *,
    entity_ids: Optional[list[str]] = None,
    now: Optional[Any] = None,
    repo: Optional[IdentityResolutionRepository] = None,
    graph: Optional[Any] = None,
    producer: Optional[Any] = None,
    edge_limit: int = _DEFAULT_EDGE_SCAN,
    persist: bool = True,
) -> dict:
    """Diff the repo's non-revoked SAME_AS edges against the graph backend.

    Args:
        tenant_id: tenant to reconcile (all reads are scoped to it).
        entity_ids: optional bounded set of canonical entity ids to check. When
            omitted, a bounded sample of the tenant's edges is scanned.
        now: injectable "current time" (a ``datetime``); defaults to ``utc_now``.
        repo / graph / producer: injectable dependencies for testing; default to
            the shared providers.
        edge_limit: max repo edges to scan in the "all" (no ``entity_ids``) path.
        persist: when True (default) a run record is written to the durable
            ``identity_graph_reconciliation_runs`` store.

    Returns:
        ``{tenant_id, checked, in_sync, drift, drift_count, computed_at}`` where
        each ``drift`` item is ``{type, source, target, detail}``.

    Never raises on an individual edge mismatch; store/graph failures degrade to
    an empty side rather than propagating.
    """
    computed_at = (now or utc_now())
    computed_at_iso = computed_at.isoformat() if hasattr(computed_at, "isoformat") else str(computed_at)

    if repo is None:
        repo = IdentityResolutionRepository()
    if graph is None:
        try:
            from dependencies.providers import get_graph
            graph = get_graph()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("graph client unavailable for reconciliation: %s", exc)
            graph = None

    norm_entity_ids = (
        [str(e) for e in entity_ids][:_DEFAULT_ENTITY_SCAN] if entity_ids else None
    )

    repo_pairs, source_ids = await _collect_repo_edges(
        repo, tenant_id, norm_entity_ids, edge_limit
    )
    graph_pairs = await _collect_graph_edges(graph, tenant_id, source_ids)

    drift: list[dict] = []
    for key, row in repo_pairs.items():
        if key not in graph_pairs:
            drift.append({
                "type": DRIFT_MISSING_IN_GRAPH,
                "source": key[0],
                "target": key[1],
                "detail": (
                    "repo SAME_AS edge is active but absent/revoked in the graph "
                    "backend (mirror write may have failed)"
                ),
            })
    for key in graph_pairs:
        if key not in repo_pairs:
            drift.append({
                "type": DRIFT_MISSING_IN_REPO,
                "source": key[0],
                "target": key[1],
                "detail": (
                    "graph SAME_AS edge has no active repo edge (repo revoke may "
                    "not have mirrored to the graph)"
                ),
            })

    checked = len(set(repo_pairs) | set(graph_pairs))
    drift_count = len(drift)
    result: dict[str, Any] = {
        "tenant_id": tenant_id,
        "checked": checked,
        "in_sync": drift_count == 0,
        "drift": drift,
        "drift_count": drift_count,
        "computed_at": computed_at_iso,
    }

    if persist:
        await _persist_run(tenant_id, norm_entity_ids, result)

    if drift_count:
        await _emit_drift_event(tenant_id, result, producer)

    return result


async def _persist_run(
    tenant_id: str,
    entity_ids: Optional[list[str]],
    result: dict,
) -> Optional[str]:
    """Write a durable run record; best-effort (never fails the reconciliation)."""
    run_id = str(uuid.uuid4())
    record = {
        "id": run_id,
        "tenant_id": tenant_id,
        "scope": "entities" if entity_ids else "tenant",
        "entity_ids": entity_ids or [],
        "checked": result["checked"],
        "in_sync": result["in_sync"],
        "drift_count": result["drift_count"],
        "drift": result["drift"],
        "computed_at": result["computed_at"],
        "created_at": result["computed_at"],
    }
    try:
        await _run_store().set(run_id, record)
        return run_id
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("failed to persist reconciliation run for %s: %s", tenant_id, exc)
        return None


async def _emit_drift_event(
    tenant_id: str,
    result: dict,
    producer: Optional[Any],
) -> None:
    """Best-effort drift event on the existing reconciliation drift topic."""
    try:
        from shared.events.events import Event, Topic
        if producer is None:
            from dependencies.providers import get_producer
            producer = get_producer()
        await producer.publish(Event(
            topic=Topic.RECONCILIATION_DRIFT_DETECTED,
            tenant_id=tenant_id,
            source_service="identity",
            payload={
                "surface": "identity_graph_edges",
                "checked": result["checked"],
                "drift_count": result["drift_count"],
                "computed_at": result["computed_at"],
            },
        ))
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("drift event emission skipped for %s: %s", tenant_id, exc)


async def repair_identity_edges(
    tenant_id: str,
    *,
    dry_run: bool = True,
    request_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    reason: str = "operator requested reconciliation repair",
    entity_ids: Optional[list[str]] = None,
    repo: Optional[IdentityResolutionRepository] = None,
    graph: Optional[Any] = None,
    producer: Optional[Any] = None,
) -> dict:
    """Plan or apply the exact fixes identified by reconciliation.

    The repository is authoritative: active repo edges missing from the graph
    are mirrored; graph-only edges are soft-revoked. Mutating runs fail closed
    unless a durable intent record is written first. The request id is the
    idempotency key, so retries return the original per-edge outcomes.
    """

    run_id = request_id or f"idgr_{uuid.uuid4().hex}"
    existing = await _repair_store().get(run_id)
    if existing is not None:
        if str(existing.get("tenant_id")) != str(tenant_id):
            raise ValueError("repair request_id already belongs to another tenant")
        return {**existing, "replayed": True}

    if repo is None:
        repo = IdentityResolutionRepository()
    if graph is None:
        from dependencies.providers import get_graph
        graph = get_graph()

    reconciliation = await reconcile_identity_edges(
        tenant_id,
        entity_ids=entity_ids,
        repo=repo,
        graph=graph,
        producer=producer,
        persist=False,
    )
    repo_pairs, source_ids = await _collect_repo_edges(
        repo,
        tenant_id,
        [str(value) for value in entity_ids] if entity_ids else None,
        _DEFAULT_EDGE_SCAN,
    )

    started_at = utc_now().isoformat()
    intent = {
        "id": run_id,
        "tenant_id": tenant_id,
        "dry_run": bool(dry_run),
        "status": "planning" if dry_run else "running",
        "actor_id": actor_id,
        "reason": reason,
        "entity_ids": entity_ids or [],
        "drift_count": reconciliation["drift_count"],
        "outcomes": [],
        "started_at": started_at,
        "completed_at": None,
        "replayed": False,
    }
    try:
        await _repair_store().set(run_id, intent)
    except Exception:
        if not dry_run:
            raise RuntimeError("durable repair intent could not be recorded")
        logger.warning("identity repair dry-run intent could not be persisted")

    outcomes: list[dict[str, Any]] = []
    for drift in reconciliation["drift"]:
        pair = (str(drift["source"]), str(drift["target"]))
        outcome: dict[str, Any] = {
            "drift_type": drift["type"],
            "source": pair[0],
            "target": pair[1],
            "action": (
                "mirror_repo_edge"
                if drift["type"] == DRIFT_MISSING_IN_GRAPH
                else "revoke_graph_edge"
            ),
            "status": "planned" if dry_run else "pending",
            "error_code": None,
        }
        if dry_run:
            outcomes.append(outcome)
            continue
        try:
            from shared.graph.graph import Edge
            from shared.graph.mutation_gateway import GraphMutationGateway
            from shared.graph.mutation_intents import edge_intent, revocation_intent

            gateway = GraphMutationGateway(graph_client=graph)
            if drift["type"] == DRIFT_MISSING_IN_GRAPH:
                row = repo_pairs.get(pair)
                if row is None:
                    raise RuntimeError("authoritative repo edge disappeared")
                current = await graph.get_edges(
                    pair[0],
                    edge_type=_SAME_AS,
                    direction="out",
                    include_revoked=False,
                )
                if not any(
                    str(edge.to_vertex_id) == pair[1]
                    and str((edge.properties or {}).get("tenant_id")) == str(tenant_id)
                    for edge in current or []
                ):
                    await gateway.apply(edge_intent(
                        Edge(
                            edge_type=_SAME_AS,
                            from_vertex_id=pair[0],
                            to_vertex_id=pair[1],
                            properties={
                                "tenant_id": tenant_id,
                                "edge_id": row.get("id"),
                                "confidence": str(row.get("confidence", "")),
                                "confidence_tier": str(row.get("confidence_tier", "")),
                                "repair_run_id": run_id,
                            },
                        ),
                        operation="edge_created",
                        tenant_id=tenant_id,
                        actor_kind="agent",
                        actor_id=actor_id or "identity_reconciliation",
                        subject_kind="entity",
                        subject_id=pair[0],
                        reason_code="identity_reconciliation",
                        causality_class="declared_reason",
                    ))
            else:
                await gateway.apply(revocation_intent(
                    from_vertex_id=pair[0],
                    to_vertex_id=pair[1],
                    edge_type=_SAME_AS,
                    reason=f"identity_reconciliation:{run_id}",
                    tenant_id=tenant_id,
                    operation="edge_tombstoned",
                    actor_kind="agent",
                    actor_id=actor_id or "identity_reconciliation",
                    subject_kind="entity",
                    subject_id=pair[0],
                    reason_code="identity_reconciliation",
                ))
            outcome["status"] = "applied"
        except Exception as exc:
            outcome["status"] = "failed"
            outcome["error_code"] = type(exc).__name__
            logger.warning(
                "identity repair edge failed tenant=%s source=%s target=%s error=%s",
                tenant_id,
                pair[0],
                pair[1],
                type(exc).__name__,
            )
        outcomes.append(outcome)

    failed = sum(1 for item in outcomes if item["status"] == "failed")
    applied = sum(1 for item in outcomes if item["status"] == "applied")
    status = "dry_run"
    if not dry_run:
        status = "failed" if failed and not applied else (
            "partially_succeeded" if failed else "succeeded"
        )
    result = {
        **intent,
        "status": status,
        "outcomes": outcomes,
        "applied": applied,
        "failed": failed,
        "completed_at": utc_now().isoformat(),
    }
    try:
        await _repair_store().set(run_id, result)
    except Exception:
        if not dry_run:
            raise RuntimeError("repair completed but durable outcomes could not be recorded")
        logger.warning("identity repair dry-run outcomes could not be persisted")
    return result


async def get_latest_reconciliation_run(tenant_id: str) -> Optional[dict]:
    """Return the most recent persisted run for a tenant, or None.

    Tenant-scoped: the store query filters on ``tenant_id`` and the newest run
    (by ``computed_at``) is returned.
    """
    try:
        runs = await _run_store().find(tenant_id=tenant_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("reconciliation run lookup failed for %s: %s", tenant_id, exc)
        return None
    if not runs:
        return None
    runs.sort(key=lambda r: r.get("computed_at", ""), reverse=True)
    return runs[0]
