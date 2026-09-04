#!/usr/bin/env python3
"""
Generate TypeScript and Python artifacts from the unified-platform JSON registries.

Companion to scripts/generate_contracts.py (which owns the event/consent/metric
registries). This generator owns the platform-plane registries added by the
unified intelligence program; new registries plug into the REGISTRIES table.

Sources (read-only — canonical source of truth):
  packages/shared/contracts/temporal-policy-registry.json
  packages/shared/contracts/interaction-vocabulary.json
  packages/shared/contracts/context-capsule-registry.json
  packages/shared/contracts/location-registry.json
  packages/shared/contracts/graph-mutation-registry.json
  packages/shared/contracts/filter-field-registry.json
  packages/shared/contracts/surface-capability-registry.json
  packages/shared/contracts/comparison-registry.json
  packages/shared/contracts/projector-ownership-registry.json
  packages/shared/contracts/model-registry.json
  packages/shared/contracts/task-profile-registry.json
  packages/shared/contracts/intelligence-projection-registry.json
  packages/shared/contracts/lens-registry.json

Generated outputs:
  packages/shared/temporal-policy.ts
  Backend Architecture/aether-backend/shared/temporal/generated_policy.py
  docs/_generated/temporal-policy-table.md
  packages/shared/interaction-contract.ts
  Backend Architecture/aether-backend/shared/product/generated_vocabulary.py
  docs/_generated/interaction-vocabulary-table.md
  packages/shared/context-capsule.ts
  Backend Architecture/aether-backend/shared/context_capsule/generated_taxonomy.py
  docs/_generated/context-capsule-table.md
  packages/shared/location-registry.ts
  Backend Architecture/aether-backend/shared/geo/generated_taxonomy.py
  docs/_generated/location-registry-table.md
  packages/shared/graph-mutation.ts
  Backend Architecture/aether-backend/shared/graph/generated_mutation_taxonomy.py
  docs/_generated/graph-mutation-table.md
  packages/shared/filter-fields.ts
  Backend Architecture/aether-backend/shared/exploration/generated_fields.py
  docs/_generated/filter-field-table.md
  packages/shared/surface-capabilities.ts
  Backend Architecture/aether-backend/shared/exploration/generated_surfaces.py
  docs/_generated/surface-capability-table.md
  packages/shared/comparison-contract.ts
  Backend Architecture/aether-backend/services/intelligence/comparison/generated_vocabulary.py
  docs/_generated/comparison-table.md
  Backend Architecture/aether-backend/services/silver/generated_ownership.py
  docs/_generated/projector-ownership-table.md
  packages/shared/model-registry.ts
  Backend Architecture/aether-backend/shared/model_governance/generated_model_registry.py
  docs/_generated/model-registry-table.md
  packages/shared/task-profile.ts
  Backend Architecture/aether-backend/shared/model_governance/generated_task_profiles.py
  docs/_generated/task-profile-table.md
  packages/shared/intelligence-projections_generated.ts
  Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py
  docs/_generated/intelligence-projection-registry-table.md
  docs/_generated/intelligence-projection-dependency-graph.md
  packages/shared/lenses_generated.ts
  Backend Architecture/aether-backend/shared/projection_engine/generated_lenses.py
  docs/_generated/lens-registry-table.md

Usage:
  python scripts/generate_platform_contracts.py           # write outputs in-place
  python scripts/generate_platform_contracts.py --check   # exit 1 on drift (CI gate)

Guarantees:
  - Idempotent: running twice produces identical output
  - Sorted: all keyed collections are emitted in sorted order
  - Validates: registry internal consistency before any write
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS = ROOT / "packages" / "shared" / "contracts"
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

# The intelligence-projection validator lives in scripts/lib and shares the
# cross-registry context computed here — delegate to it (see _projection_context)
# so the generator's validation and the standalone validator can never drift.
# Invoked as `python scripts/generate_platform_contracts.py`, sys.path[0] is
# scripts/ — the repo root must be present for the scripts.lib package import
# (same pattern as repo_doctor.py).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.lib.intelligence_projection_validation import (  # noqa: E402
    load_context as _projection_load_context,
    validate_all as _projection_validate_all,
    validate_lens_registry as _projection_validate_lens_registry,
    validate_outcome_registry as _projection_validate_outcome_registry,
)

TEMPORAL_POLICY_JSON = CONTRACTS / "temporal-policy-registry.json"
EVENT_REGISTRY_JSON = CONTRACTS / "event-registry.json"

TEMPORAL_POLICY_TS = ROOT / "packages" / "shared" / "temporal-policy.ts"
TEMPORAL_POLICY_PY = BACKEND / "shared" / "temporal" / "generated_policy.py"
TEMPORAL_POLICY_MD = ROOT / "docs" / "_generated" / "temporal-policy-table.md"

_SEVERITIES = ("error", "warning", "info")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def validate_temporal_policy(reg: dict, event_families: set[str]) -> None:
    dispositions = set(reg["dispositions"])
    codes_seen: set[str] = set()
    for entry in reg["reasonCodes"]:
        code = entry["code"]
        if code in codes_seen:
            _fail(f"duplicate temporal reason code {code!r}")
        codes_seen.add(code)
        if entry["severity"] not in _SEVERITIES:
            _fail(f"reason code {code!r} has unknown severity {entry['severity']!r}")
        if entry["disposition"] not in dispositions:
            _fail(f"reason code {code!r} has unknown disposition {entry['disposition']!r}")

    bounds_keys = {"maxFutureSkewMs", "warnSkewMs", "maxLatenessMs"}
    default = reg["defaultBounds"]
    if set(default) != bounds_keys:
        _fail(f"defaultBounds must define exactly {sorted(bounds_keys)}")
    for family, bounds in reg["familyBounds"].items():
        if family not in event_families:
            _fail(f"familyBounds references unknown event family {family!r}")
        unknown = set(bounds) - bounds_keys
        if unknown:
            _fail(f"familyBounds[{family!r}] has unknown keys {sorted(unknown)}")
        for key, value in bounds.items():
            if not isinstance(value, int) or value <= 0:
                _fail(f"familyBounds[{family!r}][{key}] must be a positive integer")
    resolved_default = {**default}
    if resolved_default["warnSkewMs"] >= resolved_default["maxFutureSkewMs"]:
        _fail("defaultBounds.warnSkewMs must be below maxFutureSkewMs")


def resolved_family_bounds(reg: dict, event_families: set[str]) -> dict[str, dict]:
    """Every event family resolves to complete bounds (default + override)."""
    default = reg["defaultBounds"]
    return {
        family: {**default, **reg["familyBounds"].get(family, {})}
        for family in sorted(event_families)
    }


# ---------------------------------------------------------------------------
# Emitters (temporal policy)
# ---------------------------------------------------------------------------

def gen_temporal_policy_ts(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("/**")
    lines.append(" * DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json")
    lines.append(" * Run: python scripts/generate_platform_contracts.py")
    lines.append(" */")
    lines.append("")
    lines.append(f"export const temporalPolicyVersion = '{reg['policyVersion']}' as const;")
    lines.append("")
    modes = ", ".join(f"'{m}'" for m in reg["enforcementModes"])
    lines.append(f"export const temporalEnforcementModes = [{modes}] as const;")
    lines.append("export type TemporalEnforcementMode = typeof temporalEnforcementModes[number];")
    lines.append("")
    dispositions = ", ".join(f"'{d}'" for d in reg["dispositions"])
    lines.append(f"export const temporalDispositions = [{dispositions}] as const;")
    lines.append("export type TemporalDisposition = typeof temporalDispositions[number];")
    lines.append("")
    lines.append("/** Disposition applied to each stable temporal reason code. */")
    lines.append("export const temporalReasonDispositions = {")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(f"  {entry['code']}: '{entry['disposition']}',")
    lines.append("} as const;")
    lines.append("")
    lines.append("export interface TemporalFamilyBounds {")
    lines.append("  maxFutureSkewMs: number;")
    lines.append("  warnSkewMs: number;")
    lines.append("  maxLatenessMs: number;")
    lines.append("}")
    lines.append("")
    lines.append("/** Complete (default-resolved) temporal bounds per event family. */")
    lines.append("export const temporalFamilyBounds: Record<string, TemporalFamilyBounds> = {")
    for family, bounds in families.items():
        lines.append(
            f"  {family}: {{ maxFutureSkewMs: {bounds['maxFutureSkewMs']}, "
            f"warnSkewMs: {bounds['warnSkewMs']}, maxLatenessMs: {bounds['maxLatenessMs']} }},"
        )
    lines.append("};")
    lines.append("")
    default = reg["defaultBounds"]
    lines.append(
        "export const temporalDefaultBounds: TemporalFamilyBounds = "
        f"{{ maxFutureSkewMs: {default['maxFutureSkewMs']}, "
        f"warnSkewMs: {default['warnSkewMs']}, maxLatenessMs: {default['maxLatenessMs']} }};"
    )
    lines.append("")
    return "\n".join(lines)


def gen_temporal_policy_py(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("# DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json")
    lines.append("# Run: python scripts/generate_platform_contracts.py")
    lines.append('"""Generated temporal enforcement policy (dispositions + per-family bounds)."""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append(f'TEMPORAL_POLICY_VERSION = "{reg["policyVersion"]}"')
    lines.append("")
    modes = ", ".join(f'"{m}"' for m in reg["enforcementModes"])
    lines.append(f"TEMPORAL_ENFORCEMENT_MODES: tuple[str, ...] = ({modes})")
    lines.append("")
    dispositions = ", ".join(f'"{d}"' for d in reg["dispositions"])
    lines.append(f"TEMPORAL_DISPOSITIONS: tuple[str, ...] = ({dispositions})")
    lines.append("")
    lines.append("# Disposition applied to each stable temporal reason code.")
    lines.append("TEMPORAL_REASON_DISPOSITIONS: dict[str, str] = {")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(f'    "{entry["code"]}": "{entry["disposition"]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Complete (default-resolved) temporal bounds per event family.")
    lines.append("TEMPORAL_FAMILY_BOUNDS: dict[str, dict[str, int]] = {")
    for family, bounds in families.items():
        lines.append(
            f'    "{family}": {{"maxFutureSkewMs": {bounds["maxFutureSkewMs"]}, '
            f'"warnSkewMs": {bounds["warnSkewMs"]}, "maxLatenessMs": {bounds["maxLatenessMs"]}}},'
        )
    lines.append("}")
    lines.append("")
    default = reg["defaultBounds"]
    lines.append(
        'TEMPORAL_DEFAULT_BOUNDS: dict[str, int] = {'
        f'"maxFutureSkewMs": {default["maxFutureSkewMs"]}, '
        f'"warnSkewMs": {default["warnSkewMs"]}, '
        f'"maxLatenessMs": {default["maxLatenessMs"]}}}'
    )
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "TEMPORAL_POLICY_VERSION",')
    lines.append('    "TEMPORAL_ENFORCEMENT_MODES",')
    lines.append('    "TEMPORAL_DISPOSITIONS",')
    lines.append('    "TEMPORAL_REASON_DISPOSITIONS",')
    lines.append('    "TEMPORAL_FAMILY_BOUNDS",')
    lines.append('    "TEMPORAL_DEFAULT_BOUNDS",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_temporal_policy_md(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("<!-- DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json -->")
    lines.append("<!-- Run: python scripts/generate_platform_contracts.py -->")
    lines.append("")
    lines.append("# Temporal Policy Registry")
    lines.append("")
    lines.append(f"Policy version: `{reg['policyVersion']}`")
    lines.append("")
    lines.append(f"Enforcement modes: {', '.join(f'`{m}`' for m in reg['enforcementModes'])}")
    lines.append("")
    lines.append("## Reason codes")
    lines.append("")
    lines.append("| Code | Severity | Disposition | Description |")
    lines.append("|---|---|---|---|")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(
            f"| `{entry['code']}` | {entry['severity']} | {entry['disposition']} | {entry['description']} |"
        )
    lines.append("")
    lines.append("## Per-family bounds (default-resolved)")
    lines.append("")
    lines.append("| Family | Max future skew (ms) | Warn skew (ms) | Max lateness (ms) |")
    lines.append("|---|---|---|---|")
    for family, bounds in families.items():
        lines.append(
            f"| `{family}` | {bounds['maxFutureSkewMs']} | {bounds['warnSkewMs']} | {bounds['maxLatenessMs']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared emission / validation helpers (used by the REGISTRIES table)
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_idents(registry: str, key: str, values: object) -> None:
    """A vocabulary list must be non-empty, unique lower_snake identifiers."""
    if not isinstance(values, list) or not values:
        _fail(f"{registry}.{key} must be a non-empty list")
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not _IDENT_RE.match(value):
            _fail(f"{registry}.{key} entry {value!r} is not a lower_snake identifier")
        if value in seen:
            _fail(f"{registry}.{key} has duplicate entry {value!r}")
        seen.add(value)


def _ts_header(source: Path) -> list[str]:
    return [
        "/**",
        f" * DO NOT EDIT — generated from {source.relative_to(ROOT).as_posix()}",
        " * Run: python scripts/generate_platform_contracts.py",
        " */",
        "",
    ]


def _py_header(source: Path, docstring: str) -> list[str]:
    return [
        f"# DO NOT EDIT — generated from {source.relative_to(ROOT).as_posix()}",
        "# Run: python scripts/generate_platform_contracts.py",
        f'"""{docstring}"""',
        "",
        "from __future__ import annotations",
        "",
    ]


def _md_header(source: Path) -> list[str]:
    return [
        f"<!-- DO NOT EDIT — generated from {source.relative_to(ROOT).as_posix()} -->",
        "<!-- Run: python scripts/generate_platform_contracts.py -->",
        "",
    ]


def _ts_const_array(name: str, type_name: str, values: list[str], doc: str | None = None) -> list[str]:
    lines: list[str] = []
    if doc:
        lines.append(f"/** {doc} */")
    joined = ", ".join(f"'{v}'" for v in values)
    single = f"export const {name} = [{joined}] as const;"
    if len(single) <= 100:
        lines.append(single)
    else:
        lines.append(f"export const {name} = [")
        for value in values:
            lines.append(f"  '{value}',")
        lines.append("] as const;")
    lines.append(f"export type {type_name} = typeof {name}[number];")
    lines.append("")
    return lines


def _py_tuple(name: str, values: list[str], comment: str | None = None) -> list[str]:
    lines: list[str] = []
    if comment:
        lines.append(f"# {comment}")
    joined = ", ".join(f'"{v}"' for v in values)
    if len(values) == 1:
        joined += ","
    single = f"{name}: tuple[str, ...] = ({joined})"
    if len(single) <= 100:
        lines.append(single)
    else:
        lines.append(f"{name}: tuple[str, ...] = (")
        for value in values:
            lines.append(f'    "{value}",')
        lines.append(")")
    lines.append("")
    return lines


def _ts_interface(name: str, fields: tuple[tuple[str, str, bool], ...], doc: str) -> list[str]:
    """Emit a TS interface from (field, ts_type, required) triples (snake_case)."""
    lines = [f"/** {doc} */", f"export interface {name} {{"]
    for field, ts_type, required in fields:
        if required:
            lines.append(f"  {field}: {ts_type};")
        else:
            lines.append(f"  {field}?: {ts_type} | null;")
    lines.append("}")
    lines.append("")
    return lines


def _md_vocab_section(title: str, values: list[str]) -> list[str]:
    return [f"## {title}", "", ", ".join(f"`{v}`" for v in values), ""]


# ---------------------------------------------------------------------------
# Registry: interaction-vocabulary
# ---------------------------------------------------------------------------

INTERACTION_VOCAB_JSON = CONTRACTS / "interaction-vocabulary.json"
INTERACTION_TS = ROOT / "packages" / "shared" / "interaction-contract.ts"
INTERACTION_PY = BACKEND / "shared" / "product" / "generated_vocabulary.py"
INTERACTION_MD = ROOT / "docs" / "_generated" / "interaction-vocabulary-table.md"

_INTERACTION_VOCAB_KEYS = (
    "interactionTypes",
    "customNamespaces",
    "resultStates",
    "evidenceBasis",
    "actorKinds",
)

# TS twin of shared/product/models.py::InteractionPayload — parity-tested.
_INTERACTION_PAYLOAD_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("tenant_id", "string", True),
    ("event_id", "string", True),
    ("occurred_at", "string", True),
    ("actor_kind", "string", False),
    ("canonical_entity_id", "string", False),
    ("anonymous_id", "string", False),
    ("user_id", "string", False),
    ("organization_id", "string", False),
    ("workspace_id", "string", False),
    ("agent_id", "string", False),
    ("wallet_id", "string", False),
    ("session_id", "string", False),
    ("device_id", "string", False),
    ("product_id", "string", False),
    ("product_area_id", "string", False),
    ("feature_id", "string", False),
    ("feature_version_id", "string", False),
    ("surface_id", "string", False),
    ("control_id", "string", False),
    ("interaction_type", "string", False),
    ("action_type", "string", False),
    ("result_state", "string", False),
    ("status_detail", "string", False),
    ("journey_id", "string", False),
    ("journey_step_id", "string", False),
    ("campaign_id", "string", False),
    ("experiment_id", "string", False),
    ("variant_id", "string", False),
    ("channel", "string", False),
    ("platform", "string", False),
    ("application_id", "string", False),
    ("application_version", "string", False),
    ("sdk_name", "string", False),
    ("sdk_version", "string", False),
    ("chain_id", "string", False),
    ("contract_address", "string", False),
    ("transaction_hash", "string", False),
    ("payment_rail", "string", False),
    ("payment_provider", "string", False),
    ("elapsed_ms", "number", False),
    ("visible_ms", "number", False),
    ("active_ms", "number", False),
    ("engaged_ms", "number", False),
    ("idle_ms", "number", False),
    ("network_wait_ms", "number", False),
    ("external_wait_ms", "number", False),
    ("provider_wait_ms", "number", False),
    ("execution_wait_ms", "number", False),
    ("scroll_pct", "number", False),
    ("viewable_pct", "number", False),
    ("completion_pct", "number", False),
    ("attempt_number", "number", False),
    ("friction_type", "string", False),
    ("error_code", "string", False),
    ("failure_category", "string", False),
    ("evidence_basis", "string", False),
    ("confidence", "number", False),
    ("consent_state", "string", False),
    ("mapping_version", "string", False),
    ("mapping_source", "string", False),
    ("mapping_confidence", "number", False),
    ("source_event_id", "string", False),
    ("correlation_id", "string", False),
)


def validate_interaction_vocabulary(reg: dict, ctx: dict) -> None:
    for key in _INTERACTION_VOCAB_KEYS:
        _require_idents("interaction-vocabulary", key, reg[key])
    if not isinstance(reg.get("customNamespaceRule"), str) or not reg["customNamespaceRule"]:
        _fail("interaction-vocabulary.customNamespaceRule must be a non-empty string")


def gen_interaction_ts(reg: dict) -> str:
    lines = _ts_header(INTERACTION_VOCAB_JSON)
    lines.append(f"export const interactionVocabularyVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "interactionTypes", "InteractionType", reg["interactionTypes"],
        "Closed canonical interaction-type vocabulary.",
    )
    lines += _ts_const_array(
        "interactionCustomNamespaces", "InteractionCustomNamespace", reg["customNamespaces"],
        reg["customNamespaceRule"],
    )
    lines += _ts_const_array(
        "interactionResultStates", "InteractionResultState", reg["resultStates"],
        "Canonical result state of an interaction.",
    )
    lines += _ts_const_array(
        "interactionEvidenceBasis", "InteractionEvidenceBasis", reg["evidenceBasis"],
        "How strongly the recorded interaction is evidenced.",
    )
    lines += _ts_const_array(
        "interactionActorKinds", "InteractionActorKind", reg["actorKinds"],
        "Who (or what) performed the interaction.",
    )
    lines += _ts_interface(
        "InteractionPayload",
        _INTERACTION_PAYLOAD_FIELDS,
        "Canonical interaction payload (Python twin: shared/product/models.py).",
    )
    return "\n".join(lines)


def gen_interaction_py(reg: dict) -> str:
    lines = _py_header(
        INTERACTION_VOCAB_JSON,
        "Generated interaction vocabulary (types, namespaces, result states, evidence, actors).",
    )
    lines.append(f'INTERACTION_VOCABULARY_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("INTERACTION_TYPES", reg["interactionTypes"],
                       "Closed canonical interaction-type vocabulary.")
    lines += _py_tuple("INTERACTION_CUSTOM_NAMESPACES", reg["customNamespaces"],
                       reg["customNamespaceRule"])
    lines += _py_tuple("INTERACTION_RESULT_STATES", reg["resultStates"],
                       "Canonical result state of an interaction.")
    lines += _py_tuple("INTERACTION_EVIDENCE_BASIS", reg["evidenceBasis"],
                       "How strongly the recorded interaction is evidenced.")
    lines += _py_tuple("INTERACTION_ACTOR_KINDS", reg["actorKinds"],
                       "Who (or what) performed the interaction.")
    lines.append("__all__ = [")
    lines.append('    "INTERACTION_VOCABULARY_VERSION",')
    lines.append('    "INTERACTION_TYPES",')
    lines.append('    "INTERACTION_CUSTOM_NAMESPACES",')
    lines.append('    "INTERACTION_RESULT_STATES",')
    lines.append('    "INTERACTION_EVIDENCE_BASIS",')
    lines.append('    "INTERACTION_ACTOR_KINDS",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_interaction_md(reg: dict) -> str:
    lines = _md_header(INTERACTION_VOCAB_JSON)
    lines.append("# Interaction Vocabulary")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines += _md_vocab_section("Interaction types", reg["interactionTypes"])
    lines += _md_vocab_section("Custom namespaces", reg["customNamespaces"])
    lines.append(f"> {reg['customNamespaceRule']}")
    lines.append("")
    lines += _md_vocab_section("Result states", reg["resultStates"])
    lines += _md_vocab_section("Evidence basis", reg["evidenceBasis"])
    lines += _md_vocab_section("Actor kinds", reg["actorKinds"])
    return "\n".join(lines)


def _summary_interaction(reg: dict) -> str:
    return (
        f"interaction-vocabulary v{reg['contractVersion']} — "
        f"{len(reg['interactionTypes'])} interaction types, "
        f"{len(reg['resultStates'])} result states"
    )


# ---------------------------------------------------------------------------
# Registry: context-capsule
# ---------------------------------------------------------------------------

CONTEXT_CAPSULE_JSON = CONTRACTS / "context-capsule-registry.json"
CONTEXT_CAPSULE_TS = ROOT / "packages" / "shared" / "context-capsule.ts"
CONTEXT_CAPSULE_PY = BACKEND / "shared" / "context_capsule" / "generated_taxonomy.py"
CONTEXT_CAPSULE_MD = ROOT / "docs" / "_generated" / "context-capsule-table.md"

_CONTEXT_CAPSULE_VOCAB_KEYS = (
    "locationSources",
    "locationSemantics",
    "precisionClasses",
    "conflictStates",
    "contextStates",
    "capsuleTransitionTypes",
)

# Emission order for retention-policy keys (fixed, so output is deterministic).
_RETENTION_POLICY_KEYS = ("maxHours", "maxDays", "tenantPolicy", "inheritsStrictest", "aggregateOnly")

# TS twin of shared/context_capsule/models.py::LocationObservation — parity-tested.
# Deliberately has NO raw-IP and NO lat/lon field: precise coordinates never
# enter the contract; the finest grain is a coarse cell + accuracy radius.
_LOCATION_OBSERVATION_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("observation_id", "string", True),
    ("tenant_id", "string", True),
    ("subject_type", "string", False),
    ("subject_id", "string", False),
    ("session_id", "string", False),
    ("source_event_id", "string", False),
    ("source", "string", True),
    ("semantics", "string", True),
    ("precision_class", "string", True),
    ("country_code", "string", False),
    ("region_code", "string", False),
    ("city", "string", False),
    ("coarse_cell", "string", False),
    ("accuracy_radius_meters", "number", False),
    ("confidence", "number", False),
    ("observed_at", "string", True),
    ("received_at", "string", False),
    ("provider", "string", False),
    ("provider_database_version", "string", False),
    ("vpn_likelihood", "number", False),
    ("proxy_likelihood", "number", False),
    ("tor_likelihood", "number", False),
    ("datacenter_likelihood", "number", False),
    ("consent_snapshot_id", "string", False),
    ("retention_class", "string", False),
    ("suppression_state", "string", False),
    ("schema_version", "string", False),
)

# TS twin of shared/context_capsule/models.py::ContextCapsule — parity-tested.
_CONTEXT_CAPSULE_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("capsule_id", "string", True),
    ("tenant_id", "string", True),
    ("session_id", "string", False),
    ("capsule_version", "number", True),
    ("valid_from", "string", True),
    ("valid_to", "string", False),
    ("actor_id", "string", False),
    ("actor_kind", "string", False),
    ("canonical_entity_id", "string", False),
    ("identity_confidence", "number", False),
    ("device_id", "string", False),
    ("device_platform", "string", False),
    ("device_class", "string", False),
    ("app_version", "string", False),
    ("sdk_name", "string", False),
    ("sdk_version", "string", False),
    ("network_observation_id", "string", False),
    ("network_connection_type", "string", False),
    ("network_asn_class", "string", False),
    ("network_vpn_likelihood", "number", False),
    ("network_proxy_likelihood", "number", False),
    ("network_datacenter_likelihood", "number", False),
    ("geo_resolved_location_id", "string", False),
    ("geo_source_semantics", "string", False),
    ("geo_country_code", "string", False),
    ("geo_region_code", "string", False),
    ("geo_city", "string", False),
    ("geo_coarse_cell", "string", False),
    ("geo_confidence", "number", False),
    ("geo_conflict_state", "string", False),
    ("campaign_id", "string", False),
    ("campaign_source", "string", False),
    ("campaign_medium", "string", False),
    ("journey_id", "string", False),
    ("journey_stage", "string", False),
    ("prior_capsule_id", "string", False),
    ("consent_snapshot_id", "string", False),
    ("policy_jurisdiction", "string", False),
    ("retention_class", "string", False),
    ("suppression_state", "string", False),
    ("source_event_id", "string", False),
    ("schema_version", "string", False),
    ("context_hash", "string", False),
)


def validate_context_capsule(reg: dict, ctx: dict) -> None:
    for key in _CONTEXT_CAPSULE_VOCAB_KEYS:
        _require_idents("context-capsule-registry", key, reg[key])
    retention = reg["retentionClasses"]
    if not isinstance(retention, dict) or not retention:
        _fail("context-capsule-registry.retentionClasses must be a non-empty object")
    for name, policy in retention.items():
        if not _IDENT_RE.match(name):
            _fail(f"retention class {name!r} is not a lower_snake identifier")
        if not isinstance(policy, dict) or not policy:
            _fail(f"retentionClasses[{name!r}] must be a non-empty object")
        unknown = set(policy) - set(_RETENTION_POLICY_KEYS)
        if unknown:
            _fail(f"retentionClasses[{name!r}] has unknown keys {sorted(unknown)}")
        for key, value in policy.items():
            if key in ("maxHours", "maxDays"):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    _fail(f"retentionClasses[{name!r}][{key}] must be a non-negative integer")
            elif value is not True:
                _fail(f"retentionClasses[{name!r}][{key}] must be true when present")


def _retention_policy_items(policy: dict) -> list[tuple[str, object]]:
    return [(k, policy[k]) for k in _RETENTION_POLICY_KEYS if k in policy]


def gen_context_capsule_ts(reg: dict) -> str:
    lines = _ts_header(CONTEXT_CAPSULE_JSON)
    lines.append(f"export const contextCapsuleContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "locationSources", "LocationSource", reg["locationSources"],
        "Where a location observation came from.",
    )
    lines += _ts_const_array(
        "locationSemantics", "LocationSemantic", reg["locationSemantics"],
        "What a location observation actually means.",
    )
    lines += _ts_const_array(
        "locationPrecisionClasses", "LocationPrecisionClass", reg["precisionClasses"],
        "Coarsest-to-finest location precision classes.",
    )
    lines += _ts_const_array(
        "locationConflictStates", "LocationConflictState", reg["conflictStates"],
        "Agreement state between concurrent location observations.",
    )
    lines += _ts_const_array(
        "contextStates", "ContextState", reg["contextStates"],
        "Interpreted context state for a subject at capsule time.",
    )
    lines += _ts_const_array(
        "contextRetentionClassNames", "ContextRetentionClass",
        sorted(reg["retentionClasses"]),
        "Named retention classes (constraints in contextRetentionClasses).",
    )
    lines.append("/** Retention constraint attached to each retention class. */")
    lines.append("export interface ContextRetentionPolicy {")
    lines.append("  maxHours?: number;")
    lines.append("  maxDays?: number;")
    lines.append("  tenantPolicy?: boolean;")
    lines.append("  inheritsStrictest?: boolean;")
    lines.append("  aggregateOnly?: boolean;")
    lines.append("}")
    lines.append("")
    lines.append("export const contextRetentionClasses: Record<ContextRetentionClass, ContextRetentionPolicy> = {")
    for name in sorted(reg["retentionClasses"]):
        items = ", ".join(
            f"{k}: {str(v).lower() if isinstance(v, bool) else v}"
            for k, v in _retention_policy_items(reg["retentionClasses"][name])
        )
        lines.append(f"  {name}: {{ {items} }},")
    lines.append("};")
    lines.append("")
    lines += _ts_const_array(
        "capsuleTransitionTypes", "CapsuleTransitionType", reg["capsuleTransitionTypes"],
        "Why a new context capsule superseded the previous one.",
    )
    lines += _ts_interface(
        "LocationObservation",
        _LOCATION_OBSERVATION_FIELDS,
        "One privacy-shaped location observation — no raw IP, no lat/lon "
        "(Python twin: shared/context_capsule/models.py).",
    )
    lines += _ts_interface(
        "ContextCapsule",
        _CONTEXT_CAPSULE_FIELDS,
        "Versioned context capsule for a session slice "
        "(Python twin: shared/context_capsule/models.py).",
    )
    return "\n".join(lines)


def gen_context_capsule_py(reg: dict) -> str:
    lines = _py_header(
        CONTEXT_CAPSULE_JSON,
        "Generated context-capsule taxonomy (location sources/semantics, states, retention).",
    )
    lines.append(f'CONTEXT_CAPSULE_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("LOCATION_SOURCES", reg["locationSources"],
                       "Where a location observation came from.")
    lines += _py_tuple("LOCATION_SEMANTICS", reg["locationSemantics"],
                       "What a location observation actually means.")
    lines += _py_tuple("LOCATION_PRECISION_CLASSES", reg["precisionClasses"],
                       "Coarsest-to-finest location precision classes.")
    lines += _py_tuple("LOCATION_CONFLICT_STATES", reg["conflictStates"],
                       "Agreement state between concurrent location observations.")
    lines += _py_tuple("CONTEXT_STATES", reg["contextStates"],
                       "Interpreted context state for a subject at capsule time.")
    lines += _py_tuple("CONTEXT_RETENTION_CLASS_NAMES", sorted(reg["retentionClasses"]),
                       "Named retention classes (constraints in CONTEXT_RETENTION_CLASSES).")
    lines.append("# Retention constraint attached to each retention class.")
    lines.append("CONTEXT_RETENTION_CLASSES: dict[str, dict[str, int | bool]] = {")
    for name in sorted(reg["retentionClasses"]):
        items = ", ".join(
            f'"{k}": {v}' for k, v in _retention_policy_items(reg["retentionClasses"][name])
        )
        lines.append(f'    "{name}": {{{items}}},')
    lines.append("}")
    lines.append("")
    lines += _py_tuple("CAPSULE_TRANSITION_TYPES", reg["capsuleTransitionTypes"],
                       "Why a new context capsule superseded the previous one.")
    lines.append("__all__ = [")
    lines.append('    "CONTEXT_CAPSULE_CONTRACT_VERSION",')
    lines.append('    "LOCATION_SOURCES",')
    lines.append('    "LOCATION_SEMANTICS",')
    lines.append('    "LOCATION_PRECISION_CLASSES",')
    lines.append('    "LOCATION_CONFLICT_STATES",')
    lines.append('    "CONTEXT_STATES",')
    lines.append('    "CONTEXT_RETENTION_CLASS_NAMES",')
    lines.append('    "CONTEXT_RETENTION_CLASSES",')
    lines.append('    "CAPSULE_TRANSITION_TYPES",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_context_capsule_md(reg: dict) -> str:
    lines = _md_header(CONTEXT_CAPSULE_JSON)
    lines.append("# Context Capsule Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines += _md_vocab_section("Location sources", reg["locationSources"])
    lines += _md_vocab_section("Location semantics", reg["locationSemantics"])
    lines += _md_vocab_section("Precision classes", reg["precisionClasses"])
    lines += _md_vocab_section("Conflict states", reg["conflictStates"])
    lines += _md_vocab_section("Context states", reg["contextStates"])
    lines.append("## Retention classes")
    lines.append("")
    lines.append("| Class | Constraint |")
    lines.append("|---|---|")
    for name in sorted(reg["retentionClasses"]):
        items = ", ".join(
            f"{k}={v}" for k, v in _retention_policy_items(reg["retentionClasses"][name])
        )
        lines.append(f"| `{name}` | {items} |")
    lines.append("")
    lines += _md_vocab_section("Capsule transition types", reg["capsuleTransitionTypes"])
    return "\n".join(lines)


def _summary_context_capsule(reg: dict) -> str:
    return (
        f"context-capsule v{reg['contractVersion']} — "
        f"{len(reg['locationSources'])} location sources, "
        f"{len(reg['contextStates'])} context states, "
        f"{len(reg['retentionClasses'])} retention classes"
    )


# ---------------------------------------------------------------------------
# Registry: location (geographic360 Phase 4 — the ONE new canonical geo authority)
# ---------------------------------------------------------------------------

LOCATION_REGISTRY_JSON = CONTRACTS / "location-registry.json"
LOCATION_REGISTRY_TS = ROOT / "packages" / "shared" / "location-registry.ts"
LOCATION_REGISTRY_PY = BACKEND / "shared" / "geo" / "generated_taxonomy.py"
LOCATION_REGISTRY_MD = ROOT / "docs" / "_generated" / "location-registry-table.md"

_LOCATION_VOCAB_KEYS = (
    "locationRoles",
    "regionTypes",
    "precisionClasses",
    "coordinateSystems",
    "cellSchemes",
)


def validate_location_registry(reg: dict, ctx: dict) -> None:
    for key in _LOCATION_VOCAB_KEYS:
        _require_idents("location-registry", key, reg[key])
    # Precision classes must stay aligned with the context-capsule ladder
    # (coarse_cell / precisionClasses) so region and coordinate precision share
    # one vocabulary — geographic360 must never invent a second ladder.
    capsule = json.loads(CONTEXT_CAPSULE_JSON.read_text())
    if reg["precisionClasses"] != capsule["precisionClasses"]:
        _fail(
            "location-registry.precisionClasses must match context-capsule "
            f"precisionClasses ({capsule['precisionClasses']})"
        )


def gen_location_registry_ts(reg: dict) -> str:
    lines = _ts_header(LOCATION_REGISTRY_JSON)
    lines.append(
        f"export const locationRegistryContractVersion = '{reg['contractVersion']}' as const;"
    )
    lines.append("")
    lines += _ts_const_array(
        "locationRoles", "LocationRole", reg["locationRoles"],
        "Role a location fact plays for its subject (residence, egress, venue, ...).",
    )
    lines += _ts_const_array(
        "regionTypes", "RegionType", reg["regionTypes"],
        "Region-type hierarchy (not US-only), continent down to locality.",
    )
    # Precision classes are single-sourced on the context-capsule twin: the
    # ladder is SHARED (validate_location_registry enforces equality against
    # context-capsule-registry.json), so re-exporting context-capsule's
    # declarations here keeps exactly one declaration in the shared barrel —
    # `export *` of both twins would otherwise collide (TS2308). Any direct
    # importer of this module still resolves the same names.
    lines.append(
        "export { locationPrecisionClasses, type LocationPrecisionClass } "
        "from './context-capsule';"
    )
    lines.append("")
    lines += _ts_const_array(
        "coordinateSystems", "CoordinateSystem", reg["coordinateSystems"],
        "Coordinate reference systems a LocationFact may carry.",
    )
    lines += _ts_const_array(
        "cellSchemes", "CellScheme", reg["cellSchemes"],
        "Spatial cell schemes (client-computed strings; never a DB spatial index).",
    )
    return "\n".join(lines)


def gen_location_registry_py(reg: dict) -> str:
    lines = _py_header(
        LOCATION_REGISTRY_JSON,
        "Generated location taxonomy (roles, region types, precision, cells).",
    )
    lines.append(f'LOCATION_REGISTRY_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("LOCATION_ROLES", reg["locationRoles"],
                       "Role a location fact plays for its subject.")
    lines += _py_tuple("REGION_TYPES", reg["regionTypes"],
                       "Region-type hierarchy (not US-only), continent down to locality.")
    lines += _py_tuple("LOCATION_PRECISION_CLASSES", reg["precisionClasses"],
                       "Coarsest-to-finest precision ladder (aligned to context-capsule).")
    lines += _py_tuple("COORDINATE_SYSTEMS", reg["coordinateSystems"],
                       "Coordinate reference systems a LocationFact may carry.")
    lines += _py_tuple("CELL_SCHEMES", reg["cellSchemes"],
                       "Spatial cell schemes (client-computed strings; never a spatial index).")
    lines.append("__all__ = [")
    lines.append('    "LOCATION_REGISTRY_CONTRACT_VERSION",')
    lines.append('    "LOCATION_ROLES",')
    lines.append('    "REGION_TYPES",')
    lines.append('    "LOCATION_PRECISION_CLASSES",')
    lines.append('    "COORDINATE_SYSTEMS",')
    lines.append('    "CELL_SCHEMES",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_location_registry_md(reg: dict) -> str:
    lines = _md_header(LOCATION_REGISTRY_JSON)
    lines.append("# Location Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines += _md_vocab_section("Location roles", reg["locationRoles"])
    lines += _md_vocab_section("Region types", reg["regionTypes"])
    lines += _md_vocab_section("Precision classes", reg["precisionClasses"])
    lines += _md_vocab_section("Coordinate systems", reg["coordinateSystems"])
    lines += _md_vocab_section("Cell schemes", reg["cellSchemes"])
    return "\n".join(lines)


def _summary_location_registry(reg: dict) -> str:
    return (
        f"location-registry v{reg['contractVersion']} — "
        f"{len(reg['locationRoles'])} roles, {len(reg['regionTypes'])} region types, "
        f"{len(reg['precisionClasses'])} precision classes, "
        f"{len(reg['cellSchemes'])} cell schemes"
    )


# ---------------------------------------------------------------------------
# Registry: graph-mutation
# ---------------------------------------------------------------------------

GRAPH_MUTATION_JSON = CONTRACTS / "graph-mutation-registry.json"
GRAPH_MUTATION_TS = ROOT / "packages" / "shared" / "graph-mutation.ts"
GRAPH_MUTATION_PY = BACKEND / "shared" / "graph" / "generated_mutation_taxonomy.py"
GRAPH_MUTATION_MD = ROOT / "docs" / "_generated" / "graph-mutation-table.md"

_GRAPH_MUTATION_VOCAB_KEYS = (
    "mutationTypes",
    "actorKinds",
    "causalityClasses",
    "explanationTypes",
)

# Aggregates a mutation can target (mirrored by the pydantic Literal).
_MUTATION_AGGREGATE_TYPES = ("node", "edge", "cluster", "score")

# TS twin of shared/graph/mutation_models.py::MutationRecord — parity-tested.
# The bitemporal field names (valid_from/valid_to/recorded_at/superseded_at)
# deliberately match shared/graph/edge_properties.py::BITEMPORAL_EDGE_PROPERTIES.
_MUTATION_RECORD_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("mutation_id", "string", True),
    ("tenant_id", "string", True),
    ("aggregate_type", " | ".join(f"'{t}'" for t in _MUTATION_AGGREGATE_TYPES), True),
    ("aggregate_id", "string", True),
    ("operation", "string", True),
    ("actor_kind", "string", False),
    ("actor_id", "string", False),
    ("subject_kind", "string", False),
    ("subject_id", "string", False),
    ("valid_from", "string", False),
    ("valid_to", "string", False),
    ("recorded_at", "string", True),
    ("superseded_at", "string", False),
    ("correlation_id", "string", False),
    ("causation_id", "string", False),
    ("source_event_id", "string", False),
    ("idempotency_key", "string", False),
    ("reason_code", "string", False),
    ("causality_class", "string", False),
    ("confidence", "number", False),
    ("evidence_refs", "string[]", False),
    ("model_refs", "string[]", False),
    ("policy_refs", "string[]", False),
    ("consent_refs", "string[]", False),
    ("before_version_id", "string", False),
    ("after_version_id", "string", False),
    ("change_set_id", "string", False),
    ("schema_version", "string", False),
)

# TS twin of shared/graph/mutation_models.py::DecisionRecord — parity-tested.
# Named GraphDecisionRecord in TS because decision-outcome-intelligence.ts
# already exports a DecisionRecord through the barrel.
_GRAPH_DECISION_RECORD_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("decision_id", "string", True),
    ("tenant_id", "string", True),
    ("decision_type", "string", True),
    ("subject_refs", "string[]", False),
    ("input_fact_versions", "Record<string, string>", False),
    ("graph_watermark", "string", False),
    ("model_versions", "Record<string, string>", False),
    ("policy_versions", "Record<string, string>", False),
    ("decision", "string", False),
    ("confidence", "number", False),
    ("human_override", "boolean", False),
    ("action_observed", "boolean", False),
    ("outcome_refs", "string[]", False),
    ("valid_at", "string", False),
    ("recorded_at", "string", False),
)

# TS twin of shared/graph/mutation_models.py::ChangeSet — parity-tested.
_CHANGE_SET_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("change_set_id", "string", True),
    ("tenant_id", "string", True),
    ("scope_type", "string", False),
    ("scope_id", "string", False),
    ("baseline_ref", "string", False),
    ("target_ref", "string", False),
    ("added_node_count", "number", False),
    ("removed_node_count", "number", False),
    ("changed_edge_count", "number", False),
    ("digest", "string", False),
)


def validate_graph_mutation(reg: dict, ctx: dict) -> None:
    for key in _GRAPH_MUTATION_VOCAB_KEYS:
        _require_idents("graph-mutation-registry", key, reg[key])


def gen_graph_mutation_ts(reg: dict) -> str:
    lines = _ts_header(GRAPH_MUTATION_JSON)
    lines.append(f"export const graphMutationContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "graphMutationTypes", "GraphMutationType", reg["mutationTypes"],
        "Every way the graph plane may change (append-only ledger vocabulary).",
    )
    lines += _ts_const_array(
        "mutationActorKinds", "MutationActorKind", reg["actorKinds"],
        "Who (or what) performed a graph mutation.",
    )
    lines += _ts_const_array(
        "mutationCausalityClasses", "MutationCausalityClass", reg["causalityClasses"],
        "Strength of the causal claim attached to a mutation.",
    )
    lines += _ts_const_array(
        "mutationExplanationTypes", "MutationExplanationType", reg["explanationTypes"],
        "How a mutation (or decision) is explained to reviewers.",
    )
    lines += _ts_interface(
        "MutationRecord",
        _MUTATION_RECORD_FIELDS,
        "One append-only graph mutation; bitemporal field names match "
        "BITEMPORAL_EDGE_PROPERTIES (Python twin: shared/graph/mutation_models.py).",
    )
    lines += _ts_interface(
        "GraphDecisionRecord",
        _GRAPH_DECISION_RECORD_FIELDS,
        "Point-in-time decision snapshot pinned to fact/model/policy versions "
        "(Python twin: DecisionRecord in shared/graph/mutation_models.py).",
    )
    lines += _ts_interface(
        "ChangeSet",
        _CHANGE_SET_FIELDS,
        "Digest of graph deltas between two refs "
        "(Python twin: shared/graph/mutation_models.py).",
    )
    return "\n".join(lines)


def gen_graph_mutation_py(reg: dict) -> str:
    lines = _py_header(
        GRAPH_MUTATION_JSON,
        "Generated graph-mutation taxonomy (mutation types, actors, causality, explanations).",
    )
    lines.append(f'GRAPH_MUTATION_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("GRAPH_MUTATION_TYPES", reg["mutationTypes"],
                       "Every way the graph plane may change (append-only ledger vocabulary).")
    lines += _py_tuple("MUTATION_ACTOR_KINDS", reg["actorKinds"],
                       "Who (or what) performed a graph mutation.")
    lines += _py_tuple("MUTATION_CAUSALITY_CLASSES", reg["causalityClasses"],
                       "Strength of the causal claim attached to a mutation.")
    lines += _py_tuple("MUTATION_EXPLANATION_TYPES", reg["explanationTypes"],
                       "How a mutation (or decision) is explained to reviewers.")
    lines.append("__all__ = [")
    lines.append('    "GRAPH_MUTATION_CONTRACT_VERSION",')
    lines.append('    "GRAPH_MUTATION_TYPES",')
    lines.append('    "MUTATION_ACTOR_KINDS",')
    lines.append('    "MUTATION_CAUSALITY_CLASSES",')
    lines.append('    "MUTATION_EXPLANATION_TYPES",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_graph_mutation_md(reg: dict) -> str:
    lines = _md_header(GRAPH_MUTATION_JSON)
    lines.append("# Graph Mutation Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines += _md_vocab_section("Mutation types", reg["mutationTypes"])
    lines += _md_vocab_section("Actor kinds", reg["actorKinds"])
    lines += _md_vocab_section("Causality classes", reg["causalityClasses"])
    lines += _md_vocab_section("Explanation types", reg["explanationTypes"])
    return "\n".join(lines)


def _summary_graph_mutation(reg: dict) -> str:
    return (
        f"graph-mutation v{reg['contractVersion']} — "
        f"{len(reg['mutationTypes'])} mutation types, "
        f"{len(reg['causalityClasses'])} causality classes"
    )


# ---------------------------------------------------------------------------
# Registry: filter-field
# ---------------------------------------------------------------------------

FILTER_FIELD_JSON = CONTRACTS / "filter-field-registry.json"
CONSENT_REGISTRY_JSON = CONTRACTS / "consent-registry.json"
GRAPH_CONTRACT_TS = ROOT / "packages" / "shared" / "graph-contract.ts"
FILTER_FIELD_TS = ROOT / "packages" / "shared" / "filter-fields.ts"
FILTER_FIELD_PY = BACKEND / "shared" / "exploration" / "generated_fields.py"
FILTER_FIELD_MD = ROOT / "docs" / "_generated" / "filter-field-table.md"

_FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _ts_filter_operators() -> set[str]:
    """The canonical FilterOperator union in graph-contract.ts — never redefined."""
    text = GRAPH_CONTRACT_TS.read_text()
    m = re.search(r"export type FilterOperator =(.*?)\n\n", text, re.S)
    if not m:
        _fail("FilterOperator type not found in packages/shared/graph-contract.ts")
    operators = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    if not operators:
        _fail("FilterOperator union parsed empty from graph-contract.ts")
    return operators


def validate_filter_fields(reg: dict, ctx: dict) -> None:
    for key in ("categories", "dataTypes", "sensitivities"):
        _require_idents("filter-field-registry", key, reg[key])
    categories = set(reg["categories"])
    data_types = set(reg["dataTypes"])
    sensitivities = set(reg["sensitivities"])
    operators_allowed = ctx["filter_operators"]
    consent_purposes = ctx["consent_purposes"]

    if not isinstance(reg["fields"], list) or not reg["fields"]:
        _fail("filter-field-registry.fields must be a non-empty list")
    ids_seen: set[str] = set()
    for field in reg["fields"]:
        fid = field["id"]
        if not _FIELD_ID_RE.match(fid):
            _fail(f"filter field id {fid!r} is not a dotted lower_snake id")
        if fid in ids_seen:
            _fail(f"duplicate filter field id {fid!r}")
        ids_seen.add(fid)
        prefix = fid.split(".", 1)[0]
        if field["category"] not in categories:
            _fail(f"filter field {fid!r} has unknown category {field['category']!r}")
        if prefix != field["category"]:
            _fail(f"filter field {fid!r} prefix must match its category {field['category']!r}")
        if not isinstance(field["label"], str) or not field["label"]:
            _fail(f"filter field {fid!r} must have a non-empty label")
        if field["dataType"] not in data_types:
            _fail(f"filter field {fid!r} has unknown dataType {field['dataType']!r}")
        ops = field["operators"]
        if not isinstance(ops, list) or not ops or len(set(ops)) != len(ops):
            _fail(f"filter field {fid!r} operators must be a non-empty unique list")
        unknown_ops = set(ops) - operators_allowed
        if unknown_ops:
            _fail(
                f"filter field {fid!r} uses operators {sorted(unknown_ops)} not in the "
                "FilterOperator union of packages/shared/graph-contract.ts"
            )
        if field["sensitivity"] not in sensitivities:
            _fail(f"filter field {fid!r} has unknown sensitivity {field['sensitivity']!r}")
        if "consentPurpose" in field and field["consentPurpose"] not in consent_purposes:
            _fail(
                f"filter field {fid!r} consentPurpose {field['consentPurpose']!r} is not a "
                "purpose key in consent-registry.json"
            )
        if "minimumCohortSize" in field:
            size = field["minimumCohortSize"]
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                _fail(f"filter field {fid!r} minimumCohortSize must be a positive integer")
        unknown_keys = set(field) - {
            "id", "label", "category", "dataType", "operators", "sensitivity",
            "consentPurpose", "minimumCohortSize",
        }
        if unknown_keys:
            _fail(f"filter field {fid!r} has unknown keys {sorted(unknown_keys)}")


def gen_filter_fields_ts(reg: dict) -> str:
    lines = _ts_header(FILTER_FIELD_JSON)
    lines.append("import type { FilterOperator } from './graph-contract';")
    lines.append("")
    lines.append(f"export const filterFieldsContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "filterFieldCategories", "FilterFieldCategory", reg["categories"],
        "Categories a filterable field can belong to.",
    )
    lines += _ts_const_array(
        "filterFieldDataTypes", "FilterFieldDataType", reg["dataTypes"],
        "Value shape of a filterable field.",
    )
    lines += _ts_const_array(
        "filterFieldSensitivities", "FilterFieldSensitivity", reg["sensitivities"],
        "Governance sensitivity of a filterable field.",
    )
    lines.append("/** One filterable field: operators are a subset of the canonical FilterOperator union. */")
    lines.append("export interface FilterFieldDefinition {")
    lines.append("  id: string;")
    lines.append("  label: string;")
    lines.append("  category: FilterFieldCategory;")
    lines.append("  dataType: FilterFieldDataType;")
    lines.append("  operators: readonly FilterOperator[];")
    lines.append("  sensitivity: FilterFieldSensitivity;")
    lines.append("  consentPurpose?: string;")
    lines.append("  minimumCohortSize?: number;")
    lines.append("}")
    lines.append("")
    lines.append("/** Canonical filter-field registry (sorted by id). */")
    lines.append("export const filterFields: readonly FilterFieldDefinition[] = [")
    for field in sorted(reg["fields"], key=lambda f: f["id"]):
        lines.append("  {")
        lines.append(f"    id: '{field['id']}',")
        lines.append(f"    label: '{field['label']}',")
        lines.append(f"    category: '{field['category']}',")
        lines.append(f"    dataType: '{field['dataType']}',")
        ops = ", ".join(f"'{op}'" for op in field["operators"])
        lines.append(f"    operators: [{ops}],")
        lines.append(f"    sensitivity: '{field['sensitivity']}',")
        if "consentPurpose" in field:
            lines.append(f"    consentPurpose: '{field['consentPurpose']}',")
        if "minimumCohortSize" in field:
            lines.append(f"    minimumCohortSize: {field['minimumCohortSize']},")
        lines.append("  },")
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


def gen_filter_fields_py(reg: dict) -> str:
    lines = _py_header(
        FILTER_FIELD_JSON,
        "Generated filter-field registry (categories, data types, sensitivities, fields).",
    )
    lines.append(f'FILTER_FIELDS_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("FILTER_FIELD_CATEGORIES", reg["categories"],
                       "Categories a filterable field can belong to.")
    lines += _py_tuple("FILTER_FIELD_DATA_TYPES", reg["dataTypes"],
                       "Value shape of a filterable field.")
    lines += _py_tuple("FILTER_FIELD_SENSITIVITIES", reg["sensitivities"],
                       "Governance sensitivity of a filterable field.")
    lines.append("# Canonical filter-field registry keyed by dotted field id (sorted).")
    lines.append("# operators are a subset of the canonical FilterOperator union in")
    lines.append("# packages/shared/graph-contract.ts — never a second filter system.")
    lines.append("FILTER_FIELDS: dict[str, dict] = {")
    for field in sorted(reg["fields"], key=lambda f: f["id"]):
        lines.append(f'    "{field["id"]}": {{')
        lines.append(f'        "label": "{field["label"]}",')
        lines.append(f'        "category": "{field["category"]}",')
        lines.append(f'        "data_type": "{field["dataType"]}",')
        ops = ", ".join(f'"{op}"' for op in field["operators"])
        lines.append(f'        "operators": ({ops}{"," if len(field["operators"]) == 1 else ""}),')
        lines.append(f'        "sensitivity": "{field["sensitivity"]}",')
        if "consentPurpose" in field:
            lines.append(f'        "consent_purpose": "{field["consentPurpose"]}",')
        if "minimumCohortSize" in field:
            lines.append(f'        "minimum_cohort_size": {field["minimumCohortSize"]},')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "FILTER_FIELDS_CONTRACT_VERSION",')
    lines.append('    "FILTER_FIELD_CATEGORIES",')
    lines.append('    "FILTER_FIELD_DATA_TYPES",')
    lines.append('    "FILTER_FIELD_SENSITIVITIES",')
    lines.append('    "FILTER_FIELDS",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_filter_fields_md(reg: dict) -> str:
    lines = _md_header(FILTER_FIELD_JSON)
    lines.append("# Filter Field Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append(f"Categories: {', '.join(f'`{c}`' for c in reg['categories'])}")
    lines.append("")
    lines.append("| Field | Label | Category | Type | Operators | Sensitivity | Consent purpose | Min cohort |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for field in sorted(reg["fields"], key=lambda f: f["id"]):
        ops = ", ".join(f"`{op}`" for op in field["operators"])
        consent = f"`{field['consentPurpose']}`" if "consentPurpose" in field else "—"
        cohort = str(field["minimumCohortSize"]) if "minimumCohortSize" in field else "—"
        lines.append(
            f"| `{field['id']}` | {field['label']} | {field['category']} | "
            f"{field['dataType']} | {ops} | {field['sensitivity']} | {consent} | {cohort} |"
        )
    lines.append("")
    return "\n".join(lines)


def _summary_filter_fields(reg: dict) -> str:
    return (
        f"filter-field v{reg['contractVersion']} — "
        f"{len(reg['fields'])} fields across {len(reg['categories'])} categories"
    )


# ---------------------------------------------------------------------------
# Registry: surface-capability
# ---------------------------------------------------------------------------

SURFACE_CAPABILITY_JSON = CONTRACTS / "surface-capability-registry.json"
SURFACE_CAPABILITY_TS = ROOT / "packages" / "shared" / "surface-capabilities.ts"
SURFACE_CAPABILITY_PY = BACKEND / "shared" / "exploration" / "generated_surfaces.py"
SURFACE_CAPABILITY_MD = ROOT / "docs" / "_generated" / "surface-capability-table.md"

_SURFACE_BOOL_KEYS = (
    "supportsFacets",
    "supportsComparison",
    "supportsSelectionSets",
    "supportsSavedViews",
    "supportsExport",
)


def _exploration_contract_vocab(name: str) -> set[str]:
    """Vocabulary owned by the hand-authored exploration-contract.ts."""
    import re as _re

    text = (ROOT / "packages" / "shared" / "exploration-contract.ts").read_text()
    m = _re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, _re.S)
    if not m:
        _fail(f"exploration-contract.ts const array {name!r} not found")
    return set(_re.findall(r"'([a-z_]+)'", m.group(1)))


def validate_surface_capabilities(reg: dict, ctx: dict) -> None:
    for key in ("temporalModes", "views", "filterDispositions"):
        _require_idents("surface-capability-registry", key, reg[key])
    # Single vocabulary owner: exploration-contract.ts. The registry's copies
    # must match exactly (the generated TS imports the types instead of
    # re-declaring the consts — no barrel collisions).
    for json_key, ts_name in (
        ("temporalModes", "explorationTemporalModes"),
        ("views", "explorationViews"),
        ("filterDispositions", "filterDispositions"),
    ):
        owner = _exploration_contract_vocab(ts_name)
        if set(reg[json_key]) != owner:
            _fail(
                f"surface-capability-registry.{json_key} drifted from "
                f"exploration-contract.ts {ts_name}: registry-only="
                f"{sorted(set(reg[json_key]) - owner)}, contract-only="
                f"{sorted(owner - set(reg[json_key]))}"
            )
    temporal_modes = set(reg["temporalModes"])
    views = set(reg["views"])
    field_categories = ctx["filter_field_categories"]

    if not isinstance(reg["surfaces"], list) or not reg["surfaces"]:
        _fail("surface-capability-registry.surfaces must be a non-empty list")
    ids_seen: set[str] = set()
    for surface in reg["surfaces"]:
        sid = surface["surfaceId"]
        if not _IDENT_RE.match(sid):
            _fail(f"surfaceId {sid!r} is not a lower_snake identifier")
        if sid in ids_seen:
            _fail(f"duplicate surfaceId {sid!r}")
        ids_seen.add(sid)
        for key, allowed, source in (
            ("supportedFieldCategories", field_categories, "filter-field-registry categories"),
            ("supportedTemporalModes", temporal_modes, "temporalModes"),
            ("supportedViews", views, "views"),
        ):
            values = surface[key]
            if not isinstance(values, list) or not values or len(set(values)) != len(values):
                _fail(f"surface {sid!r} {key} must be a non-empty unique list")
            unknown = set(values) - allowed
            if unknown:
                _fail(f"surface {sid!r} {key} has values {sorted(unknown)} outside {source}")
        for key in _SURFACE_BOOL_KEYS:
            if not isinstance(surface[key], bool):
                _fail(f"surface {sid!r} {key} must be a boolean")
        unknown_keys = set(surface) - {
            "surfaceId", "supportedFieldCategories", "supportedTemporalModes",
            "supportedViews", *_SURFACE_BOOL_KEYS,
        }
        if unknown_keys:
            _fail(f"surface {sid!r} has unknown keys {sorted(unknown_keys)}")


def gen_surface_capabilities_ts(reg: dict) -> str:
    surfaces = sorted(reg["surfaces"], key=lambda s: s["surfaceId"])
    lines = _ts_header(SURFACE_CAPABILITY_JSON)
    lines.append("import type { FilterFieldCategory } from './filter-fields';")
    lines.append("// Vocabulary owner: exploration-contract.ts — the registry's copies are")
    lines.append("// validated equal at generation time (single source, no barrel collisions).")
    lines.append("import type {")
    lines.append("  ExplorationTemporalMode,")
    lines.append("  ExplorationView,")
    lines.append("} from './exploration-contract';")
    lines.append("")
    lines.append(f"export const surfaceCapabilitiesContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "explorationSurfaceIds", "ExplorationSurfaceId",
        [s["surfaceId"] for s in surfaces],
        "Exploration surfaces registered with the fabric (sorted).",
    )
    lines.append("/** Declared capabilities of one exploration surface. */")
    lines.append("export interface SurfaceCapability {")
    lines.append("  surfaceId: ExplorationSurfaceId;")
    lines.append("  supportedFieldCategories: readonly FilterFieldCategory[];")
    lines.append("  supportedTemporalModes: readonly ExplorationTemporalMode[];")
    lines.append("  supportedViews: readonly ExplorationView[];")
    lines.append("  supportsFacets: boolean;")
    lines.append("  supportsComparison: boolean;")
    lines.append("  supportsSelectionSets: boolean;")
    lines.append("  supportsSavedViews: boolean;")
    lines.append("  supportsExport: boolean;")
    lines.append("}")
    lines.append("")
    lines.append("export const surfaceCapabilities: Record<ExplorationSurfaceId, SurfaceCapability> = {")
    for surface in surfaces:
        lines.append(f"  {surface['surfaceId']}: {{")
        lines.append(f"    surfaceId: '{surface['surfaceId']}',")
        for key in ("supportedFieldCategories", "supportedTemporalModes", "supportedViews"):
            values = ", ".join(f"'{v}'" for v in surface[key])
            lines.append(f"    {key}: [{values}],")
        for key in _SURFACE_BOOL_KEYS:
            lines.append(f"    {key}: {str(surface[key]).lower()},")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def gen_surface_capabilities_py(reg: dict) -> str:
    surfaces = sorted(reg["surfaces"], key=lambda s: s["surfaceId"])
    lines = _py_header(
        SURFACE_CAPABILITY_JSON,
        "Generated surface-capability registry (surfaces, temporal modes, views, dispositions).",
    )
    lines.append(f'SURFACE_CAPABILITIES_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("EXPLORATION_SURFACE_IDS", [s["surfaceId"] for s in surfaces],
                       "Exploration surfaces registered with the fabric (sorted).")
    lines += _py_tuple("EXPLORATION_TEMPORAL_MODES", reg["temporalModes"],
                       "Temporal query modes a surface may support.")
    lines += _py_tuple("EXPLORATION_VIEWS", reg["views"],
                       "Render views a surface may support.")
    lines += _py_tuple("FILTER_DISPOSITIONS", reg["filterDispositions"],
                       "What the fabric did with one filter on one surface — never silently dropped.")
    lines.append("# Declared capabilities per surface (sorted by surface id).")
    lines.append("SURFACE_CAPABILITIES: dict[str, dict] = {")
    for surface in surfaces:
        lines.append(f'    "{surface["surfaceId"]}": {{')
        for json_key, py_key in (
            ("supportedFieldCategories", "supported_field_categories"),
            ("supportedTemporalModes", "supported_temporal_modes"),
            ("supportedViews", "supported_views"),
        ):
            values = ", ".join(f'"{v}"' for v in surface[json_key])
            if len(surface[json_key]) == 1:
                values += ","
            lines.append(f'        "{py_key}": ({values}),')
        for json_key, py_key in (
            ("supportsFacets", "supports_facets"),
            ("supportsComparison", "supports_comparison"),
            ("supportsSelectionSets", "supports_selection_sets"),
            ("supportsSavedViews", "supports_saved_views"),
            ("supportsExport", "supports_export"),
        ):
            lines.append(f'        "{py_key}": {surface[json_key]},')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "SURFACE_CAPABILITIES_CONTRACT_VERSION",')
    lines.append('    "EXPLORATION_SURFACE_IDS",')
    lines.append('    "EXPLORATION_TEMPORAL_MODES",')
    lines.append('    "EXPLORATION_VIEWS",')
    lines.append('    "FILTER_DISPOSITIONS",')
    lines.append('    "SURFACE_CAPABILITIES",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_surface_capabilities_md(reg: dict) -> str:
    surfaces = sorted(reg["surfaces"], key=lambda s: s["surfaceId"])
    lines = _md_header(SURFACE_CAPABILITY_JSON)
    lines.append("# Surface Capability Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines += _md_vocab_section("Temporal modes", reg["temporalModes"])
    lines += _md_vocab_section("Views", reg["views"])
    lines += _md_vocab_section("Filter dispositions", reg["filterDispositions"])
    lines.append("## Surfaces")
    lines.append("")
    lines.append(
        "| Surface | Field categories | Temporal modes | Views | Facets | Comparison | "
        "Selection sets | Saved views | Export |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for surface in surfaces:
        cats = ", ".join(f"`{c}`" for c in surface["supportedFieldCategories"])
        modes = ", ".join(f"`{m}`" for m in surface["supportedTemporalModes"])
        views = ", ".join(f"`{v}`" for v in surface["supportedViews"])
        flags = " | ".join("yes" if surface[k] else "no" for k in _SURFACE_BOOL_KEYS)
        lines.append(f"| `{surface['surfaceId']}` | {cats} | {modes} | {views} | {flags} |")
    lines.append("")
    return "\n".join(lines)


def _summary_surface_capabilities(reg: dict) -> str:
    return (
        f"surface-capability v{reg['contractVersion']} — "
        f"{len(reg['surfaces'])} surfaces, {len(reg['filterDispositions'])} filter dispositions"
    )


# ---------------------------------------------------------------------------
# Registry: comparison
# ---------------------------------------------------------------------------

COMPARISON_JSON = CONTRACTS / "comparison-registry.json"
COMPARISON_TS = ROOT / "packages" / "shared" / "comparison-contract.ts"
COMPARISON_PY = BACKEND / "services" / "intelligence" / "comparison" / "generated_vocabulary.py"
COMPARISON_MD = ROOT / "docs" / "_generated" / "comparison-table.md"

# (json key, TS const, TS type, Python tuple, doc)
_COMPARISON_VOCABS: tuple[tuple[str, str, str, str, str], ...] = (
    ("comparisonModes", "comparisonModes", "ComparisonMode", "COMPARISON_MODES",
     "What is being compared against what."),
    ("baselineTypes", "baselineTypes", "BaselineType", "BASELINE_TYPES",
     "Where the baseline side of a comparison comes from."),
    ("alignmentOutcomes", "alignmentOutcomes", "AlignmentOutcome", "ALIGNMENT_OUTCOMES",
     "How well the two sides could be aligned before comparing."),
    ("runStates", "comparisonRunStates", "ComparisonRunState", "COMPARISON_RUN_STATES",
     "Lifecycle states of a comparison run."),
    ("severities", "comparisonSeverities", "ComparisonSeverity", "COMPARISON_SEVERITIES",
     "Severity ladder for comparison findings."),
    ("dispositions", "comparisonDispositions", "ComparisonDisposition", "COMPARISON_DISPOSITIONS",
     "Recommended handling of a comparison finding."),
    ("factLinkageStates", "factLinkageStates", "FactLinkageState", "FACT_LINKAGE_STATES",
     "How a finding's supporting facts are linked to the subject."),
    ("causalClaimLevels", "causalClaimLevels", "CausalClaimLevel", "CAUSAL_CLAIM_LEVELS",
     "Strength ladder for causal claims attached to a finding."),
    ("comparisonDimensions", "comparisonDimensions", "ComparisonDimension", "COMPARISON_DIMENSIONS",
     "Dimensions along which two subjects can be compared."),
    ("materialityComponents", "materialityComponents", "MaterialityComponent", "MATERIALITY_COMPONENTS",
     "Components blended into a finding's materiality score."),
)

# TS twin of services/intelligence/comparison/contracts.py::ComparisonSubject.
_COMPARISON_SUBJECT_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("subject_type", "string", True),
    ("subject_id", "string", True),
    ("tenant_id", "string", False),
    ("label", "string", False),
    ("as_of", "string", False),
)

# TS twin of services/intelligence/comparison/contracts.py::BaselineSpec.
_BASELINE_SPEC_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("baseline_type", "string", True),
    ("subject", "ComparisonSubject", False),
    ("window_start", "string", False),
    ("window_end", "string", False),
    ("rolling_window_days", "number", False),
    ("cohort_definition_id", "string", False),
    ("policy_id", "string", False),
    ("scenario_id", "string", False),
)

# TS twin of services/intelligence/comparison/contracts.py::ComparisonDefinition.
_COMPARISON_DEFINITION_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("definition_id", "string", True),
    ("tenant_id", "string", True),
    ("name", "string", False),
    ("mode", "string", True),
    ("subject", "ComparisonSubject", True),
    ("baseline", "BaselineSpec", True),
    ("dimensions", "string[]", False),
    ("temporal_mode", "string", False),
    ("created_at", "string", False),
    ("created_by", "string", False),
    ("schema_version", "string", False),
)

# TS twin of services/intelligence/comparison/contracts.py::ComparisonRun.
_COMPARISON_RUN_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("run_id", "string", True),
    ("definition_id", "string", True),
    ("tenant_id", "string", True),
    ("state", "string", True),
    ("requested_at", "string", False),
    ("started_at", "string", False),
    ("completed_at", "string", False),
    ("as_of", "string", False),
    ("graph_watermark", "string", False),
    ("alignment_outcome", "string", False),
    ("finding_count", "number", False),
    ("degraded_reason", "string", False),
    ("error_code", "string", False),
    ("schema_version", "string", False),
)

# TS twin of services/intelligence/comparison/contracts.py::ComparisonFinding.
_COMPARISON_FINDING_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("id", "string", True),
    ("comparison_run_id", "string", True),
    ("tenant_id", "string", True),
    ("finding_type", "string", True),
    ("title", "string", False),
    ("narrative", "string", False),
    ("subject_refs", "string[]", False),
    ("dimension", "string", False),
    ("metric", "string", False),
    ("observed_value", "number", False),
    ("baseline_value", "number", False),
    ("delta", "number", False),
    ("normalized_delta", "number", False),
    ("direction", "string", False),
    ("severity", "string", False),
    ("materiality", "number", False),
    ("confidence", "number", False),
    ("evidence_status", "string", False),
    ("reconciliation_state", "string", False),
    ("first_observed_at", "string", False),
    ("last_observed_at", "string", False),
    ("persistence", "number", False),
    ("affected_entity_count", "number", False),
    ("economic_impact", "number", False),
    ("risk_impact", "number", False),
    ("policy_impact", "number", False),
    ("recommended_disposition", "string", False),
    ("recommendation_id", "string", False),
    ("investigation_id", "string", False),
    ("suppression_reason", "string", False),
)


def validate_comparison(reg: dict, ctx: dict) -> None:
    for json_key, _ts_const, _ts_type, _py_name, _doc in _COMPARISON_VOCABS:
        _require_idents("comparison-registry", json_key, reg[json_key])


def gen_comparison_ts(reg: dict) -> str:
    lines = _ts_header(COMPARISON_JSON)
    lines.append(f"export const comparisonContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    for json_key, ts_const, ts_type, _py_name, doc in _COMPARISON_VOCABS:
        lines += _ts_const_array(ts_const, ts_type, reg[json_key], doc)
    lines += _ts_interface(
        "ComparisonSubject",
        _COMPARISON_SUBJECT_FIELDS,
        "One side of a comparison "
        "(Python twin: services/intelligence/comparison/contracts.py).",
    )
    lines += _ts_interface(
        "BaselineSpec",
        _BASELINE_SPEC_FIELDS,
        "How the baseline side of a comparison is resolved "
        "(Python twin: services/intelligence/comparison/contracts.py).",
    )
    lines += _ts_interface(
        "ComparisonDefinition",
        _COMPARISON_DEFINITION_FIELDS,
        "Saved definition of a comparison "
        "(Python twin: services/intelligence/comparison/contracts.py).",
    )
    lines += _ts_interface(
        "ComparisonRun",
        _COMPARISON_RUN_FIELDS,
        "One execution of a comparison definition "
        "(Python twin: services/intelligence/comparison/contracts.py).",
    )
    lines += _ts_interface(
        "ComparisonFinding",
        _COMPARISON_FINDING_FIELDS,
        "One materiality-scored difference surfaced by a comparison run "
        "(Python twin: services/intelligence/comparison/contracts.py).",
    )
    return "\n".join(lines)


def gen_comparison_py(reg: dict) -> str:
    lines = _py_header(
        COMPARISON_JSON,
        "Generated comparison vocabulary (modes, baselines, states, severities, materiality).",
    )
    lines.append(f'COMPARISON_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    for json_key, _ts_const, _ts_type, py_name, doc in _COMPARISON_VOCABS:
        lines += _py_tuple(py_name, reg[json_key], doc)
    lines.append("__all__ = [")
    lines.append('    "COMPARISON_CONTRACT_VERSION",')
    for _json_key, _ts_const, _ts_type, py_name, _doc in _COMPARISON_VOCABS:
        lines.append(f'    "{py_name}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_comparison_md(reg: dict) -> str:
    lines = _md_header(COMPARISON_JSON)
    lines.append("# Comparison Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    titles = {
        "comparisonModes": "Comparison modes",
        "baselineTypes": "Baseline types",
        "alignmentOutcomes": "Alignment outcomes",
        "runStates": "Run states",
        "severities": "Severities",
        "dispositions": "Dispositions",
        "factLinkageStates": "Fact linkage states",
        "causalClaimLevels": "Causal claim levels",
        "comparisonDimensions": "Comparison dimensions",
        "materialityComponents": "Materiality components",
    }
    for json_key, _ts_const, _ts_type, _py_name, _doc in _COMPARISON_VOCABS:
        lines += _md_vocab_section(titles[json_key], reg[json_key])
    return "\n".join(lines)


def _summary_comparison(reg: dict) -> str:
    return (
        f"comparison v{reg['contractVersion']} — "
        f"{len(reg['comparisonModes'])} modes, {len(reg['comparisonDimensions'])} dimensions, "
        f"{len(reg['materialityComponents'])} materiality components"
    )


# ---------------------------------------------------------------------------
# Registry: projector-ownership (WP2.4 — Silver projection plane)
# ---------------------------------------------------------------------------

PROJECTOR_OWNERSHIP_JSON = CONTRACTS / "projector-ownership-registry.json"
PROJECTOR_OWNERSHIP_PY = BACKEND / "services" / "silver" / "generated_ownership.py"
PROJECTOR_OWNERSHIP_MD = ROOT / "docs" / "_generated" / "projector-ownership-table.md"

_PROJECTOR_LIST_KEYS = (
    "eventFamilies",
    "eventTypes",
    "ownedActivityEventTypes",
    "convergentActivityEventTypes",
    "unregisteredEventTypes",
)


def validate_projector_ownership(reg: dict, ctx: dict) -> None:
    """Internal consistency of the ownership registry (registry-vs-dispatcher
    parity is enforced separately by scripts/validate_projector_ownership.py)."""
    roles = set(reg["activityRoles"])
    statuses = set(reg["noProjectionStatuses"])
    event_families: set[str] = ctx["event_families"]

    names_seen: set[str] = set()
    owned_families: set[str] = set()
    owner_by_type: dict[str, str] = {}
    for entry in reg["projectors"]:
        name = entry["name"]
        if name in names_seen:
            _fail(f"duplicate projector entry {name!r}")
        names_seen.add(name)
        if entry["activityRole"] not in roles:
            _fail(f"projector {name!r} has unknown activityRole {entry['activityRole']!r}")
        if not entry.get("table"):
            _fail(f"projector {name!r} is missing its silver table")
        for key in _PROJECTOR_LIST_KEYS:
            values = entry.get(key)
            if values is None:
                continue
            if values != sorted(values):
                _fail(f"projector {name!r}.{key} must be sorted")
            if len(set(values)) != len(values):
                _fail(f"projector {name!r}.{key} has duplicates")
        types = set(entry["eventTypes"])
        unregistered = set(entry.get("unregisteredEventTypes", ()))
        if not unregistered <= types:
            _fail(f"projector {name!r}: unregisteredEventTypes must be a subset of eventTypes")
        owned = set(entry["ownedActivityEventTypes"])
        convergent = set(entry.get("convergentActivityEventTypes", ()))
        if not owned <= types or not convergent <= types:
            _fail(f"projector {name!r}: activity event types must be a subset of eventTypes")
        if owned & convergent:
            _fail(f"projector {name!r}: owned and convergent activity types overlap")
        if entry["activityRole"] == "no_activity" and (owned or convergent):
            _fail(f"projector {name!r}: no_activity projectors cannot emit canonical activity")
        unknown_families = set(entry["eventFamilies"]) - event_families
        if unknown_families:
            _fail(f"projector {name!r} references unknown families {sorted(unknown_families)}")
        owned_families |= set(entry["eventFamilies"])
        for event_type in owned:
            # ADR-C4: no event type may be claimed by two activity owners.
            if event_type in owner_by_type:
                _fail(
                    f"event type {event_type!r} claimed by two activity owners: "
                    f"{owner_by_type[event_type]!r} and {name!r}"
                )
            owner_by_type[event_type] = name

    no_projection_families: set[str] = set()
    for entry in reg["noProjection"]:
        family = entry["family"]
        if family in no_projection_families:
            _fail(f"duplicate noProjection family {family!r}")
        no_projection_families.add(family)
        if entry["status"] not in statuses:
            _fail(f"noProjection[{family!r}] has unknown status {entry['status']!r}")
        if family not in event_families:
            _fail(f"noProjection references unknown family {family!r}")
        if family in owned_families:
            _fail(f"family {family!r} is both projected and declared noProjection")

    uncovered = event_families - owned_families - no_projection_families
    if uncovered:
        _fail(
            "event families neither owned by a projector nor declared noProjection: "
            f"{sorted(uncovered)}"
        )
    if not any(e["name"] == "SilverGraphProjector" for e in reg["outOfBand"]):
        _fail("outOfBand must declare the SilverGraphProjector")


def gen_projector_ownership_py(reg: dict) -> str:
    lines = _py_header(
        PROJECTOR_OWNERSHIP_JSON,
        "Generated Silver projector ownership (dispatcher order, activity owners, gaps).",
    )
    lines.append(
        f'PROJECTOR_OWNERSHIP_CONTRACT_VERSION = "{reg["contractVersion"]}"'
    )
    lines.append("")
    lines.append("# Deterministic dispatcher order (ADR-C3) — must match _ALL_PROJECTORS.")
    lines.append("PROJECTOR_ORDER: tuple[str, ...] = (")
    for entry in reg["projectors"]:
        lines.append(f'    "{entry["name"]}",')
    lines.append(")")
    lines.append("")
    lines.append("# Silver table each projector writes.")
    lines.append("PROJECTOR_TABLES: dict[str, str] = {")
    for entry in reg["projectors"]:
        lines.append(f'    "{entry["name"]}": "{entry["table"]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Canonical-activity role per projector (ADR-C4).")
    lines.append("PROJECTOR_ACTIVITY_ROLES: dict[str, str] = {")
    for entry in reg["projectors"]:
        lines.append(f'    "{entry["name"]}": "{entry["activityRole"]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Event-registry families each projector projects facts for.")
    lines.append("PROJECTOR_EVENT_FAMILIES: dict[str, tuple[str, ...]] = {")
    for entry in reg["projectors"]:
        joined = ", ".join(f'"{f}"' for f in entry["eventFamilies"])
        if len(entry["eventFamilies"]) == 1:
            joined += ","
        lines.append(f'    "{entry["name"]}": ({joined}),')
    lines.append("}")
    lines.append("")
    lines.append("# Exact dispatcher handles per projector.")
    lines.append("PROJECTOR_EVENT_TYPES: dict[str, tuple[str, ...]] = {")
    for entry in reg["projectors"]:
        lines.append(f'    "{entry["name"]}": (')
        for event_type in entry["eventTypes"]:
            lines.append(f'        "{event_type}",')
        lines.append("    ),")
    lines.append("}")
    lines.append("")
    lines.append("# ADR-C4: the single canonical-activity owner per event type.")
    lines.append("ACTIVITY_OWNER_BY_EVENT_TYPE: dict[str, str] = {")
    owner_by_type: dict[str, str] = {}
    for entry in reg["projectors"]:
        for event_type in entry["ownedActivityEventTypes"]:
            owner_by_type[event_type] = entry["name"]
    for event_type in sorted(owner_by_type):
        lines.append(f'    "{event_type}": "{owner_by_type[event_type]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Later adapter-backed emitters converging on the owner's activity row.")
    lines.append("CONVERGENT_ACTIVITY_EVENT_TYPES: dict[str, tuple[str, ...]] = {")
    for entry in reg["projectors"]:
        convergent = entry.get("convergentActivityEventTypes")
        if not convergent:
            continue
        joined = ", ".join(f'"{t}"' for t in convergent)
        if len(convergent) == 1:
            joined += ","
        lines.append(f'    "{entry["name"]}": ({joined}),')
    lines.append("}")
    lines.append("")
    lines.append("# Accepted event families with no dispatcher projector (family → status).")
    lines.append("NO_PROJECTION_FAMILIES: dict[str, str] = {")
    for entry in sorted(reg["noProjection"], key=lambda e: e["family"]):
        lines.append(f'    "{entry["family"]}": "{entry["status"]}",')
    lines.append("}")
    lines.append("")
    out_of_band = ", ".join(f'"{e["name"]}"' for e in reg["outOfBand"])
    if len(reg["outOfBand"]) == 1:
        out_of_band += ","
    lines.append("# Dispatcher stages outside the fact-projector list.")
    lines.append(f"OUT_OF_BAND_PROJECTORS: tuple[str, ...] = ({out_of_band})")
    lines.append("")
    lines.append("__all__ = [")
    for name in (
        "PROJECTOR_OWNERSHIP_CONTRACT_VERSION",
        "PROJECTOR_ORDER",
        "PROJECTOR_TABLES",
        "PROJECTOR_ACTIVITY_ROLES",
        "PROJECTOR_EVENT_FAMILIES",
        "PROJECTOR_EVENT_TYPES",
        "ACTIVITY_OWNER_BY_EVENT_TYPE",
        "CONVERGENT_ACTIVITY_EVENT_TYPES",
        "NO_PROJECTION_FAMILIES",
        "OUT_OF_BAND_PROJECTORS",
    ):
        lines.append(f'    "{name}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_projector_ownership_md(reg: dict) -> str:
    lines = _md_header(PROJECTOR_OWNERSHIP_JSON)
    lines.append("# Silver Projector Ownership Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append(
        "Projectors in EXACT dispatcher order (ADR-C3). Activity ownership is "
        "ADR-C4: one real-world event, one canonical activity owner."
    )
    lines.append("")
    lines.append("| # | Projector | Table | Activity role | Families | Types | Owned activity types |")
    lines.append("|---|---|---|---|---|---|---|")
    for position, entry in enumerate(reg["projectors"], start=1):
        families = ", ".join(f"`{f}`" for f in entry["eventFamilies"]) or "—"
        lines.append(
            f"| {position} | `{entry['name']}` | `{entry['table']}` "
            f"| {entry['activityRole']} | {families} "
            f"| {len(entry['eventTypes'])} | {len(entry['ownedActivityEventTypes'])} |"
        )
    lines.append("")
    convergent_rows = [
        (entry["name"], entry["convergentActivityEventTypes"])
        for entry in reg["projectors"]
        if entry.get("convergentActivityEventTypes")
    ]
    if convergent_rows:
        lines.append("## Convergent activity emitters")
        lines.append("")
        lines.append(
            "These projectors also emit canonical activity for the listed event "
            "types but converge on the owner's row via the idempotent upsert."
        )
        lines.append("")
        lines.append("| Projector | Event types |")
        lines.append("|---|---|")
        for name, types in convergent_rows:
            lines.append(f"| `{name}` | {', '.join(f'`{t}`' for t in types)} |")
        lines.append("")
    unregistered_rows = [
        (entry["name"], entry["unregisteredEventTypes"])
        for entry in reg["projectors"]
        if entry.get("unregisteredEventTypes")
    ]
    if unregistered_rows:
        lines.append("## Handled types absent from the event registry")
        lines.append("")
        lines.append("| Projector | Event types |")
        lines.append("|---|---|")
        for name, types in unregistered_rows:
            lines.append(f"| `{name}` | {', '.join(f'`{t}`' for t in types)} |")
        lines.append("")
    lines.append("## Families with no projector")
    lines.append("")
    lines.append("| Family | Status | Target tables | Reason |")
    lines.append("|---|---|---|---|")
    for entry in sorted(reg["noProjection"], key=lambda e: e["family"]):
        targets = ", ".join(f"`{t}`" for t in entry.get("targetTables", ())) or "—"
        lines.append(
            f"| `{entry['family']}` | {entry['status']} | {targets} | {entry['reason']} |"
        )
    lines.append("")
    lines.append("## Out-of-band stages")
    lines.append("")
    for entry in reg["outOfBand"]:
        lines.append(f"- `{entry['name']}` ({entry['role']}): {entry['description']}")
    lines.append("")
    return "\n".join(lines)


def _summary_projector_ownership(reg: dict) -> str:
    owned = sum(len(e["ownedActivityEventTypes"]) for e in reg["projectors"])
    return (
        f"projector ownership v{reg['contractVersion']} — "
        f"{len(reg['projectors'])} projectors, {owned} activity-owned event types, "
        f"{len(reg['noProjection'])} no-projection families"
    )


# ---------------------------------------------------------------------------
# Registry: model-registry (model-harness LLM catalog)
# ---------------------------------------------------------------------------

MODEL_REGISTRY_JSON = CONTRACTS / "model-registry.json"
MODEL_REGISTRY_TS = ROOT / "packages" / "shared" / "model-registry.ts"
MODEL_REGISTRY_PY = BACKEND / "shared" / "model_governance" / "generated_model_registry.py"
MODEL_REGISTRY_MD = ROOT / "docs" / "_generated" / "model-registry-table.md"

_MODEL_REGISTRY_VOCAB_KEYS = (
    "providers",
    "capabilities",
    "thinkingModes",
    "effortLevels",
    "modelStatuses",
)


def validate_model_registry(reg: dict, ctx: dict) -> None:
    for key in _MODEL_REGISTRY_VOCAB_KEYS:
        _require_idents("model-registry", key, reg[key])
    providers = set(reg["providers"])
    capabilities = set(reg["capabilities"])
    thinking_modes = set(reg["thinkingModes"])
    effort_levels = set(reg["effortLevels"])
    model_statuses = set(reg["modelStatuses"])

    if not isinstance(reg["models"], list) or not reg["models"]:
        _fail("model-registry.models must be a non-empty list")
    ids_seen: set[str] = set()
    for model in reg["models"]:
        mid = model["modelId"]
        if mid in ids_seen:
            _fail(f"duplicate modelId {mid!r}")
        ids_seen.add(mid)
        if model["provider"] not in providers:
            _fail(f"model {mid!r} has unknown provider {model['provider']!r}")
        unknown = set(model["capabilities"]) - capabilities
        if unknown:
            _fail(f"model {mid!r} has capabilities {sorted(unknown)} outside capabilities")
        unknown = set(model["thinkingModes"]) - thinking_modes
        if unknown:
            _fail(f"model {mid!r} has thinkingModes {sorted(unknown)} outside thinkingModes")
        unknown = set(model["effortLevels"]) - effort_levels
        if unknown:
            _fail(f"model {mid!r} has effortLevels {sorted(unknown)} outside effortLevels")
        if model["status"] not in model_statuses:
            _fail(f"model {mid!r} has unknown status {model['status']!r}")

    aliases = reg["aliases"]
    if not isinstance(aliases, dict):
        _fail("model-registry.aliases must be an object")
    for alias, target in aliases.items():
        if target not in ids_seen:
            _fail(f"model alias {alias!r} resolves to unknown modelId {target!r}")


def _ts_str(value: str) -> str:
    """Single-quoted TS string literal (escaped)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _py_str(value: str) -> str:
    """Double-quoted Python string literal (escaped)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _py_tuple_literal(values: list) -> str:
    """A Python tuple literal of string values, e.g. ('a', 'b') or ('a',)."""
    if not values:
        return "()"
    joined = ", ".join(_py_str(v) for v in values)
    if len(values) == 1:
        joined += ","
    return f"({joined})"


def gen_model_registry_ts(reg: dict) -> str:
    lines = _ts_header(MODEL_REGISTRY_JSON)
    lines.append(f"export const modelRegistryVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "modelRegistryProviders", "ModelRegistryProvider", reg["providers"],
        "Providers registered with the harness.",
    )
    lines += _ts_const_array(
        "modelRegistryCapabilities", "ModelRegistryCapability", reg["capabilities"],
        "Capability flags that drive adapter behavior.",
    )
    lines += _ts_const_array(
        "modelRegistryThinkingModes", "ModelRegistryThinkingMode", reg["thinkingModes"],
        "Thinking modes a model may support.",
    )
    lines += _ts_const_array(
        "modelRegistryEffortLevels", "ModelRegistryEffortLevel", reg["effortLevels"],
        "Effort ladder a model may support.",
    )
    lines += _ts_const_array(
        "modelRegistryModelStatuses", "ModelRegistryModelStatus", reg["modelStatuses"],
        "Lifecycle status of a registered model.",
    )
    lines.append("/** Alias → canonical modelId. */")
    lines.append("export const modelRegistryAliases: Record<string, string> = {")
    for alias in sorted(reg["aliases"]):
        lines.append(f"  {_ts_str(alias)}: {_ts_str(reg['aliases'][alias])},")
    lines.append("};")
    lines.append("")
    lines.append("/** Canonical model catalog (JSON file order). */")
    lines.append("export const modelRegistryModels = [")
    for model in reg["models"]:
        lines.append("  {")
        lines.append(f"    modelId: {_ts_str(model['modelId'])},")
        lines.append(f"    provider: {_ts_str(model['provider'])},")
        lines.append(f"    family: {_ts_str(model['family'])},")
        lines.append(f"    contextWindowTokens: {model['contextWindowTokens']},")
        lines.append(f"    maxOutputTokens: {model['maxOutputTokens']},")
        caps = ", ".join(_ts_str(c) for c in model["capabilities"])
        lines.append(f"    capabilities: [{caps}],")
        modes = ", ".join(_ts_str(m) for m in model["thinkingModes"])
        lines.append(f"    thinkingModes: [{modes}],")
        efforts = ", ".join(_ts_str(e) for e in model["effortLevels"])
        lines.append(f"    effortLevels: [{efforts}],")
        lines.append(f"    samplingParamsSupported: {str(model['samplingParamsSupported']).lower()},")
        lines.append(f"    inputCostPerMTok: {model['inputCostPerMTok']},")
        lines.append(f"    outputCostPerMTok: {model['outputCostPerMTok']},")
        lines.append(f"    status: {_ts_str(model['status'])},")
        lines.append(f"    notes: {_ts_str(model['notes'])},")
        lines.append("  },")
    lines.append("] as const;")
    lines.append("")
    return "\n".join(lines)


def gen_model_registry_py(reg: dict) -> str:
    lines = _py_header(
        MODEL_REGISTRY_JSON,
        "Generated model-harness catalog (providers, capabilities, cost, aliases, models).",
    )
    lines.append("from typing import Any")
    lines.append("")
    lines.append(f'MODEL_REGISTRY_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("MODEL_REGISTRY_PROVIDERS", reg["providers"],
                       "Providers registered with the harness.")
    lines += _py_tuple("MODEL_REGISTRY_CAPABILITIES", reg["capabilities"],
                       "Capability flags that drive adapter behavior.")
    lines += _py_tuple("MODEL_REGISTRY_THINKING_MODES", reg["thinkingModes"],
                       "Thinking modes a model may support.")
    lines += _py_tuple("MODEL_REGISTRY_EFFORT_LEVELS", reg["effortLevels"],
                       "Effort ladder a model may support.")
    lines += _py_tuple("MODEL_REGISTRY_MODEL_STATUSES", reg["modelStatuses"],
                       "Lifecycle status of a registered model.")
    lines.append("# Alias -> canonical modelId.")
    lines.append("MODEL_REGISTRY_ALIASES: dict[str, str] = {")
    for alias in sorted(reg["aliases"]):
        lines.append(f'    "{alias}": "{reg["aliases"][alias]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Canonical model catalog (JSON file order).")
    lines.append("MODEL_REGISTRY_MODELS: tuple[dict[str, Any], ...] = (")
    for model in reg["models"]:
        lines.append("    {")
        lines.append(f'        "modelId": "{model["modelId"]}",')
        lines.append(f'        "provider": "{model["provider"]}",')
        lines.append(f'        "family": "{model["family"]}",')
        lines.append(f'        "contextWindowTokens": {model["contextWindowTokens"]},')
        lines.append(f'        "maxOutputTokens": {model["maxOutputTokens"]},')
        lines.append(f'        "capabilities": {_py_tuple_literal(model["capabilities"])},')
        lines.append(f'        "thinkingModes": {_py_tuple_literal(model["thinkingModes"])},')
        lines.append(f'        "effortLevels": {_py_tuple_literal(model["effortLevels"])},')
        lines.append(f'        "samplingParamsSupported": {model["samplingParamsSupported"]},')
        lines.append(f'        "inputCostPerMTok": {model["inputCostPerMTok"]},')
        lines.append(f'        "outputCostPerMTok": {model["outputCostPerMTok"]},')
        lines.append(f'        "status": "{model["status"]}",')
        lines.append(f'        "notes": {_py_str(model["notes"])},')
        lines.append("    },")
    lines.append(")")
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "MODEL_REGISTRY_VERSION",')
    lines.append('    "MODEL_REGISTRY_PROVIDERS",')
    lines.append('    "MODEL_REGISTRY_CAPABILITIES",')
    lines.append('    "MODEL_REGISTRY_THINKING_MODES",')
    lines.append('    "MODEL_REGISTRY_EFFORT_LEVELS",')
    lines.append('    "MODEL_REGISTRY_MODEL_STATUSES",')
    lines.append('    "MODEL_REGISTRY_ALIASES",')
    lines.append('    "MODEL_REGISTRY_MODELS",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_model_registry_md(reg: dict) -> str:
    lines = _md_header(MODEL_REGISTRY_JSON)
    lines.append("# Model Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append("Canonical catalog of harness LLM models — availability, capability flags, cost, and lifecycle status.")
    lines.append("")
    lines.append("| Model | Provider | Context | Max output | Input $/MTok | Output $/MTok | Status | Capabilities |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for model in reg["models"]:
        caps = ", ".join(f"`{c}`" for c in model["capabilities"])
        lines.append(
            f"| `{model['modelId']}` | {model['provider']} | {model['contextWindowTokens']} "
            f"| {model['maxOutputTokens']} | {model['inputCostPerMTok']} | {model['outputCostPerMTok']} "
            f"| {model['status']} | {caps} |"
        )
    lines.append("")
    lines.append("## Aliases")
    lines.append("")
    for alias in sorted(reg["aliases"]):
        lines.append(f"- `{alias}` → `{reg['aliases'][alias]}`")
    lines.append("")
    return "\n".join(lines)


def _summary_model_registry(reg: dict) -> str:
    return (
        f"model-registry v{reg['contractVersion']} — "
        f"{len(reg['models'])} models, {len(reg['providers'])} providers, "
        f"{len(reg['aliases'])} aliases"
    )


# ---------------------------------------------------------------------------
# Registry: task-profile (harness task execution policy)
# ---------------------------------------------------------------------------

TASK_PROFILE_JSON = CONTRACTS / "task-profile-registry.json"
TASK_PROFILE_TS = ROOT / "packages" / "shared" / "task-profile.ts"
TASK_PROFILE_PY = BACKEND / "shared" / "model_governance" / "generated_task_profiles.py"
TASK_PROFILE_MD = ROOT / "docs" / "_generated" / "task-profile-table.md"

_TASK_PROFILE_VOCAB_KEYS = ("modelRoles", "routingModes", "guardrailKinds", "outputKinds")


def validate_task_profile_registry(reg: dict, ctx: dict) -> None:
    for key in _TASK_PROFILE_VOCAB_KEYS:
        _require_idents("task-profile-registry", key, reg[key])
    model_roles = set(reg["modelRoles"])
    routing_modes = set(reg["routingModes"])
    guardrail_kinds = set(reg["guardrailKinds"])
    output_kinds = set(reg["outputKinds"])

    if not isinstance(reg["profiles"], list) or not reg["profiles"]:
        _fail("task-profile-registry.profiles must be a non-empty list")
    ids_seen: set[str] = set()
    for profile in reg["profiles"]:
        pid = profile["profileId"]
        if pid in ids_seen:
            _fail(f"duplicate profileId {pid!r}")
        ids_seen.add(pid)
        if profile["modelRole"] not in model_roles:
            _fail(f"profile {pid!r} has unknown modelRole {profile['modelRole']!r}")
        default_mode = profile["defaultRoutingMode"]
        if default_mode not in routing_modes:
            _fail(f"profile {pid!r} has unknown defaultRoutingMode {default_mode!r}")
        allowed = profile["allowedRoutingModes"]
        if not isinstance(allowed, list) or not allowed:
            _fail(f"profile {pid!r} allowedRoutingModes must be a non-empty list")
        unknown = set(allowed) - routing_modes
        if unknown:
            _fail(f"profile {pid!r} has routing modes {sorted(unknown)} outside routingModes")
        if default_mode not in allowed:
            _fail(f"profile {pid!r} defaultRoutingMode {default_mode!r} must be in allowedRoutingModes")
        if profile["outputKind"] not in output_kinds:
            _fail(f"profile {pid!r} has unknown outputKind {profile['outputKind']!r}")
        guardrails = profile["guardrails"]
        if not isinstance(guardrails, list) or not guardrails:
            _fail(f"profile {pid!r} guardrails must be a non-empty list")
        unknown = set(guardrails) - guardrail_kinds
        if unknown:
            _fail(f"profile {pid!r} has guardrails {sorted(unknown)} outside guardrailKinds")
        if not isinstance(profile["evidenceRequired"], bool):
            _fail(f"profile {pid!r} evidenceRequired must be a boolean")
        version = profile["version"]
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            _fail(f"profile {pid!r} version must be an integer >= 1")
        for key in ("maxTokens", "timeoutMs"):
            value = profile[key]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                _fail(f"profile {pid!r} {key} must be a positive integer")
        max_retries = profile["maxRetries"]
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            _fail(f"profile {pid!r} maxRetries must be an integer >= 0")


def gen_task_profiles_ts(reg: dict) -> str:
    lines = _ts_header(TASK_PROFILE_JSON)
    lines.append(f"export const taskProfileRegistryVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array("modelRoles", "ModelRole", reg["modelRoles"],
                             "Model role a task profile binds.")
    lines += _ts_const_array("routingModes", "RoutingMode", reg["routingModes"],
                             "Routing modes available to a task profile.")
    lines += _ts_const_array("guardrailKinds", "GuardrailKind", reg["guardrailKinds"],
                             "Guardrail kinds a task profile may require.")
    lines += _ts_const_array("outputKinds", "OutputKind", reg["outputKinds"],
                             "Output kinds a task profile may produce.")
    lines.append("/** Canonical task profiles (JSON file order). */")
    lines.append("export const taskProfiles = [")
    for profile in reg["profiles"]:
        lines.append("  {")
        lines.append(f"    profileId: {_ts_str(profile['profileId'])},")
        lines.append(f"    version: {profile['version']},")
        lines.append(f"    purpose: {_ts_str(profile['purpose'])},")
        lines.append(f"    modelRole: {_ts_str(profile['modelRole'])},")
        lines.append(f"    defaultRoutingMode: {_ts_str(profile['defaultRoutingMode'])},")
        allowed = ", ".join(_ts_str(m) for m in profile["allowedRoutingModes"])
        lines.append(f"    allowedRoutingModes: [{allowed}],")
        lines.append(f"    outputKind: {_ts_str(profile['outputKind'])},")
        guardrails = ", ".join(_ts_str(g) for g in profile["guardrails"])
        lines.append(f"    guardrails: [{guardrails}],")
        lines.append(f"    evidenceRequired: {str(profile['evidenceRequired']).lower()},")
        lines.append(f"    maxTokens: {profile['maxTokens']},")
        lines.append(f"    timeoutMs: {profile['timeoutMs']},")
        lines.append(f"    maxRetries: {profile['maxRetries']},")
        lines.append("  },")
    lines.append("] as const;")
    lines.append("")
    return "\n".join(lines)


def gen_task_profiles_py(reg: dict) -> str:
    lines = _py_header(
        TASK_PROFILE_JSON,
        "Generated harness task-profile registry (roles, routing, guardrails, bounds).",
    )
    lines.append("from typing import Any")
    lines.append("")
    lines.append(f'TASK_PROFILE_REGISTRY_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple("MODEL_ROLES", reg["modelRoles"],
                       "Model role a task profile binds.")
    lines += _py_tuple("ROUTING_MODES", reg["routingModes"],
                       "Routing modes available to a task profile.")
    lines += _py_tuple("GUARDRAIL_KINDS", reg["guardrailKinds"],
                       "Guardrail kinds a task profile may require.")
    lines += _py_tuple("OUTPUT_KINDS", reg["outputKinds"],
                       "Output kinds a task profile may produce.")
    lines.append("# Canonical task profiles (JSON file order).")
    lines.append("TASK_PROFILES: tuple[dict[str, Any], ...] = (")
    for profile in reg["profiles"]:
        lines.append("    {")
        lines.append(f'        "profileId": "{profile["profileId"]}",')
        lines.append(f'        "version": {profile["version"]},')
        lines.append(f'        "purpose": {_py_str(profile["purpose"])},')
        lines.append(f'        "modelRole": "{profile["modelRole"]}",')
        lines.append(f'        "defaultRoutingMode": "{profile["defaultRoutingMode"]}",')
        lines.append(f'        "allowedRoutingModes": {_py_tuple_literal(profile["allowedRoutingModes"])},')
        lines.append(f'        "outputKind": "{profile["outputKind"]}",')
        lines.append(f'        "guardrails": {_py_tuple_literal(profile["guardrails"])},')
        lines.append(f'        "evidenceRequired": {profile["evidenceRequired"]},')
        lines.append(f'        "maxTokens": {profile["maxTokens"]},')
        lines.append(f'        "timeoutMs": {profile["timeoutMs"]},')
        lines.append(f'        "maxRetries": {profile["maxRetries"]},')
        lines.append("    },")
    lines.append(")")
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "TASK_PROFILE_REGISTRY_VERSION",')
    lines.append('    "MODEL_ROLES",')
    lines.append('    "ROUTING_MODES",')
    lines.append('    "GUARDRAIL_KINDS",')
    lines.append('    "OUTPUT_KINDS",')
    lines.append('    "TASK_PROFILES",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_task_profiles_md(reg: dict) -> str:
    lines = _md_header(TASK_PROFILE_JSON)
    lines.append("# Task Profile Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append("Canonical task-profile registry binding a model role, routing policy, guardrails, output kind, and latency/cost bounds to named harness tasks.")
    lines.append("")
    lines.append("| Profile | Version | Role | Routing | Output kind | Guardrails | Evidence | Max tokens | Timeout (ms) | Retries | Purpose |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for profile in reg["profiles"]:
        guardrails = ", ".join(f"`{g}`" for g in profile["guardrails"])
        evidence = "yes" if profile["evidenceRequired"] else "no"
        lines.append(
            f"| `{profile['profileId']}` | {profile['version']} | {profile['modelRole']} "
            f"| {profile['defaultRoutingMode']} | {profile['outputKind']} | {guardrails} "
            f"| {evidence} | {profile['maxTokens']} | {profile['timeoutMs']} "
            f"| {profile['maxRetries']} | {profile['purpose']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _summary_task_profiles(reg: dict) -> str:
    return (
        f"task-profile v{reg['contractVersion']} — "
        f"{len(reg['profiles'])} profiles, {len(reg['modelRoles'])} model roles, "
        f"{len(reg['routingModes'])} routing modes"
    )


# ---------------------------------------------------------------------------
# Registry: intelligence-projection (P0 — 360 intelligence projection plane)
# ---------------------------------------------------------------------------

INTELLIGENCE_PROJECTION_JSON = CONTRACTS / "intelligence-projection-registry.json"
INTELLIGENCE_PROJECTION_TS = ROOT / "packages" / "shared" / "intelligence-projections_generated.ts"
INTELLIGENCE_PROJECTION_PY = BACKEND / "shared" / "intelligence_projections" / "generated_registry.py"
INTELLIGENCE_PROJECTION_TABLE_MD = ROOT / "docs" / "_generated" / "intelligence-projection-registry-table.md"
INTELLIGENCE_PROJECTION_GRAPH_MD = ROOT / "docs" / "_generated" / "intelligence-projection-dependency-graph.md"

# Fixed schema field orders for deterministic emission (order-stable generation:
# reordering arrays / shuffling key order across a rebase yields zero diff).
# These mirror the per-entry schema enforced by
# scripts/lib/intelligence_projection_validation.py.
_PROJECTION_FIELD_ORDER = (
    "id", "displayName", "projectionKind", "implementationState",
    "implementationBlueprint", "ownsCanonicalTruth", "subjectKinds",
    "canonicalAuthorities", "hardDependencies", "projectionDependencies",
    "optionalProjectionDependencies", "inputRefs", "outputSections",
    "supportedTemporalModes", "surfaceIds", "capabilityKeys", "metricRefs",
    "graphMutationPolicy", "requiresEvidence", "requiresDimensionState",
    "requiresFreshness", "requiresLimitations", "tenantScoped", "policyScoped",
    "readinessRequirements", "security", "costProfile",
    "commercialClassification", "legacyBindings", "deprecatedReason",
    "successorId", "pendingAuthority", "pendingReference",
)
_READINESS_REQUIREMENTS_FIELD_ORDER = (
    "requiresImplementation", "requiresDependencies", "requiresTenantEntitlement",
    "requiresProviderReadiness", "requiresEvidenceHealth",
)
_SECURITY_FIELD_ORDER = (
    "tenantScoped", "requiresAuthorization", "requiresHistoricalConsentEvaluation",
    "exportClass", "distillationRisk",
)
_COST_PROFILE_FIELD_ORDER = ("class", "supportsAsync")
_COMMERCIAL_CLASSIFICATION_FIELD_ORDER = ("sellableCapability", "meterRefs", "costClassRefs")
_LEGACY_BINDINGS_FIELD_ORDER = ("routes", "surfaceIds", "services", "migrationMode", "migrationBlueprint")
_PENDING_FIELD_ORDER = ("id", "kind", "reason", "resolvesInProjection")
_LENS_FIELD_ORDER = (
    "id", "displayName", "kind", "baseLens", "description", "domain",
    "applicableSubjectKinds", "temporalModes", "default",
)

_OBJECT_FIELD_ORDERS = {
    frozenset(_LENS_FIELD_ORDER): _LENS_FIELD_ORDER,
    frozenset(_PROJECTION_FIELD_ORDER): _PROJECTION_FIELD_ORDER,
    frozenset(_READINESS_REQUIREMENTS_FIELD_ORDER): _READINESS_REQUIREMENTS_FIELD_ORDER,
    frozenset(_SECURITY_FIELD_ORDER): _SECURITY_FIELD_ORDER,
    frozenset(_COST_PROFILE_FIELD_ORDER): _COST_PROFILE_FIELD_ORDER,
    frozenset(_COMMERCIAL_CLASSIFICATION_FIELD_ORDER): _COMMERCIAL_CLASSIFICATION_FIELD_ORDER,
    frozenset(_LEGACY_BINDINGS_FIELD_ORDER): _LEGACY_BINDINGS_FIELD_ORDER,
    frozenset(_PENDING_FIELD_ORDER): _PENDING_FIELD_ORDER,
}


def _projection_field_order(value: dict) -> tuple[str, ...]:
    """Fixed schema field order for a known object; sorted otherwise.

    ``_``-prefixed annotation keys (e.g. ``_comment``) are ignored so a comment
    can never break the frozenset match nor leak into an emitted literal.
    """
    known = frozenset(k for k in value if not k.startswith("_"))
    return _OBJECT_FIELD_ORDERS.get(known, tuple(sorted(known)))


def _sorted_value(value: object) -> object:
    """Recursively normalize a registry value before emission.

    (a) Every list value is sorted (order-stable generation: reordering arrays
    / shuffling key order across a rebase yields zero diff) — lists of dicts
    (pending declarations) sort by their ``id`` key.
    (b) Every ``_``-prefixed key (``_comment`` and any other annotation key) is
    dropped recursively, so annotation text never reaches the artifacts and the
    cleaned dict matches the fixed schema field orders.
    """
    if isinstance(value, dict):
        return {
            k: _sorted_value(v)
            for k, v in value.items()
            if not k.startswith("_")
        }
    if isinstance(value, list):
        items = [_sorted_value(v) for v in value]
        return sorted(
            items,
            key=lambda v: v["id"] if isinstance(v, dict) and "id" in v else repr(v),
        )
    return value


def _ts_literal(value: object, depth: int = 0) -> str:
    """Deterministic TypeScript literal for a JSON value."""
    pad = "  " * depth
    child_pad = "  " * (depth + 1)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(v, str) for v in value):
            return "[" + ", ".join(_ts_literal(v) for v in value) + "]"
        parts = [child_pad + _ts_literal(v, depth + 1) for v in value]
        return "[\n" + ",\n".join(parts) + "\n" + pad + "]"
    if isinstance(value, dict):
        parts = [
            f"{child_pad}{key}: {_ts_literal(value[key], depth + 1)}"
            for key in _projection_field_order(value)
        ]
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"
    raise TypeError(f"cannot render TS literal for {value!r}")


def _py_literal(value: object, depth: int = 0) -> str:
    """Deterministic Python literal for a JSON value.

    String lists become tuples (matching generated_surfaces.py); lists of dicts
    (pending declarations) stay lists.
    """
    pad = "    " * depth
    child_pad = "    " * (depth + 1)
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return _py_str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(v, str) for v in value):
            return _py_tuple_literal(value)
        parts = [child_pad + _py_literal(v, depth + 1) for v in value]
        return "[\n" + ",\n".join(parts) + "\n" + pad + "]"
    if isinstance(value, dict):
        parts = [
            f"{child_pad}{_py_str(key)}: {_py_literal(value[key], depth + 1)}"
            for key in _projection_field_order(value)
        ]
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"
    raise TypeError(f"cannot render Python literal for {value!r}")


def validate_intelligence_projection_registry(reg: dict, ctx: dict) -> list[str]:
    """Validate the intelligence-projection registry (thin lib wrapper).

    Returns ONLY messages with severity == "error". The real registry
    legitimately carries optional-edge dependency-cycle WARNINGS (union cycles
    are benign — the lazy runtime degrades missing optional deps to
    not_applicable); those must NOT fail generation. Like the other registry
    validators, any error exits non-zero (fail-closed) before any artifact is
    emitted.
    """
    errors = [
        v.message
        for v in _projection_validate_all(reg, ctx)
        if v.severity == "error"
    ]
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
    return errors


def gen_intelligence_projection_ts(reg: dict) -> str:
    projections = sorted(reg["projections"], key=lambda p: p["id"])
    lines = _ts_header(INTELLIGENCE_PROJECTION_JSON)
    lines.append(
        f"export const intelligenceProjectionsContractVersion = '{reg['contractVersion']}' as const;"
    )
    lines.append("")
    lines += _ts_const_array(
        "intelligenceProjectionIds", "IntelligenceProjectionId",
        [p["id"] for p in projections],
        "Registered intelligence projections (sorted).",
    )
    lines += _ts_const_array(
        "intelligenceProjectionKinds", "IntelligenceProjectionKind",
        sorted(reg["projectionKinds"]),
        "Projection kinds a 360 may be (sorted).",
    )
    lines += _ts_const_array(
        "intelligenceProjectionImplementationStates",
        "IntelligenceProjectionImplementationState",
        sorted(reg["implementationStates"]),
        "Implementation states — repo metadata, NOT readiness (sorted).",
    )
    lines += _ts_const_array(
        "intelligenceProjectionSectionStates",
        "IntelligenceProjectionSectionState",
        sorted(reg["sectionStates"]),
        "Section states a projection result section may carry (sorted).",
    )
    lines += _ts_const_array(
        "intelligenceProjectionSubjectKinds",
        "IntelligenceProjectionSubjectKind",
        sorted(reg["subjectKinds"]),
        "Subject kinds a projection may be asked about (sorted).",
    )
    lines.append("/** One pending declaration ({id, kind, reason, resolvesInProjection}). */")
    lines.append("export interface PendingResolution {")
    lines.append("  id: string;")
    lines.append("  kind: string;")
    lines.append("  reason: string;")
    lines.append("  resolvesInProjection: string;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ProjectionReadinessRequirements {")
    lines.append("  requiresImplementation: boolean;")
    lines.append("  requiresDependencies: boolean;")
    lines.append("  requiresTenantEntitlement: boolean;")
    lines.append("  requiresProviderReadiness: boolean;")
    lines.append("  requiresEvidenceHealth: boolean;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ProjectionSecurity {")
    lines.append("  tenantScoped: boolean;")
    lines.append("  requiresAuthorization: boolean;")
    lines.append("  requiresHistoricalConsentEvaluation: boolean;")
    lines.append("  exportClass: string;")
    lines.append("  distillationRisk: string;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ProjectionCostProfile {")
    lines.append("  class: string;")
    lines.append("  supportsAsync: boolean;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ProjectionCommercialClassification {")
    lines.append("  sellableCapability: boolean;")
    lines.append("  meterRefs: readonly string[];")
    lines.append("  costClassRefs: readonly string[];")
    lines.append("}")
    lines.append("")
    lines.append("export interface ProjectionLegacyBindings {")
    lines.append("  routes: readonly string[];")
    lines.append("  surfaceIds: readonly string[];")
    lines.append("  services: readonly string[];")
    lines.append("  migrationMode: string;")
    lines.append("  migrationBlueprint: string;")
    lines.append("}")
    lines.append("")
    lines.append("/** One registered intelligence projection (mirrors the registry schema). */")
    lines.append("export interface IntelligenceProjectionDefinition {")
    lines.append("  id: IntelligenceProjectionId;")
    lines.append("  displayName: string;")
    lines.append("  projectionKind: IntelligenceProjectionKind;")
    lines.append("  implementationState: IntelligenceProjectionImplementationState;")
    lines.append("  implementationBlueprint: string;")
    lines.append("  ownsCanonicalTruth: false;")
    lines.append("  subjectKinds: readonly IntelligenceProjectionSubjectKind[];")
    lines.append("  canonicalAuthorities: readonly string[];")
    lines.append("  hardDependencies: readonly string[];")
    lines.append("  projectionDependencies: readonly string[];")
    lines.append("  optionalProjectionDependencies: readonly string[];")
    lines.append("  inputRefs: readonly string[];")
    lines.append("  outputSections: readonly string[];")
    lines.append("  supportedTemporalModes: readonly string[];")
    lines.append("  surfaceIds: readonly string[];")
    lines.append("  capabilityKeys: readonly string[];")
    lines.append("  metricRefs: readonly string[];")
    lines.append("  graphMutationPolicy: 'read_only' | 'canonical_gateway_only';")
    lines.append("  requiresEvidence: boolean;")
    lines.append("  requiresDimensionState: boolean;")
    lines.append("  requiresFreshness: boolean;")
    lines.append("  requiresLimitations: boolean;")
    lines.append("  tenantScoped: boolean;")
    lines.append("  policyScoped: boolean;")
    lines.append("  readinessRequirements: ProjectionReadinessRequirements;")
    lines.append("  security: ProjectionSecurity;")
    lines.append("  costProfile: ProjectionCostProfile;")
    lines.append("  commercialClassification: ProjectionCommercialClassification;")
    lines.append("  legacyBindings: ProjectionLegacyBindings;")
    lines.append("  deprecatedReason: string | null;")
    lines.append("  successorId: string | null;")
    lines.append("  pendingAuthority: readonly PendingResolution[];")
    lines.append("  pendingReference: readonly PendingResolution[];")
    lines.append("}")
    lines.append("")
    lines.append("export const intelligenceProjectionDefinitions: Record<")
    lines.append("  IntelligenceProjectionId,")
    lines.append("  IntelligenceProjectionDefinition")
    lines.append("> = {")
    for projection in projections:
        lines.append(f"  {projection['id']}: {_ts_literal(_sorted_value(projection), 1)},")
    lines.append("};")
    lines.append("")
    lines.append("export interface ProjectionDependencyGraphEntry {")
    lines.append("  required: readonly IntelligenceProjectionId[];")
    lines.append("  optional: readonly IntelligenceProjectionId[];")
    lines.append("}")
    lines.append("")
    lines.append("export const projectionDependencyGraph: Record<")
    lines.append("  IntelligenceProjectionId,")
    lines.append("  ProjectionDependencyGraphEntry")
    lines.append("> = {")
    for projection in projections:
        required = sorted(projection["projectionDependencies"])
        optional = sorted(projection["optionalProjectionDependencies"])
        lines.append(
            f"  {projection['id']}: {{ required: {_ts_literal(required)}, "
            f"optional: {_ts_literal(optional)} }},"
        )
    lines.append("};")
    lines.append("")
    lines.append("export const pendingAuthorities: Partial<")
    lines.append("  Record<IntelligenceProjectionId, readonly PendingResolution[]>")
    lines.append("> = {")
    for projection in projections:
        entries = sorted(projection["pendingAuthority"], key=lambda d: d["id"])
        if not entries:
            continue
        lines.append(f"  {projection['id']}: {_ts_literal(_sorted_value(entries), 1)},")
    lines.append("};")
    lines.append("")
    lines.append("export const pendingReferences: Partial<")
    lines.append("  Record<IntelligenceProjectionId, readonly PendingResolution[]>")
    lines.append("> = {")
    for projection in projections:
        entries = sorted(projection["pendingReference"], key=lambda d: d["id"])
        if not entries:
            continue
        lines.append(f"  {projection['id']}: {_ts_literal(_sorted_value(entries), 1)},")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def gen_intelligence_projection_py(reg: dict) -> str:
    projections = sorted(reg["projections"], key=lambda p: p["id"])
    lines = _py_header(
        INTELLIGENCE_PROJECTION_JSON,
        "Generated intelligence-projection registry (360 projection plane).",
    )
    lines.append(f'INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple(
        "INTELLIGENCE_PROJECTION_IDS",
        [p["id"] for p in projections],
        "Registered intelligence projections (sorted).",
    )
    lines += _py_tuple(
        "PROJECTION_KINDS",
        sorted(reg["projectionKinds"]),
        "Projection kinds a 360 may be.",
    )
    lines += _py_tuple(
        "PROJECTION_IMPLEMENTATION_STATES",
        sorted(reg["implementationStates"]),
        "Implementation states — repo metadata, NOT readiness.",
    )
    lines += _py_tuple(
        "PROJECTION_SECTION_STATES",
        sorted(reg["sectionStates"]),
        "Section states a projection result section may carry.",
    )
    lines += _py_tuple(
        "GRAPH_MUTATION_POLICIES",
        sorted(reg["graphMutationPolicies"]),
        "Graph-mutation policies a projection may declare.",
    )
    lines += _py_tuple(
        "PROJECTION_SUBJECT_KINDS",
        sorted(reg["subjectKinds"]),
        "Subject kinds a projection may be asked about.",
    )
    lines.append("# Full projection definitions (sorted by projection id).")
    lines.append("INTELLIGENCE_PROJECTION_DEFINITIONS: dict[str, dict] = {")
    for projection in projections:
        lines.append(f'    "{projection["id"]}": {_py_literal(_sorted_value(projection), 1)},')
    lines.append("}")
    lines.append("")
    lines.append("# Required/optional projection dependencies (sorted by projection id).")
    lines.append("PROJECTION_DEPENDENCY_GRAPH: dict[str, dict] = {")
    for projection in projections:
        required = _py_tuple_literal(sorted(projection["projectionDependencies"]))
        optional = _py_tuple_literal(sorted(projection["optionalProjectionDependencies"]))
        lines.append(
            f'    "{projection["id"]}": {{"required": {required}, "optional": {optional}}},'
        )
    lines.append("}")
    lines.append("")
    lines.append("# projection id -> registered surfaces (sorted).")
    lines.append("PROJECTION_SURFACE_MAP: dict[str, tuple] = {")
    for projection in projections:
        lines.append(
            f'    "{projection["id"]}": {_py_tuple_literal(sorted(projection["surfaceIds"]))},'
        )
    lines.append("}")
    lines.append("")
    lines.append("# projection id -> capability keys (sorted).")
    lines.append("PROJECTION_CAPABILITY_MAP: dict[str, tuple] = {")
    for projection in projections:
        lines.append(
            f'    "{projection["id"]}": {_py_tuple_literal(sorted(projection["capabilityKeys"]))},'
        )
    lines.append("}")
    lines.append("")
    lines.append("# Pending canonical-authority declarations (sorted by projection id).")
    lines.append("PENDING_AUTHORITIES: dict[str, list] = {")
    for projection in projections:
        entries = sorted(projection["pendingAuthority"], key=lambda d: d["id"])
        if not entries:
            continue
        lines.append(f'    "{projection["id"]}": {_py_literal(_sorted_value(entries), 1)},')
    lines.append("}")
    lines.append("")
    lines.append("# Pending reference declarations (sorted by projection id).")
    lines.append("PENDING_REFERENCES: dict[str, list] = {")
    for projection in projections:
        entries = sorted(projection["pendingReference"], key=lambda d: d["id"])
        if not entries:
            continue
        lines.append(f'    "{projection["id"]}": {_py_literal(_sorted_value(entries), 1)},')
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [")
    for name in sorted((
        "INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION",
        "INTELLIGENCE_PROJECTION_IDS",
        "INTELLIGENCE_PROJECTION_DEFINITIONS",
        "PROJECTION_DEPENDENCY_GRAPH",
        "PROJECTION_SURFACE_MAP",
        "PROJECTION_CAPABILITY_MAP",
        "PROJECTION_KINDS",
        "PROJECTION_IMPLEMENTATION_STATES",
        "PROJECTION_SECTION_STATES",
        "PROJECTION_SUBJECT_KINDS",
        "GRAPH_MUTATION_POLICIES",
        "PENDING_AUTHORITIES",
        "PENDING_REFERENCES",
    )):
        lines.append(f'    "{name}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_intelligence_projection_table_md(reg: dict) -> str:
    projections = sorted(reg["projections"], key=lambda p: p["id"])
    lines = _md_header(INTELLIGENCE_PROJECTION_JSON)
    lines.append("# Intelligence Projection Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append(
        "A 360 is an intelligence projection over canonical Aether truth — never a "
        "competing system of record. `implementationState` is repo metadata, NOT readiness."
    )
    lines.append("")
    lines += _md_vocab_section("Projection kinds", sorted(reg["projectionKinds"]))
    lines += _md_vocab_section("Implementation states", sorted(reg["implementationStates"]))
    lines += _md_vocab_section("Section states", sorted(reg["sectionStates"]))
    lines += _md_vocab_section("Graph mutation policies", sorted(reg["graphMutationPolicies"]))
    lines.append("## Projections")
    lines.append("")
    lines.append(
        "| Projection | Kind | State | Hard spines | Projection deps | Surfaces | "
        "Capability keys | Graph policy | Authorities | Legacy routes | Blueprint |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for projection in projections:
        spines = ", ".join(f"`{s}`" for s in sorted(projection["hardDependencies"]))
        required = [f"`{d}`" for d in sorted(projection["projectionDependencies"])]
        optional = [f"`{d}`(opt)" for d in sorted(projection["optionalProjectionDependencies"])]
        deps = ", ".join(required + optional)
        surfaces = ", ".join(f"`{s}`" for s in sorted(projection["surfaceIds"]))
        caps = ", ".join(f"`{c}`" for c in sorted(projection["capabilityKeys"]))
        authorities = ", ".join(f"`{a}`" for a in sorted(projection["canonicalAuthorities"]))
        routes = ", ".join(f"`{r}`" for r in sorted(projection["legacyBindings"]["routes"]))
        blueprint = projection["implementationBlueprint"]
        lines.append(
            f"| `{projection['id']}` | {projection['projectionKind']} | "
            f"{projection['implementationState']} | {spines} | {deps} | {surfaces} | "
            f"{caps} | {projection['graphMutationPolicy']} | {authorities} | {routes} | "
            f"`{blueprint}` |"
        )
    lines.append("")
    return "\n".join(lines)


def gen_intelligence_projection_graph_md(reg: dict) -> str:
    projections = sorted(reg["projections"], key=lambda p: p["id"])
    lines = _md_header(INTELLIGENCE_PROJECTION_JSON)
    lines.append("# Intelligence Projection Dependency Graph")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append(
        "Hard spines (solid `-->`), required projection dependencies (dashed "
        "`-.->`) and optional projection dependencies (dotted `-.-o`). Cycles "
        "are intentional (optional unions); Mermaid renders them fine."
    )
    lines.append("")
    lines.append("## Dependency graph")
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart LR")
    for projection in projections:
        pid = projection["id"]
        for spine in sorted(projection["hardDependencies"]):
            lines.append(f"  {pid} --> {spine}")
        for dep in sorted(projection["projectionDependencies"]):
            lines.append(f"  {pid} -.-> {dep}")
        for dep in sorted(projection["optionalProjectionDependencies"]):
            lines.append(f"  {pid} -.-o {dep}")
    lines.append("```")
    lines.append("")
    pending: list[tuple[str, str, dict]] = []
    for projection in projections:
        for kind, entries in (
            ("authority", projection.get("pendingAuthority", [])),
            ("reference", projection.get("pendingReference", [])),
        ):
            for entry in sorted(entries, key=lambda d: d["id"]):
                pending.append((projection["id"], kind, entry))
    if pending:
        lines.append("## Pending resolutions")
        lines.append("")
        lines.append("| Projection | Kind | Id | Reason | Resolves in projection |")
        lines.append("|---|---|---|---|---|")
        for pid, kind, entry in pending:
            lines.append(
                f"| `{pid}` | {kind} | `{entry['id']}` | {entry['reason']} | "
                f"`{entry['resolvesInProjection']}` |"
            )
        lines.append("")
    return "\n".join(lines)


def _summary_intelligence_projections(reg: dict) -> str:
    pending_authorities = sum(len(p.get("pendingAuthority", [])) for p in reg["projections"])
    pending_references = sum(len(p.get("pendingReference", [])) for p in reg["projections"])
    return (
        f"intelligence-projection v{reg['contractVersion']} — "
        f"{len(reg['projections'])} projections, "
        f"{pending_authorities} pending authorities, {pending_references} pending references"
    )


# ---------------------------------------------------------------------------
# Registry: lens-registry (A8 — projection-engine lens registry)
# ---------------------------------------------------------------------------

LENS_REGISTRY_JSON = CONTRACTS / "lens-registry.json"
LENS_REGISTRY_TS = ROOT / "packages" / "shared" / "lenses_generated.ts"
LENS_REGISTRY_PY = BACKEND / "shared" / "projection_engine" / "generated_lenses.py"
LENS_REGISTRY_MD = ROOT / "docs" / "_generated" / "lens-registry-table.md"

# Fixed schema field order for deterministic emission (order-stable generation).
# (``_LENS_FIELD_ORDER`` is defined with the projection field-order block.)


def validate_lens_registry(reg: dict, ctx: dict) -> list[str]:
    """Validate the lens registry (thin lib wrapper, rule group ``lens_registry``).

    Delegates to scripts/lib/intelligence_projection_validation.validate_lens_registry
    so generation and the standalone validator compute the SAME facts. Any error
    exits non-zero (fail-closed) before any artifact is emitted.
    """
    errors = [
        v.message
        for v in _projection_validate_lens_registry(reg, ctx)
        if v.severity == "error"
    ]
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
    return errors


def gen_lens_registry_ts(reg: dict) -> str:
    lenses = sorted(reg["lenses"], key=lambda l: l["id"])
    lines = _ts_header(LENS_REGISTRY_JSON)
    lines.append(f"export const lensRegistryContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "lensRegistryKinds", "LensRegistryKind",
        sorted(reg["lensKinds"]),
        "Lens kinds a lens may be (sorted).",
    )
    lines += _ts_const_array(
        "lensIds", "LensId",
        [l["id"] for l in lenses],
        "Registered projection-engine lenses (sorted).",
    )
    lines.append("/** One registered projection-engine lens (mirrors the registry schema). */")
    lines.append("export interface LensDescriptor {")
    lines.append("  id: LensId;")
    lines.append("  displayName: string;")
    lines.append("  kind: LensRegistryKind;")
    lines.append("  baseLens: LensId | null;")
    lines.append("  description: string;")
    lines.append("  domain: string;")
    lines.append("  applicableSubjectKinds: readonly string[];")
    lines.append("  temporalModes: readonly string[];")
    lines.append("  default: boolean;")
    lines.append("}")
    lines.append("")
    lines.append("export const lensDefinitions: Record<LensId, LensDescriptor> = {")
    for lens in lenses:
        lines.append(f"  {lens['id']}: {_ts_literal(_sorted_value(lens), 1)},")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def gen_lens_registry_py(reg: dict) -> str:
    lenses = sorted(reg["lenses"], key=lambda l: l["id"])
    lines = _py_header(
        LENS_REGISTRY_JSON,
        "Generated projection-engine lens registry (A8 projection engine).",
    )
    lines.append(f'LENS_REGISTRY_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple(
        "LENS_KINDS",
        sorted(reg["lensKinds"]),
        "Lens kinds a lens may be.",
    )
    lines += _py_tuple(
        "LENS_IDS",
        [l["id"] for l in lenses],
        "Registered projection-engine lenses (sorted).",
    )
    lines.append("# Full lens definitions (sorted by lens id).")
    lines.append("LENS_DEFINITIONS: dict[str, dict] = {")
    for lens in lenses:
        lines.append(f'    "{lens["id"]}": {_py_literal(_sorted_value(lens), 1)},')
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [")
    for name in sorted(("LENS_REGISTRY_CONTRACT_VERSION", "LENS_IDS", "LENS_KINDS", "LENS_DEFINITIONS")):
        lines.append(f'    "{name}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_lens_registry_md(reg: dict) -> str:
    lenses = sorted(reg["lenses"], key=lambda l: l["id"])
    lines = _md_header(LENS_REGISTRY_JSON)
    lines.append("# Projection Engine — Lens Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append("Composable viewing frames a projection applies over canonical Aether truth — one default base lens (`standard`) plus domain/capability overlay lenses.")
    lines.append("")
    lines.append("| Lens | Kind | Base | Domain | Subjects | Temporal modes | Default |")
    lines.append("|---|---|---|---|---|---|---|")
    for lens in lenses:
        base = lens["baseLens"] or "—"
        # Sort list-valued fields — the table must be order-stable the same way
        # the TS/PY twins are (_sorted_value) so a registry reorder yields zero
        # diff across all artifacts.
        subjects = ", ".join(f"`{s}`" for s in sorted(lens["applicableSubjectKinds"]))
        modes = ", ".join(f"`{m}`" for m in sorted(lens["temporalModes"]))
        lines.append(
            f"| `{lens['id']}` | {lens['kind']} | {base} | {lens['domain']} "
            f"| {subjects} | {modes} | {'yes' if lens['default'] else ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def _summary_lens_registry(reg: dict) -> str:
    overlays = sum(1 for l in reg["lenses"] if l["kind"] == "overlay")
    return (
        f"lens-registry v{reg['contractVersion']} — "
        f"{len(reg['lenses'])} lenses "
        f"({len(reg['lenses']) - overlays} base, {overlays} overlays)"
    )


OUTCOME_TYPES_JSON = CONTRACTS / "outcome-type-registry.json"
OUTCOME_TYPES_TS = ROOT / "packages" / "shared" / "outcome-types_generated.ts"
OUTCOME_TYPES_PY = BACKEND / "shared" / "measurement" / "generated_outcome_types.py"
OUTCOME_TYPES_MD = ROOT / "docs" / "_generated" / "outcome-type-registry-table.md"


def validate_outcome_registry(reg: dict, ctx: dict) -> list[str]:
    """Validate the outcome-type registry (thin lib wrapper, rule group ``outcome_registry``).

    Delegates to scripts/lib/intelligence_projection_validation.validate_outcome_registry
    so generation and the standalone validator compute the SAME facts. Any error
    exits non-zero (fail-closed) before any artifact is emitted.
    """
    errors = [
        v.message
        for v in _projection_validate_outcome_registry(reg, ctx)
        if v.severity == "error"
    ]
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
    return errors


def gen_outcome_types_ts(reg: dict) -> str:
    types = sorted(reg["outcomeTypes"], key=lambda t: t["id"])
    lines = _ts_header(OUTCOME_TYPES_JSON)
    lines.append(f"export const outcomeTypeRegistryContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "outcomeTypeDomains", "OutcomeTypeDomain",
        sorted(reg["domains"]),
        "Outcome domains a type may belong to (sorted).",
    )
    lines += _ts_const_array(
        "outcomeTypeIds", "OutcomeTypeId",
        [t["id"] for t in types],
        "Registered outcome types (sorted).",
    )
    lines.append("/** One registered outcome type (mirrors the registry schema). */")
    lines.append("export interface OutcomeTypeDescriptor {")
    lines.append("  id: OutcomeTypeId;")
    lines.append("  domain: OutcomeTypeDomain;")
    lines.append("  name: string;")
    lines.append("  description: string;")
    lines.append("}")
    lines.append("")
    lines.append("export const outcomeTypeDefinitions: Record<OutcomeTypeId, OutcomeTypeDescriptor> = {")
    for t in types:
        lines.append(f"  {t['id']}: {_ts_literal(_sorted_value(t), 1)},")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def gen_outcome_types_py(reg: dict) -> str:
    types = sorted(reg["outcomeTypes"], key=lambda t: t["id"])
    lines = _py_header(
        OUTCOME_TYPES_JSON,
        "Generated outcome-type registry (Outcome360).",
    )
    lines.append(f'OUTCOME_TYPE_REGISTRY_CONTRACT_VERSION = "{reg["contractVersion"]}"')
    lines.append("")
    lines += _py_tuple(
        "OUTCOME_DOMAINS",
        sorted(reg["domains"]),
        "Outcome domains a type may belong to (sorted).",
    )
    lines += _py_tuple(
        "OUTCOME_TYPE_IDS",
        [t["id"] for t in types],
        "Registered outcome types (sorted).",
    )
    lines.append("# Full outcome-type definitions (sorted by id).")
    lines.append("OUTCOME_TYPE_DEFINITIONS: dict[str, dict] = {")
    for t in types:
        lines.append(f'    "{t["id"]}": {_py_literal(_sorted_value(t), 1)},')
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [")
    for name in sorted(
        ("OUTCOME_TYPE_REGISTRY_CONTRACT_VERSION", "OUTCOME_DOMAINS", "OUTCOME_TYPE_IDS", "OUTCOME_TYPE_DEFINITIONS")
    ):
        lines.append(f'    "{name}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_outcome_types_md(reg: dict) -> str:
    types = sorted(reg["outcomeTypes"], key=lambda t: t["id"])
    lines = _md_header(OUTCOME_TYPES_JSON)
    lines.append("# Outcome360 — Outcome Type Registry")
    lines.append("")
    lines.append(f"Contract version: `{reg['contractVersion']}`")
    lines.append("")
    lines.append("Canonical outcome-type vocabulary the Outcome360 projection consumes — every type belongs to exactly one domain.")
    lines.append("")
    lines.append("| Domain | Outcome type | Name | Description |")
    lines.append("|---|---|---|---|")
    for t in types:
        lines.append(f"| `{t['domain']}` | `{t['id']}` | {t['name']} | {t['description']} |")
    lines.append("")
    return "\n".join(lines)


def _summary_outcome_types(reg: dict) -> str:
    return (
        f"outcome-type-registry v{reg['contractVersion']} — "
        f"{len(reg['outcomeTypes'])} outcome types across {len(reg['domains'])} domains"
    )


# ---------------------------------------------------------------------------
# Registry table + write/check machinery
# ---------------------------------------------------------------------------

# Each entry: (registry json path, validate(reg, ctx), ((output path, gen(reg)), ...),
# summary(reg)). Temporal policy predates the table and keeps its bespoke wiring
# in main() because its emitters take the default-resolved family bounds.
REGISTRIES: tuple = (
    (
        INTERACTION_VOCAB_JSON,
        validate_interaction_vocabulary,
        (
            (INTERACTION_TS, gen_interaction_ts),
            (INTERACTION_PY, gen_interaction_py),
            (INTERACTION_MD, gen_interaction_md),
        ),
        _summary_interaction,
    ),
    (
        CONTEXT_CAPSULE_JSON,
        validate_context_capsule,
        (
            (CONTEXT_CAPSULE_TS, gen_context_capsule_ts),
            (CONTEXT_CAPSULE_PY, gen_context_capsule_py),
            (CONTEXT_CAPSULE_MD, gen_context_capsule_md),
        ),
        _summary_context_capsule,
    ),
    (
        LOCATION_REGISTRY_JSON,
        validate_location_registry,
        (
            (LOCATION_REGISTRY_TS, gen_location_registry_ts),
            (LOCATION_REGISTRY_PY, gen_location_registry_py),
            (LOCATION_REGISTRY_MD, gen_location_registry_md),
        ),
        _summary_location_registry,
    ),
    (
        GRAPH_MUTATION_JSON,
        validate_graph_mutation,
        (
            (GRAPH_MUTATION_TS, gen_graph_mutation_ts),
            (GRAPH_MUTATION_PY, gen_graph_mutation_py),
            (GRAPH_MUTATION_MD, gen_graph_mutation_md),
        ),
        _summary_graph_mutation,
    ),
    (
        FILTER_FIELD_JSON,
        validate_filter_fields,
        (
            (FILTER_FIELD_TS, gen_filter_fields_ts),
            (FILTER_FIELD_PY, gen_filter_fields_py),
            (FILTER_FIELD_MD, gen_filter_fields_md),
        ),
        _summary_filter_fields,
    ),
    (
        SURFACE_CAPABILITY_JSON,
        validate_surface_capabilities,
        (
            (SURFACE_CAPABILITY_TS, gen_surface_capabilities_ts),
            (SURFACE_CAPABILITY_PY, gen_surface_capabilities_py),
            (SURFACE_CAPABILITY_MD, gen_surface_capabilities_md),
        ),
        _summary_surface_capabilities,
    ),
    (
        COMPARISON_JSON,
        validate_comparison,
        (
            (COMPARISON_TS, gen_comparison_ts),
            (COMPARISON_PY, gen_comparison_py),
            (COMPARISON_MD, gen_comparison_md),
        ),
        _summary_comparison,
    ),
    (
        PROJECTOR_OWNERSHIP_JSON,
        validate_projector_ownership,
        (
            (PROJECTOR_OWNERSHIP_PY, gen_projector_ownership_py),
            (PROJECTOR_OWNERSHIP_MD, gen_projector_ownership_md),
        ),
        _summary_projector_ownership,
    ),
    (
        MODEL_REGISTRY_JSON,
        validate_model_registry,
        (
            (MODEL_REGISTRY_TS, gen_model_registry_ts),
            (MODEL_REGISTRY_PY, gen_model_registry_py),
            (MODEL_REGISTRY_MD, gen_model_registry_md),
        ),
        _summary_model_registry,
    ),
    (
        TASK_PROFILE_JSON,
        validate_task_profile_registry,
        (
            (TASK_PROFILE_TS, gen_task_profiles_ts),
            (TASK_PROFILE_PY, gen_task_profiles_py),
            (TASK_PROFILE_MD, gen_task_profiles_md),
        ),
        _summary_task_profiles,
    ),
    (
        INTELLIGENCE_PROJECTION_JSON,
        validate_intelligence_projection_registry,
        (
            (INTELLIGENCE_PROJECTION_TS, gen_intelligence_projection_ts),
            (INTELLIGENCE_PROJECTION_PY, gen_intelligence_projection_py),
            (INTELLIGENCE_PROJECTION_TABLE_MD, gen_intelligence_projection_table_md),
            (INTELLIGENCE_PROJECTION_GRAPH_MD, gen_intelligence_projection_graph_md),
        ),
        _summary_intelligence_projections,
    ),
    (
        LENS_REGISTRY_JSON,
        validate_lens_registry,
        (
            (LENS_REGISTRY_TS, gen_lens_registry_ts),
            (LENS_REGISTRY_PY, gen_lens_registry_py),
            (LENS_REGISTRY_MD, gen_lens_registry_md),
        ),
        _summary_lens_registry,
    ),
    (
        OUTCOME_TYPES_JSON,
        validate_outcome_registry,
        (
            (OUTCOME_TYPES_TS, gen_outcome_types_ts),
            (OUTCOME_TYPES_PY, gen_outcome_types_py),
            (OUTCOME_TYPES_MD, gen_outcome_types_md),
        ),
        _summary_outcome_types,
    ),
)


@functools.lru_cache(maxsize=1)
def _projection_context() -> dict:
    """Cross-registry context for the intelligence-projection validator.

    Delegates to scripts/lib/intelligence_projection_validation.load_context()
    (surface_ids, surface_temporal_modes, metric_names, graph_mutation_types,
    route_prefixes, backend_source_paths) so this generator's validation and
    the standalone validator (scripts/validate_intelligence_projections.py)
    compute the SAME facts and can never drift. Cached (maxsize=1) so a single
    generator run loads the cross-registry facts exactly once.
    """
    return _projection_load_context()


def _load_context() -> dict:
    """Cross-registry facts used by validators (never mutated by emitters)."""
    event_reg = json.loads(EVENT_REGISTRY_JSON.read_text())
    consent_reg = json.loads(CONSENT_REGISTRY_JSON.read_text())
    filter_reg = json.loads(FILTER_FIELD_JSON.read_text())
    ctx = {
        "event_families": {e["family"] for e in event_reg["events"]},
        "consent_purposes": {p["key"] for p in consent_reg["purposes"]},
        "filter_operators": _ts_filter_operators(),
        "filter_field_categories": set(filter_reg["categories"]),
    }
    # The intelligence-projection validator receives the SAME cross-registry
    # context the standalone lib computes. Delegating (and caching) means the
    # generator's validation and the standalone validator can never drift —
    # documented per the P0 plan. Existing keys stay intact for the registries
    # that depend on them.
    ctx.update(_projection_context())
    return ctx


def _apply(path: Path, content: str, check: bool, diffs: list[str]) -> None:
    if path.exists():
        current = path.read_text()
        if current == content:
            return
        if check:
            diffs.append(str(path.relative_to(ROOT)))
            return
    elif check:
        # A missing generated file is real drift — --check must be blind to
        # nothing, so a deleted artifact is reported (never silently accepted).
        diffs.append(str(path.relative_to(ROOT)))
        return
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"  written: {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any generated file differs from the committed version (CI gate)",
    )
    args = parser.parse_args()

    ctx = _load_context()

    temporal_reg = json.loads(TEMPORAL_POLICY_JSON.read_text())
    validate_temporal_policy(temporal_reg, ctx["event_families"])
    families = resolved_family_bounds(temporal_reg, ctx["event_families"])

    diffs: list[str] = []
    _apply(TEMPORAL_POLICY_TS, gen_temporal_policy_ts(temporal_reg, families), args.check, diffs)
    _apply(TEMPORAL_POLICY_PY, gen_temporal_policy_py(temporal_reg, families), args.check, diffs)
    _apply(TEMPORAL_POLICY_MD, gen_temporal_policy_md(temporal_reg, families), args.check, diffs)

    summaries = [
        f"temporal policy v{temporal_reg['policyVersion']} — "
        f"{len(temporal_reg['reasonCodes'])} reason codes, {len(families)} families"
    ]

    for json_path, validate, artifacts, summarize in REGISTRIES:
        reg = json.loads(json_path.read_text())
        validate(reg, ctx)
        for out_path, gen in artifacts:
            _apply(out_path, gen(reg), args.check, diffs)
        summaries.append(summarize(reg))

    if diffs:
        print("DRIFT: generated files differ from committed versions:", file=sys.stderr)
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        print("Run: python scripts/generate_platform_contracts.py", file=sys.stderr)
        return 1

    for summary in summaries:
        print(f"OK: {summary} — all artifacts up-to-date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
