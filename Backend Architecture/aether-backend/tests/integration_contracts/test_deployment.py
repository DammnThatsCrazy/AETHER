"""Deployment contract: the real credential_platform entry loads and validates."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared.integration_contracts.deployment import (
    DeploymentContract,
    DeploymentContractError,
    load_capability,
)

_REL = Path("docs") / "integration-control-plane" / "DEPLOYMENT_CONTRACT.yaml"


def _find_contract_file() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _REL
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"could not locate {_REL} above {__file__}")


def _load_capabilities() -> dict:
    with _find_contract_file().open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return doc["capabilities"]


def test_credential_platform_entry_loads_and_validates() -> None:
    entry = _load_capabilities()["credential_platform"]
    contract = load_capability(entry)
    assert isinstance(contract, DeploymentContract)
    assert contract.application_code_ready is True
    assert "postgres" in contract.required_services
    assert "AETHER_CREDENTIAL_BACKEND" in contract.required_secrets
    assert contract.required_public_urls == []
    assert contract.provider_registration_steps == []
    assert len(contract.deployment_blockers) == 2
    assert contract.migration is not None
    assert "alembic upgrade head" in contract.migration


def test_all_capability_entries_load() -> None:
    for name, entry in _load_capabilities().items():
        contract = load_capability(entry)
        assert isinstance(contract, DeploymentContract), name


def test_minimal_entry_defaults() -> None:
    contract = load_capability({"application_code_ready": False})
    assert contract.application_code_ready is False
    assert contract.required_services == []
    assert contract.migration is None


def test_invalid_entries_rejected() -> None:
    with pytest.raises(DeploymentContractError):
        load_capability({})  # missing application_code_ready
    with pytest.raises(DeploymentContractError):
        load_capability({"application_code_ready": True, "surprise": 1})  # extra key
    with pytest.raises(DeploymentContractError):
        load_capability(["not", "a", "mapping"])  # type: ignore[arg-type]
