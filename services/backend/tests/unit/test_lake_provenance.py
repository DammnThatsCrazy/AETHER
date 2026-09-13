"""Unit tests: Bronze provenance and Silver promotion policy gate."""
from __future__ import annotations

import pytest

from repositories.lake import (
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
