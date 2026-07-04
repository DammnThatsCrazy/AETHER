"""Unit tests for the consent, entities, capabilities generators.

Each module is loaded by file path so the tests can exercise it in
isolation without requiring scripts/ to be on sys.path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PKG = ROOT / "scripts" / "docs_extract"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- extract_consent -------------------------------------------------------


@pytest.fixture(scope="module")
def ec():
    return _load("extract_consent")


def test_consent_purposes_match_union_and_docblock(ec):
    text = (ROOT / "packages" / "shared" / "consent.ts").read_text(encoding="utf-8")
    payload = ec.build_payload(text)
    names = [p["name"] for p in payload["purposes"]]
    assert set(names) == {"analytics", "marketing", "personalization", "web3", "agent", "commerce", "financial_activity", "credit", "location"}
    assert len(names) == 9
    for p in payload["purposes"]:
        assert p["description"], f"{p['name']} has empty description"


def test_consent_state_fields_include_all_purposes(ec):
    text = (ROOT / "packages" / "shared" / "consent.ts").read_text(encoding="utf-8")
    payload = ec.build_payload(text)
    for purpose in ["analytics", "marketing", "personalization", "web3", "agent", "commerce", "financial_activity", "credit", "location"]:
        assert purpose in payload["state_fields"]


def test_consent_raises_when_purpose_missing_description(ec):
    text = (
        "/**\n * - foo: described\n */\n"
        "export type ConsentPurpose = | 'foo' | 'undescribed';\n"
        "export interface ConsentState { foo: boolean; }\n"
    )
    with pytest.raises(ValueError, match="undescribed"):
        ec.build_payload(text)


def test_consent_handles_digit_in_purpose_name(ec):
    """Regression: 'web3' nearly slipped past the doc-line regex."""
    text = (
        "/**\n * - web3: described\n */\n"
        "export type ConsentPurpose = | 'web3';\n"
        "export interface ConsentState { web3: boolean; }\n"
    )
    payload = ec.build_payload(text)
    assert payload["purposes"] == [{"name": "web3", "description": "described"}]


# --- extract_entities ------------------------------------------------------


@pytest.fixture(scope="module")
def ee():
    return _load("extract_entities")


def test_entities_planes_match_source_groups(ee):
    text = (ROOT / "packages" / "shared" / "entities.ts").read_text(encoding="utf-8")
    payload = ee.build_payload(text)
    names = [p["name"] for p in payload["planes"]]
    # Expect at least the canonical planes from the source.
    expected_subset = {
        "Core (always present)",
        "Commerce plane",
        "Blockchain-specific (additive)",
        "Agent plane",
    }
    assert expected_subset.issubset(set(names))


def test_entities_no_duplicates(ee):
    text = (ROOT / "packages" / "shared" / "entities.ts").read_text(encoding="utf-8")
    payload = ee.build_payload(text)
    all_kinds = payload["all_kinds"]
    assert len(all_kinds) == len(set(all_kinds))


def test_entities_includes_canonical_kinds(ee):
    text = (ROOT / "packages" / "shared" / "entities.ts").read_text(encoding="utf-8")
    payload = ee.build_payload(text)
    for required in ["tenant", "user", "wallet", "agent", "payment"]:
        assert required in payload["all_kinds"]


def test_entities_raises_on_duplicate(ee):
    text = (
        "export type EntityKind =\n"
        "  // Core\n"
        "  | 'tenant'\n"
        "  // Core repeated\n"
        "  | 'tenant';\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        ee.build_payload(text)


# --- extract_capabilities --------------------------------------------------


@pytest.fixture(scope="module")
def cap():
    return _load("extract_capabilities")


def test_capabilities_extracts_known_layers(cap):
    text = (ROOT / "packages" / "shared" / "capabilities.ts").read_text(encoding="utf-8")
    payload = cap.build_payload(text)
    layer_names = {l["name"] for l in payload["graph_layers"]}
    assert {"agent", "commerce", "x402", "onchain"} <= layer_names


def test_capabilities_extracts_flag_and_level(cap):
    text = (ROOT / "packages" / "shared" / "capabilities.ts").read_text(encoding="utf-8")
    payload = cap.build_payload(text)
    by_name = {l["name"]: l for l in payload["graph_layers"]}
    assert by_name["agent"]["flag"] == "IG_AGENT_LAYER"
    assert by_name["agent"]["level"] == "L2"
    assert by_name["x402"]["flag"] == "IG_X402_LAYER"
    assert by_name["x402"]["level"] == "L3b"


def test_capabilities_extracts_manifest_fields(cap):
    text = (ROOT / "packages" / "shared" / "capabilities.ts").read_text(encoding="utf-8")
    payload = cap.build_payload(text)
    names = {f["name"] for f in payload["manifest_fields"]}
    assert {"schemaVersion", "activeFamilies", "supportedPurposes", "layers"} <= names


def test_capabilities_handles_digit_in_layer_name(cap):
    """Regression: 'x402' nearly slipped past the layer-line regex."""
    text = (
        "export interface CapabilityManifest { foo: string; }\n"
        "export interface GraphLayerFlags {\n"
        "  x402: boolean;  // IG_X402_LAYER (L3b)\n"
        "}\n"
    )
    payload = cap.build_payload(text)
    layer_names = [l["name"] for l in payload["graph_layers"]]
    assert layer_names == ["x402"]


def test_capabilities_preserves_inline_object_types(cap):
    """Regression for codex review on PR #70: the old `[^;]+` regex
    stopped at the first `;` inside an inline object type, truncating
    ``featureFlags?: { key: string; enabled: boolean; value?: unknown }[]``
    to ``{ key: string``. The brace-aware parser must capture the full
    type string."""
    text = (
        "export interface CapabilityManifest {\n"
        "  featureFlags?: { key: string; enabled: boolean; value?: unknown }[];\n"
        "  scalar: string;\n"
        "}\n"
        "export interface GraphLayerFlags { foo: boolean; }\n"
    )
    payload = cap.build_payload(text)
    by_name = {f["name"]: f for f in payload["manifest_fields"]}
    assert "featureFlags" in by_name
    assert by_name["featureFlags"]["type"] == (
        "{ key: string; enabled: boolean; value?: unknown }[]"
    )
    assert by_name["featureFlags"]["optional"] is True
    # The non-nested sibling must still be parsed.
    assert by_name["scalar"]["type"] == "string"


def test_capabilities_real_source_featureFlags_intact(cap):
    """End-to-end: the canonical capabilities.ts produces a complete
    featureFlags type, not the truncated `{ key: string`."""
    text = (ROOT / "packages" / "shared" / "capabilities.ts").read_text(encoding="utf-8")
    payload = cap.build_payload(text)
    by_name = {f["name"]: f for f in payload["manifest_fields"]}
    assert "featureFlags" in by_name
    type_str = by_name["featureFlags"]["type"]
    # Must include all three nested members + the trailing `[]`.
    assert "key:" in type_str
    assert "enabled:" in type_str
    assert "value?:" in type_str
    assert type_str.rstrip().endswith("[]")


def test_capabilities_split_fields_respects_brace_depth(cap):
    """White-box test of the helper: semicolons inside `{}`, `[]`, and
    `<>` must not split a field."""
    chunks = cap._split_fields(" a: { b: string; c: number; }; d: T<E; F>; ")
    # Two `;`-terminated chunks expected.
    chunk_texts = [c[0].strip() for c in chunks]
    assert chunk_texts == ["a: { b: string; c: number; }", "d: T<E; F>"]
