from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "Backend Architecture" / "aether-backend" / "alembic" / "versions" / "20260730_consent_control_plane_seed.py"

REQUIRED_TABLES = [
    "consent_receipt_history",
    "tenant_processing_profiles",
    "integration_policy_manifests",
    "detected_integrations",
    "connector_policy_decisions",
    "data_inventory_fields",
    "suppression_ledger",
    "webhook_quarantine",
    "privacy_action_outbox",
    "dsr_execution_steps",
]


def test_control_plane_migration_declares_required_tables_and_indexes():
    source = MIGRATION.read_text()
    assert "ALTER TABLE consent_receipts ADD COLUMN IF NOT EXISTS" in source
    for table in REQUIRED_TABLES:
        assert table in source
    for fragment in ("tenant_id", "idempotency_key", "subject_id", "anonymous_id", "provider", "purpose", "policy_version", "expires_at", "legal_hold"):
        assert fragment in source
    assert "UNIQUE (tenant_id, idempotency_key)" in source
    assert "DROP TABLE IF EXISTS" in source
    assert "raw_secret" not in source.lower()
    assert "secret TEXT" not in source
