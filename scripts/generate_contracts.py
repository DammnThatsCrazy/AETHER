#!/usr/bin/env python3
"""
Generate TypeScript and Python contract artifacts from JSON canonical registries.

Sources (read-only — canonical source of truth):
  packages/shared/contracts/event-registry.json
  packages/shared/contracts/consent-registry.json
  packages/shared/contracts/metric-registry.json

Generated outputs:
  packages/shared/consent.ts
  packages/shared/events.ts                 (generated section only, between markers)
  packages/shared/measurement-contract.ts
  Backend Architecture/aether-backend/services/ingestion/generated_registry.py
  Backend Architecture/aether-backend/shared/measurement/generated_registry.py
  docs/_generated/event-registry-table.md
  docs/_generated/consent-registry-table.md
  docs/_generated/metric-registry-table.md
  packages/web/src/core/generated-consent-map.ts

Usage:
  python scripts/generate_contracts.py           # write all outputs in-place
  python scripts/generate_contracts.py --check   # exit 1 if any output differs (CI gate)

Guarantees:
  - Idempotent: running twice produces identical output
  - Sorted: all lists and maps are emitted in sorted order
  - Validates: no duplicate types, all referenced purposes/families exist
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
CONSENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"
METRIC_REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "metric-registry.json"
INTEGRATION_CONSENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "integration-consent-registry.json"
TRAFFIC_SOURCE_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "traffic-source-registry.json"

CONSENT_TS = ROOT / "packages" / "shared" / "consent.ts"
EVENTS_TS = ROOT / "packages" / "shared" / "events.ts"
MEASUREMENT_TS = ROOT / "packages" / "shared" / "measurement-contract.ts"
GENERATED_REGISTRY_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "services" / "ingestion" / "generated_registry.py"
)
GENERATED_METRIC_REGISTRY_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "shared" / "measurement" / "generated_registry.py"
)
EVENT_TABLE_MD = ROOT / "docs" / "_generated" / "event-registry-table.md"
CONSENT_TABLE_MD = ROOT / "docs" / "_generated" / "consent-registry-table.md"
METRIC_TABLE_MD = ROOT / "docs" / "_generated" / "metric-registry-table.md"
WEB_CONSENT_MAP_TS = (
    ROOT / "packages" / "web" / "src" / "core" / "generated-consent-map.ts"
)
INTEGRATION_CONSENT_TS = ROOT / "packages" / "shared" / "integration-consent.ts"
INTEGRATION_CONSENT_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "shared" / "privacy" / "generated_integration_consent.py"
)
INTEGRATION_CONSENT_SWIFT = (
    ROOT / "packages" / "ios" / "Sources" / "AetherSDK" / "GeneratedIntegrationConsent.swift"
)
INTEGRATION_CONSENT_KT = (
    ROOT / "packages" / "android" / "src" / "main" / "java" / "com" / "aether" / "sdk" / "GeneratedIntegrationConsent.kt"
)
INTEGRATION_CONSENT_TABLE_MD = ROOT / "docs" / "_generated" / "integration-consent-registry-table.md"
TRAFFIC_SOURCE_TS = ROOT / "packages" / "shared" / "traffic-source.ts"
TRAFFIC_SOURCE_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "services" / "traffic" / "generated_registry.py"
)
TRAFFIC_SOURCE_TABLE_MD = ROOT / "docs" / "_generated" / "traffic-source-registry-table.md"
RIGHTS_AUTHORITY_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "rights-authority-registry.json"
RIGHTS_TRANSFORM_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "rights-transform-registry.json"
RIGHTS_ACTIVATION_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "rights-activation-profile-registry.json"
RIGHTS_TS = ROOT / "packages" / "shared" / "rights-authority.ts"
RIGHTS_PY = ROOT / "Backend Architecture" / "aether-backend" / "shared" / "rights_authority" / "generated_registry.py"
RIGHTS_TABLE_MD = ROOT / "docs" / "_generated" / "rights-authority-registry-table.md"

# Markers used in events.ts to delimit the generated section
GENERATED_START = "// @generated-start"
GENERATED_END = "// @generated-end"

GENERATED_PY_HEADER = """\
# DO NOT EDIT — generated from packages/shared/contracts/event-registry.json
# Run: python scripts/generate_contracts.py
"""


# ---------------------------------------------------------------------------
# Registry loading and validation
# ---------------------------------------------------------------------------

def load_registries() -> tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    event_reg = json.loads(EVENT_REGISTRY.read_text())
    consent_reg = json.loads(CONSENT_REGISTRY.read_text())
    metric_reg = json.loads(METRIC_REGISTRY_JSON.read_text())
    integration_reg = json.loads(INTEGRATION_CONSENT_REGISTRY.read_text())
    traffic_reg = json.loads(TRAFFIC_SOURCE_REGISTRY.read_text())
    rights_reg = json.loads(RIGHTS_AUTHORITY_REGISTRY.read_text())
    transform_reg = json.loads(RIGHTS_TRANSFORM_REGISTRY.read_text())
    activation_reg = json.loads(RIGHTS_ACTIVATION_REGISTRY.read_text())
    return (
        event_reg, consent_reg, metric_reg, integration_reg, traffic_reg,
        rights_reg, transform_reg, activation_reg,
    )


def validate_rights_registries(
    rights_reg: dict, transform_reg: dict, activation_reg: dict,
) -> None:
    """Validate the IRRL vocabularies before emitting any language twin."""
    def unique(entries: list[dict], field: str, label: str) -> set[str]:
        values = [str(entry[field]) for entry in entries]
        if len(values) != len(set(values)):
            print(f"ERROR: duplicate {label} identifiers", file=sys.stderr)
            sys.exit(1)
        return set(values)

    classes = unique(rights_reg["rightsClasses"], "id", "rights class")
    actions = unique(rights_reg["actions"], "id", "rights action")
    profiles = unique(rights_reg["rightsProfiles"], "id", "rights profile")
    retention = unique(rights_reg["retentionClasses"], "id", "retention class")
    transforms = unique(transform_reg["transforms"], "id", "rights transform")
    activation_profiles = unique(activation_reg["profiles"], "id", "activation profile")
    if profiles != activation_profiles:
        print(
            "ERROR: rights profile and activation profile registries drift "
            f"missing={sorted(profiles - activation_profiles)} "
            f"extra={sorted(activation_profiles - profiles)}",
            file=sys.stderr,
        )
        sys.exit(1)
    for action in rights_reg["actions"]:
        if not action.get("id") or not action.get("label"):
            print("ERROR: rights action requires id and label", file=sys.stderr)
            sys.exit(1)
    for profile in rights_reg["rightsProfiles"]:
        unknown = set(profile.get("allowedActions", [])) - actions
        if unknown:
            print(f"ERROR: profile {profile['id']!r} has unknown actions {sorted(unknown)}", file=sys.stderr)
            sys.exit(1)
    for transform in transform_reg["transforms"]:
        unknown_inputs = set(transform.get("inputClasses", [])) - classes
        if transform.get("outputClass") not in classes:
            unknown_inputs.add(str(transform.get("outputClass")))
        if unknown_inputs:
            print(f"ERROR: transform {transform['id']!r} has unknown classes {sorted(unknown_inputs)}", file=sys.stderr)
            sys.exit(1)
    for state in activation_reg.get("rightsActivationStates", []):
        if not state.startswith("rights_"):
            print(f"ERROR: invalid rights activation state {state!r}", file=sys.stderr)
            sys.exit(1)
    if not retention:
        print("ERROR: rights registry must declare a retention class", file=sys.stderr)
        sys.exit(1)


def validate_metrics(metric_reg: dict) -> None:
    metrics = metric_reg["metrics"]

    # No duplicate metric names
    names_seen: set[str] = set()
    for m in metrics:
        name = m["name"]
        if name in names_seen:
            print(f"ERROR: duplicate metric name {name!r}", file=sys.stderr)
            sys.exit(1)
        names_seen.add(name)

    # Every metric carries the required fields
    required = ("name", "version", "unit", "allowsProbability", "minSample")
    for m in metrics:
        for field in required:
            if field not in m:
                print(
                    f"ERROR: metric {m.get('name')!r} missing field {field!r}",
                    file=sys.stderr,
                )
                sys.exit(1)


def validate(event_reg: dict, consent_reg: dict) -> None:
    events = event_reg["events"]
    purposes = {p["key"] for p in consent_reg["purposes"]}
    families = {e["family"] for e in events}

    # No duplicate event types
    types_seen: set[str] = set()
    for e in events:
        if e["type"] in types_seen:
            print(f"ERROR: duplicate event type {e['type']!r}", file=sys.stderr)
            sys.exit(1)
        types_seen.add(e["type"])

    # All referenced purposes must exist in consent registry
    for e in events:
        for p in e.get("requiredPurposes", []):
            if p not in purposes:
                print(f"ERROR: event {e['type']!r} references unknown purpose {p!r}", file=sys.stderr)
                sys.exit(1)

    # Validate consent purposes have required fields
    for p in consent_reg["purposes"]:
        for field in ("key", "label", "retentionDays", "revocationBehavior"):
            if field not in p:
                print(f"ERROR: consent purpose {p.get('key')!r} missing field {field!r}", file=sys.stderr)
                sys.exit(1)


def validate_integration_consent(integration_reg: dict, consent_reg: dict) -> None:
    """Validate the provider-neutral connector governance registry."""
    required = {
        "connectorType",
        "connectorClass",
        "provider",
        "category",
        "dataFlowDirection",
        "riskTier",
        "implementationStatus",
        "supportedCapabilities",
        "requiredTenantPermissions",
        "requiresProviderAdminInstall",
        "requiresTenantAdminApproval",
        "requiredSubjectPurposes",
        "supportedProcessingBases",
        "defaultProcessingBasis",
        "dataCategories",
        "identitySignals",
        "allowsIdentityLinking",
        "allowsGraphProjection",
        "allowsModelTraining",
        "allowsPreConsentProcessing",
        "complianceEvidenceEvents",
        "suppressionEvents",
        "retentionClass",
        "rawPayloadPolicy",
        "quarantinePolicy",
        "providerConsentBridge",
        "providerSignatureScheme",
        "supportsHistoricalBackfill",
        "supportsOutboundActivation",
    }
    expected = {
        "slack",
        "generic_webhook",
        "shopify",
        "stripe",
        "hubspot",
        "salesforce",
        "klaviyo",
        "sendgrid",
        "customerio",
        "mailchimp",
        "postmark",
        "iterable",
        "braze",
        "segment",
        "posthog",
        "ga4",
        "jira",
        "linear",
        "zendesk",
        "intercom",
        "dune",
        "apple_pay",
        "google_pay",
        "outbound_activation",
    }
    purposes = {p["key"] for p in consent_reg.get("purposes", [])}
    seen: set[str] = set()

    for entry in integration_reg.get("connectors", []):
        connector_type = entry.get("connectorType")
        if not connector_type:
            print("ERROR: integration connector missing connectorType", file=sys.stderr)
            sys.exit(1)
        if connector_type in seen:
            print(f"ERROR: duplicate integration connector {connector_type!r}", file=sys.stderr)
            sys.exit(1)
        seen.add(connector_type)

        missing = sorted(required - set(entry))
        if missing:
            print(
                f"ERROR: integration connector {connector_type!r} missing fields {missing}",
                file=sys.stderr,
            )
            sys.exit(1)

        for purpose in entry.get("requiredSubjectPurposes", []):
            if purpose not in purposes:
                print(
                    f"ERROR: integration connector {connector_type!r} references unknown purpose {purpose!r}",
                    file=sys.stderr,
                )
                sys.exit(1)

        if not entry.get("retentionClass") or not entry.get("rawPayloadPolicy"):
            print(
                f"ERROR: integration connector {connector_type!r} lacks retention/raw payload policy",
                file=sys.stderr,
            )
            sys.exit(1)

        signature = entry.get("providerSignatureScheme")
        if entry.get("supportsHistoricalBackfill") and signature in {"", "none", None}:
            print(
                f"ERROR: integration connector {connector_type!r} lacks provider signature scheme",
                file=sys.stderr,
            )
            sys.exit(1)

    missing_expected = sorted(expected - seen)
    extra = sorted(seen - expected)
    if missing_expected or extra:
        print(
            f"ERROR: integration connector set drift missing={missing_expected} extra={extra}",
            file=sys.stderr,
        )
        sys.exit(1)


def _ts_literal(value) -> str:
    return json.dumps(value, indent=2)


def validate_traffic_source(traffic_reg: dict) -> None:
    """Validate the canonical traffic-source registry.

    Every cross-reference inside the registry must point at a declared
    dimension value so no generator output can carry an invalid enum.
    """
    dims = traffic_reg["dimensions"]
    required_dims = (
        "traffic_origin", "economic_class", "channel_family",
        "source_class", "entry_method", "proof_level",
    )
    for dim in required_dims:
        values = dims.get(dim)
        if not values:
            print(f"ERROR: traffic-source registry missing dimension {dim!r}", file=sys.stderr)
            sys.exit(1)
        if len(values) != len(set(values)):
            print(f"ERROR: traffic-source dimension {dim!r} has duplicates", file=sys.stderr)
            sys.exit(1)

    source_classes = set(dims["source_class"])
    channel_families = set(dims["channel_family"])
    economic_classes = set(dims["economic_class"])
    entry_methods = set(dims["entry_method"])
    proof_levels = set(dims["proof_level"])

    defaults = {k: v for k, v in traffic_reg["sourceClassDefaults"].items() if not k.startswith("_")}
    if set(defaults) != source_classes:
        print(
            f"ERROR: sourceClassDefaults drift — missing={sorted(source_classes - set(defaults))} "
            f"extra={sorted(set(defaults) - source_classes)}",
            file=sys.stderr,
        )
        sys.exit(1)
    for sc, d in defaults.items():
        if d["channelFamily"] not in channel_families:
            print(f"ERROR: sourceClassDefaults[{sc!r}] unknown channelFamily {d['channelFamily']!r}", file=sys.stderr)
            sys.exit(1)
        if d["economicClass"] not in economic_classes:
            print(f"ERROR: sourceClassDefaults[{sc!r}] unknown economicClass {d['economicClass']!r}", file=sys.stderr)
            sys.exit(1)
        if not d.get("label"):
            print(f"ERROR: sourceClassDefaults[{sc!r}] missing label", file=sys.stderr)
            sys.exit(1)

    for legacy, canonical in traffic_reg["legacySourceClassAliases"].items():
        if legacy.startswith("_"):
            continue
        if canonical not in source_classes:
            print(f"ERROR: legacy alias {legacy!r} maps to unknown source_class {canonical!r}", file=sys.stderr)
            sys.exit(1)
    for channel, canonical in traffic_reg["legacyPaidChannelMap"].items():
        if channel.startswith("_"):
            continue
        if canonical not in source_classes:
            print(f"ERROR: legacyPaidChannelMap {channel!r} maps to unknown source_class {canonical!r}", file=sys.stderr)
            sys.exit(1)

    for click_id, meta in traffic_reg["clickIdClasses"].items():
        if click_id.startswith("_"):
            continue
        if meta["sourceClass"] not in source_classes:
            print(f"ERROR: clickIdClasses[{click_id!r}] unknown sourceClass {meta['sourceClass']!r}", file=sys.stderr)
            sys.exit(1)

    ceilings = {k: v for k, v in traffic_reg["entryMethodProofCeilings"].items() if not k.startswith("_")}
    if set(ceilings) != entry_methods:
        print(
            f"ERROR: entryMethodProofCeilings drift — missing={sorted(entry_methods - set(ceilings))} "
            f"extra={sorted(set(ceilings) - entry_methods)}",
            file=sys.stderr,
        )
        sys.exit(1)
    for method, level in ceilings.items():
        if level not in proof_levels:
            print(f"ERROR: entryMethodProofCeilings[{method!r}] unknown proof_level {level!r}", file=sys.stderr)
            sys.exit(1)


def _strip_comments(value):
    """Recursively drop '_comment' keys so generated artifacts stay data-only."""
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if k != "_comment"}
    if isinstance(value, list):
        return [_strip_comments(v) for v in value]
    return value


def gen_traffic_source_ts(traffic_reg: dict) -> str:
    reg = _strip_comments(traffic_reg)
    dims = reg["dimensions"]
    version = reg["contractVersion"]

    def union(name: str) -> str:
        return "\n".join(f"  | '{v}'" for v in dims[name])

    def const_array(name: str) -> str:
        return "\n".join(f"  '{v}'," for v in dims[name])

    defaults_entries = "\n".join(
        f"  {json.dumps(sc)}: {{ channelFamily: {json.dumps(d['channelFamily'])}, "
        f"economicClass: {json.dumps(d['economicClass'])}, label: {json.dumps(d['label'])} }},"
        for sc, d in reg["sourceClassDefaults"].items()
    )

    return (
        "// =============================================================================\n"
        f"// Aether SDK — Canonical Traffic-Source Contract (v{version})\n"
        "// DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json\n"
        "// Run: python scripts/generate_contracts.py\n"
        "//\n"
        "// SDKs observe acquisition evidence; the backend classifies. These types exist\n"
        "// so SDKs and product surfaces can name backend classifications without ever\n"
        "// computing them locally. Classification and campaign identity are separate\n"
        "// dimensions: none of these values implies a campaign.\n"
        "// =============================================================================\n"
        "\n"
        f"export const TRAFFIC_SOURCE_CONTRACT_VERSION = '{version}';\n"
        "\n"
        "/** Where the visit physically came from, independent of who paid for it. */\n"
        "export type TrafficOrigin =\n"
        f"{union('traffic_origin')};\n"
        "\n"
        "/** Whether money is known to be behind the touch. */\n"
        "export type EconomicClass =\n"
        f"{union('economic_class')};\n"
        "\n"
        "/** Coarse channel grouping used for reporting rollups. */\n"
        "export type ChannelFamily =\n"
        f"{union('channel_family')};\n"
        "\n"
        "/** Canonical source classification. 'direct_unknown' is the honest fallback —\n"
        " * it never claims the user typed a URL. */\n"
        "export type SourceClass =\n"
        f"{union('source_class')};\n"
        "\n"
        "/** How the entry evidence was physically observed. */\n"
        "export type EntryMethod =\n"
        f"{union('entry_method')};\n"
        "\n"
        "/** Strength of the evidence behind the classification. */\n"
        "export type ProofLevel =\n"
        f"{union('proof_level')};\n"
        "\n"
        "export const TRAFFIC_ORIGINS: readonly TrafficOrigin[] = [\n"
        f"{const_array('traffic_origin')}\n"
        "] as const;\n"
        "\n"
        "export const ECONOMIC_CLASSES: readonly EconomicClass[] = [\n"
        f"{const_array('economic_class')}\n"
        "] as const;\n"
        "\n"
        "export const CHANNEL_FAMILIES: readonly ChannelFamily[] = [\n"
        f"{const_array('channel_family')}\n"
        "] as const;\n"
        "\n"
        "export const SOURCE_CLASSES: readonly SourceClass[] = [\n"
        f"{const_array('source_class')}\n"
        "] as const;\n"
        "\n"
        "export const ENTRY_METHODS: readonly EntryMethod[] = [\n"
        f"{const_array('entry_method')}\n"
        "] as const;\n"
        "\n"
        "export const PROOF_LEVELS: readonly ProofLevel[] = [\n"
        f"{const_array('proof_level')}\n"
        "] as const;\n"
        "\n"
        "export interface SourceClassDefaults {\n"
        "  channelFamily: ChannelFamily;\n"
        "  economicClass: EconomicClass;\n"
        "  /** Customer-facing label. 'direct_unknown' renders as 'Direct / Unknown',\n"
        "   * never as a typed-URL claim. */\n"
        "  label: string;\n"
        "}\n"
        "\n"
        "export const SOURCE_CLASS_DEFAULTS: Readonly<Record<SourceClass, SourceClassDefaults>> = {\n"
        f"{defaults_entries}\n"
        "};\n"
        "\n"
        "/** Historical source_class values normalized at API boundaries. */\n"
        "export const LEGACY_SOURCE_CLASS_ALIASES: Readonly<Record<string, SourceClass>> =\n"
        f"  {json.dumps(reg['legacySourceClassAliases'])};\n"
        "\n"
        "/** Normalize a possibly-legacy source_class value to the canonical vocabulary. */\n"
        "export function canonicalSourceClass(value: string): SourceClass | string {\n"
        "  return LEGACY_SOURCE_CLASS_ALIASES[value] ?? value;\n"
        "}\n"
    )


def gen_traffic_source_py(traffic_reg: dict) -> str:
    reg = _strip_comments(traffic_reg)
    dims = reg["dimensions"]
    version = reg["contractVersion"]

    def frozenset_lines(name: str) -> str:
        return ",\n".join(f'    "{v}"' for v in sorted(dims[name]))

    def dict_block(mapping: dict) -> str:
        return "\n".join(
            f"    {json.dumps(k)}: {json.dumps(v)}," for k, v in sorted(mapping.items())
        )

    return (
        "# DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json\n"
        "# Run: python scripts/generate_contracts.py\n"
        f"# Contract version: {version}\n"
        '"""Canonical traffic-source vocabulary shared by classifier, projections and APIs."""\n'
        "\n"
        f'TRAFFIC_SOURCE_CONTRACT_VERSION = "{version}"\n'
        "\n"
        "TRAFFIC_ORIGINS: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('traffic_origin')},\n"
        "})\n"
        "\n"
        "ECONOMIC_CLASSES: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('economic_class')},\n"
        "})\n"
        "\n"
        "CHANNEL_FAMILIES: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('channel_family')},\n"
        "})\n"
        "\n"
        "SOURCE_CLASSES: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('source_class')},\n"
        "})\n"
        "\n"
        "ENTRY_METHODS: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('entry_method')},\n"
        "})\n"
        "\n"
        "PROOF_LEVELS: frozenset[str] = frozenset({\n"
        f"{frozenset_lines('proof_level')},\n"
        "})\n"
        "\n"
        "# source_class -> {channelFamily, economicClass, label}. Labels are the\n"
        "# customer-facing vocabulary: direct_unknown renders as 'Direct / Unknown',\n"
        "# never as an unsupported typed-URL claim.\n"
        "SOURCE_CLASS_DEFAULTS: dict[str, dict[str, str]] = {\n"
        f"{dict_block(reg['sourceClassDefaults'])}\n"
        "}\n"
        "\n"
        "# Historical values normalized to the canonical vocabulary at API boundaries.\n"
        "LEGACY_SOURCE_CLASS_ALIASES: dict[str, str] = {\n"
        f"{dict_block(reg['legacySourceClassAliases'])}\n"
        "}\n"
        "\n"
        "# v2 display channel -> canonical source_class for legacy 'paid' rows.\n"
        "LEGACY_PAID_CHANNEL_MAP: dict[str, str] = {\n"
        f"{dict_block(reg['legacyPaidChannelMap'])}\n"
        "}\n"
        "\n"
        "# Lowercased utm_source tokens -> canonical search platform.\n"
        "UTM_SEARCH_SOURCE_ALIASES: dict[str, str] = {\n"
        f"{dict_block(reg['utmSourceAliases']['search'])}\n"
        "}\n"
        "\n"
        "# Lowercased utm_source tokens -> canonical social platform.\n"
        "UTM_SOCIAL_SOURCE_ALIASES: dict[str, str] = {\n"
        f"{dict_block(reg['utmSourceAliases']['social'])}\n"
        "}\n"
        "\n"
        "# Lowercased utm_medium token sets, evaluated together with utm_source.\n"
        "MEDIUM_TOKENS: dict[str, frozenset[str]] = {\n"
        + "\n".join(
            f"    {json.dumps(k)}: frozenset({sorted(v)!r}),"
            for k, v in sorted(reg["mediumTokens"].items())
        )
        + "\n"
        "}\n"
        "\n"
        "# Advertising click identifiers -> {source, sourceClass}. Paid click evidence\n"
        "# outranks conflicting self-declared organic UTM labels; conflicts are recorded.\n"
        "CLICK_ID_CLASSES: dict[str, dict[str, str]] = {\n"
        f"{dict_block(reg['clickIdClasses'])}\n"
        "}\n"
        "\n"
        "# Maximum proof_level each entry_method can justify on its own.\n"
        "ENTRY_METHOD_PROOF_CEILINGS: dict[str, str] = {\n"
        f"{dict_block(reg['entryMethodProofCeilings'])}\n"
        "}\n"
        "\n"
        "\n"
        "def canonical_source_class(value: str) -> str:\n"
        '    """Normalize a possibly-legacy source_class to the canonical vocabulary."""\n'
        "    return LEGACY_SOURCE_CLASS_ALIASES.get(value, value)\n"
    )


def gen_traffic_source_table_md(traffic_reg: dict) -> str:
    reg = _strip_comments(traffic_reg)
    dims = reg["dimensions"]
    version = reg["contractVersion"]

    dim_rows = "\n".join(
        f"| `{name}` | {len(values)} | {', '.join('`' + v + '`' for v in values)} |"
        for name, values in dims.items()
    )
    class_rows = "\n".join(
        f"| `{sc}` | `{d['channelFamily']}` | `{d['economicClass']}` | {d['label']} |"
        for sc, d in reg["sourceClassDefaults"].items()
    )
    return (
        "<!-- DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json -->\n"
        "<!-- Run: python scripts/generate_contracts.py -->\n"
        "\n"
        f"# Aether Canonical Traffic-Source Registry (contract v{version})\n"
        "\n"
        "Classification and campaign identity are independent dimensions. The\n"
        "customer-facing fallback is **Direct / Unknown** — never a typed-URL claim.\n"
        "\n"
        "## Dimensions\n"
        "\n"
        "| Dimension | Values | Vocabulary |\n"
        "|---|---|---|\n"
        f"{dim_rows}\n"
        "\n"
        "## Source classes\n"
        "\n"
        "| Source class | Channel family | Economic class | Label |\n"
        "|---|---|---|---|\n"
        f"{class_rows}\n"
    )


# ---------------------------------------------------------------------------
# consent.ts generator
# ---------------------------------------------------------------------------

def gen_consent_ts(consent_reg: dict) -> str:
    purposes = consent_reg["purposes"]
    version = consent_reg["contractVersion"]

    purpose_keys = [p["key"] for p in purposes]
    required_opt_in = [p["key"] for p in purposes if p.get("explicitOptInRequired")]
    default_enabled = {p["key"]: p.get("defaultEnabled", False) for p in purposes}

    union_lines = "\n".join(f"  | '{k}'" for k in purpose_keys)
    const_array = "\n".join(f"  '{k}'," for k in purpose_keys)
    state_fields = "\n".join(f"  {k}: boolean;" for k in purpose_keys)
    default_fields = "\n".join(
        f"  {k}: {'true' if default_enabled[k] else 'false'},"
        for k in purpose_keys
    )

    purpose_docs = []
    for p in purposes:
        note = ""
        if p.get("explicitOptInRequired"):
            note = " Always requires explicit opt-in."
        purpose_docs.append(f" * - {p['key']}: {p['description']}{note}")
    purpose_doc_str = "\n".join(purpose_docs)

    return textwrap.dedent(f"""\
        // =============================================================================
        // Aether SDK — Shared Consent Contract (v{version})
        // DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json
        // Run: python scripts/generate_contracts.py
        // =============================================================================

        /**
         * Canonical consent purposes. Web SDK, native SDKs, and the backend validator
         * MUST all recognize these exact strings.
         *
        {purpose_doc_str}
         */
        export type ConsentPurpose =
        {union_lines};

        export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
        {const_array}
        ] as const;

        /** Purposes that ALWAYS require explicit opt-in (never granted by accept-all). */
        export const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = [
        {chr(10).join("  '" + k + "'," for k in required_opt_in)}
        ] as const;

        /** Consent state stored locally by each SDK and stamped onto every event. */
        export interface ConsentState {{
        {state_fields}
          updatedAt: string;
          policyVersion: string;
        }}

        export interface ConsentConfig {{
          purposes: ConsentPurpose[];
          policyUrl: string;
          policyVersion: string;
        }}

        /**
         * Default consent state used by every SDK at init (no consent granted).
         * Consent UI pre-checks purposes based on defaultEnabled in the registry.
         */
        export const DEFAULT_CONSENT_STATE: Omit<ConsentState, 'updatedAt' | 'policyVersion'> = {{
        {default_fields}
        }};
        """)


# ---------------------------------------------------------------------------
# events.ts generated-section generator
# ---------------------------------------------------------------------------

def _grouped_event_lines(events: list[dict]) -> str:
    """Emit EventType union lines grouped by family."""
    from collections import defaultdict
    by_family: dict[str, list[str]] = defaultdict(list)
    family_order: list[str] = []
    for e in events:
        f = e["family"]
        if f not in by_family:
            family_order.append(f)
        by_family[f].append(e["type"])

    lines: list[str] = []
    for family in family_order:
        types = by_family[family]
        lines.append(f"  // {family}")
        for t in types:
            lines.append(f"  | '{t}'")
    return "\n".join(lines)


def _family_union(events: list[dict]) -> str:
    families = sorted(set(e["family"] for e in events))
    return "\n".join(f"  | '{f}'" for f in families)


def _event_family_map(events: list[dict]) -> str:
    lines: list[str] = []
    for e in events:
        lines.append(f"  {e['type']}: '{e['family']}',")
    # Group into compact rows of 4
    return "\n".join(lines)


def _event_consent_map(events: list[dict]) -> str:
    lines: list[str] = []
    for e in events:
        purposes = e.get("requiredPurposes", [])
        primary = purposes[0] if purposes else "analytics"
        lines.append(f"  {e['type']}: '{primary}',")
    return "\n".join(lines)


def gen_events_ts_section(event_reg: dict) -> str:
    """Return the content to insert between @generated-start and @generated-end."""
    events = event_reg["events"]
    version = event_reg["contractVersion"]

    return (
        f"// @generated — DO NOT EDIT. Source: packages/shared/contracts/event-registry.json\n"
        f"// Contract version: {version} — Run: python scripts/generate_contracts.py\n"
        f"\n"
        f"/** The canonical event-type string union the backend validates. */\n"
        f"export type EventType =\n"
        f"{_grouped_event_lines(events)}\n"
        f"  ;\n"
        f"\n"
        f"export type EventFamily =\n"
        f"{_family_union(events)}\n"
        f"  ;\n"
        f"\n"
        f"/** Map from each event type to its family. */\n"
        f"export const EVENT_FAMILY: Record<EventType, EventFamily> = {{\n"
        f"{_event_family_map(events)}\n"
        f"}};\n"
        f"\n"
        f"/**\n"
        f" * Primary required consent purpose for each event type.\n"
        f" * Events with empty requiredPurposes (e.g. 'consent') are omitted — always allowed.\n"
        f" */\n"
        f"export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {{\n"
        f"{_event_consent_map(events)}\n"
        f"}};\n"
    )


def update_events_ts(event_reg: dict, current: str) -> str:
    """Replace the generated section between markers, preserving everything else."""
    start_idx = current.find(GENERATED_START)
    end_idx = current.find(GENERATED_END)

    if start_idx == -1 or end_idx == -1:
        print(
            "ERROR: events.ts is missing @generated-start / @generated-end markers.\n"
            "Add the markers around the EventType union, EventFamily, EVENT_FAMILY, "
            "and EVENT_CONSENT_PURPOSE sections.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Everything up to and including the start marker line
    preamble = current[: start_idx + len(GENERATED_START)] + "\n"
    # Everything from the end marker onward
    postamble = current[end_idx:]

    inner = gen_events_ts_section(event_reg)
    return preamble + inner + postamble


# ---------------------------------------------------------------------------
# generated_registry.py generator
# ---------------------------------------------------------------------------

def gen_python_registry(event_reg: dict, consent_reg: dict) -> str:
    events = event_reg["events"]
    version = event_reg["contractVersion"]

    type_lines = ",\n".join(f'    "{e["type"]}"' for e in events)

    consent_lines: list[str] = []
    for e in events:
        purposes = e.get("requiredPurposes", [])
        primary = purposes[0] if purposes else "analytics"
        consent_lines.append(f'    "{e["type"]}": "{primary}",')
    consent_map = "\n".join(consent_lines)

    family_lines = "\n".join(f'    "{e["type"]}": "{e["family"]}",' for e in events)

    purpose_keys = sorted(p["key"] for p in consent_reg.get("purposes", []))
    purpose_lines = ",\n".join(f'    "{k}"' for k in purpose_keys)

    return (
        f"{GENERATED_PY_HEADER}"
        f"# Contract version: {version}\n"
        f"\n"
        f'CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({{\n'
        f'{type_lines},\n'
        f'}})\n'
        f"\n"
        f"# Canonical consent purposes — generated from consent-registry.json.\n"
        f"CONSENT_PURPOSES: frozenset[str] = frozenset({{\n"
        f"{purpose_lines},\n"
        f"}})\n"
        f"\n"
        f"# Primary required consent purpose per event type.\n"
        f"# Events with no required purposes (e.g. 'consent') map to 'analytics'.\n"
        f"EVENT_CONSENT_PURPOSE: dict[str, str] = {{\n"
        f"{consent_map}\n"
        f"}}\n"
        f"\n"
        f"EVENT_FAMILY: dict[str, str] = {{\n"
        f"{family_lines}\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Web SDK generated consent map generator
# ---------------------------------------------------------------------------

def gen_web_consent_map_ts(event_reg: dict) -> str:
    """Registry-derived event->consent-purpose map + canonical type set for the
    web SDK. Replaces the previously hand-maintained CONSENT_MAP so the runtime
    consent gate cannot drift from the canonical registry.
    """
    events = event_reg["events"]
    version = event_reg["contractVersion"]

    rows = sorted(
        (e["type"], (e.get("requiredPurposes") or ["analytics"])[0]) for e in events
    )
    entries = "\n".join(f'  {json.dumps(t)}: {json.dumps(p)},' for t, p in rows)

    return (
        "// DO NOT EDIT — generated from packages/shared/contracts/event-registry.json\n"
        "// Run: python scripts/generate_contracts.py\n"
        f"// Contract version: {version}\n"
        "//\n"
        "// Registry-derived event -> primary-consent-purpose map and canonical event\n"
        "// type set for the web SDK. This replaces the previously hand-maintained\n"
        "// CONSENT_MAP so the runtime consent gate can never drift from the registry.\n"
        "\n"
        "export const EVENT_CONSENT_PURPOSE: Readonly<Record<string, string>> = {\n"
        f"{entries}\n"
        "};\n"
        "\n"
        "/** Every canonical event type the backend registry recognises. */\n"
        "export const CANONICAL_EVENT_TYPES: ReadonlySet<string> = new Set(\n"
        "  Object.keys(EVENT_CONSENT_PURPOSE),\n"
        ");\n"
        "\n"
        "/** True if `type` is a canonical registry event type. */\n"
        "export function isCanonicalEventType(type: string): boolean {\n"
        "  return CANONICAL_EVENT_TYPES.has(type);\n"
        "}\n"
    )


def gen_integration_consent_ts(reg: dict) -> str:
    connectors = reg["connectors"]
    version = reg["contractVersion"]
    connector_union = "\n".join(f"  | '{c['connectorType']}'" for c in connectors)
    entries = ",\n".join(
        f"  {json.dumps(c['connectorType'])}: {_ts_literal(c)}" for c in connectors
    )
    flags = [
        "AETHER_CONSENT_CONTROL_PLANE_V2",
        "AETHER_CONNECTOR_POLICY_GATE",
        "AETHER_INTEGRATION_DISCOVERY",
        "AETHER_PREFERENCE_CENTER_V1",
        "AETHER_CHECKOUT_HARDENING_V1",
        "AETHER_CONSENT_LIFECYCLE_ENFORCEMENT",
    ]
    flag_union = "\n".join(f"  | '{flag}'" for flag in flags)
    flag_entries = "\n".join(f"  {json.dumps(flag)}: false," for flag in flags)

    return textwrap.dedent(f"""\
        // =============================================================================
        // Aether SDK — Integration Consent Governance Registry (v{version})
        // DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json
        // Run: python scripts/generate_contracts.py
        // =============================================================================

        import type {{ ConsentPurpose }} from './consent';

        export type IntegrationConnectorType =
        {connector_union}
          ;

        export type AetherConsentControlPlaneFlag =
        {flag_union}
          ;

        export interface ProcessingDecision {{
          decisionId: string;
          tenantId: string;
          connectorType?: IntegrationConnectorType | string;
          sourceKind: string;
          subjectId?: string;
          anonymousId?: string;
          purpose?: ConsentPurpose | string;
          processingBasis?: string;
          allowed: boolean;
          reasonCode?: string;
          identityLinkingAllowed: boolean;
          graphProjectionAllowed: boolean;
          modelTrainingAllowed: boolean;
          activationAllowed: boolean;
          retentionClass: string;
          quarantineRequired: boolean;
          policyVersion: string;
          consentReceiptId?: string;
          evaluatedAt: string;
        }}

        export interface CanonicalConsentReceipt {{
          receipt_id: string;
          tenant_id: string;
          subject_id?: string;
          anonymous_id?: string;
          purposes: readonly ConsentPurpose[];
          state: 'granted' | 'denied' | 'revoked' | 'expired';
          source: string;
          provider?: string;
          policy_version: string;
          jurisdiction_context?: string;
          mode?: string;
          lawful_basis?: string;
          granted_at?: string;
          denied_at?: string;
          revoked_at?: string;
          expires_at?: string;
          gpc_observed?: boolean;
          dnt_observed?: boolean;
          provider_consent_id?: string;
          integrity_hash: string;
          idempotency_key: string;
          metadata?: Readonly<Record<string, unknown>>;
        }}

        export interface IntegrationConsentPolicy {{
          connectorType: IntegrationConnectorType;
          connectorClass: string;
          provider: string;
          category: string;
          dataFlowDirection: string;
          riskTier: string;
          implementationStatus: string;
          supportedCapabilities: readonly string[];
          requiredTenantPermissions: readonly string[];
          requiresProviderAdminInstall: boolean;
          requiresTenantAdminApproval: boolean;
          requiredSubjectPurposes: readonly ConsentPurpose[];
          supportedProcessingBases: readonly string[];
          defaultProcessingBasis: string;
          dataCategories: readonly string[];
          identitySignals: readonly string[];
          allowsIdentityLinking: boolean;
          allowsGraphProjection: boolean;
          allowsModelTraining: boolean;
          allowsPreConsentProcessing: boolean;
          complianceEvidenceEvents: readonly string[];
          suppressionEvents: readonly string[];
          retentionClass: string;
          rawPayloadPolicy: string;
          quarantinePolicy: string;
          providerConsentBridge: string;
          providerSignatureScheme: string;
          supportsHistoricalBackfill: boolean;
          supportsOutboundActivation: boolean;
          notes?: string;
        }}

        export const INTEGRATION_CONSENT_REGISTRY_VERSION = '{version}';

        export const AETHER_CONSENT_CONTROL_PLANE_FLAGS: Readonly<Record<AetherConsentControlPlaneFlag, false>> = {{
        {flag_entries}
        }} as const;

        export const INTEGRATION_CONSENT_POLICIES: Readonly<Record<IntegrationConnectorType, IntegrationConsentPolicy>> = {{
        {entries}
        }} as const;
        """)


def gen_integration_consent_py(reg: dict) -> str:
    flags = [
        "AETHER_CONSENT_CONTROL_PLANE_V2",
        "AETHER_CONNECTOR_POLICY_GATE",
        "AETHER_INTEGRATION_DISCOVERY",
        "AETHER_PREFERENCE_CENTER_V1",
        "AETHER_CHECKOUT_HARDENING_V1",
        "AETHER_CONSENT_LIFECYCLE_ENFORCEMENT",
    ]
    return (
        "# DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json\n"
        "# Run: python scripts/generate_contracts.py\n"
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class ProcessingDecision:\n"
        "    decisionId: str\n"
        "    tenantId: str\n"
        "    sourceKind: str\n"
        "    allowed: bool\n"
        "    identityLinkingAllowed: bool\n"
        "    graphProjectionAllowed: bool\n"
        "    modelTrainingAllowed: bool\n"
        "    activationAllowed: bool\n"
        "    retentionClass: str\n"
        "    quarantineRequired: bool\n"
        "    policyVersion: str\n"
        "    evaluatedAt: str\n"
        "    connectorType: str | None = None\n"
        "    subjectId: str | None = None\n"
        "    anonymousId: str | None = None\n"
        "    purpose: str | None = None\n"
        "    processingBasis: str | None = None\n"
        "    reasonCode: str | None = None\n"
        "    consentReceiptId: str | None = None\n\n"
        f"INTEGRATION_CONSENT_REGISTRY_VERSION = {reg['contractVersion']!r}\n"
        f"AETHER_CONSENT_CONTROL_PLANE_FLAGS = {dict.fromkeys(flags, False)!r}\n"
        f"INTEGRATION_CONSENT_POLICIES = {reg['connectors']!r}\n"
        "INTEGRATION_CONSENT_POLICY_BY_TYPE = {p['connectorType']: p for p in INTEGRATION_CONSENT_POLICIES}\n"
    )


def gen_integration_consent_swift(reg: dict) -> str:
    cases = "\n".join(
        f"    case {c['connectorType'].replace('_', '')} = \"{c['connectorType']}\""
        for c in reg["connectors"]
    )
    return f"""// DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json
// Run: python scripts/generate_contracts.py
import Foundation

public let integrationConsentRegistryVersion = "{reg['contractVersion']}"

public enum IntegrationConnectorType: String, CaseIterable {{
{cases}
}}

public struct ProcessingDecision: Codable, Equatable {{
    public let decisionId: String
    public let tenantId: String
    public let connectorType: String?
    public let sourceKind: String
    public let subjectId: String?
    public let anonymousId: String?
    public let purpose: String?
    public let processingBasis: String?
    public let allowed: Bool
    public let reasonCode: String?
    public let identityLinkingAllowed: Bool
    public let graphProjectionAllowed: Bool
    public let modelTrainingAllowed: Bool
    public let activationAllowed: Bool
    public let retentionClass: String
    public let quarantineRequired: Bool
    public let policyVersion: String
    public let consentReceiptId: String?
    public let evaluatedAt: String
}}
"""


def gen_integration_consent_kotlin(reg: dict) -> str:
    entries = ",\n".join(
        f"    {c['connectorType'].upper()}(\"{c['connectorType']}\")"
        for c in reg["connectors"]
    )
    return f"""// DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json
// Run: python scripts/generate_contracts.py
package com.aether.sdk

const val INTEGRATION_CONSENT_REGISTRY_VERSION: String = "{reg['contractVersion']}"

enum class IntegrationConnectorType(val connectorType: String) {{
{entries}
}}

data class ProcessingDecision(
    val decisionId: String,
    val tenantId: String,
    val connectorType: String? = null,
    val sourceKind: String,
    val subjectId: String? = null,
    val anonymousId: String? = null,
    val purpose: String? = null,
    val processingBasis: String? = null,
    val allowed: Boolean,
    val reasonCode: String? = null,
    val identityLinkingAllowed: Boolean,
    val graphProjectionAllowed: Boolean,
    val modelTrainingAllowed: Boolean,
    val activationAllowed: Boolean,
    val retentionClass: String,
    val quarantineRequired: Boolean,
    val policyVersion: String,
    val consentReceiptId: String? = null,
    val evaluatedAt: String,
)
"""


# ---------------------------------------------------------------------------
# measurement-contract.ts + generated_registry.py (metric) generators
# ---------------------------------------------------------------------------

def _ts_number(value) -> str:
    """Render a JSON number/None as a TypeScript numeric-or-null literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # bool is a subclass of int — guard first
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _py_value(value) -> str:
    """Render a JSON scalar as a Python literal (None/bool/int/float/str)."""
    if value is None:
        return "None"
    if isinstance(value, bool):  # bool is a subclass of int — guard first
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    return repr(str(value))


def gen_measurement_ts(metric_reg: dict) -> str:
    metrics = metric_reg["metrics"]
    version = metric_reg["contractVersion"]

    name_union = "\n".join(f"  | '{m['name']}'" for m in metrics)

    def_objects: list[str] = []
    for m in metrics:
        def_objects.append(
            "  {\n"
            f"    name: '{m['name']}',\n"
            f"    version: '{m['version']}',\n"
            f"    unit: '{m['unit']}',\n"
            f"    description: '{m.get('description', '')}',\n"
            f"    lower: {_ts_number(m.get('lower'))},\n"
            f"    upper: {_ts_number(m.get('upper'))},\n"
            f"    allowsProbability: {_ts_number(m['allowsProbability'])},\n"
            f"    minSample: {_ts_number(m['minSample'])},\n"
            "  },"
        )
    defs_str = "\n".join(def_objects)

    return textwrap.dedent(f"""\
        // =============================================================================
        // Aether SDK — Shared Metric Registry Contract (v{version})
        // DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json
        // Run: python scripts/generate_contracts.py
        // =============================================================================

        /** Contract version of the canonical metric registry. */
        export const metricRegistryVersion = '{version}';

        /** Canonical metric names the measurement plane knows how to report. */
        export type MetricName =
        {name_union}
          ;

        /** Definition of a single measurable metric. */
        export interface MetricDefinition {{
          name: MetricName;
          version: string;
          unit: string;
          description: string;
          lower: number | null;
          upper: number | null;
          allowsProbability: boolean;
          minSample: number;
        }}

        /** Every registered metric definition, keyed positionally by MetricName. */
        export const metricDefinitions: readonly MetricDefinition[] = [
        {defs_str}
        ] as const;
        """)


def gen_metric_registry_py(metric_reg: dict) -> str:
    metrics = metric_reg["metrics"]
    version = metric_reg["contractVersion"]

    entries: list[str] = []
    for m in metrics:
        entries.append(
            f'    "{m["name"]}": {{\n'
            f'        "name": {_py_value(m["name"])},\n'
            f'        "version": {_py_value(m["version"])},\n'
            f'        "unit": {_py_value(m["unit"])},\n'
            f'        "description": {_py_value(m.get("description", ""))},\n'
            f'        "lower": {_py_value(m.get("lower"))},\n'
            f'        "upper": {_py_value(m.get("upper"))},\n'
            f'        "allows_probability": {_py_value(m["allowsProbability"])},\n'
            f'        "min_sample": {_py_value(m["minSample"])},\n'
            f'    }},'
        )
    entries_str = "\n".join(entries)

    return (
        f"{GENERATED_PY_HEADER}"
        f"# Source: packages/shared/contracts/metric-registry.json\n"
        f"# Contract version: {version}\n"
        f"\n"
        f'GENERATED_METRIC_REGISTRY_VERSION = "{version}"\n'
        f"\n"
        f"# Metric name -> field dict. Field names mirror shared/measurement/registry.py's\n"
        f"# MetricDefinition so the parity test can compare the two source by source.\n"
        f"GENERATED_METRICS: dict[str, dict] = {{\n"
        f"{entries_str}\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Markdown docs generators
# ---------------------------------------------------------------------------

def gen_event_table_md(event_reg: dict) -> str:
    events = event_reg["events"]
    version = event_reg["contractVersion"]
    total = len(events)

    rows: list[str] = []
    for e in events:
        purposes = ", ".join(e.get("requiredPurposes", []) or ["—"])
        status = e.get("status", "active")
        marker = " *(deprecated)*" if status == "deprecated" else ""
        rows.append(
            f"| `{e['type']}`{marker} | `{e['family']}` | {purposes} | "
            f"{e.get('privacyClass', '')} | {e.get('description', '')} |"
        )

    rows_str = "\n".join(rows)
    return (
        f"<!-- DO NOT EDIT — generated from packages/shared/contracts/event-registry.json -->\n"
        f"<!-- Run: python scripts/generate_contracts.py -->\n"
        f"\n"
        f"# Aether Event Registry ({total} types, contract v{version})\n"
        f"\n"
        f"| Event Type | Family | Required Purposes | Privacy Class | Description |\n"
        f"|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


def gen_consent_table_md(consent_reg: dict) -> str:
    purposes = consent_reg["purposes"]
    version = consent_reg["contractVersion"]

    rows: list[str] = []
    for p in purposes:
        opt_in = "✓ required" if p.get("explicitOptInRequired") else "no"
        default = "yes" if p.get("defaultEnabled") else "no"
        retention = f"{p['retentionDays']}d"
        rows.append(
            f"| `{p['key']}` | {p['label']} | {default} | {opt_in} | "
            f"{retention} | {p.get('revocationBehavior', '')} | {p.get('description', '')} |"
        )

    rows_str = "\n".join(rows)
    return (
        f"<!-- DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json -->\n"
        f"<!-- Run: python scripts/generate_contracts.py -->\n"
        f"\n"
        f"# Aether Consent Registry ({len(purposes)} purposes, contract v{version})\n"
        f"\n"
        f"| Purpose | Label | Default | Explicit Opt-in | Retention | Revocation | Description |\n"
        f"|---|---|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


def gen_metric_table_md(metric_reg: dict) -> str:
    metrics = metric_reg["metrics"]
    version = metric_reg["contractVersion"]

    rows: list[str] = []
    for m in metrics:
        lower = m.get("lower")
        upper = m.get("upper")
        lo = "-∞" if lower is None else repr(lower)
        hi = "∞" if upper is None else repr(upper)
        bounds = f"[{lo}, {hi}]"
        allows = "yes" if m["allowsProbability"] else "no"
        rows.append(
            f"| `{m['name']}` | {m['version']} | {m['unit']} | {bounds} | "
            f"{allows} | {m['minSample']} | {m.get('description', '')} |"
        )

    rows_str = "\n".join(rows)
    return (
        f"<!-- DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json -->\n"
        f"<!-- Run: python scripts/generate_contracts.py -->\n"
        f"\n"
        f"# Aether Metric Registry ({len(metrics)} metrics, contract v{version})\n"
        f"\n"
        f"| Metric | Version | Unit | Bounds | Allows Probability | Min Sample | Description |\n"
        f"|---|---|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


def gen_integration_consent_table_md(reg: dict) -> str:
    rows: list[str] = []
    for c in reg["connectors"]:
        purposes = ", ".join(c["requiredSubjectPurposes"])
        rows.append(
            f"| `{c['connectorType']}` | {c['provider']} | {c['category']} | "
            f"{c['riskTier']} | {c['implementationStatus']} | {purposes} | "
            f"{c['defaultProcessingBasis']} | {c['rawPayloadPolicy']} | "
            f"{c['providerSignatureScheme']} |"
        )
    rows_str = "\n".join(rows)
    return (
        "<!-- DO NOT EDIT — generated from packages/shared/contracts/integration-consent-registry.json -->\n"
        "<!-- Run: python scripts/generate_contracts.py -->\n"
        "\n"
        f"# Aether Integration Consent Registry ({len(reg['connectors'])} connectors/adapters, contract v{reg['contractVersion']})\n"
        "\n"
        "| Connector | Provider | Category | Risk | Status | Purposes | Default basis | Raw payload policy | Signature scheme |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


def gen_rights_ts(rights_reg: dict, transform_reg: dict, activation_reg: dict) -> str:
    """Generate the public, reference-only IRRL vocabulary twin."""
    def union(values: list[str]) -> str:
        return "\n".join(f"  | {json.dumps(value)}" for value in values)

    def quoted_array(values: list[str]) -> str:
        return ", ".join(json.dumps(value) for value in values)

    return (
        "// DO NOT EDIT — generated from packages/shared/contracts/rights-authority-registry.json\n"
        "// Run: python scripts/generate_contracts.py\n\n"
        f"export const RIGHTS_AUTHORITY_CONTRACT_VERSION = {json.dumps(rights_reg['contractVersion'])};\n\n"
        "export type RightsClass =\n"
        f"{union([x['id'] for x in rights_reg['rightsClasses']])};\n\n"
        "export type RightsAction =\n"
        f"{union([x['id'] for x in rights_reg['actions']])};\n\n"
        "export type RightsDecisionOutcome =\n"
        f"{union(rights_reg['decisionOutcomes'])};\n\n"
        "export type RightsProfile =\n"
        f"{union([x['id'] for x in rights_reg['rightsProfiles']])};\n\n"
        "export type RightsActivationState =\n"
        f"{union(activation_reg['rightsActivationStates'])};\n\n"
        "export type RightsTransform =\n"
        f"{union([x['id'] for x in transform_reg['transforms']])};\n\n"
        f"export const RIGHTS_CLASSES = [{quoted_array([x['id'] for x in rights_reg['rightsClasses']])}] as const;\n"
        f"export const RIGHTS_ACTIONS = [{quoted_array([x['id'] for x in rights_reg['actions']])}] as const;\n"
        f"export const RIGHTS_DECISION_OUTCOMES = [{quoted_array(rights_reg['decisionOutcomes'])}] as const;\n"
        f"export const RIGHTS_PROFILES = [{quoted_array([x['id'] for x in rights_reg['rightsProfiles']])}] as const;\n"
        f"export const RIGHTS_TRANSFORMS = [{quoted_array([x['id'] for x in transform_reg['transforms']])}] as const;\n"
        f"export const RIGHTS_ACTIVATION_STATES = [{quoted_array(activation_reg['rightsActivationStates'])}] as const;\n\n"
        "export interface RightsReference {\n"
        "  policySetId?: string;\n"
        "  envelopeId?: string;\n"
        "  decisionId?: string;\n"
        "  lineageSetHash?: string;\n"
        "  retentionClass?: string;\n"
        "}\n"
    )


def gen_rights_py(rights_reg: dict, transform_reg: dict, activation_reg: dict) -> str:
    """Generate the backend vocabulary twin; policy logic remains hand-authored."""
    rights_classes = [x["id"] for x in rights_reg["rightsClasses"]]
    actions = [x["id"] for x in rights_reg["actions"]]
    profiles = [x["id"] for x in rights_reg["rightsProfiles"]]
    transforms = [x["id"] for x in transform_reg["transforms"]]
    return (
        "# DO NOT EDIT — generated from packages/shared/contracts/rights-authority-registry.json\n"
        "# Run: python scripts/generate_contracts.py\n"
        f"# Contract version: {rights_reg['contractVersion']}\n\n"
        f"RIGHTS_AUTHORITY_CONTRACT_VERSION = {_py_value(rights_reg['contractVersion'])}\n"
        f"RIGHTS_CLASSES: frozenset[str] = frozenset({rights_classes!r})\n"
        f"RIGHTS_ACTIONS: frozenset[str] = frozenset({actions!r})\n"
        f"RIGHTS_DECISION_OUTCOMES: frozenset[str] = frozenset({rights_reg['decisionOutcomes']!r})\n"
        f"RIGHTS_PROFILES: frozenset[str] = frozenset({profiles!r})\n"
        f"RIGHTS_TRANSFORMS: frozenset[str] = frozenset({transforms!r})\n"
        f"RIGHTS_ACTIVATION_STATES: frozenset[str] = frozenset({activation_reg['rightsActivationStates']!r})\n\n"
        f"RIGHTS_ACTION_DEFINITIONS: dict[str, dict] = {({x['id']: x for x in rights_reg['actions']})!r}\n"
        f"RIGHTS_PROFILE_DEFINITIONS: dict[str, dict] = {({x['id']: x for x in rights_reg['rightsProfiles']})!r}\n"
        f"RIGHTS_TRANSFORM_DEFINITIONS: dict[str, dict] = {({x['id']: x for x in transform_reg['transforms']})!r}\n"
    )


def gen_rights_table_md(rights_reg: dict, transform_reg: dict, activation_reg: dict) -> str:
    action_rows = "\n".join(
        f"| `{x['id']}` | {x['label']} | {'yes' if x['requiresEnvelope'] else 'no'} | {'yes' if x['requiresSourceGrant'] else 'no'} |"
        for x in rights_reg["actions"]
    )
    transform_rows = "\n".join(
        f"| `{x['id']}` | `{x['outputClass']}` | {', '.join(f'`{v}`' for v in x['requiresEvidence'])} | {'yes' if x['requiresApproval'] else 'no'} |"
        for x in transform_reg["transforms"]
    )
    profile_names = ", ".join(f"`{x['id']}`" for x in rights_reg["rightsProfiles"])
    activation_states = ", ".join(f"`{x}`" for x in activation_reg["rightsActivationStates"])
    return (
        "<!-- DO NOT EDIT — generated from the IRRL registries -->\n"
        "<!-- Run: python scripts/generate_contracts.py -->\n\n"
        f"# AETHER Rights Authority (contract v{rights_reg['contractVersion']})\n\n"
        "## Actions\n\n"
        "| Action | Label | Envelope required | Source grant required |\n|---|---|---:|---:|\n"
        f"{action_rows}\n\n"
        "## Registered transforms\n\n"
        "| Transform | Output class | Evidence | Approval |\n|---|---|---|---:|\n"
        f"{transform_rows}\n\n"
        "## Profiles and activation states\n\n"
        f"Profiles: {profile_names}.\n\n"
        f"Activation states: {activation_states}.\n"
    )


# ---------------------------------------------------------------------------
# Write / check helpers
# ---------------------------------------------------------------------------

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


def _apply_events_ts(event_reg: dict, check: bool, diffs: list[str]) -> None:
    if not EVENTS_TS.exists():
        print("ERROR: events.ts not found", file=sys.stderr)
        sys.exit(1)
    current = EVENTS_TS.read_text()
    updated = update_events_ts(event_reg, current)
    if current == updated:
        return
    if check:
        diffs.append(str(EVENTS_TS.relative_to(ROOT)))
        return
    EVENTS_TS.write_text(updated)
    print(f"  written: {EVENTS_TS.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any generated file differs from the committed version (CI gate)",
    )
    args = parser.parse_args()

    (
        event_reg, consent_reg, metric_reg, integration_reg, traffic_reg,
        rights_reg, transform_reg, activation_reg,
    ) = load_registries()
    validate(event_reg, consent_reg)
    validate_metrics(metric_reg)
    validate_integration_consent(integration_reg, consent_reg)
    validate_traffic_source(traffic_reg)
    validate_rights_registries(rights_reg, transform_reg, activation_reg)

    diffs: list[str] = []

    _apply(CONSENT_TS, gen_consent_ts(consent_reg), args.check, diffs)
    _apply_events_ts(event_reg, args.check, diffs)
    _apply(GENERATED_REGISTRY_PY, gen_python_registry(event_reg, consent_reg), args.check, diffs)
    _apply(MEASUREMENT_TS, gen_measurement_ts(metric_reg), args.check, diffs)
    _apply(GENERATED_METRIC_REGISTRY_PY, gen_metric_registry_py(metric_reg), args.check, diffs)
    _apply(EVENT_TABLE_MD, gen_event_table_md(event_reg), args.check, diffs)
    _apply(CONSENT_TABLE_MD, gen_consent_table_md(consent_reg), args.check, diffs)
    _apply(METRIC_TABLE_MD, gen_metric_table_md(metric_reg), args.check, diffs)
    _apply(WEB_CONSENT_MAP_TS, gen_web_consent_map_ts(event_reg), args.check, diffs)
    _apply(INTEGRATION_CONSENT_TS, gen_integration_consent_ts(integration_reg), args.check, diffs)
    _apply(INTEGRATION_CONSENT_PY, gen_integration_consent_py(integration_reg), args.check, diffs)
    _apply(INTEGRATION_CONSENT_SWIFT, gen_integration_consent_swift(integration_reg), args.check, diffs)
    _apply(INTEGRATION_CONSENT_KT, gen_integration_consent_kotlin(integration_reg), args.check, diffs)
    _apply(
        INTEGRATION_CONSENT_TABLE_MD,
        gen_integration_consent_table_md(integration_reg),
        args.check,
        diffs,
    )
    _apply(TRAFFIC_SOURCE_TS, gen_traffic_source_ts(traffic_reg), args.check, diffs)
    _apply(TRAFFIC_SOURCE_PY, gen_traffic_source_py(traffic_reg), args.check, diffs)
    _apply(TRAFFIC_SOURCE_TABLE_MD, gen_traffic_source_table_md(traffic_reg), args.check, diffs)
    _apply(RIGHTS_TS, gen_rights_ts(rights_reg, transform_reg, activation_reg), args.check, diffs)
    _apply(RIGHTS_PY, gen_rights_py(rights_reg, transform_reg, activation_reg), args.check, diffs)
    _apply(RIGHTS_TABLE_MD, gen_rights_table_md(rights_reg, transform_reg, activation_reg), args.check, diffs)

    if diffs:
        print("DRIFT: generated files differ from committed versions:", file=sys.stderr)
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        print("Run: python scripts/generate_contracts.py", file=sys.stderr)
        return 1

    n = len(event_reg["events"])
    np = len(consent_reg["purposes"])
    nm = len(metric_reg["metrics"])
    ni = len(integration_reg["connectors"])
    nr = len(rights_reg["actions"])
    print(
        f"OK: {n} event types, {np} consent purposes, {nm} metrics, {ni} integration policies, "
        f"{nr} rights actions "
        f"— all artifacts up-to-date"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
