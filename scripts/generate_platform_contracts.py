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
  packages/shared/contracts/graph-mutation-registry.json
  packages/shared/contracts/filter-field-registry.json
  packages/shared/contracts/surface-capability-registry.json

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
  packages/shared/graph-mutation.ts
  Backend Architecture/aether-backend/shared/graph/generated_mutation_taxonomy.py
  docs/_generated/graph-mutation-table.md
  packages/shared/filter-fields.ts
  Backend Architecture/aether-backend/shared/exploration/generated_fields.py
  docs/_generated/filter-field-table.md
  packages/shared/surface-capabilities.ts
  Backend Architecture/aether-backend/shared/exploration/generated_surfaces.py
  docs/_generated/surface-capability-table.md

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
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS = ROOT / "packages" / "shared" / "contracts"
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

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


def validate_surface_capabilities(reg: dict, ctx: dict) -> None:
    for key in ("temporalModes", "views", "filterDispositions"):
        _require_idents("surface-capability-registry", key, reg[key])
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
    lines.append("")
    lines.append(f"export const surfaceCapabilitiesContractVersion = '{reg['contractVersion']}' as const;")
    lines.append("")
    lines += _ts_const_array(
        "explorationSurfaceIds", "ExplorationSurfaceId",
        [s["surfaceId"] for s in surfaces],
        "Exploration surfaces registered with the fabric (sorted).",
    )
    lines += _ts_const_array(
        "explorationTemporalModes", "ExplorationTemporalMode", reg["temporalModes"],
        "Temporal query modes a surface may support.",
    )
    lines += _ts_const_array(
        "explorationViews", "ExplorationView", reg["views"],
        "Render views a surface may support.",
    )
    lines += _ts_const_array(
        "filterDispositions", "FilterDisposition", reg["filterDispositions"],
        "What the fabric did with one filter on one surface — never silently dropped.",
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
)


def _load_context() -> dict:
    """Cross-registry facts used by validators (never mutated by emitters)."""
    event_reg = json.loads(EVENT_REGISTRY_JSON.read_text())
    consent_reg = json.loads(CONSENT_REGISTRY_JSON.read_text())
    filter_reg = json.loads(FILTER_FIELD_JSON.read_text())
    return {
        "event_families": {e["family"] for e in event_reg["events"]},
        "consent_purposes": {p["key"] for p in consent_reg["purposes"]},
        "filter_operators": _ts_filter_operators(),
        "filter_field_categories": set(filter_reg["categories"]),
    }


def _apply(path: Path, content: str, check: bool, diffs: list[str]) -> None:
    if path.exists():
        current = path.read_text()
        if current == content:
            return
        if check:
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
