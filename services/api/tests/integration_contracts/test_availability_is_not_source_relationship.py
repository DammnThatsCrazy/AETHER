"""Availability flags say where a capability may be provisioned, never who owns data."""

from __future__ import annotations

from pathlib import Path

from connectors.provider_runtime.manifest_service import manifest_service

BACKEND = Path(__file__).resolve().parents[2]
SOURCE_AUTHORITY_FILES = (
    "shared/integration_contracts/source_relationship.py",
    "connectors/provider_runtime/rights_admission.py",
    "connectors/integrations/data_rights/service.py",
    "ingestion/imports/rights_admission.py",
)

# Capabilities certified for Olympus-system provisioning. Adding one requires
# certification evidence; it still never implies source_relationship=olympus_source.
CERTIFIED_OLYMPUS_SYSTEM: frozenset[str] = frozenset()


def test_olympus_system_availability_requires_certification():
    claimed = {
        identity
        for identity, manifest in manifest_service.merged_manifests().items()
        if manifest.availability.olympus_system
    }
    assert claimed <= CERTIFIED_OLYMPUS_SYSTEM, sorted(claimed - CERTIFIED_OLYMPUS_SYSTEM)


def test_source_authority_never_reads_availability_flags():
    for relative in SOURCE_AUTHORITY_FILES:
        text = (BACKEND / relative).read_text(encoding="utf-8")
        for flag in ("olympus_system", "kyber_managed", "tenant_self_service"):
            assert flag not in text, f"{relative} derives authority from {flag}"
