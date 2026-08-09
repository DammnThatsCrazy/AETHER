#!/usr/bin/env python3
"""Credential-Turnkey Evidence Bundle generator (program sec30.C).

Builds a checksummed, machine-readable evidence bundle that aggregates the
repo's canonical registries into one deterministic JSON manifest. It is the
single evidence artifact a credential-turnkey reviewer can verify against
source: every section is derived from a committed registry (never from live
state), every aggregated source file carries a SHA-256 checksum, and the
manifest is sealed with a SHA-256 root checksum.

Determinism contract (asserted by tests/unit/test_evidence_bundle.py):

* No timestamps, no randomness, no environment values are embedded. Two runs in
  the same checkout produce byte-identical output and an identical root
  checksum. All keys and lists are sorted before serialization.
* The root checksum is computed over the canonical serialization of the full
  manifest with the ``root_checksum`` block removed:
  ``sha256(utf8(json.dumps(document, sort_keys=True, separators=(',', ':'))))``.
* Environment-controlled evidence (pass/fail test counts, ``terraform
  validate/plan/apply``, live provider credential validation) is recorded
  explicitly as ``pending`` — never fabricated.

Sections (REQUIRED_SECTIONS): manifests, certification, test_suites,
fault_tests, migration_state, worker_topology, infrastructure_validation,
entitlement_registry, meter_registry, storage_policies, readiness_state.

Output: ``release-evidence/credential-turnkey-evidence-bundle-<phase>.json``
(default phase ``pre-staging``; timestamp-free, deterministic).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

BUNDLE_NAME = "credential-turnkey-evidence-bundle"
SCHEMA_VERSION = 1
PROGRAM_REF = "sec30.C"
DEFAULT_PHASE = "pre-staging"

# Every section the bundle must capture. The generator fails loudly if a
# section's aggregator is missing; the tests fail if a required section is
# absent from the produced manifest.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "manifests",
    "certification",
    "test_suites",
    "fault_tests",
    "migration_state",
    "worker_topology",
    "infrastructure_validation",
    "entitlement_registry",
    "meter_registry",
    "storage_policies",
    "readiness_state",
)


# ── primitives ──────────────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    return _sha256_bytes(path.read_bytes())


def _rel(path: Path) -> str:
    """Repo-root-relative POSIX path (stable across hosts)."""
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _canonical_json(obj: Any) -> bytes:
    """Deterministic byte serialization: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _json_safe(value: Any) -> Any:
    """Normalize enums / Decimals / pydantic models / sets into JSON primitives.

    Lists and sets are sorted deterministically (a set has no natural order; a
    list is sorted only when it is genuinely unordered — callers that care about
    list order sort explicitly before handing data to this helper).
    """
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        items = [_json_safe(v) for v in value]
        return sorted(items, key=lambda x: _canonical_json(x).decode("utf-8"))
    if hasattr(value, "model_dump"):  # pydantic BaseModel
        return _json_safe(value.model_dump())
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text())


def _migration_literals(source: str) -> tuple[Any, Any]:
    """Extract ``revision`` / ``down_revision`` literals via AST (no imports).

    Alembic version modules import application models, so they must never be
    imported at evidence-build time. AST parsing reads only the two revision
    assignments; ``down_revision`` may be ``None``, a string, or a tuple
    (a merge head).
    """
    tree = ast.parse(source)
    revision = down_revision = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "revision":
            try:
                revision = ast.literal_eval(node.value)
            except Exception:  # pragma: no cover - defensive
                revision = None
        elif target.id == "down_revision":
            try:
                down_revision = ast.literal_eval(node.value)
            except Exception:  # pragma: no cover - defensive
                down_revision = None
    return revision, down_revision


# ── section aggregators ────────────────────────────────────────────────────
# Each returns (data, source_files) where source_files are repo-root-relative
# paths that must appear in the top-level ``file_checksums`` map.


def _aggregate_manifests() -> tuple[dict[str, Any], list[str]]:
    from shared.integration_contracts import catalog

    manifests = list(catalog.build_connector_manifests()) + list(
        catalog.build_payment_rail_manifests()
    )
    records: list[dict[str, Any]] = []
    for manifest in manifests:
        d = manifest.model_dump()
        readiness = d.get("readiness") or {}
        records.append(
            {
                "provider_family": d["provider_family"],
                "product_id": d["product_id"],
                "capability_id": d["capability_id"],
                "display_name": d["display_name"],
                "category": d["category"],
                "readiness_state": _json_safe(readiness.get("state")),
                "certification_state": _json_safe(d.get("certification_state")),
                "data_outputs": sorted(d.get("data_outputs") or []),
                "product_destinations": sorted(d.get("product_destinations") or []),
            }
        )
    records.sort(key=lambda r: (r["provider_family"], r["product_id"], r["capability_id"]))

    by_family: dict[str, int] = {}
    for r in records:
        by_family[r["provider_family"]] = by_family.get(r["provider_family"], 0) + 1

    sources = sorted(
        _rel(f) for f in (BACKEND_ROOT / "shared" / "integration_contracts").glob("*.py")
    )
    return (
        {
            "manifest_count": len(records),
            "family_count": len(by_family),
            "by_family": dict(sorted(by_family.items())),
            "manifests": records,
        },
        sources,
    )


def _aggregate_certification() -> tuple[dict[str, Any], list[str]]:
    from shared.certification.registry import build_capability_matrix

    matrix = _json_safe(build_capability_matrix())

    cert_dir = REPO_ROOT / "release-evidence" / "profile"
    certificates: list[dict[str, Any]] = []
    for f in sorted(cert_dir.glob("*.json")):
        doc = json.loads(f.read_text())
        certificates.append(
            {
                "file": _rel(f),
                "sha256": sha256_file(f),
                "profile": doc.get("profile"),
                "readiness_state": doc.get("readiness_state"),
                "conclusion": doc.get("conclusion"),
                "deployable": doc.get("deployable"),
            }
        )

    sources = sorted(
        _rel(f)
        for f in list((BACKEND_ROOT / "shared" / "certification").glob("*.py"))
        + list(cert_dir.glob("*.json"))
    )
    return (
        {
            "capability_matrix": matrix,
            "provider_count": matrix["summary"]["total"],
            "certificate_count": len(certificates),
            "certificates": certificates,
        },
        sources,
    )


def _aggregate_test_suites() -> tuple[dict[str, Any], list[str]]:
    path = REPO_ROOT / "config" / "test_suites.yaml"
    doc = _load_yaml(path)
    suites = doc.get("suites", [])
    records = [
        {
            "id": s.get("id"),
            "subsystem": s.get("subsystem"),
            "paths": sorted(s.get("paths") or []),
            "runner": list(s.get("runner") or []),
            "environments": sorted(s.get("environments") or []),
            "skip_policy": s.get("skip_policy"),
            "release_class": s.get("release_class"),
        }
        for s in suites
    ]
    records.sort(key=lambda r: (r["id"] or ""))
    schema = REPO_ROOT / "config" / "test_suites.schema.json"
    return (
        {
            "schema_version": doc.get("schema_version"),
            "suite_count": len(records),
            # Pass/fail counts are produced by a CI/local pytest run — recorded
            # explicitly as pending environment-controlled evidence.
            "execution_status": "pending_environment_controlled",
            "suites": records,
        },
        [_rel(path), _rel(schema)],
    )


def _aggregate_fault_tests() -> tuple[dict[str, Any], list[str]]:
    fault_dir = BACKEND_ROOT / "tests" / "faults"
    files: list[dict[str, Any]] = []
    for f in sorted(fault_dir.glob("*.py")):
        files.append(
            {
                "file": _rel(f),
                "sha256": sha256_file(f),
                "lines": f.read_text().count("\n"),
            }
        )
    faultkit = BACKEND_ROOT / "tests" / "adversarial" / "faultkit.py"
    faultkit_record = (
        {"file": _rel(faultkit), "sha256": sha256_file(faultkit)} if faultkit.exists() else None
    )
    sources = [r["file"] for r in files]
    if faultkit_record:
        sources.append(faultkit_record["file"])
    return (
        {
            "fault_test_file_count": len(files),
            "fault_test_files": files,
            "faultkit": faultkit_record,
        },
        sorted(sources),
    )


def _aggregate_migration_state() -> tuple[dict[str, Any], list[str]]:
    versions_dir = BACKEND_ROOT / "alembic" / "versions"
    revisions: dict[str, str] = {}
    file_records: list[dict[str, Any]] = []
    for f in sorted(versions_dir.glob("*.py")):
        revision, down_revision = _migration_literals(f.read_text())
        if revision:
            revisions[str(revision)] = f.name
        file_records.append(
            {
                "file": _rel(f),
                "revision": revision,
                "down_revision": _json_safe(down_revision),
                "sha256": sha256_file(f),
            }
        )

    # Every revision that appears as someone's down_revision is not a head.
    referenced: set[str] = set()
    for record in file_records:
        down = record["down_revision"]
        values = down if isinstance(down, list) else [down]
        referenced.update(v for v in values if isinstance(v, str))

    heads = sorted(set(revisions) - referenced)
    return (
        {
            "revision_count": len(revisions),
            "head_revisions": heads,
            "head_count": len(heads),
            "single_head": len(heads) == 1,
            "files": file_records,
        },
        sorted(_rel(f) for f in versions_dir.glob("*.py")),
    )


def _aggregate_worker_topology() -> tuple[dict[str, Any], list[str]]:
    from services.runtime.roles import (  # dependency-free by design
        ALL_ROLES,
        CONSUMER_ROLES,
        EXECUTION_GROUPS,
        RELEASE_CRITICAL_ROLES,
        ROLE_CAPABILITIES,
        ROLE_TO_SPEC_NAMES,
        WORKER_ROLES,
        owning_role,
    )

    spec_names = sorted({s for names in ROLE_TO_SPEC_NAMES.values() for s in names})
    spec_owner = {spec: owning_role(spec) for spec in spec_names}
    return (
        {
            "worker_role_count": len(WORKER_ROLES),
            "worker_roles": sorted(WORKER_ROLES),
            "all_roles": sorted(ALL_ROLES),
            "execution_groups": {k: sorted(v) for k, v in sorted(EXECUTION_GROUPS.items())},
            "release_critical_roles": sorted(RELEASE_CRITICAL_ROLES),
            "role_capabilities": dict(sorted(ROLE_CAPABILITIES.items())),
            "consumer_roles": sorted(CONSUMER_ROLES),
            "role_to_spec_names": {k: sorted(v) for k, v in sorted(ROLE_TO_SPEC_NAMES.items())},
            "supervised_spec_count": len(spec_owner),
            "spec_owner_index": dict(sorted(spec_owner.items())),
        },
        [
            "Backend Architecture/aether-backend/services/runtime/roles.py",
            "Backend Architecture/aether-backend/services/runtime/specs.py",
            "Backend Architecture/aether-backend/services/runtime/supervisor.py",
        ],
    )


def _walk_terraform_files(root: Path) -> list[str]:
    """All ``*.tf`` files under a terraform root, skipping dot-dirs (.terraform)."""
    out: list[str] = []
    for f in sorted(root.rglob("*.tf")):
        if any(part.startswith(".") for part in f.relative_to(root).parts):
            continue
        out.append(_rel(f))
    return out


def _aggregate_infrastructure_validation() -> tuple[dict[str, Any], list[str]]:
    tf_root = REPO_ROOT / "AWS Deployment" / "aether-aws" / "terraform"
    tf_files = _walk_terraform_files(tf_root) if tf_root.exists() else []
    profiles_dir = tf_root / "profiles"
    profiles = sorted(f.name for f in profiles_dir.glob("*.tfvars")) if profiles_dir.exists() else []
    envs_dir = tf_root / "environments"
    environments = (
        sorted(d.name for d in envs_dir.glob("*") if d.is_dir()) if envs_dir.exists() else []
    )

    dp_path = REPO_ROOT / "config" / "deployment_profiles.yaml"
    dp = _load_yaml(dp_path)
    profile_rows = [
        {"id": k, "class": v.get("class")} for k, v in sorted((dp.get("profiles") or {}).items())
    ]

    trc_path = REPO_ROOT / "config" / "terraform_resource_contracts.yaml"
    trc = _load_yaml(trc_path)
    contract_count = len(trc.get("required_resources") or {}) + len(
        trc.get("forbidden_resources") or {}
    )

    deploy_profile_path = REPO_ROOT / "config" / "deploy_profile.yaml"
    deploy_profile = _load_yaml(deploy_profile_path)

    artifact_path = REPO_ROOT / "artifacts" / "profile-policy-result.json"
    artifact_summary: dict[str, Any] | None = None
    if artifact_path.exists():
        a = json.loads(artifact_path.read_text())
        artifact_summary = {
            "file": _rel(artifact_path),
            "sha256": sha256_file(artifact_path),
            "profile": a.get("profile"),
            "passed": a.get("passed"),
            "checks_total": a.get("checks_total"),
            "checks_failed": a.get("checks_failed"),
            "terraform_version": a.get("terraform_version"),
        }

    return (
        {
            "terraform": {
                "terraform_root": _rel(tf_root) if tf_root.exists() else None,
                "tf_file_count": len(tf_files),
                "tf_files": tf_files,
                "profile_tfvars": profiles,
                "environment_dirs": environments,
            },
            "deployment_profiles": {
                "max_supported_profile": dp.get("max_supported_profile"),
                "profile_count": len(profile_rows),
                "profiles": profile_rows,
            },
            "terraform_resource_contracts": {
                "sha256": sha256_file(trc_path),
                "schema_version": trc.get("schema_version"),
                "contract_rule_count": contract_count,
            },
            "capability_topology": {
                "terraform_modules_dir": deploy_profile.get("terraform_modules_dir"),
                "required_capabilities": sorted(deploy_profile.get("required_capabilities") or []),
            },
            "terraform_plan_validation_artifact": artifact_summary,
            # Live terraform validation requires AWS credentials and a real
            # state backend — environment-controlled, never fabricated.
            "live_validation": {
                "terraform_validate": "pending",
                "terraform_plan": "pending",
                "terraform_apply": "pending",
            },
        },
        sorted(tf_files + [_rel(profiles_dir / p) for p in profiles])
        + [_rel(dp_path), _rel(trc_path), _rel(deploy_profile_path)]
        + ([_rel(artifact_path)] if artifact_path.exists() else []),
    )


def _aggregate_entitlement_registry() -> tuple[dict[str, Any], list[str]]:
    from shared.plans.service_catalog import SERVICE_CATALOG

    services: list[dict[str, Any]] = []
    for s in SERVICE_CATALOG:
        plan_access = {
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in s.plan_access.items()
        }
        services.append(
            {
                "name": s.name,
                "pillar": s.pillar,
                "endpoint_pattern": s.endpoint_pattern,
                "plan_access": dict(sorted(plan_access.items())),
            }
        )
    services.sort(key=lambda r: (r["name"] or ""))

    cm_path = REPO_ROOT / "config" / "capability_matrix.yaml"
    cm = _load_yaml(cm_path)
    caps = [
        {
            "id": c.get("id"),
            "route": c.get("route"),
            "runtime_role": c.get("runtime_role"),
        }
        for c in cm.get("capabilities") or []
    ]
    caps.sort(key=lambda r: (r["id"] or ""))

    packs_dir = REPO_ROOT / "config" / "agent_access_reference_packs"
    packs = [
        {"file": _rel(f), "sha256": sha256_file(f)}
        for f in sorted(packs_dir.iterdir())
        if f.is_file()
    ]

    cc_path = REPO_ROOT / "config" / "control_catalog.yaml"
    cc = _load_yaml(cc_path)
    controls = cc.get("controls") or []
    by_family: dict[str, int] = {}
    for c in controls:
        fam = c.get("control_family") or "unknown"
        by_family[fam] = by_family.get(fam, 0) + 1

    return (
        {
            "service_catalog_count": len(services),
            "services": services,
            "capability_matrix_count": len(caps),
            "capability_matrix_entries": caps,
            "agent_access_reference_packs": packs,
            "control_catalog": {
                "control_count": len(controls),
                "by_family": dict(sorted(by_family.items())),
            },
        },
        sorted(
            [
                "Backend Architecture/aether-backend/shared/plans/service_catalog.py",
                _rel(cm_path),
                _rel(cc_path),
            ]
            + [p["file"] for p in packs]
        ),
    )


def _aggregate_meter_registry() -> tuple[dict[str, Any], list[str]]:
    from shared.computation.generated_registry import GENERATED_DEFINITIONS, REGISTRY_DIGEST
    from shared.providers import CATEGORY_PROVIDERS, PROVIDER_FACTORY, ProviderCategory

    categories = {c.value for c in ProviderCategory}
    category_providers: dict[str, list[str]] = {}
    for cat, providers in CATEGORY_PROVIDERS.items():
        key = cat.value if hasattr(cat, "value") else str(cat)
        category_providers[key] = sorted(providers)

    metered = [d for d in GENERATED_DEFINITIONS if d.get("definition_id") == "billing.metered_usage"]
    return (
        {
            "provider_category_count": len(categories),
            "provider_categories": sorted(categories),
            "category_providers": dict(sorted(category_providers.items())),
            "provider_factory_count": len(PROVIDER_FACTORY),
            "computation_registry_digest": REGISTRY_DIGEST,
            "metered_definition": _json_safe(metered[0]) if metered else None,
        },
        [
            "Backend Architecture/aether-backend/shared/providers/__init__.py",
            "Backend Architecture/aether-backend/shared/providers/categories.py",
            "Backend Architecture/aether-backend/shared/providers/meter.py",
            "Backend Architecture/aether-backend/shared/providers/registry.py",
            "Backend Architecture/aether-backend/shared/computation/generated_registry.py",
        ],
    )


def _aggregate_storage_policies() -> tuple[dict[str, Any], list[str]]:
    path = REPO_ROOT / "config" / "storage_policies.yaml"
    doc = _load_yaml(path)
    policies = doc.get("policies") or []
    records = [
        {
            "resource_type": p.get("resource_type"),
            "authoritative_store": p.get("authoritative_store"),
            "codec": p.get("codec"),
            "format": p.get("format"),
            "retention_class": p.get("retention_class"),
            "delete_behavior": p.get("delete_behavior"),
            "requires_consent_invalidation": p.get("requires_consent_invalidation"),
        }
        for p in policies
    ]
    records.sort(key=lambda r: (r["resource_type"] or ""))
    return (
        {
            "schema_version": doc.get("schema_version"),
            "enforcement_status": doc.get("enforcement_status"),
            "policy_count": len(records),
            "resource_types": [r["resource_type"] for r in records],
            "policies": records,
        },
        [_rel(path)],
    )


def _aggregate_readiness_state() -> tuple[dict[str, Any], list[str]]:
    from shared.certification.readiness import (
        IMPLEMENTATION_STATUS_TO_READINESS,
        CredentialReadiness,
        readiness_rank,
    )
    from shared.certification.registry import build_capability_matrix

    tokens = {c.value: readiness_rank(c) for c in CredentialReadiness}
    status_mapping = {
        k.value if hasattr(k, "value") else str(k): v.value if hasattr(v, "value") else str(v)
        for k, v in IMPLEMENTATION_STATUS_TO_READINESS.items()
    }

    matrix = build_capability_matrix()
    by_state = matrix["summary"]["by_state"]
    present_ranks = [
        (readiness_rank(CredentialReadiness(state)), state) for state in by_state
    ]
    highest = max(present_ranks) if present_ranks else None

    cert_dir = REPO_ROOT / "release-evidence" / "profile"
    profile_states: list[dict[str, str]] = []
    for f in sorted(cert_dir.glob("*.json")):
        doc = json.loads(f.read_text())
        profile_states.append(
            {"profile": doc.get("profile"), "readiness_state": doc.get("readiness_state")}
        )

    return (
        {
            "readiness_tokens": dict(sorted(tokens.items(), key=lambda kv: (kv[1], kv[0]))),
            "implementation_status_mapping": dict(sorted(status_mapping.items())),
            "capability_summary": matrix["summary"],
            "highest_present_readiness": {
                "state": highest[1],
                "rank": highest[0],
            }
            if highest
            else None,
            "profile_certificate_states": profile_states,
            "production_readiness_claim": False,
            "production_readiness_note": (
                "production_ready requires live_validated + security_reviewed "
                "(+ externally_audited where requires_external_audit); no provider "
                "holds live validation evidence in this repo — claim stays pending."
            ),
        },
        sorted(
            ["Backend Architecture/aether-backend/shared/certification/readiness.py"]
            + [_rel(f) for f in cert_dir.glob("*.json")]
        ),
    )


# ── pending (environment-controlled) evidence ───────────────────────────────


def _build_pending_evidence(sections: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Explicit list of environment-controlled evidence that is NOT fabricated.

    Anything that requires live credentials / CI execution / cloud state is
    listed as ``pending`` with the exact reason, so a reviewer can see that the
    bundle is honest about what has not been proven yet.
    """
    pending: list[dict[str, str]] = []

    for suite in sections["test_suites"].get("suites", []):
        pending.append(
            {
                "item": f"test-suite:{suite['id']}:results",
                "status": "pending",
                "reason": "pass/fail counts require a CI or local pytest execution",
            }
        )

    for tf in ("terraform_validate", "terraform_plan", "terraform_apply"):
        pending.append(
            {
                "item": f"infrastructure:{tf}",
                "status": "pending",
                "reason": "requires live terraform, AWS credentials and a real state backend",
            }
        )

    matrix = sections["certification"]["capability_matrix"]
    for key, prov in matrix.get("providers", {}).items():
        state = prov.get("state")
        if state in ("credential_waiting", "scaffolded", "implementation_in_progress"):
            pending.append(
                {
                    "item": f"provider:{prov.get('provider')}:{prov.get('domain')}",
                    "status": "pending",
                    "reason": (
                        f"credential-readiness '{state}' requires configured "
                        "credentials/endpoints for replay/live validation"
                    ),
                }
            )

    pending.append(
        {
            "item": "readiness:production_ready",
            "status": "pending",
            "reason": "production_ready requires live_validated AND security_reviewed "
            "(plus externally_audited where requires_external_audit)",
        }
    )
    pending.sort(key=lambda r: r["item"])
    return pending


# ── bundle assembly ─────────────────────────────────────────────────────────


def build_evidence_bundle(phase: str = DEFAULT_PHASE) -> dict[str, Any]:
    """Build the deterministic evidence bundle document (in-memory)."""
    aggregators: dict[str, Any] = {
        "manifests": _aggregate_manifests,
        "certification": _aggregate_certification,
        "test_suites": _aggregate_test_suites,
        "fault_tests": _aggregate_fault_tests,
        "migration_state": _aggregate_migration_state,
        "worker_topology": _aggregate_worker_topology,
        "infrastructure_validation": _aggregate_infrastructure_validation,
        "entitlement_registry": _aggregate_entitlement_registry,
        "meter_registry": _aggregate_meter_registry,
        "storage_policies": _aggregate_storage_policies,
        "readiness_state": _aggregate_readiness_state,
    }

    missing = [s for s in REQUIRED_SECTIONS if s not in aggregators]
    if missing:
        raise RuntimeError(f"missing evidence aggregators for sections: {sorted(missing)}")

    sections: dict[str, dict[str, Any]] = {}
    sources: set[str] = set()
    for key in REQUIRED_SECTIONS:
        data, srcs = aggregators[key]()
        sections[key] = data
        sources.update(srcs)

    file_checksums = {
        rel: sha256_file(REPO_ROOT / rel) for rel in sorted(sources)
    }

    document: dict[str, Any] = {
        "bundle": {
            "name": BUNDLE_NAME,
            "program": PROGRAM_REF,
            "phase": phase,
            "schema_version": SCHEMA_VERSION,
            "determinism": (
                "no timestamps, no randomness, no environment values; "
                "all keys and lists sorted; two runs in the same checkout "
                "produce byte-identical output"
            ),
        },
        "sections": sections,
        "file_checksums": file_checksums,
        "pending_evidence": _build_pending_evidence(sections),
    }

    # Root checksum covers everything except the root_checksum block itself, so
    # a verifier can recompute it by removing that block and canonicalizing.
    document["root_checksum"] = {
        "algorithm": "sha256",
        "canonicalization": (
            "sha256(utf8(json.dumps(document-minus-root_checksum, sort_keys=True, "
            "separators=(',', ':'), ensure_ascii=True)))"
        ),
        "value": _sha256_bytes(_canonical_json(document)),
    }
    return document


def write_bundle(document: dict[str, Any], out_path: Path) -> None:
    """Write the bundle as deterministic pretty JSON (sorted keys)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_output(phase: str) -> Path:
    return REPO_ROOT / "release-evidence" / f"{BUNDLE_NAME}-{phase}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"Build the {BUNDLE_NAME} ({PROGRAM_REF}): deterministic, checksummed "
            "evidence bundle aggregated from canonical registries."
        )
    )
    parser.add_argument("--phase", default=DEFAULT_PHASE, help="release phase token")
    parser.add_argument(
        "--out",
        default=None,
        help=f"output path (default: release-evidence/{BUNDLE_NAME}-<phase>.json)",
    )
    args = parser.parse_args(argv)

    document = build_evidence_bundle(phase=args.phase)
    out = Path(args.out) if args.out else default_output(args.phase)
    write_bundle(document, out)
    print(f"wrote {out}")
    print(f"root sha256: {document['root_checksum']['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
