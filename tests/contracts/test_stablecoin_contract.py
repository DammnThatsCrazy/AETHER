"""Contract test: stablecoin.ts types are exported from shared and meet invariants."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_INDEX = ROOT / "packages" / "shared" / "index.ts"
STABLECOIN_TS = ROOT / "packages" / "shared" / "stablecoin.ts"


def test_stablecoin_exported_from_shared_barrel():
    index_text = SHARED_INDEX.read_text(encoding="utf-8")
    assert "export * from './stablecoin'" in index_text or 'export * from "./stablecoin"' in index_text, (
        "packages/shared/index.ts must re-export from './stablecoin'"
    )


def test_stablecoin_schema_version_constant():
    text = STABLECOIN_TS.read_text(encoding="utf-8")
    assert "STABLECOIN_SCHEMA_VERSION = 'stablecoin.intelligence.v1'" in text or \
           'STABLECOIN_SCHEMA_VERSION = "stablecoin.intelligence.v1"' in text, (
        "STABLECOIN_SCHEMA_VERSION must equal 'stablecoin.intelligence.v1'"
    )


def test_stablecoin_observation_contract_has_required_fields():
    text = STABLECOIN_TS.read_text(encoding="utf-8")
    required_fields = [
        "observation_id", "tenant_id", "schema_version", "source_record_id",
        "source_execution_id", "observed_at", "chain_id", "network",
        "transaction_hash", "finality_status", "event_type",
        "deployment_id", "canonical_asset_id", "amount_atomic",
    ]
    for field in required_fields:
        assert f"{field}:" in text, (
            f"StablecoinObservationContract must include field '{field}'"
        )


def test_execution_by_aether_absent_from_stablecoin_contract():
    text = STABLECOIN_TS.read_text(encoding="utf-8")
    assert "execution_by_aether" not in text, (
        "execution_by_aether must never appear in stablecoin contract — Aether observes, never executes"
    )
