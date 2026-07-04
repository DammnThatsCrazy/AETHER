"""Generic CSV/JSON/NDJSON import connector for tenant-provided derivatives records."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Mapping

from services.derivatives.models import BronzeObservation, DerivativesValidationError, decimal_from_provider


@dataclass(frozen=True)
class ImportRowError:
    row_number: int
    reason: str
    raw_row: Mapping[str, Any]


@dataclass(frozen=True)
class ImportReport:
    batch_id: str
    accepted_rows: int
    quarantined_rows: int
    observations: list[BronzeObservation] = field(default_factory=list)
    row_errors: list[ImportRowError] = field(default_factory=list)


_REQUIRED_FILL_FIELDS = {"source_record_id", "account", "market", "side", "price", "quantity", "executed_at"}


def parse_import_payload(
    *,
    tenant_id: str,
    provider: str,
    deployment: str,
    batch_id: str,
    payload: str,
    content_type: str,
    mapping_version: str,
    dry_run: bool = False,
) -> ImportReport:
    rows = _load_rows(payload, content_type)
    observations: list[BronzeObservation] = []
    errors: list[ImportRowError] = []
    for idx, row in enumerate(rows, start=1):
        try:
            observations.append(_row_to_bronze(tenant_id, provider, deployment, batch_id, row, mapping_version))
        except DerivativesValidationError as exc:
            errors.append(ImportRowError(row_number=idx, reason=str(exc), raw_row=row))
    if dry_run:
        observations = []
    return ImportReport(
        batch_id=batch_id,
        accepted_rows=len(rows) - len(errors),
        quarantined_rows=len(errors),
        observations=observations,
        row_errors=errors,
    )


def _load_rows(payload: str, content_type: str) -> list[dict[str, Any]]:
    normalized = content_type.lower()
    if normalized in {"application/x-ndjson", "application/ndjson", "ndjson"}:
        return [json.loads(line) for line in payload.splitlines() if line.strip()]
    if normalized in {"application/json", "json"}:
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            return [dict(row) for row in parsed]
        if isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
            return [dict(row) for row in parsed["rows"]]
        raise DerivativesValidationError("json import must be a list or object with rows")
    if normalized in {"text/csv", "csv"}:
        return [dict(row) for row in csv.DictReader(StringIO(payload))]
    raise DerivativesValidationError(f"unsupported import content type {content_type}")


def _row_to_bronze(
    tenant_id: str,
    provider: str,
    deployment: str,
    batch_id: str,
    row: Mapping[str, Any],
    mapping_version: str,
) -> BronzeObservation:
    missing = sorted(field for field in _REQUIRED_FILL_FIELDS if not row.get(field))
    if missing:
        raise DerivativesValidationError(f"missing required fields: {', '.join(missing)}")
    decimal_from_provider(row["price"], "price")
    decimal_from_provider(row["quantity"], "quantity")
    source_record_id = str(row["source_record_id"])
    account = str(row["account"])
    raw_payload = dict(row)
    raw_payload["mapping_version"] = mapping_version
    raw_payload["batch_id"] = batch_id
    return BronzeObservation(
        tenant_id=tenant_id,
        provider=provider,
        deployment=deployment,
        record_type="raw_fill",
        source_record_id=source_record_id,
        raw_payload=raw_payload,
        observed_at=str(row["executed_at"]),
        idempotency_key=":".join([tenant_id, provider, deployment, account, batch_id, source_record_id]),
    )
