"""Unit tests: Bronze provenance and Silver promotion policy gate."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

import repositories.repos as repos
from repositories.lake import (
    BronzeRepository,
    ProvenanceStatus,
    SilverRepository,
    _compute_provenance_status,
    _compute_quarantine_status,
    make_raw_record,
)


def test_make_raw_record_includes_provenance_fields():
    rec = make_raw_record(
        source="dune_api",
        source_tag="dune_api_2024",
        provider_record_id="tx_001",
        payload={"block": 1},
        license_status="valid",
        terms_status="approved",
        olympus_owned_source=True,
        source_manifest_id="manifest_dune_api",
    )
    assert "provenance_status" in rec
    assert "quarantine_status" in rec
    assert "raw_payload_hash" in rec
    assert "license_status" in rec
    assert rec["olympus_owned_source"] is True
    assert rec["source_manifest_id"] == "manifest_dune_api"


def test_valid_license_no_quarantine():
    rec = make_raw_record(
        source="dune_api",
        source_tag="tag",
        provider_record_id="tx_001",
        payload={},
        license_status="valid",
        terms_status="approved",
    )
    assert rec["quarantine_status"] == "not_quarantined"
    assert rec["provenance_status"] == ProvenanceStatus.VALID.value


def test_missing_license_quarantined():
    rec = make_raw_record(
        source="unknown_source",
        source_tag="tag",
        provider_record_id="tx_002",
        payload={},
        license_status="unknown",
        terms_status="unknown",
    )
    assert rec["quarantine_status"] == "quarantined"
    assert rec["provenance_status"] == ProvenanceStatus.MISSING_LICENSE.value


def test_pending_review_license_quarantined():
    rec = make_raw_record(
        source="test_source",
        source_tag="tag",
        provider_record_id="tx_003",
        payload={},
        license_status="pending_review",
        terms_status="pending_review",
    )
    assert rec["quarantine_status"] == "quarantined"


def test_compute_provenance_missing_source_id():
    status = _compute_provenance_status(
        license_status="valid",
        terms_status="approved",
        provider_record_id="",
    )
    assert status == ProvenanceStatus.MISSING_SOURCE_ID


def test_compute_quarantine_status_quarantined():
    q = _compute_quarantine_status(ProvenanceStatus.MISSING_LICENSE, "unknown")
    assert q == "quarantined"


def test_compute_quarantine_status_not_quarantined():
    q = _compute_quarantine_status(ProvenanceStatus.VALID, "valid")
    assert q == "not_quarantined"


def test_silver_promotion_blocked_for_quarantined():
    quarantined_bronze = {
        "quarantine_status": "quarantined",
        "provenance_status": ProvenanceStatus.MISSING_LICENSE.value,
    }
    eligible, reason = SilverRepository.check_promotion_eligibility(quarantined_bronze)
    assert eligible is False
    assert "quarantined" in reason


def test_silver_promotion_blocked_for_unverified():
    unverified_bronze = {
        "quarantine_status": "not_quarantined",  # would pass first check
        "provenance_status": ProvenanceStatus.UNVERIFIED.value,
    }
    eligible, reason = SilverRepository.check_promotion_eligibility(unverified_bronze)
    assert eligible is False
    assert "provenance_not_valid" in reason


def test_silver_promotion_allowed_for_valid():
    valid_bronze = {
        "quarantine_status": "not_quarantined",
        "provenance_status": ProvenanceStatus.VALID.value,
    }
    eligible, reason = SilverRepository.check_promotion_eligibility(valid_bronze)
    assert eligible is True
    assert reason == "eligible"


def test_raw_payload_hash_is_deterministic():
    payload = {"block": 12345, "tx": "0xabc"}
    rec1 = make_raw_record("s", "t", "id", payload)
    rec2 = make_raw_record("s", "t", "id", payload)
    assert rec1["raw_payload_hash"] == rec2["raw_payload_hash"]


async def _provider_bronze_row(monkeypatch, *, confirmed_signal_ids=None):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repository = BronzeRepository("provider_records")
    record_id = f"provider-record-{uuid4().hex}"
    row = {
        "id": record_id,
        "source": "shopify.admin.orders_read",
        "source_tag": "provider:shopify:tenant-1",
        "provider_record_id": "order-1",
        "schema_version": "2",
        "idempotency_key": f"idem-{uuid4().hex}",
        "tenant_id": "tenant-1",
        "provenance_status": ProvenanceStatus.MISSING_LICENSE.value,
        "license_status": "unknown",
        "terms_status": "unknown",
        "quarantine_status": "quarantined",
        "payload": {
            "record_id": "order-1",
            "tenant_id": "tenant-1",
            "provider_identity": "shopify.admin.orders_read",
            "metadata": {"rights_decision_ref": "rdec_original"},
            "payload": {"order_id": "order-1", "total": "12.50"},
        },
    }
    if confirmed_signal_ids is not None:
        row["payload"]["metadata"]["confirmed_signal_ids"] = confirmed_signal_ids
    stored = await repository.insert(record_id, row)
    return repository, stored


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("provenance_status",), ProvenanceStatus.VALID.value),
        (("quarantine_status",), "not_quarantined"),
        (("license_status",), "valid"),
        (("payload", "metadata", "rights_decision_ref"), "rdec_forged"),
    ],
)
async def test_provider_records_reject_provenance_and_rights_marker_edits(monkeypatch, path, value):
    repository, row = await _provider_bronze_row(monkeypatch)
    edited = deepcopy(row)
    target = edited
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValueError, match="immutable"):
        await repository.update(row["id"], edited)

    persisted = await repository.find_by_id(row["id"])
    assert persisted["provenance_status"] == ProvenanceStatus.MISSING_LICENSE.value
    assert persisted["quarantine_status"] == "quarantined"
    assert persisted["payload"]["metadata"]["rights_decision_ref"] == "rdec_original"


@pytest.mark.asyncio
async def test_provider_records_reject_raw_payload_edits(monkeypatch):
    repository, row = await _provider_bronze_row(monkeypatch)
    edited = deepcopy(row)
    edited["payload"]["payload"]["total"] = "0.01"

    with pytest.raises(ValueError, match="immutable"):
        await repository.update(row["id"], edited)

    persisted = await repository.find_by_id(row["id"])
    assert persisted["payload"]["payload"]["total"] == "12.50"


@pytest.mark.asyncio
async def test_provider_records_allow_confirmation_id_append(monkeypatch):
    repository, row = await _provider_bronze_row(monkeypatch)
    updated = deepcopy(row)
    updated["payload"]["metadata"]["confirmed_signal_ids"] = ["signal-1"]

    persisted = await repository.update(row["id"], updated)

    assert persisted["payload"]["metadata"]["confirmed_signal_ids"] == ["signal-1"]
    assert persisted["payload"]["payload"] == row["payload"]["payload"]
    assert persisted["provenance_status"] == row["provenance_status"]
    assert persisted["quarantine_status"] == row["quarantine_status"]


@pytest.mark.asyncio
async def test_provider_records_reject_confirmation_id_removal(monkeypatch):
    repository, row = await _provider_bronze_row(
        monkeypatch, confirmed_signal_ids=["signal-1", "signal-2"]
    )
    updated = deepcopy(row)
    updated["payload"]["metadata"]["confirmed_signal_ids"] = ["signal-2"]

    with pytest.raises(ValueError, match="only be appended"):
        await repository.update(row["id"], updated)


@pytest.mark.asyncio
async def test_provider_record_update_guard_does_not_change_other_bronze_domains(
    monkeypatch,
):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repository = BronzeRepository("sdk_events")
    record_id = f"sdk-event-{uuid4().hex}"
    row = await repository.insert(
        record_id,
        {"payload": {"event": "before"}, "tenant_id": "tenant-1"},
    )
    edited = deepcopy(row)
    edited["payload"]["event"] = "after"

    updated = await repository.update(record_id, edited)

    assert updated["payload"]["event"] == "after"
