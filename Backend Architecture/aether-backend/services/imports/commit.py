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
  commit's graph edges (soft-revoke), deletes the commit's Bronze rows, and
  garbage-collects only import-owned vertices proven to have no active/shared
  references. The source file bytes are never touched.
- **Replay** rolls back the prior live commit's edges, then re-stages under a
  fresh commit id, so the graph never accumulates duplicate edges.

The commit runs on the durable jobs platform (`import.commit`); the functions
here are also directly callable (and tested) without a worker.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.imports_repo import get_imports_repository
from services.card_linked_payments.import_session import (
    MAX_SESSION_RETRIES,
    ImportSessionState,
    lifecycle_state_of,
)
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


def _norm_column(name: Any) -> str:
    """Normalize a column name for policy classification (lowercase, non-alnum
    stripped) — mirrors the fingerprint classifier's key normalization."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


async def _enforce_imports_consent_policy(
    tenant_id: str, fields: list[FieldMapping], staged_rows: list[dict]
) -> None:
    """WS-B3 T-class commit data-policy gate (mandatory, before any Bronze write).

    An import commit is a tenant back-office (T) attestation — the FSM approve
    transition is the consent gate — so there is deliberately NO per-subject
    server-receipt lookup here. The mandatory T-class layer is scrub (the caller
    applies it to every Bronze payload copy) PLUS this data-policy check, which
    runs BEFORE any Bronze write so a denial fails the commit closed with no
    partial Bronze. There is no per-path S toggle on the import path, so the
    ``imports_consent_policy_enabled`` flag cannot be a bypass: if an operator
    disables it the commit DENIES instead of ingesting with the policy layer
    switched off.

    Classification never trusts the client-supplied mapping ``source_column``
    label in isolation:
      * fingerprinting is detected from the ACTUAL staged column names (the
        schema of the ingested rows), not mapping labels, and is default-deny;
      * per-column data classes are only evaluated for a mapping source_column
        that is PROVEN present among the real ingested columns. An empty or
        phantom source_column (not resolvable against the staged data) is
        DENIED by default (``mapping_source_column_unresolved``) rather than
        skipped — a client cannot launder prohibited content under a label no
        policy ever sees.
    ``evaluate_data_policy`` is default-allow when no tenant compliance profile
    exists, so a tenant without a profile only ever trips on fingerprinting.
    """
    from config.settings import settings

    if not settings.ingress_consent.imports_consent_policy_enabled:
        # Fail closed: the mandatory T-class policy layer cannot be bypassed by
        # disabling the flag (an import must never skip data-policy).
        raise ConflictError("import_consent_policy_denied:enforcement_disabled")
    from services.consent.authority import evaluate_data_policy
    from services.ingestion.validation import classify_fingerprints

    denied: list[str] = []

    # 1. Fingerprinting over the ACTUAL staged columns (schema/content, never
    #    the mapping labels; values are never kept).
    fingerprint_seen = False
    for staged in staged_rows:
        for row in staged["rows"]:
            if classify_fingerprints(row):
                fingerprint_seen = True
                break
        if fingerprint_seen:
            break
    if fingerprint_seen:
        allowed, reason = await evaluate_data_policy(tenant_id, "fingerprint")
        if not allowed:
            denied.append(reason or "fingerprinting_not_authorized")

    # 2. Tenant-prohibited data classes. Only columns PROVEN present in the
    #    staged data are classified; unresolved mapping source_columns deny by
    #    default instead of being skipped.
    real_columns = {
        _norm_column(key)
        for staged in staged_rows
        for row in staged["rows"]
        for key in row
    }
    for fm in fields:
        data_class = _norm_column(fm.source_column)
        if not data_class or data_class not in real_columns:
            denied.append("mapping_source_column_unresolved")
            continue
        allowed, reason = await evaluate_data_policy(tenant_id, data_class)
        if not allowed:
            denied.append(reason or "data_classification_denied")

    if denied:
        unique = sorted(set(denied))
        logger.warning(
            "import_consent_policy_denied tenant=%s import_class=tenants reasons=%s",
            tenant_id, unique,
        )
        metrics.increment(
            "import_consent_policy_blocked_total",
            labels={"reason": "|".join(unique), "tenant_id": tenant_id},
        )
        raise ConflictError(f"import_consent_policy_denied:{'|'.join(unique)}")


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
    # WS-B3: rows are staged in full (per file) before any Bronze write so the
    # consent-policy gate can run against every row up front — a denial must
    # fail the commit closed with no partial Bronze.
    staged_rows: list[dict] = []
    for schema in schemas:
        file_id = schema.get("file_id")
        if not file_id:
            continue
        meta, content = await storage.get_content(tenant_id, file_id)
        fmt = detect_format(meta["filename"], meta.get("content_type", ""), content)
        rows, _info = read_rows(content, fmt)
        records, errors = build_primitive_records(fields, rows)
        for rec in records:
            rec["file_id"] = file_id  # lineage for the Silver projection
        all_records.extend(records)
        row_errors.extend(errors)
        staged_rows.append({"file_id": file_id, "rows": rows})

    # T-class data-policy gate before any durable write (no partial Bronze).
    await _enforce_imports_consent_policy(tenant_id, fields, staged_rows)

    # Scrub is the MANDATORY T-class minimization layer and runs UNCONDITIONALLY
    # (redaction never rejects). It is applied to the Bronze payload copy ONLY:
    # secret-key columns are redacted in what is persisted under tenant_import,
    # while the graph-building records keep the governor-approved mapped values.
    from services.ingestion.validation import scrub_sensitive_fields

    for staged in staged_rows:
        file_id = staged["file_id"]
        for idx, row in enumerate(staged["rows"]):
            payload, _ = scrub_sensitive_fields(row)
            _rec, is_new = await bronze.ingest(
                source=BRONZE_DOMAIN,
                source_tag=commit_id,
                provider_record_id=f"{file_id}:{idx}",
                payload=payload,
                tenant_id=tenant_id,
                license_status="tenant_owned",
                terms_status="approved",
            )
            if is_new:
                bronze_rows += 1

    vertices, edges = plan_graph(tenant_id, all_records)
    created_edges = await _apply_graph(tenant_id, commit_id, vertices, edges)

    # Project the committed records into Silver (silver_import_facts) for the
    # analytical layer. Best-effort — Bronze is the durable source of truth and a
    # replay re-derives the facts, so a Silver hiccup must never fail the commit.
    silver_rows = await _project_silver(
        tenant_id, import_id, commit_id, int(mapping.get("version", 1)), all_records
    )

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
            "silver_rows": silver_rows,
            "row_errors": len(row_errors),
        },
        "created_edges": created_edges,
        "upserted_vertices": [vertex["vertex_id"] for vertex in vertices],
        "bronze_source_tag": commit_id,
        "row_errors": row_errors[:500],
    }


async def _apply_graph(
    tenant_id: str, commit_id: str, vertices: list[dict], edges: list[dict]
) -> list[dict]:
    """Upsert vertices and add edges idempotently; return the edges actually
    created (so a rollback can revoke exactly them)."""
    from shared.graph.graph import Edge, Vertex, get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import edge_intent, vertex_intent

    graph = get_graph_client()
    gateway = GraphMutationGateway(graph_client=graph)
    for v in vertices:
        existing = await graph.get_vertex(v["vertex_id"])
        existing_props = dict(existing.properties or {}) if existing is not None else {}
        existing_tenant = existing_props.get("tenant_id")
        if existing_tenant not in (None, "", tenant_id):
            raise ValueError("import vertex id is already owned by another tenant")

        owners = set(existing_props.get("import_commit_ids") or [])
        if existing_props.get("import_commit_id"):
            owners.add(str(existing_props["import_commit_id"]))
        owners.add(commit_id)
        props = {
            **existing_props,
            **v["properties"],
            "tenant_id": tenant_id,
            "import_commit_ids": sorted(str(owner) for owner in owners),
        }
        if existing is None:
            props["import_commit_id"] = commit_id
        await gateway.apply(vertex_intent(
            Vertex(vertex_type=v["vertex_type"], vertex_id=v["vertex_id"], properties=props),
            operation="node_versioned", tenant_id=tenant_id,
            actor_kind="import", actor_id=commit_id, correlation_id=commit_id,
        ))

    created: list[dict] = []
    for e in edges:
        existing = await graph.get_edges(e["from"], edge_type=e["type"], direction="out")
        if any(x.to_vertex_id == e["to"] for x in existing):
            continue  # idempotent: this edge already connects these vertices
        await gateway.apply(edge_intent(
            Edge(
                edge_type=e["type"],
                from_vertex_id=e["from"],
                to_vertex_id=e["to"],
                properties={"tenant_id": tenant_id, "import_commit_id": commit_id},
            ),
            operation="edge_created", tenant_id=tenant_id,
            actor_kind="import", actor_id=commit_id,
            # Key the enforce/shadow idempotency on the commit so a replay or a
            # post-rollback re-commit re-materializes the same relationship as a
            # fresh edge instead of hitting the prior commit's ledger row and
            # being deduplicated (which would leave `created` recording an edge
            # that was never re-projected).
            source_event_id=commit_id,
            correlation_id=commit_id, causality_class="declared_reason",
        ))
        created.append(e)
    return created


async def _project_silver(
    tenant_id: str,
    import_id: str,
    commit_id: str,
    mapping_version: int,
    records: list[dict],
) -> int:
    """Best-effort Silver projection of the committed records into
    ``silver_import_facts``. Returns the number of rows written (0 on any
    failure — never raises, so a Silver hiccup cannot fail a durable commit)."""
    if not records:
        return 0
    try:
        from datetime import datetime, timezone

        from services.silver.projectors.import_projector import get_import_projector
        from services.silver.writer import SilverFactWriter

        result = get_import_projector().project_records(
            tenant_id=tenant_id,
            commit_id=commit_id,
            import_id=import_id,
            mapping_version=mapping_version,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            records=records,
        )
        return await SilverFactWriter().persist([result])
    except Exception as exc:  # pragma: no cover — Silver hiccup must not fail a commit
        logger.debug("import silver projection skipped: %s", exc)
        return 0


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _commit_entry_allowed(state: Optional[ImportSessionState], session: dict) -> bool:
    """The retry-safe commit entry guard.

    Accepts: a fresh commit (NORMALIZING, legacy ``approved``); a retry
    (FAILED — set by ``mark_failed`` after an in-process failure); a
    crash-recovery resume (COMMITTING — a hard crash leaves the session in
    ``committing`` with no failure recorded); and a mid-finalization resume
    (PROJECTING / RECONCILING — a transient failure between finalization
    transitions left a successfully staged commit stranded). Both the retry and
    the COMMITTING resume are refused once the session's recorded-failure
    budget is exhausted, so a deterministically failing commit cannot loop
    forever inside the FSM. The mid-finalization resume only advances FSM arcs
    (nothing is re-staged), so it carries no budget of its own.
    """
    if state is ImportSessionState.NORMALIZING:
        return True
    if state in (ImportSessionState.PROJECTING, ImportSessionState.RECONCILING):
        return True
    if state in (ImportSessionState.FAILED, ImportSessionState.COMMITTING):
        return int(session.get("retry_count", 0) or 0) < MAX_SESSION_RETRIES
    return False


async def commit_import(tenant_id: str, import_id: str) -> dict:
    """Resumable, idempotent commit of an approved import to Bronze + the graph.

    Entry states (retry-safe): NORMALIZING (legacy ``approved``) for a fresh
    commit; FAILED for a job retry / operator requeue; COMMITTING for a
    crash-recovery resume; and PROJECTING / RECONCILING for a mid-finalization
    resume (a transient failure between finalization transitions left a
    successfully staged commit stranded — the retry advances the remaining arcs
    to COMPLETED instead of being rejected). The commit id is persisted on the
    session (``active_commit_id``) at entry, so a crash mid-commit resumes under
    the SAME id: Bronze ingest, graph upserts and the commit row are idempotent,
    so replaying never duplicates rows/edges and never silently stops mid-import.

    On failure the session is marked FAILED with ``failure_reason`` +
    ``retry_count`` (both preserved across retries) instead of being stuck in
    ``committing`` forever — a retry then re-enters COMMITTING and resumes.
    """
    from services.imports.session_persistence import (
        mark_failed,
        transition_session,
    )

    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    state = lifecycle_state_of(session)
    if not _commit_entry_allowed(state, session):
        raise ConflictError(
            f"import is not commit-eligible in state {state.value if state else 'UNKNOWN'!r} "
            "(eligible: NORMALIZING/approved, FAILED, a stranded COMMITTING, "
            "or a mid-finalization PROJECTING/RECONCILING)"
        )

    # A session stranded mid-finalization (PROJECTING / RECONCILING) already
    # staged and recorded its commit row; a retry resumes the remaining
    # lifecycle transitions instead of re-running staging. Idempotent — the
    # transitions only advance FSM arcs, nothing is re-applied.
    if state in (ImportSessionState.PROJECTING, ImportSessionState.RECONCILING):
        commit_id = session.get("active_commit_id")
        if not commit_id:
            latest = await repo.latest_commit(tenant_id, import_id)
            commit_id = latest.get("commit_id") if latest else None
        if not commit_id:
            raise ConflictError(
                "import session is mid-finalization but has no commit row; cannot resume"
            )
        record = await repo.get_commit(tenant_id, commit_id)
        return await _finalize_commit(
            repo, tenant_id, import_id, record,
            resume_from=state,
            source_checksum=session.get("source_checksum"),
        )

    commit_id = session.get("active_commit_id")
    if not commit_id:
        commit_id = f"impc_{uuid.uuid4().hex}"
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.COMMITTING,
            patch={"active_commit_id": commit_id, "commit_started_at": _now_iso()},
        )
    else:
        # Resume: re-enter COMMITTING (self arc) and refresh the commit anchor
        # so the sweeper/requeue grant a fresh stranded-detection window.
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.COMMITTING,
            patch={"commit_started_at": _now_iso()},
        )

    try:
        record = await _stage_and_mutate(tenant_id, import_id, session, commit_id)
    except Exception as exc:
        await mark_failed(
            repo, tenant_id, import_id,
            failure_reason="commit staging failed",
            exc=exc,
        )
        raise

    # The commit row upserts by commit_id, so a resume overwrites the prior
    # (partial) record instead of accumulating duplicates.
    await repo.create_commit(tenant_id, import_id, record)

    # Drive the program lifecycle: Bronze+graph staging was COMMITTING; Silver
    # projection is PROJECTING; provider corroboration is RECONCILING.
    return await _finalize_commit(
        repo, tenant_id, import_id, record,
        resume_from=None,
        source_checksum=session.get("source_checksum"),
    )


async def _finalize_commit(
    repo: Any,
    tenant_id: str,
    import_id: str,
    record: dict,
    *,
    resume_from: Optional[ImportSessionState],
    source_checksum: Optional[str],
) -> dict:
    """Drive the post-staging lifecycle to COMPLETED, idempotently.

    Fresh path (``resume_from=None``): PROJECTING -> RECONCILING -> COMPLETED.
    Resume path: a session stranded in PROJECTING / RECONCILING (a transient
    failure between finalization transitions) advances only the remaining arcs
    — PROJECTING -> RECONCILING -> COMPLETED, or RECONCILING -> COMPLETED — so
    the retry completes the commit instead of being rejected by the entry
    guard. Nothing is re-staged and the commit row is never re-created, so a
    re-run cannot double-apply projections/commits.
    """
    from services.imports.session_persistence import transition_session

    if resume_from is None:
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.PROJECTING,
            patch={"projection_state": "completed"},
        )
    if resume_from is not ImportSessionState.RECONCILING:
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.RECONCILING,
            patch={"reconciliation_state": "pending_provider_corroboration"},
        )
    legacy = (
        "partially_committed"
        if record["status"] == "partially_committed"
        else "committed"
    )
    counts = record.get("counts", {})
    await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.COMPLETED,
        legacy_status=legacy,
        patch={
            "projection_state": "completed",
            # Provider corroboration has NOT run — nothing here invokes a real
            # reconciliation path or checks evidence. Keep the honest
            # "not yet corroborated" marker instead of claiming "cleared": a
            # cleared verdict is recorded only by a real reconciliation path
            # that corroborates the staged import against provider evidence.
            "reconciliation_state": "pending_provider_corroboration",
            "accepted_count": int(counts.get("records", 0) or 0),
            "rejected_count": int(counts.get("row_errors", 0) or 0),
            "duplicate_count": max(
                0,
                int(counts.get("records", 0) or 0)
                - int(counts.get("bronze_rows", 0) or 0),
            ),
            "quarantine_count": 0,
            "schema_version": record.get("mapping_version"),
            "source_checksum": source_checksum,
            "completed_at": _now_iso(),
        },
    )
    metrics.increment("import_committed_total", labels={"status": record["status"]})
    await _emit(
        "IMPORT_COMMITTED",
        tenant_id,
        {
            "import_id": import_id,
            "commit_id": record["commit_id"],
            "counts": record.get("counts"),
        },
    )
    return record


async def rollback_import(
    tenant_id: str, import_id: str, *, commit_id: Optional[str] = None, reason: str = "operator rollback"
) -> dict:
    """Revoke edges, delete Bronze rows, and safely collect orphan vertices.

    Source files remain immutable. A vertex is deleted only when graph-level
    ownership and reference checks prove it belongs exclusively to this commit.
    """
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
    vertex_gc = await _garbage_collect_vertices(tenant_id, commit)

    from repositories.lake import BronzeRepository

    bronze_deleted = await BronzeRepository(BRONZE_DOMAIN).rollback_by_source_tag(
        commit.get("bronze_source_tag", commit_id)
    )
    manifest = {
        "edges_revoked": revoked,
        "bronze_deleted": bronze_deleted,
        "vertices_deleted": vertex_gc["deleted"],
        "vertices_retained": vertex_gc["retained"],
        "reason": reason,
    }
    await repo.create_rollback(tenant_id, import_id, commit_id, manifest)
    await repo.update_commit(tenant_id, commit_id, rolled_back=True)
    from services.imports.session_persistence import transition_session

    await transition_session(
        repo, tenant_id, import_id, ImportSessionState.ROLLED_BACK
    )
    metrics.increment("import_rolled_back_total")
    await _emit("IMPORT_ROLLED_BACK", tenant_id, {"import_id": import_id, "commit_id": commit_id,
                                                  **manifest})
    return {"commit_id": commit_id, **manifest, "status": "rolled_back"}


async def _revoke_commit_edges(tenant_id: str, commit: dict, reason: str) -> int:
    from shared.graph.graph import get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import revocation_intent

    graph = get_graph_client()
    gateway = GraphMutationGateway(graph_client=graph)
    commit_id = commit.get("commit_id") or ""
    revoked = 0
    for e in commit.get("created_edges", []):
        outcome = await gateway.apply(revocation_intent(
            from_vertex_id=e["from"], to_vertex_id=e["to"], edge_type=e["type"],
            reason=reason, tenant_id=tenant_id,
            operation="edge_tombstoned", actor_kind="import", actor_id=commit_id,
            reason_code="import_rolled_back", correlation_id=commit_id,
            # Mirror the create path: key the revocation on the commit so a
            # replay/rollback of a re-materialized edge is not deduplicated
            # against a prior commit's revocation of the same edge tuple.
            source_event_id=commit_id,
        ))
        result = outcome.projection_result
        revoked += result if isinstance(result, int) else 0
    return revoked


async def _garbage_collect_vertices(tenant_id: str, commit: dict) -> dict:
    """Delete only vertices proven orphaned and owned by this import commit."""
    from shared.graph.graph import get_graph_client

    graph = get_graph_client()
    commit_id = str(commit.get("commit_id") or "")
    deleted: list[str] = []
    retained: list[dict] = []
    for vertex_id in dict.fromkeys(commit.get("upserted_vertices", [])):
        try:
            removed, reason = await graph.delete_vertex_if_orphaned(
                str(vertex_id),
                tenant_id,
                commit_id,
            )
        except Exception as exc:
            removed, reason = False, type(exc).__name__
        if removed:
            deleted.append(str(vertex_id))
        else:
            retained.append({"vertex_id": str(vertex_id), "reason": reason})
    return {"deleted": deleted, "retained": retained}


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
        await _garbage_collect_vertices(tenant_id, prior)
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
