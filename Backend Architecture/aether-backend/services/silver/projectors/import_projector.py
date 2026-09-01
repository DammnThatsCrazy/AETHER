"""Silver projector for committed tenant imports.

Turns the canonical primitive records a commit stages into ``silver_import_facts``
— one row per ``(commit, file, row, primitive)``. Unlike the SDK-event projectors,
this one is invoked **inline** from the import commit (not via the
``SDK_EVENTS_VALIDATED`` dispatcher): the commit already holds every primitive
record, so no Bronze re-read is needed. The write is best-effort — Bronze is the
durable source of truth and a replay re-derives the facts — so a Silver hiccup
never fails a durable commit.
"""

from __future__ import annotations

from typing import Any, Optional

from services.silver.projectors.base import ProjectionResult

SILVER_IMPORT_TABLE = "silver_import_facts"


class ImportProjector:
    """Projects a commit's primitive records into ``silver_import_facts`` rows."""

    def project_records(
        self,
        *,
        tenant_id: str,
        commit_id: str,
        import_id: str,
        mapping_version: int,
        occurred_at: str,
        records: list[dict[str, Any]],
    ) -> ProjectionResult:
        rows: list[dict[str, Any]] = []
        for rec in records:
            file_id = rec.get("file_id") or ""
            row_index = rec.get("row")
            primitive = rec.get("primitive")
            # Unique per (commit, file, row, primitive); a replay uses a fresh
            # commit_id, so replays naturally get distinct keys (matching Bronze's
            # per-commit staging semantics) and never collide with the prior run.
            idem = f"{commit_id}:{file_id}:{row_index}:{primitive}"
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "source_event_id": idem,
                    "source_event_type": "import.committed",
                    "occurred_at": occurred_at,
                    "privacy_class": "behavioral",
                    "idempotency_key": idem,
                    "payload": rec.get("fields") or {},
                    "commit_id": commit_id,
                    "import_id": import_id,
                    "mapping_version": mapping_version,
                    "primitive": primitive,
                    "row_index": row_index,
                    "bronze_source_tag": commit_id,
                    "bronze_record_id": f"{file_id}:{row_index}",
                    # Reference-only IRRL context inherited from the source
                    # Bronze row. SilverFactWriter revalidates the signed
                    # decisions immediately before persistence.
                    "rights": rec.get("rights") or {},
                }
            )
        return ProjectionResult(table=SILVER_IMPORT_TABLE, rows=rows)


_projector: Optional[ImportProjector] = None


def get_import_projector() -> ImportProjector:
    global _projector
    if _projector is None:
        _projector = ImportProjector()
    return _projector
