"""Bridge the card-linked bulk import through the canonical import engine.

Rather than reimplement schema analysis / PII detection / dry-run validation /
lineage, the card-linked tenant import reuses ``services.imports``:

  * PII / sensitivity detection — ``services.imports.analyzer.analyze_bytes``
    profiles each column and flags pii / identifier / secret / governance
    columns;
  * dry-run validation — ``services.imports.validation.validate_mapping``
    replays a canonical card-linked field mapping over the rows and reports,
    deterministically, whether every required field is populated and every
    transform applies cleanly;
  * review-approval — ``mapping_requires_review`` decides whether the import
    needs a governance review before commit;
  * lineage — a per-batch lineage record (import id, mapping version, schema
    signature, validation summary, PII columns, review decision) is stamped
    onto every ingested flow so provenance is auditable.

Reconciliation against later provider events reuses the existing
``CardLinkedIngestionService._try_reconcile`` (wallet-hash + program match),
so an imported row upgrades to ``matched`` when a provider webhook later
corroborates it — no separate reconciler is added.

DEFERRED (noted, not silently dropped): full lifecycle wiring through
``services.imports.service`` (durable ImportSession rows, Bronze→Silver commit,
replay/rollback) is out of scope for this pass; the card-linked import path
here invokes the engine's *validation + PII + lineage* hooks only and persists
through the card-linked flow store. Row-level validation errors are surfaced in
lineage; blocked instrument PII is still hard-rejected upstream by
``_guard_pii`` before anything reaches this bridge.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from services.imports.analyzer import analyze_bytes, header_signature
from services.imports.contracts import FieldMapping, mapping_requires_review
from services.imports.validation import validate_mapping

# Canonical card-linked import mapping: source columns → import primitives.
# Only columns present in a row are validated; required fields drive dry-run
# validation. Kept deterministic and side-effect free.
CARD_LINKED_IMPORT_MAPPING: tuple[FieldMapping, ...] = (
    FieldMapping(source_column="card_program_id", primitive="entity",
                 target_field="external_id", required=True),
    FieldMapping(source_column="wallet_address_hash", primitive="identifier",
                 target_field="value", transform="trim"),
    FieldMapping(source_column="basis", primitive="action",
                 target_field="action_type", required=True),
    FieldMapping(source_column="occurred_at", primitive="action",
                 target_field="occurred_at", transform="to_timestamp"),
    FieldMapping(source_column="amount_usd", primitive="metric",
                 target_field="value", transform="to_number"),
)

CARD_LINKED_IMPORT_MAPPING_VERSION = 1


def _import_id(tenant_id: str, rows: list[dict[str, Any]]) -> str:
    """Deterministic import id from the tenant + the batch's row ids/shape."""
    seed = json.dumps(
        {"tenant": tenant_id, "ids": [str(r.get("id")) for r in rows], "n": len(rows)},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return "climp_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def build_import_lineage(tenant_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the card-linked rows through the import engine's PII + validation +
    review hooks and return a lineage record for the batch.

    Never raises on ordinary row-validation problems — those are reported in the
    lineage (``validation_ok`` / ``rows_invalid``) so the batch can proceed while
    the drift stays auditable. Only a genuinely un-analyzable payload propagates.
    """
    import_id = _import_id(tenant_id, rows)
    # Serialize the batch to JSON bytes so the canonical analyzer profiles it
    # exactly as it would a tenant-uploaded file (PII / sensitivity detection).
    payload = json.dumps(rows, default=str).encode("utf-8")
    schema = analyze_bytes(import_id, payload, filename="card_linked_import.json",
                           content_type="application/json")

    columns = list(schema.columns)
    fields = [fm for fm in CARD_LINKED_IMPORT_MAPPING
              if any(fm.source_column in r for r in rows)]

    # Dry-run validation over the materialized rows (deterministic).
    string_rows = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]
    validation = validate_mapping(
        import_id=import_id,
        mapping_version=CARD_LINKED_IMPORT_MAPPING_VERSION,
        fields=fields,
        rows=string_rows,
        columns=columns,
    )

    mapping_review, review_reasons = mapping_requires_review(fields, columns)
    pii_columns = sorted(
        c.name for c in columns
        if c.sensitivity in ("pii", "identifier", "secret", "governance")
    )
    # A governed card-linked import carries identity data — any detected PII /
    # identifier / secret / governance column (mapped or not) warrants human
    # review before the rows are trusted, so it is folded into the decision.
    if pii_columns:
        review_reasons = review_reasons + [
            f"sensitive column present: {name}" for name in pii_columns
        ]
    review_required = mapping_review or validation.governance_review_required or bool(pii_columns)

    return {
        "import_id": import_id,
        "engine": "services.imports",
        "mapping_version": CARD_LINKED_IMPORT_MAPPING_VERSION,
        "header_signature": header_signature([c.name for c in columns]),
        "schema_format": schema.format,
        "row_count": schema.row_count,
        "pii_columns": pii_columns,
        "column_sensitivity": {c.name: c.sensitivity for c in columns},
        "validation_ok": validation.ok,
        "rows_total": validation.rows_total,
        "rows_valid": validation.rows_valid,
        "rows_invalid": validation.rows_invalid,
        "review_required": review_required,
        "review_reasons": sorted(set(review_reasons) | set(validation.governance_reasons)),
        "validation_error_codes": sorted({e.code for e in validation.errors}),
        "source": "card_linked_import",
    }
