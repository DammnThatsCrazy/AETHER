"""
Aether Service — Staged Mutation Commit Pipeline

The controlled path from human approval to canonical graph commit:

    staged → (operator approves review batch) → approved
           → commit_approved_mutations() → committed | quarantined | failed_commit
           → rollback_mutation()          → rolled_back

Safety properties:
  - Commit only ever follows an explicit human approval. Nothing here can
    commit a staged/rejected mutation, and nothing auto-approves.
  - Edge writes go through build_edge_properties (deterministic idempotency
    key) and GraphWriteValidator before touching the graph client.
  - When CIS is enabled, the MutationGateway risk-scores every commit; the
    quarantine band marks the mutation quarantined and skips the write.
  - Partial batch failure is never silent: every mutation gets a per-mutation
    result, failures continue past (other mutations still commit), and the
    batch lands in ``quarantined`` for operator attention unless everything
    committed cleanly.
  - Every transition is audited on the agent timeline.

Staged mutation target contract (what workers stage / operators approve):
    vertex: target={"kind": "vertex", "vertex_type": ..., "vertex_id": ...}
            diff={"properties": {...}}
    edge:   target={"kind": "edge", "edge_type": ...,
                    "from_vertex_id": ..., "to_vertex_id": ...}
            diff={"properties": {...}, "confidence": 0.0-1.0 optional}
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.cis.mutation_gateway import get_gateway
from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
from shared.graph.graph import Edge, GraphClient, Vertex, _escape_gremlin
from shared.graph.write_validator import GraphWriteValidator
from shared.logger.logger import get_logger, metrics
from services.agent.runtime_repository import (
    MUTATION_CLASSES,
    get_agent_runtime_repository,
    utc_now,
)

logger = get_logger("aether.service.agent.mutation_commit")

_graph: GraphClient | None = None


def _graph_client() -> GraphClient:
    """Module-scoped GraphClient (lazy) — tests monkeypatch this seam."""
    global _graph
    if _graph is None:
        _graph = GraphClient()
    return _graph


def _require_review_enabled() -> None:
    if not settings.one_person_ops.staged_mutation_review_enabled:
        raise BadRequestError("Staged graph mutation review-to-commit is not enabled")


def _result(mutation_id: str, status: str, detail: str = "") -> dict[str, Any]:
    entry: dict[str, Any] = {"mutation_id": mutation_id, "status": status}
    if detail:
        entry["detail"] = detail[:500]
    return entry


async def _set_mutation_status(
    repo: Any,
    tenant_id: str,
    mutation: dict[str, Any],
    status: str,
    actor: str,
    request_id: str,
    extra: dict[str, Any] | None = None,
    event_type: str | None = None,
) -> None:
    mutation["status"] = status
    mutation["updated_at"] = utc_now()
    for key, value in (extra or {}).items():
        mutation[key] = value
    await repo.staged_mutations.set(mutation["mutation_id"], mutation)
    await repo.append_event(
        tenant_id,
        event_type or f"mutation.{status}",
        "commit",
        mutation,
        mutation.get("objective_id", ""),
        actor,
        request_id,
    )
    metrics.increment(
        "agent_staged_mutation_transitions",
        labels={"status": status, "mutation_class": str(mutation.get("mutation_class", 0))},
    )


def _mutation_entity(mutation: dict[str, Any]) -> tuple[str, str]:
    """(entity_id, entity_type) for CIS risk scoring."""
    target = mutation.get("target") or {}
    if target.get("kind") == "vertex":
        return str(target.get("vertex_id", "")), str(target.get("vertex_type", "ENTITY"))
    return (
        f"{target.get('from_vertex_id', '')}->{target.get('to_vertex_id', '')}",
        str(target.get("edge_type", "EDGE")),
    )


async def _cis_check(tenant_id: str, mutation: dict[str, Any]) -> Any | None:
    """Run the CIS MutationGateway when enabled; None means 'no gate'."""
    if not settings.cis.enabled:
        return None
    entity_id, entity_type = _mutation_entity(mutation)
    return await get_gateway().evaluate_mutation(
        mutation_id=mutation["mutation_id"],
        tenant_id=tenant_id,
        mutation_class=int(mutation.get("mutation_class", 1) or 1),
        entity_id=entity_id,
        entity_type=entity_type,
        proposed_changes=mutation.get("diff") or {},
    )


def _build_vertex(tenant_id: str, mutation: dict[str, Any]) -> Vertex:
    target = mutation.get("target") or {}
    vertex_type = str(target.get("vertex_type", "") or "")
    vertex_id = str(target.get("vertex_id", "") or "")
    if not vertex_type or not vertex_id:
        raise ValueError("vertex mutations require target.vertex_type and target.vertex_id")
    properties = dict((mutation.get("diff") or {}).get("properties") or {})
    properties.setdefault("tenant_id", tenant_id)
    properties.setdefault("provenance", "staged_mutation_review")
    properties.setdefault("source_mutation_id", mutation["mutation_id"])
    return Vertex(vertex_type=vertex_type, vertex_id=vertex_id, properties=properties)


def _build_edge(tenant_id: str, mutation: dict[str, Any], actor: str) -> Edge:
    target = mutation.get("target") or {}
    edge_type = str(target.get("edge_type", "") or "")
    from_id = str(target.get("from_vertex_id", "") or "")
    to_id = str(target.get("to_vertex_id", "") or "")
    if not edge_type or not from_id or not to_id:
        raise ValueError(
            "edge mutations require target.edge_type, target.from_vertex_id and target.to_vertex_id"
        )
    diff = mutation.get("diff") or {}
    try:
        confidence = float(diff.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0
    properties = build_edge_properties(
        tenant_id=tenant_id,
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        # The commit is authorized by an explicit human approval; the staging
        # agent remains on the provenance/correlation trail below.
        actor_kind="human",
        actor_id=actor,
        provenance="staged_mutation_review",
        valid_from=utc_now(),
        confidence=confidence,
        correlation_id=mutation["mutation_id"],
        **{
            k: str(v)
            for k, v in (diff.get("properties") or {}).items()
            if k not in {"tenant_id", "idempotency_key"}
        },
    )
    return Edge(edge_type=edge_type, from_vertex_id=from_id, to_vertex_id=to_id, properties=properties)


async def commit_approved_mutations(
    tenant_id: str,
    batch_id: str,
    actor: str,
    request_id: str = "",
    graph: GraphClient | None = None,
) -> dict[str, Any]:
    """Commit every APPROVED staged mutation in a review batch.

    Returns full per-mutation results — a partial failure is reported, never
    silently swallowed. Idempotent: already-committed mutations are reported
    as committed without re-applying, so a duplicate call is safe.
    """
    _require_review_enabled()
    repo = get_agent_runtime_repository()
    batch = await repo.review_batches.get(batch_id)
    if not batch or batch.get("tenant_id") != tenant_id:
        raise NotFoundError("Review batch")
    if batch.get("status") not in {"approved", "quarantined", "committed"}:
        # pending/rejected batches carry no approval — human review is the
        # only path into this pipeline.
        raise ConflictError(f"Cannot commit review batch in status '{batch.get('status')}'")

    client = graph or _graph_client()
    validator = GraphWriteValidator()
    results: list[dict[str, Any]] = []

    for mutation_id in batch.get("mutation_ids", []):
        mutation = await repo.staged_mutations.get(mutation_id)
        if not mutation or mutation.get("tenant_id") != tenant_id:
            results.append(_result(mutation_id, "missing"))
            continue
        status = mutation.get("status")
        if status == "committed":
            results.append(_result(mutation_id, "committed", "already committed (idempotent)"))
            continue
        if status != "approved":
            # rejected / staged / rolled_back / quarantined mutations never
            # commit from here — approval is per-mutation, not just per-batch.
            results.append(_result(mutation_id, "skipped_not_approved", f"status={status}"))
            continue

        mutation_class = mutation.get("mutation_class")
        if mutation_class not in MUTATION_CLASSES:
            await _set_mutation_status(
                repo, tenant_id, mutation, "failed_commit", actor, request_id,
                extra={"commit_error": f"invalid mutation_class: {mutation_class}"},
                event_type="mutation.commit_failed",
            )
            results.append(_result(mutation_id, "failed_commit", "invalid mutation_class"))
            continue

        target_kind = (mutation.get("target") or {}).get("kind")
        try:
            if target_kind == "vertex":
                op: dict[str, Any] = {"kind": "vertex"}
                vertex = _build_vertex(tenant_id, mutation)
                op["vertex_id"] = vertex.vertex_id
                op["vertex_type"] = vertex.vertex_type
                edge = None
            elif target_kind == "edge":
                op = {"kind": "edge"}
                edge = _build_edge(tenant_id, mutation, actor)
                op["edge_type"] = edge.edge_type
                op["from_vertex_id"] = edge.from_vertex_id
                op["to_vertex_id"] = edge.to_vertex_id
                op["idempotency_key"] = edge.properties.get("idempotency_key", "")
                vertex = None
            else:
                raise ValueError(f"unsupported target.kind: {target_kind!r}")
        except ValueError as exc:
            await _set_mutation_status(
                repo, tenant_id, mutation, "failed_commit", actor, request_id,
                extra={"commit_error": str(exc)[:500]},
                event_type="mutation.commit_failed",
            )
            results.append(_result(mutation_id, "failed_commit", str(exc)))
            continue

        if edge is not None:
            validation = validator.validate(edge)
            if not validation.passed:
                await _set_mutation_status(
                    repo, tenant_id, mutation, "failed_commit", actor, request_id,
                    extra={"commit_error": "; ".join(validation.violations)[:500]},
                    event_type="mutation.commit_failed",
                )
                results.append(_result(mutation_id, "failed_commit", "graph write validation failed"))
                continue

        risk = await _cis_check(tenant_id, mutation)
        if risk is not None and (risk.quarantined or risk.band == "quarantine"):
            await _set_mutation_status(
                repo, tenant_id, mutation, "quarantined", actor, request_id,
                extra={
                    "quarantine": {
                        "risk_score": risk.score,
                        "risk_band": risk.band,
                        "quarantine_id": risk.quarantine_id,
                    }
                },
            )
            results.append(_result(mutation_id, "quarantined", f"risk_band={risk.band}"))
            continue

        try:
            if vertex is not None:
                await client.add_vertex(vertex)
            elif edge is not None:
                await client.add_edge(edge)
        except Exception as exc:
            # Graph unreachable / write rejected: quarantine-style failure,
            # preserved for operator retry — never dropped.
            await _set_mutation_status(
                repo, tenant_id, mutation, "failed_commit", actor, request_id,
                extra={"commit_error": f"{type(exc).__name__}: {exc}"[:500]},
                event_type="mutation.commit_failed",
            )
            results.append(_result(mutation_id, "failed_commit", type(exc).__name__))
            continue

        await _set_mutation_status(
            repo, tenant_id, mutation, "committed", actor, request_id,
            extra={
                "committed_at": utc_now(),
                "committed_by": actor,
                "commit_op": op,
                # Rollback metadata: enough to attempt a best-effort inverse.
                "rollback": {"supported": True, "inverse": op},
            },
        )
        results.append(_result(mutation_id, "committed"))

    counts = {
        "committed": sum(1 for r in results if r["status"] == "committed"),
        "quarantined": sum(1 for r in results if r["status"] == "quarantined"),
        "failed": sum(1 for r in results if r["status"] in {"failed_commit", "missing"}),
        "skipped": sum(1 for r in results if r["status"] == "skipped_not_approved"),
    }
    clean = counts["quarantined"] == 0 and counts["failed"] == 0
    batch_status = "committed" if clean else "quarantined"
    batch["status"] = batch_status
    batch["updated_at"] = utc_now()
    batch["commit_results"] = results
    await repo.review_batches.set(batch_id, batch)
    await repo.append_event(
        tenant_id, f"batch.{batch_status}", "commit",
        {"batch_id": batch_id, **counts},
        batch.get("objective_id", ""), actor, request_id,
    )
    logger.info(
        "Staged mutation commit: tenant=%s batch=%s committed=%s quarantined=%s failed=%s skipped=%s request_id=%s",
        tenant_id, batch_id, counts["committed"], counts["quarantined"],
        counts["failed"], counts["skipped"], request_id,
    )
    return {"batch_id": batch_id, "batch_status": batch_status, "results": results, **counts}


async def rollback_mutation(
    tenant_id: str,
    mutation_id: str,
    actor: str,
    request_id: str = "",
    graph: GraphClient | None = None,
) -> dict[str, Any]:
    """Mark a committed mutation rolled_back with a best-effort graph inverse.

    The durable rolled_back status + audit trail is the contract; the graph
    inverse (vertex/edge drop) is best-effort and its outcome is recorded.
    """
    _require_review_enabled()
    repo = get_agent_runtime_repository()
    mutation = await repo.staged_mutations.get(mutation_id)
    if not mutation or mutation.get("tenant_id") != tenant_id:
        raise NotFoundError("Staged mutation")
    if mutation.get("status") == "rolled_back":
        return mutation  # idempotent
    if mutation.get("status") != "committed":
        raise ConflictError(f"Cannot roll back mutation in status '{mutation.get('status')}'")

    client = graph or _graph_client()
    inverse = (mutation.get("rollback") or {}).get("inverse") or mutation.get("commit_op") or {}
    inverse_applied = False
    inverse_error = ""
    try:
        if inverse.get("kind") == "vertex" and inverse.get("vertex_id"):
            await client.query(f"g.V('{_escape_gremlin(inverse['vertex_id'])}').drop()")
            inverse_applied = True
        elif inverse.get("kind") == "edge":
            idem = inverse.get("idempotency_key") or make_edge_idempotency_key(
                tenant_id,
                str(inverse.get("edge_type", "")),
                str(inverse.get("from_vertex_id", "")),
                str(inverse.get("to_vertex_id", "")),
            )
            await client.query(
                f"g.E().has('idempotency_key', '{_escape_gremlin(idem)}').drop()"
            )
            inverse_applied = True
    except Exception as exc:
        inverse_error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning(
            "Rollback inverse failed (recorded, continuing): tenant=%s mutation=%s error=%s",
            tenant_id, mutation_id, inverse_error,
        )

    await _set_mutation_status(
        repo, tenant_id, mutation, "rolled_back", actor, request_id,
        extra={
            "rolled_back_at": utc_now(),
            "rolled_back_by": actor,
            "rollback": {
                "supported": bool(inverse),
                "inverse": inverse,
                "inverse_applied": inverse_applied,
                "inverse_error": inverse_error,
            },
        },
    )
    return mutation
