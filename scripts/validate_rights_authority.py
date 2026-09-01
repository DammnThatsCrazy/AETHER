#!/usr/bin/env python3
"""Validate the canonical IRRL authority and enforcement spine.

This is intentionally a small static gate. Runtime tests prove behavior for
the authority and representative PEPs; this gate prevents a later refactor
from silently removing the durable registry, migration chain, or a protected
materialization boundary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

REQUIRED_FILES = (
    "packages/shared/contracts/rights-authority-registry.json",
    "packages/shared/contracts/rights-authority.schema.json",
    "packages/shared/contracts/rights-transform-registry.json",
    "packages/shared/contracts/rights-activation-profile-registry.json",
    "packages/shared/rights-authority.ts",
    "Backend Architecture/aether-backend/shared/rights_authority/generated_registry.py",
    "Backend Architecture/aether-backend/shared/rights_authority/contracts.py",
    "Backend Architecture/aether-backend/shared/rights_authority/repository.py",
    "Backend Architecture/aether-backend/shared/rights_authority/service.py",
    "Backend Architecture/aether-backend/shared/rights_authority/pep.py",
    "Backend Architecture/aether-backend/shared/rights_authority/remediation.py",
    "Backend Architecture/aether-backend/shared/rights_authority/reconciliation.py",
    "Backend Architecture/aether-backend/services/ingestion/rights.py",
    "Backend Architecture/aether-backend/services/olympus/gateway.py",
    "Backend Architecture/aether-backend/services/rights_authority_worker.py",
    "Backend Architecture/aether-backend/alembic/versions/20260903_irrl_rights_authority.py",
    "Backend Architecture/aether-backend/alembic/versions/20260904_graph_rights_columns.py",
    "Backend Architecture/aether-backend/alembic/versions/20260905_olympus_rights_promotion.py",
    "Backend Architecture/aether-backend/alembic/versions/20260906_irrl_evidence_remediation.py",
    "Backend Architecture/aether-backend/alembic/versions/20260907_irrl_audit_outbox.py",
)

WIRED_FILES = {
    "Backend Architecture/aether-backend/services/ingestion/batch.py": ("authorize_ingestion",),
    "Backend Architecture/aether-backend/repositories/lake.py": ("_require_rights_context",),
    "Backend Architecture/aether-backend/services/model_governance/training_gate.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/shared/graph/mutation_gateway.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/services/exploration/service.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/services/export/service.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/services/profile/routes.py": ("_RightsProfileRoute",),
    "Backend Architecture/aether-backend/services/kyber/graph/scoped_gateway.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/services/operational_intelligence/routes.py": ("_RightsGraphRoute",),
    "Backend Architecture/aether-backend/services/ml_serving/routes.py": ("evaluate_rights",),
    "Backend Architecture/aether-backend/services/olympus/gateway.py": ("evaluate_rights", "kill_switch"),
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required IRRL file: {rel}")

    try:
        authority = json.loads(_read("packages/shared/contracts/rights-authority-registry.json"))
        transforms = json.loads(_read("packages/shared/contracts/rights-transform-registry.json"))
        profiles = json.loads(_read("packages/shared/contracts/rights-activation-profile-registry.json"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"canonical rights registry is unreadable: {exc}")
        authority = transforms = profiles = {}

    action_ids = {entry.get("id") for entry in authority.get("actions", [])}
    if len(action_ids) != len(authority.get("actions", [])) or None in action_ids:
        errors.append("rights-authority-registry actions must have unique ids")
    if not action_ids:
        errors.append("rights-authority-registry must declare actions")
    transform_ids = {entry.get("id") for entry in transforms.get("transforms", [])}
    if len(transform_ids) != len(transforms.get("transforms", [])) or None in transform_ids:
        errors.append("rights-transform-registry transforms must have unique ids")
    profile_ids = {entry.get("id") for entry in profiles.get("profiles", [])}
    if len(profile_ids) != len(profiles.get("profiles", [])) or None in profile_ids:
        errors.append("rights-activation-profile-registry profiles must have unique ids")

    repository = _read("Backend Architecture/aether-backend/shared/rights_authority/repository.py")
    for table in (
        "irrl_policy_sets", "irrl_artifact_rights_envelopes", "irrl_rights_decisions",
        "irrl_derivation_edges", "irrl_impact_graphs", "irrl_revocations",
        "irrl_source_grants", "irrl_evidence_manifests", "irrl_remediation_steps",
        "irrl_remediation_receipts",
        "irrl_rights_audit_outbox",
    ):
        if table not in repository:
            errors.append(f"IRRL repository is missing durable table mapping: {table}")

    service = _read("Backend Architecture/aether-backend/shared/rights_authority/service.py")
    for token in ("_finalize", "verify_signature", "lineage_hash", "audit_ledger", "signature_key_id"):
        if token not in service:
            errors.append(f"IRRL authority must retain {token}")

    for rel, tokens in WIRED_FILES.items():
        try:
            text = _read(rel)
        except OSError:
            continue
        for token in tokens:
            if token not in text:
                errors.append(f"protected path lost rights wiring {token!r}: {rel}")

    allowlist = ROOT / "scripts/allowlists/graph_write_paths.json"
    try:
        if json.loads(allowlist.read_text(encoding="utf-8")):
            errors.append("graph direct-writer allowlist must remain empty after gateway migration")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"graph writer allowlist is unreadable: {exc}")

    migrations = [
        "20260903_irrl_rights_authority.py",
        "20260904_graph_rights_columns.py",
        "20260905_olympus_rights_promotion.py",
        "20260906_irrl_evidence_remediation.py",
        "20260907_irrl_audit_outbox.py",
    ]
    previous = "20260902_graph_pg_backend"
    for name in migrations:
        text = _read(f"Backend Architecture/aether-backend/alembic/versions/{name}")
        expected = f'down_revision = "{previous}"'
        if expected not in text:
            errors.append(f"migration {name} must continue from {previous}")
        previous = name.removesuffix(".py")

    if errors:
        print("rights authority validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(
        "rights authority validation OK: durable IRRL, evidence/remediation, "
        "and protected PEP wiring present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
