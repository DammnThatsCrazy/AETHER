"""
Aether Service — Tenant Import Engine (ingest → analyze → map → validate)

Orchestrates the durable, tenant-scoped import lifecycle up to the point a
mapping has been validated and (if it touches sensitive data) approved. Nothing
is reported analyzed/validated/approved unless the evidence is persisted:
uploaded bytes carry a sha256; a schema profile is stored per file; a validation
result (with capped row errors) is stored per run; and governance-sensitive
mappings force an explicit review before they can be approved.

The commit / Bronze / Silver / graph half lives in a separate change; this
module deliberately stops at ``approved``.
"""

from __future__ import annotations

from typing import Optional

from repositories.imports_repo import get_imports_repository
from services.card_linked_payments.import_session import ImportSessionState
from services.imports.contracts import (
    FieldMapping,
    is_terminal_status,
    mapping_requires_review,
)
from services.imports.session_persistence import (
    ensure_program_fields,
    transition_session,
)
from services.imports.storage import get_import_storage
from shared.common.common import BadRequestError, ConflictError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.imports.service")

# Default per-upload cap. The BYTEA repo enforces a 32 MB hard ceiling; this
# lower default leaves room for a plan-tier lookup to raise/lower it later.
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Rows validated per run. Files are capped at a few tens of MB, so a full
# in-memory pass is honest and cheap; this bounds pathological wide files.
MAX_VALIDATION_ROWS = 100_000

# Per-tenant cap on concurrently in-flight (non-terminal) imports — bounds
# resource use and makes a runaway client fail closed rather than pile up work.
MAX_CONCURRENT_IMPORTS = 25


async def _emit(topic_name: str, tenant_id: str, payload: dict) -> None:
    """Best-effort bus publish; the import flow never fails on telemetry."""
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_name, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        producer = get_producer()
        await producer.publish(Event(topic=topic, tenant_id=tenant_id, payload=payload))
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(f"import event publish skipped: {exc}")


def max_upload_bytes_for(plan_tier: Optional[str]) -> int:
    """Per-upload byte cap for a plan tier (seam for plan-specific limits)."""
    return DEFAULT_MAX_UPLOAD_BYTES


def _ensure_not_terminal(session: dict) -> None:
    if is_terminal_status(session.get("status", "")):
        raise ConflictError(
            f"import {session.get('id')} is in terminal state "
            f"{session.get('status')!r} and accepts no further changes"
        )


# ── lifecycle ────────────────────────────────────────────────────────────────


async def create_import(tenant_id: str, *, created_by: Optional[str] = None) -> dict:
    repo = get_imports_repository()
    active = await repo.count_active_sessions(tenant_id)
    if active >= MAX_CONCURRENT_IMPORTS:
        raise ConflictError(
            f"tenant has {active} imports in flight (max {MAX_CONCURRENT_IMPORTS}); "
            "finish, cancel, or roll back an existing import first"
        )
    session = await repo.create_session(tenant_id, created_by=created_by)
    # Seed the program-spec lifecycle fields (JSONB) so the operator surface
    # and sweeper can rely on them being present on every session.
    await ensure_program_fields(repo, tenant_id, session["id"])
    metrics.increment("import_sessions_created_total")
    await _emit("IMPORT_CREATED", tenant_id, {"import_id": session["id"]})
    return session


async def get_import(tenant_id: str, import_id: str) -> dict:
    """Session + its files + latest schema/mapping/validation summaries."""
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    files = await get_import_storage().list_for_import(tenant_id, import_id)
    schemas = await repo.list_schemas(tenant_id, import_id)
    mapping = await repo.get_latest_mapping(tenant_id, import_id)
    validation = await repo.get_latest_validation(tenant_id, import_id)
    return {
        "session": session,
        "files": files,
        "schemas": [s.get("profile") for s in schemas],
        "mapping": mapping,
        "validation": validation,
    }


async def list_imports(tenant_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    return await get_imports_repository().list_sessions(
        tenant_id, limit=limit, offset=offset
    )


async def store_file(
    tenant_id: str,
    import_id: str,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> dict:
    """Validate the format allowlist and size, store the bytes, advance the
    session to ``uploaded``. Rejects unsupported/oversized files up front."""
    from services.imports.analyzer import detect_format  # lazy: agent-owned module

    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    _ensure_not_terminal(session)
    if not content:
        raise BadRequestError("uploaded file is empty")
    if len(content) > max_bytes:
        raise BadRequestError(
            f"file exceeds the {max_bytes} byte upload cap ({len(content)} bytes)"
        )
    # Content-sniff + extension agreement; raises BadRequestError('unsupported_format')
    # for xlsx/parquet/zip/etc. — the zip-bomb class is eliminated (no archive support).
    fmt = detect_format(filename, content_type, content)

    stored = await get_import_storage().put(
        tenant_id,
        import_id=import_id,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    files = await get_import_storage().list_for_import(tenant_id, import_id)
    # Program-spec fields: a deterministic batch checksum over every stored
    # file's sha256 (single-file imports use the file's own checksum) and the
    # UPLOADED lifecycle transition.
    checksums = sorted(f.get("sha256") or "" for f in files)
    import hashlib

    checksum = checksums[0] if len(checksums) == 1 else hashlib.sha256(
        "\n".join(checksums).encode("utf-8")
    ).hexdigest()
    await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.UPLOADED,
        patch={"file_count": len(files), "source_checksum": checksum},
    )
    metrics.increment("import_files_uploaded_total", labels={"format": fmt})
    await _emit(
        "IMPORT_UPLOADED",
        tenant_id,
        {"import_id": import_id, "file_id": stored["id"], "format": fmt},
    )
    return {**stored, "format": fmt}


async def analyze_import(tenant_id: str, import_id: str) -> dict:
    """Analyze every uploaded file's schema; store a profile per file."""
    from services.imports.analyzer import analyze_bytes  # lazy: agent-owned module

    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    _ensure_not_terminal(session)
    storage = get_import_storage()
    files = await storage.list_for_import(tenant_id, import_id)
    if not files:
        raise BadRequestError("no files to analyze — upload a file first")

    await repo.set_status(tenant_id, import_id, "analyzing")
    profiles: list[dict] = []
    total_rows = 0
    for f in files:
        _meta, content = await storage.get_content(tenant_id, f["id"])
        profile = analyze_bytes(
            f["id"], content, f["filename"], f.get("content_type", "")
        )
        profile_dict = profile.model_dump(mode="json")
        await repo.save_schema(tenant_id, import_id, f["id"], profile_dict)
        profiles.append(profile_dict)
        total_rows += int(profile_dict.get("row_count", 0) or 0)

    await repo.update_session(
        tenant_id, import_id, status="analyzed", row_count=total_rows
    )
    metrics.increment("import_analyzed_total")
    await _emit(
        "IMPORT_ANALYZED",
        tenant_id,
        {"import_id": import_id, "file_count": len(files), "row_count": total_rows},
    )
    return {"import_id": import_id, "schemas": profiles, "row_count": total_rows}


def _coerce_fields(raw_fields: list[dict]) -> list[FieldMapping]:
    return [FieldMapping(**f) for f in raw_fields]


async def set_mapping(tenant_id: str, import_id: str, raw_fields: list[dict]) -> dict:
    """Validate a proposed mapping structurally and persist a new version."""
    from services.imports.mapping import validate_mapping_fields  # lazy: agent-owned

    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    _ensure_not_terminal(session)
    fields = _coerce_fields(raw_fields)
    errors = validate_mapping_fields(fields)
    if errors:
        raise BadRequestError("invalid mapping: " + "; ".join(errors))

    stored = await repo.save_mapping(
        tenant_id, import_id, [f.model_dump(mode="json") for f in fields]
    )
    await repo.set_status(tenant_id, import_id, "mapped")
    return stored


async def apply_template(tenant_id: str, import_id: str, template_id: str) -> dict:
    """Apply a saved template's fields as the mapping for this import."""
    repo = get_imports_repository()
    template = await repo.get_template(tenant_id, template_id)
    return await set_mapping(tenant_id, import_id, template.get("fields", []))


async def suggest_templates(tenant_id: str, import_id: str) -> dict:
    """Templates whose header signature matches this import's first file, with
    per-template drift against the actual columns."""
    from services.imports.analyzer import header_signature  # lazy
    from services.imports.mapping import match_template, template_drift  # lazy

    repo = get_imports_repository()
    await repo.get_session(tenant_id, import_id)  # tenant guard
    schemas = await repo.list_schemas(tenant_id, import_id)
    if not schemas:
        return {"import_id": import_id, "matched": None, "candidates": []}
    columns = [c["name"] for c in (schemas[0].get("profile", {}).get("columns") or [])]
    signature = header_signature(columns)
    templates = await repo.list_templates(tenant_id)
    matched = match_template(signature, templates)
    candidates = [
        {
            "template_id": t["id"],
            "name": t.get("name"),
            "drift": template_drift(t.get("fields", []), columns),
        }
        for t in templates
    ]
    return {
        "import_id": import_id,
        "header_signature": signature,
        "matched": matched.get("id") if matched else None,
        "candidates": candidates,
    }


async def create_template(
    tenant_id: str, *, name: str, fields: list[dict], column_names: list[str]
) -> dict:
    from services.imports.analyzer import header_signature  # lazy
    from services.imports.mapping import validate_mapping_fields  # lazy

    coerced = _coerce_fields(fields)
    errors = validate_mapping_fields(coerced)
    if errors:
        raise BadRequestError("invalid template mapping: " + "; ".join(errors))
    signature = header_signature(column_names)
    return await get_imports_repository().create_template(
        tenant_id,
        name=name,
        header_signature=signature,
        fields=[f.model_dump(mode="json") for f in coerced],
    )


async def list_templates(tenant_id: str) -> list[dict]:
    return await get_imports_repository().list_templates(tenant_id)


async def delete_template(tenant_id: str, template_id: str) -> bool:
    return await get_imports_repository().delete_template(tenant_id, template_id)


async def validate_import(tenant_id: str, import_id: str) -> dict:
    """Dry-run the latest mapping against the uploaded rows; persist the result.

    On success moves to ``validated``; when the mapping touches
    governance-sensitive data (identifiers / governance facts / PII columns) it
    moves to ``review_required`` — an explicit approval is then needed before a
    (future) commit.
    """
    from services.imports.analyzer import read_rows  # lazy
    from services.imports.validation import validate_mapping  # lazy

    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    _ensure_not_terminal(session)
    mapping = await repo.get_latest_mapping(tenant_id, import_id)
    if mapping is None:
        raise BadRequestError("no mapping to validate — define a mapping first")
    schemas = await repo.list_schemas(tenant_id, import_id)
    if not schemas:
        raise BadRequestError("no analyzed schema — analyze the import first")

    fields = _coerce_fields(mapping.get("fields", []))
    storage = get_import_storage()
    from services.imports.analyzer import detect_format  # lazy

    # Program-spec lifecycle: the dry-run is VALIDATING. A transient failure
    # AFTER this transition (retrieval / parse / schema / validate_mapping /
    # save_validation) must not leave the session pinned in VALIDATING — the
    # FSM forbids a VALIDATING -> VALIDATING retry, which would permanently
    # wedge the import until the sweeper dead-letters it. Fall back to UPLOADED
    # (the re-validate entry — the FSM explicitly supports VALIDATING ->
    # UPLOADED) and record the reason for audit, so the job retry re-enters
    # VALIDATING legally instead of being rejected.
    await transition_session(
        repo, tenant_id, import_id, ImportSessionState.VALIDATING
    )

    try:
        # Aggregate rows + columns across files (single-file is the common case).
        all_rows: list[dict] = []
        all_columns = []
        for schema in schemas:
            profile = schema.get("profile", {})
            from services.imports.contracts import ColumnProfile

            all_columns.extend(ColumnProfile(**c) for c in profile.get("columns", []))
            file_id = schema.get("file_id")
            if not file_id:
                continue
            _meta, content = await storage.get_content(tenant_id, file_id)
            fmt = detect_format(_meta["filename"], _meta.get("content_type", ""), content)
            rows, _info = read_rows(content, fmt)
            all_rows.extend(rows[:MAX_VALIDATION_ROWS])

        result = validate_mapping(
            import_id=import_id,
            mapping_version=int(mapping.get("version", 1)),
            fields=fields,
            rows=all_rows,
            columns=all_columns,
        )
        result_dict = result.model_dump(mode="json")
        await repo.save_validation(tenant_id, import_id, result_dict)
    except Exception as exc:
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.UPLOADED,
            patch={
                "failure_reason": (
                    f"validation dry-run failed transiently: "
                    f"{type(exc).__name__}: {exc}"
                ),
            },
        )
        raise

    review_required, reasons = mapping_requires_review(fields, all_columns)
    schema_version = int(mapping.get("version", 1))
    # Failed validation is REJECTED (program spec) — never left sitting in
    # 'validated'/'review_required' as if it passed. Governance review is an
    # orthogonal signal: the session is VALIDATED but awaiting explicit
    # approval (legacy status stays review_required for the frontend).
    if not result_dict.get("ok", False):
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.REJECTED,
            legacy_status="review_required",
            patch={
                "failure_reason": (
                    f"validation failed: {result_dict.get('rows_invalid')} of "
                    f"{result_dict.get('rows_total')} rows invalid"
                ),
                "accepted_count": int(result_dict.get("rows_valid", 0) or 0),
                "rejected_count": int(result_dict.get("rows_invalid", 0) or 0),
                "duplicate_count": 0,
                "quarantine_count": 0,
                "schema_version": schema_version,
            },
        )
        next_status = "review_required"
    else:
        await transition_session(
            repo,
            tenant_id,
            import_id,
            ImportSessionState.VALIDATED,
            legacy_status="review_required" if review_required else "validated",
            patch={
                "accepted_count": int(result_dict.get("rows_valid", 0) or 0),
                "rejected_count": int(result_dict.get("rows_invalid", 0) or 0),
                "schema_version": schema_version,
            },
        )
        next_status = "review_required" if review_required else "validated"
    metrics.increment(
        "import_validated_total",
        labels={"ok": str(result_dict.get("ok", False)).lower()},
    )
    await _emit(
        "IMPORT_VALIDATED",
        tenant_id,
        {
            "import_id": import_id,
            "ok": result_dict.get("ok"),
            "rows_invalid": result_dict.get("rows_invalid"),
            "review_required": review_required,
        },
    )
    return {"status": next_status, "validation": result_dict, "review_reasons": reasons}


async def approve_import(
    tenant_id: str, import_id: str, *, approver: Optional[str] = None
) -> dict:
    """Approve a validated/review-required import for commit. Caller must have
    already enforced tenant-admin permission at the route layer."""
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    _ensure_not_terminal(session)
    status = session.get("status")
    if status not in {"validated", "review_required"}:
        raise ConflictError(
            f"import must be validated before approval (current: {status!r})"
        )
    # A REJECTED session projects 'review_required' for the frontend, but the
    # FSM is authoritative: it must be VALIDATED (not REJECTED) to approve.
    from services.card_linked_payments.import_session import lifecycle_state_of

    if lifecycle_state_of(session) is ImportSessionState.REJECTED:
        raise ConflictError("cannot approve: the latest validation did not pass")
    validation = await repo.get_latest_validation(tenant_id, import_id)
    if validation is None or not validation.get("ok", False):
        raise ConflictError("cannot approve: the latest validation did not pass")
    # Approval enters NORMALIZING (records ready to build / commit); the legacy
    # status stays 'approved' so the existing commit route + frontend keep
    # working.
    updated = await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.NORMALIZING,
        patch={"approved_by": approver},
    )
    metrics.increment("import_approved_total")
    return updated


async def cancel_import(tenant_id: str, import_id: str) -> dict:
    repo = get_imports_repository()
    session = await repo.get_session(tenant_id, import_id)
    if is_terminal_status(session.get("status", "")):
        raise ConflictError(
            f"import is already terminal ({session.get('status')!r})"
        )
    # The program FSM has no CANCELLED state — a cancelled session is a stopped
    # session, mapped to the ROLLED_BACK hard-stop (legacy status stays
    # 'cancelled' so the frontend's enum keeps parsing).
    updated = await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.ROLLED_BACK,
        legacy_status="cancelled",
    )
    metrics.increment("import_cancelled_total")
    return updated
