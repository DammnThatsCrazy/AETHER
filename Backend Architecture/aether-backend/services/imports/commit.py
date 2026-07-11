"""
Aether Service — Import Engine commit / replay / rollback

The mutation half of the Import Engine. An *approved* import is staged, with
full lineage, into two durable places:

- **Bronze** (`BronzeRepository("tenant_import")`) — every source row is ingested
  immutably, tagged with the commit id (the Bronze ``source_tag``), so the exact
  rows a commit produced are recoverable and reversible.
- **The graph** — entity / resource / identifier vertices are upserted
  (idempotent) and relationship / has-identifier edges are added, each carrying
  the ``import_commit_id`` as a lineage property. Every edge created is recorded
  on the commit so a rollback can revoke *exactly* those edges.

Guarantees:
- Nothing commits unless the session is ``approved`` and the latest validation
  passed. A commit records real counts; a partial failure yields
  ``partially_committed`` (never a silent success).
- **Rollback is reversible without data loss of the source**: it revokes the
  commit's graph edges (soft-revoke) and deletes the commit's Bronze rows, but
  the source file bytes are never touched. Upserted vertices persist (the graph
  client exposes no vertex delete, and a vertex may be shared) — documented.
- **Replay** rolls back the prior live commit's edges, then re-stages under a
  fresh commit id, so the graph never accumulates duplicate edges.

The commit runs on the durable jobs platform (`import.commit`); the functions
here are also directly callable (and tested) without a worker.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from repositories.imports_repo import get_imports_repository
from services.imports.contracts import FieldMapping
from shared.common.common import BadRequestError, ConflictError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.imports.commit")

BRONZE_DOMAIN = "tenant_import"

# Primitives that become graph vertices, and the edge primitives.
_VERTEX_PRIMITIVES = {"entity", "resource", "identifier"}


async def _emit(topic_name: str, tenant_id: str, payload: dict) -> None:
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_name, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        await get_producer().publish(Event(topic=topic, tenant_id=tenant_id, payload=payload))
    except Exception as exc:  # pragma: no cover — telemetry never fails a commit
        logger.debug(f"import commit event publish skipped: {exc}")


def _coerce_fields(raw: list[dict]) -> list[FieldMapping]:
    return [FieldMapping(**f) for f in raw]


def build_primitive_records(
    fields: list[FieldMapping], rows: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Apply the mapping to every row, grouped by primitive.

    Returns ``(records, errors)``. Each record is
    ``{"primitive", "row", "fields": {target_field: value}}``. A row that fails a
    transform contributes an error dict and is skipped for that primitive (the
    import was validated before approval, so this is defensive).
    """
    from services.imports.validation import apply_transform

    by_primitive: dict[str, list[FieldMapping]] = {}
    for fm in fields:
        by_primitive.setdefault(fm.primitive, []).append(fm)

    records: list[dict] = []
    errors: list[dict] = []
    for idx, row in enumerate(rows):
        for primitive, fms in by_primitive.items():
            built: dict[str, Any] = {}
            failed = False
            for fm in fms:
                if fm.source_column not in row:
                    errors.append({"row": idx, "primitive": primitive,
                                   "code": "missing_column", "column": fm.source_column})
                    failed = True
                    break
                try:
                    built[fm.target_field] = apply_transform(row[fm.source_column], fm.transform)
                except ValueError as exc:
                    errors.append({"row": idx, "primitive": primitive,
                                   "code": "transform_failed", "column": fm.source_column,
                                   "detail": str(exc)})
                    failed = True
                    break
            if not failed:
                records.append({"primitive": primitive, "row": idx, "fields": built})
    return records, errors


def _vid(kind: str, tenant_id: str, key: str) -> str:
    return f"{kind}:{tenant_id}:{key}"


def plan_graph(tenant_id: str, records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deterministically plan the vertices and edges a set of records produces —
    pure, non-mutating (drives both the commit and the graph-preview)."""
    vertices: dict[str, dict] = {}
    edges: list[dict] = []
    for rec in records:
        primitive = rec["primitive"]
        f = rec["fields"]
        if primitive == "entity":
            ext = f.get("external_id")
            if not ext:
                continue
            vid = _vid("entity", tenant_id, str(ext))
            vertices[vid] = {
                "vertex_id": vid,
                "vertex_type": str(f.get("entity_type") or "Entity"),
                "properties": {k: v for k, v in f.items() if k != "attributes"},
            }
        elif primitive == "resource":
            ext = f.get("external_id")
            if not ext:
                continue
            vid = _vid("resource", tenant_id, str(ext))
            vertices[vid] = {
                "vertex_id": vid,
                "vertex_type": str(f.get("resource_type") or "Resource"),
                "properties": {k: v for k, v in f.items() if k != "attributes"},
            }
        elif primitive == "identifier":
            value = f.get("value")
            itype = f.get("identifier_type") or "identifier"
            if not value:
                continue
            vid = _vid("identifier", tenant_id, f"{itype}:{value}")
            vertices[vid] = {
                "vertex_id": vid,
                "vertex_type": "Identifier",
                "properties": {"identifier_type": str(itype), "value": str(value)},
            }
            entity_ref = f.get("entity_ref")
            if entity_ref:
                edges.append({
                    "from": _vid("entity", tenant_id, str(entity_ref)),
                    "to": vid,
                    "type": "HAS_IDENTIFIER",
                })
        elif primitive == "relationship":
            from_ref, to_ref = f.get("from_ref"), f.get("to_ref")
            if not from_ref or not to_ref:
                continue
            edges.append({
                "from": _vid("entity", tenant_id, str(from_ref)),
                "to": _vid("entity", tenant_id, str(to_ref)),
                "type": str(f.get("relationship_type") or "RELATED_TO"),
            })
    return list(vertices.values()), edges


async def _stage_and_mutate(
    tenant_id: str, import_id: str, session: dict, commit_id: str
) -> dict:
    """Bronze-stage every row and apply the planned graph mutations. Returns the
    commit record (counts + the edges created, for rollback). No status guards —
    the callers own the lifecycle transitions."""
    from repositories.lake import BronzeRepository
    from services.imports.storage import get_import_storage

    repo = get_imports_repository()
    mapping = await repo.get_latest_mapping(tenant_id, import_id)
    if mapping is None:
        raise BadRequestError("no mapping to commit")
    schemas = await repo.list_schemas(tenant_id, import_id)
    if not schemas:
        raise BadRequestError("no analyzed schema to commit")

    fields = _coerce_fields(mapping.get("fields", []))
    storage = get_import_storage()
    bronze = BronzeRepository(BRONZE_DOMAIN)

    from services.imports.analyzer import detect_format, read_rows

    bronze_rows = 0
    all_records: list[dict] = []
    row_errors: list[dict] = []
    for schema in schemas:
        file_id = schema.get("file_id")
        if not file_id:
            continue
        meta, content = await storage.get_content(tenant_id, file_id)
        fmt = detect_format(meta["filename"], meta.get("content_type", ""), content)
        rows, _info = read_rows(content, fmt)
        records, errors = build_primitive_records(fields, rows)
        all_records.extend(records)
        row_errors.extend(errors)
        for idx, row in enumerate(rows):
            _rec, is_new = await bronze.ingest(
                source=BRONZE_DOMAIN,
                source_tag=commit_id,
                provider_record_id=f"{file_id}:{idx}",
                payload=row,
                tenant_id=tenant_id,
                license_status="tenant_owned",
                terms_status="approved",
            )
            if is_new:
                bronze_rows += 1

    vertices, edges = plan_graph(tenant_id, all_records)
    created_edges = await _apply_graph(tenant_id, commit_id, vertices, edges)

    status = "partially_committed" if row_errors else "committed"
    return {
        "commit_id": commit_id,
        "mapping_version": int(mapping.get("version", 1)),
        "status": status,
        "counts": {
            "bronze_rows": bronze_rows,
            "records": len(all_records),
            "vertices": len(vertices),
            "edges": len(created_edges),
            "row_errors": len(row_errors),
        },
        "created_edges": created_edges,
        "bronze_source_tag": commit_id,
        "row_errors": row_errors[:500],
    }


async def _apply_graph(
    tenant_id: str, commit_id: str, vertices: list[dict], edges: list[dict]
) -> list[dict]:
    """Upsert vertices and add edges idempotently; return the edges actually
    created (so a rollback can revoke exactly them)."""
    from shared.graph.graph import Edge, Vertex, get_graph_client

    graph = get_graph_client()
    for v in vertices:
        props = {**v["properties"], "tenant_id": tenant_id, "import_commit_id": commit_id}
        await graph.upsert_vertex(
            Vertex(vertex_type=v["vertex_type"], vertex_id=v["vertex_id"], properties=props)
        )

    created: list[dict] = []
    for e in edges:
        existing = await graph.get_edges(e["from"], edge_type=e["type"], direction="out")
        if any(x.to_vertex_id == e["to"] for x in existing):
            continue  # idempotent: this edge already connects these vertices
        await graph.add_edge(
            Edge(
                edge_type=e["type"],
                from_vertex_id=e["from"],
                to_vertex_id=e["to"],
                properties={"tenant_id": tenant_id, "import_commit_id": commit_id},
            )
        )
        created.append(e)
    return created


# ── public API ───────────────────────────────────────────────────────────────


async def graph_preview(tenant_id: str, import_id: str) -> dict:
    """Non-mutating: the vertices and edges a commit *would* produce."""
    from services.imports.analyzer import detect_format, read_rows
    from services.imports.storage import get_import_storage

    repo = get_imports_repository()
    await repo.get_session(tenant_id, import_id)  # tenant guard
    mapping = await repo.get_latest_mapping(tenant_id, import_id)
    if mapping is None:
        raise BadRequestError("no mapping to preview")
    fields = _coerce_fields(mapping.get("fields", []))
    storage = get_import_storage()
    records: list[dict] = []
    for schema in await repo.list_schemas(tenant_id, import_id):
        file_id = schema.get("file_id")
        if not file_id:
            continue
        meta, content = await storage.get_content(tenant_id, file_id)
        fmt = detect_format(meta["filename"], meta.get("content_type", ""), content)
        rows, _ = read_rows(content, fmt)
        recs, _errs = build_primitive_records(fields, rows)
        records.extend(recs)
    vertices, edges = plan_graph(tenant_id, records)
    return {
        "import_id": import_id,
        "vertices": vertices[:200],
        "edges": edges[:200],
        "counts": {"vertices": len(vertices), "edges": len(edges), "records": len(records)},
    }


async def commit_import(tenant_id: str, import_id: str) -> dict:
    """Commit an approved import to Bronze + the graph."""
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    if session.get("status") != "approved":
        raise ConflictError(
            f"import must be approved before commit (current: {session.get('status')!r})"
        )
    await repo.set_status(tenant_id, import_id, "committing")
    commit_id = f"impc_{uuid.uuid4().hex}"
    try:
        record = await _stage_and_mutate(tenant_id, import_id, session, commit_id)
    except Exception:
        await repo.set_status(tenant_id, import_id, "failed")
        raise
    await repo.create_commit(tenant_id, import_id, record)
    await repo.set_status(tenant_id, import_id, record["status"])
    metrics.increment("import_committed_total", labels={"status": record["status"]})
    await _emit("IMPORT_COMMITTED", tenant_id, {"import_id": import_id, "commit_id": commit_id,
                                                "counts": record["counts"]})
    return record


async def rollback_import(
    tenant_id: str, import_id: str, *, commit_id: Optional[str] = None, reason: str = "operator rollback"
) -> dict:
    """Revoke a commit's graph edges and delete its Bronze rows; the source file
    bytes are never touched. Upserted vertices persist (no vertex delete)."""
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    if commit_id is None:
        latest = await repo.latest_commit(tenant_id, import_id)
        if latest is None:
            raise BadRequestError("no commit to roll back")
        commit_id = latest["commit_id"]
    commit = await repo.get_commit(tenant_id, commit_id)
    if commit.get("rolled_back"):
        raise ConflictError(f"commit {commit_id} is already rolled back")

    revoked = await _revoke_commit_edges(tenant_id, commit, reason)

    from repositories.lake import BronzeRepository

    bronze_deleted = await BronzeRepository(BRONZE_DOMAIN).rollback_by_source_tag(
        commit.get("bronze_source_tag", commit_id)
    )
    manifest = {"edges_revoked": revoked, "bronze_deleted": bronze_deleted, "reason": reason}
    await repo.create_rollback(tenant_id, import_id, commit_id, manifest)
    await repo.update_commit(tenant_id, commit_id, rolled_back=True)
    await repo.set_status(tenant_id, import_id, "rolled_back")
    metrics.increment("import_rolled_back_total")
    await _emit("IMPORT_ROLLED_BACK", tenant_id, {"import_id": import_id, "commit_id": commit_id,
                                                  **manifest})
    return {"commit_id": commit_id, **manifest, "status": "rolled_back"}


async def _revoke_commit_edges(tenant_id: str, commit: dict, reason: str) -> int:
    from shared.graph.graph import get_graph_client

    graph = get_graph_client()
    revoked = 0
    for e in commit.get("created_edges", []):
        revoked += await graph.revoke_edge(
            e["from"], e["to"], e["type"], reason=reason, tenant_id=tenant_id
        )
    return revoked


async def replay_import(tenant_id: str, import_id: str) -> dict:
    """Re-stage from the approved mapping under a fresh commit. Revokes the prior
    live commit's edges first, so the graph never accumulates duplicates."""
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    if session.get("status") not in {"committed", "partially_committed", "rolled_back"}:
        raise ConflictError(
            f"only a committed import can be replayed (current: {session.get('status')!r})"
        )
    prior = await repo.latest_commit(tenant_id, import_id)
    if prior is not None and not prior.get("rolled_back"):
        await _revoke_commit_edges(tenant_id, prior, "superseded by replay")
        await repo.update_commit(tenant_id, prior["commit_id"], rolled_back=True)

    await repo.set_status(tenant_id, import_id, "committing")
    commit_id = f"impc_{uuid.uuid4().hex}"
    record = await _stage_and_mutate(tenant_id, import_id, session, commit_id)
    record["replayed"] = True
    await repo.create_commit(tenant_id, import_id, record)
    await repo.set_status(tenant_id, import_id, record["status"])
    metrics.increment("import_replayed_total")
    await _emit("IMPORT_REPLAYED", tenant_id, {"import_id": import_id, "commit_id": commit_id})
    return record


# ── jobs platform registration ───────────────────────────────────────────────


def _outcome_status(record: dict) -> str:
    return "succeeded" if record["status"] == "committed" else "partially_succeeded"


async def commit_job_handler(payload: dict, ctx: Any):
    """``import.commit`` job handler — module-level (not a closure) so it resolves
    the same module identity as its caller and stays testable directly."""
    from services.jobs.handlers import JobOutcome

    record = await commit_import(ctx.tenant_id, payload["import_id"])
    return JobOutcome(status=_outcome_status(record), result=record)


async def replay_job_handler(payload: dict, ctx: Any):
    """``import.replay`` job handler (module-level, directly testable)."""
    from services.jobs.handlers import JobOutcome

    record = await replay_import(ctx.tenant_id, payload["import_id"])
    return JobOutcome(status=_outcome_status(record), result=record)


def register_import_handlers() -> None:
    """Register the import.commit / import.replay job handlers (idempotent)."""
    from services.jobs.handlers import HANDLER_REGISTRY, register_handler

    if "import.commit" in HANDLER_REGISTRY:
        return
    register_handler("import.commit")(commit_job_handler)
    register_handler("import.replay")(replay_job_handler)
