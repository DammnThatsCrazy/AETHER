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
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.graph.write_validator import GraphWriteValidator
from shared.logger.logger import get_logger, metrics
from services.agent.runtime_repository import (
    APPROVAL_TTL_SECONDS,
    MUTATION_CLASSES,
    _age_seconds,
    get_agent_runtime_repository,
    mutation_fingerprint,
    target_key_for,
    utc_now,
)

logger = get_logger("aether.service.agent.mutation_commit")


def _approval_gate(mutation: dict[str, Any]) -> tuple[bool, str, str]:
    """Verify the operator approval still authorizes committing THIS content.

    Returns (ok, result_status, detail). A failure here is a *re-approvable*
    conflict (not a hard failure): the mutation keeps its ``approved`` status so
    the operator can re-approve, and no graph write happens.

      - approval_expired : the approval is older than APPROVAL_TTL_SECONDS.
      - needs_reapproval : the target/diff/class changed since it was approved,
                           so the recorded approval no longer covers it.
    """
    approved_at = mutation.get("approved_at")
    if not approved_at:
        return False, "needs_reapproval", "no approval timestamp recorded"
    if _age_seconds(approved_at) > APPROVAL_TTL_SECONDS:
        return False, "approval_expired", f"approval older than {APPROVAL_TTL_SECONDS}s"
    recorded = mutation.get("approval_fingerprint")
    if recorded and recorded != mutation_fingerprint(mutation):
        return False, "needs_reapproval", "mutation content changed since approval"
    return True, "approved", ""

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
    # Fail-closed on the emergency stop at the PIPELINE level, not just the
    # route: a scheduled job, a direct API call, or any non-operator caller that
    # reaches commit is blocked while the kill switch is engaged.
    kill_switch = await repo.get_kill_switch(tenant_id)
    if kill_switch.get("enabled"):
        raise ConflictError("Agent kill switch is engaged; canonical commit is disabled")
    batch = await repo.review_batches.get(batch_id)
    if not batch or batch.get("tenant_id") != tenant_id:
        raise NotFoundError("Review batch")
    if batch.get("status") not in {"approved", "quarantined", "committed"}:
        # pending/rejected batches carry no approval — human review is the
        # only path into this pipeline.
        raise ConflictError(f"Cannot commit review batch in status '{batch.get('status')}'")

    client = graph or _graph_client()
    gateway = GraphMutationGateway(graph_client=client)
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

        # Approval invariant gate: a stale (expired) or content-changed approval
        # cannot commit. These are re-approvable conflicts — the mutation keeps
        # its ``approved`` status, no graph write happens, and the batch will not
        # be reported clean, so the operator must re-approve to proceed.
        ok, gate_status, gate_detail = _approval_gate(mutation)
        if not ok:
            mutation["conflict"] = {"kind": gate_status, "detail": gate_detail}
            mutation["updated_at"] = utc_now()
            await repo.staged_mutations.set(mutation_id, mutation)
            await repo.append_event(
                tenant_id, "mutation.commit_blocked", "commit", mutation,
                mutation.get("objective_id", ""), actor, request_id,
            )
            metrics.increment("agent_mutation_commit_blocked", labels={"reason": gate_status})
            results.append(_result(mutation_id, gate_status, gate_detail))
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

        # Optimistic concurrency: the mutation was staged against a specific
        # version of its canonical target (base_version / ETag). If the target
        # has been committed to since, this commit is stale and is rejected —
        # the operator re-stages/re-approves against the fresh version. A missing
        # base_version (legacy staged rows) skips the check.
        tkey = target_key_for(mutation.get("target"))
        expected_version = mutation.get("base_version")
        if expected_version is not None:
            current_version = await repo.canonical_version(tenant_id, tkey)
            if int(expected_version) != int(current_version):
                mutation["conflict"] = {
                    "kind": "stale_version",
                    "expected_version": int(expected_version),
                    "current_version": int(current_version),
                }
                mutation["updated_at"] = utc_now()
                await repo.staged_mutations.set(mutation_id, mutation)
                await repo.append_event(
                    tenant_id, "mutation.commit_conflict", "commit", mutation,
                    mutation.get("objective_id", ""), actor, request_id,
                )
                metrics.increment("agent_mutation_commit_blocked", labels={"reason": "stale_version"})
                results.append(_result(
                    mutation_id, "stale_version",
                    f"expected={expected_version} current={current_version}",
                ))
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
                await gateway.apply(vertex_intent(
                    vertex, operation="node_created",
                    tenant_id=tenant_id, actor_kind="human", actor_id=actor,
                    correlation_id=mutation["mutation_id"],
                ))
            elif edge is not None:
                await gateway.apply(edge_intent(
                    edge, operation="edge_created",
                    tenant_id=tenant_id, actor_kind="human", actor_id=actor,
                    correlation_id=mutation["mutation_id"],
                ))
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

        # Advance the canonical target version so any other mutation staged
        # against the prior version is now detectably stale (optimistic
        # concurrency). Recorded on the mutation for post-commit reconciliation.
        committed_version = await repo.bump_canonical_version(tenant_id, tkey, mutation_id)
        await _set_mutation_status(
            repo, tenant_id, mutation, "committed", actor, request_id,
            extra={
                "committed_at": utc_now(),
                "committed_by": actor,
                "commit_op": op,
                "committed_version": committed_version,
                "target_key": tkey,
                # Rollback metadata: enough to attempt a best-effort inverse.
                "rollback": {"supported": True, "inverse": op},
            },
        )
        results.append(_result(mutation_id, "committed"))

    _blocked_statuses = {"approval_expired", "needs_reapproval", "stale_version"}
    counts = {
        "committed": sum(1 for r in results if r["status"] == "committed"),
        "quarantined": sum(1 for r in results if r["status"] == "quarantined"),
        "failed": sum(1 for r in results if r["status"] in {"failed_commit", "missing"}),
        "skipped": sum(1 for r in results if r["status"] == "skipped_not_approved"),
        # Re-approvable conflicts: expired/changed approval or a stale version.
        "blocked": sum(1 for r in results if r["status"] in _blocked_statuses),
    }
    clean = counts["quarantined"] == 0 and counts["failed"] == 0 and counts["blocked"] == 0
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


def _inverse_of(tenant_id: str, mutation: dict[str, Any]) -> dict[str, Any]:
    return (mutation.get("rollback") or {}).get("inverse") or mutation.get("commit_op") or {}


def _existence_gremlin(tenant_id: str, op: dict[str, Any]) -> str:
    """Read-only count query used to VERIFY an inverse actually applied and for
    post-commit reconciliation of a committed receipt against graph state."""
    if op.get("kind") == "vertex" and op.get("vertex_id"):
        return f"g.V('{_escape_gremlin(str(op['vertex_id']))}').count()"
    idem = op.get("idempotency_key") or make_edge_idempotency_key(
        tenant_id,
        str(op.get("edge_type", "")),
        str(op.get("from_vertex_id", "")),
        str(op.get("to_vertex_id", "")),
    )
    return f"g.E().has('idempotency_key', '{_escape_gremlin(str(idem))}').count()"


def _count_from_result(result: Any) -> int | None:
    """Interpret a Gremlin count() result. None means the backend could not
    confirm (e.g. the in-memory no-op backend returns []), which callers treat
    as best-effort / unconfirmed rather than a definitive absence."""
    if not isinstance(result, list) or not result:
        return None
    head = result[0]
    if isinstance(head, bool):
        return int(head)
    if isinstance(head, int):
        return head
    if isinstance(head, dict):
        for key in ("count", "value", "0"):
            if key in head:
                try:
                    return int(head[key])
                except (TypeError, ValueError):
                    return None
    try:
        return int(head)
    except (TypeError, ValueError):
        return None


async def _graph_presence(client: GraphClient, tenant_id: str, op: dict[str, Any]) -> tuple[bool | None, int | None]:
    """Return (present, count). ``present`` is None when the backend can't be read."""
    try:
        result = await client.query(_existence_gremlin(tenant_id, op))
    except Exception as exc:  # existence probe must never mask the primary op
        logger.warning("Graph presence probe failed: tenant=%s error=%s", tenant_id, type(exc).__name__)
        return None, None
    count = _count_from_result(result)
    if count is None:
        return None, None
    return count > 0, count


async def rollback_mutation(
    tenant_id: str,
    mutation_id: str,
    actor: str,
    request_id: str = "",
    graph: GraphClient | None = None,
) -> dict[str, Any]:
    """Roll a committed mutation back, VERIFY the inverse applied, and open a
    durable repair task when the graph cannot be fully restored.

    Flow: attempt the inverse (vertex/edge drop) → read the graph back to
    confirm the artifact is absent → on success mark ``rolled_back`` with a
    durable verification receipt; if the inverse errored or the artifact is
    still present, mark ``rollback_repair_required`` and enqueue a repair task
    for the operator. Idempotent for already-rolled-back/repair states.
    """
    _require_review_enabled()
    repo = get_agent_runtime_repository()
    mutation = await repo.staged_mutations.get(mutation_id)
    if not mutation or mutation.get("tenant_id") != tenant_id:
        raise NotFoundError("Staged mutation")
    if mutation.get("status") in {"rolled_back", "rollback_repair_required"}:
        return mutation  # idempotent
    if mutation.get("status") != "committed":
        raise ConflictError(f"Cannot roll back mutation in status '{mutation.get('status')}'")

    client = graph or _graph_client()
    inverse = _inverse_of(tenant_id, mutation)
    inverse_applied = False
    inverse_error = ""
    try:
        if inverse.get("kind") == "vertex" and inverse.get("vertex_id"):
            await client.query(f"g.V('{_escape_gremlin(str(inverse['vertex_id']))}').drop()")
            inverse_applied = True
        elif inverse.get("kind") == "edge":
            idem = inverse.get("idempotency_key") or make_edge_idempotency_key(
                tenant_id,
                str(inverse.get("edge_type", "")),
                str(inverse.get("from_vertex_id", "")),
                str(inverse.get("to_vertex_id", "")),
            )
            await client.query(
                f"g.E().has('idempotency_key', '{_escape_gremlin(str(idem))}').drop()"
            )
            inverse_applied = True
    except Exception as exc:
        inverse_error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning(
            "Rollback inverse failed (recorded, continuing): tenant=%s mutation=%s error=%s",
            tenant_id, mutation_id, inverse_error,
        )

    # VERIFY: read the graph back and confirm the artifact is gone.
    present, remaining = await _graph_presence(client, tenant_id, inverse)
    verified = present is False               # definitively absent
    confirmed = present is not None           # the backend could actually be read
    verification = {
        "method": "graph_count_probe",
        "checked_at": utc_now(),
        "confirmed": confirmed,
        "remaining": remaining,
    }

    repair_id = ""
    if inverse_error or present is True:
        # The inverse could not fully restore state — open a repair task and mark
        # the mutation for operator follow-up rather than reporting a clean undo.
        status = "rollback_repair_required"
        reason = "inverse_error" if inverse_error else "artifact_still_present"
        repair = await repo.open_repair_task(
            tenant_id, mutation, reason,
            {"inverse": inverse, "inverse_error": inverse_error, "remaining": remaining},
            actor, request_id,
        )
        repair_id = repair["repair_id"]
        metrics.increment("agent_rollback_verified", labels={"result": "repair_required"})
    else:
        status = "rolled_back"
        metrics.increment("agent_rollback_verified", labels={"result": "verified" if confirmed else "unconfirmed"})

    await _set_mutation_status(
        repo, tenant_id, mutation, status, actor, request_id,
        extra={
            "rolled_back_at": utc_now(),
            "rolled_back_by": actor,
            "rollback": {
                "supported": bool(inverse),
                "inverse": inverse,
                "inverse_applied": inverse_applied,
                "inverse_error": inverse_error,
                "verified": verified,
                "verification": verification,
                "repair_required": status == "rollback_repair_required",
                "repair_id": repair_id,
            },
        },
        event_type=f"mutation.{status}",
    )
    return mutation


async def reconcile_mutation(
    tenant_id: str,
    mutation_id: str,
    actor: str,
    request_id: str = "",
    graph: GraphClient | None = None,
) -> dict[str, Any]:
    """Post-commit reconciliation: compare a committed receipt to graph state.

    A committed mutation's target must be present in the graph; a rolled_back
    mutation's target must be absent. The result is recorded on the mutation as
    a durable reconciliation receipt and surfaced on the timeline. Drift (a
    committed receipt with no matching graph artifact, or vice versa) is flagged
    but not auto-repaired — the operator decides.
    """
    _require_review_enabled()
    repo = get_agent_runtime_repository()
    mutation = await repo.staged_mutations.get(mutation_id)
    if not mutation or mutation.get("tenant_id") != tenant_id:
        raise NotFoundError("Staged mutation")
    status = mutation.get("status")
    if status not in {"committed", "rolled_back"}:
        raise ConflictError(f"Cannot reconcile mutation in status '{status}'")

    client = graph or _graph_client()
    op = mutation.get("commit_op") or _inverse_of(tenant_id, mutation)
    present, count = await _graph_presence(client, tenant_id, op)
    expected_present = status == "committed"
    if present is None:
        consistent: bool | None = None      # backend not readable — indeterminate
    else:
        consistent = present == expected_present
    receipt = {
        "checked_at": utc_now(),
        "status_at_check": status,
        "expected_present": expected_present,
        "observed_present": present,
        "observed_count": count,
        "consistent": consistent,
    }
    mutation["reconciliation"] = receipt
    mutation["updated_at"] = utc_now()
    await repo.staged_mutations.set(mutation_id, mutation)
    event_type = "mutation.reconciled" if consistent is not False else "mutation.reconcile_drift"
    await repo.append_event(
        tenant_id, event_type, "commit",
        {"mutation_id": mutation_id, **receipt},
        mutation.get("objective_id", ""), actor, request_id,
    )
    metrics.increment(
        "agent_mutation_reconciled",
        labels={"consistent": "unknown" if consistent is None else str(consistent).lower()},
    )
    return {"mutation_id": mutation_id, **receipt}


async def reconcile_batch(
    tenant_id: str,
    batch_id: str,
    actor: str,
    request_id: str = "",
    graph: GraphClient | None = None,
) -> dict[str, Any]:
    """Reconcile every committed/rolled_back mutation in a batch against the graph."""
    _require_review_enabled()
    repo = get_agent_runtime_repository()
    batch = await repo.review_batches.get(batch_id)
    if not batch or batch.get("tenant_id") != tenant_id:
        raise NotFoundError("Review batch")
    results: list[dict[str, Any]] = []
    for mutation_id in batch.get("mutation_ids", []):
        mutation = await repo.staged_mutations.get(mutation_id)
        if not mutation or mutation.get("tenant_id") != tenant_id:
            continue
        if mutation.get("status") not in {"committed", "rolled_back"}:
            continue
        results.append(await reconcile_mutation(tenant_id, mutation_id, actor, request_id, graph=graph))
    drift = sum(1 for r in results if r["consistent"] is False)
    return {"batch_id": batch_id, "reconciled": len(results), "drift": drift, "results": results}
