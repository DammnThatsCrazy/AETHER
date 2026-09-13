"""DB-free contract tests for the Data Exchange Plane (M0).

The Data Exchange contracts are pure vocabulary + pydantic models with no
repository, route, or job dependencies, so these tests import them directly.
They pin the invariants that M1–M5 build on: explicit directions, an explicit
(never byte-inferred) artifact status vocabulary, day-one ingress formats,
and the sealed-by-default classification set.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.data_exchange import contracts as c


def _artifact(**overrides: object) -> c.DataArtifactContract:
    base: dict[str, object] = {
        "artifact_id": "art_1",
        "tenant_id": "tnt_1",
        "direction": "ingress",
        "artifact_type": "import_source",
        "object_key": "tenant/tnt_1/data-exchange/ingress/2026/09/art_1/f.csv",
        "filename": "f.csv",
        "format": "csv",
        "content_type": "text/csv",
        "size_bytes": 12,
        "sha256": "a" * 64,
        "classification": "none",
        "status": "uploaded",
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return c.DataArtifactContract(**base)


def test_directions_are_ingress_and_egress_only() -> None:
    assert set(c.DATA_EXCHANGE_DIRECTIONS) == {"ingress", "egress"}


def test_artifact_statuses_are_explicit_and_terminal_subset() -> None:
    assert "available" in c.DATA_ARTIFACT_STATUSES
    assert "committed" in c.DATA_ARTIFACT_STATUSES
    assert "draft" not in c.DATA_ARTIFACT_STATUSES  # no implicit-by-bytes states
    assert set(c.DATA_ARTIFACT_TERMINAL_STATUSES) <= set(c.DATA_ARTIFACT_STATUSES)


def test_ingress_and_egress_format_vocabularies_are_distinct() -> None:
    assert "jsonl" in c.DATA_EXCHANGE_INGRESS_FORMATS
    assert "jsonl" not in c.DATA_EXCHANGE_EGRESS_FORMATS
    assert "ndjson" in c.DATA_EXCHANGE_EGRESS_FORMATS
    assert "ndjson" not in c.DATA_EXCHANGE_INGRESS_FORMATS
    assert "parquet" in c.DATA_EXCHANGE_INGRESS_FORMATS
    assert "parquet" in c.DATA_EXCHANGE_EGRESS_FORMATS


def test_classification_blocklist_is_valid_and_sealed() -> None:
    assert set(c.DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS) <= set(
        c.DATA_EXCHANGE_CLASSIFICATIONS
    )
    assert "secret" in c.DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS
    assert "credential" in c.DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS


def test_artifact_requires_tenant_and_object_key() -> None:
    with pytest.raises(ValidationError):
        _artifact(tenant_id="")  # empty tenant rejected
    with pytest.raises(ValidationError):
        _artifact(object_key="")  # empty object key rejected


def test_artifact_accepts_valid_ingress_and_egress() -> None:
    ingress = _artifact(direction="ingress", artifact_type="import_source")
    assert ingress.direction == "ingress"
    assert ingress.tenant_id == "tnt_1"
    egress = _artifact(
        direction="egress",
        artifact_type="export",
        object_key="tenant/tnt_1/data-exchange/egress/2026/09/art_1/e.parquet",
        filename="e.parquet",
        format="parquet",
        content_type="application/vnd.apache.parquet",
    )
    assert egress.direction == "egress"


def test_day_one_source_type_is_file() -> None:
    source = c.ImportSourceContract(
        import_id="imp_1",
        tenant_id="tnt_1",
        source_type="file",
        artifact_id="art_1",
        format="csv",
    )
    assert source.source_type == "file"
    assert source.ownership == "unknown"
    assert "s3" in c.DATA_EXCHANGE_SOURCE_TYPES  # future source, already modeled


def test_export_format_rejects_pdf() -> None:
    with pytest.raises(ValidationError):
        c.ExportSpecContract(
            export_id="exp_1",
            tenant_id="tnt_1",
            resource="profile360",
            format="pdf",  # type: ignore[arg-type]  # PDF is a report, not a format
        )


def test_report_contract_has_no_structured_format_field() -> None:
    report = c.ReportSpecContract(
        report_id="rep_1",
        tenant_id="tnt_1",
        resource="profile360",
        template="standard",
    )
    assert report.report_id == "rep_1"
    assert not hasattr(report, "format")  # PDF never enters EgressFormat


def test_mapping_contract_pins_a_version() -> None:
    with pytest.raises(ValidationError):
        c.ImportMappingContract(import_id="imp_1", tenant_id="tnt_1", version=0)
