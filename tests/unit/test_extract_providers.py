"""Unit tests for scripts/docs_extract/extract_providers.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_extract" / "extract_providers.py"
CATEGORIES_PY = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "providers"
    / "categories.py"
)


@pytest.fixture(scope="module")
def ep():
    spec = importlib.util.spec_from_file_location("extract_providers", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_providers"] = module
    spec.loader.exec_module(module)
    return module


# --- end-to-end against the real source -----------------------------------


def test_real_source_has_24_providers(ep):
    text = CATEGORIES_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    assert len(payload["all_providers"]) == 24


def test_real_source_has_11_categories(ep):
    text = CATEGORIES_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    assert len(payload["categories"]) == 11


def test_real_source_includes_canonical_providers(ep):
    text = CATEGORIES_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    names = {p["name"] for p in payload["all_providers"]}
    # Sample of canonical providers that must always be present.
    for required in [
        "quicknode", "alchemy", "infura",
        "etherscan", "moralis",
        "twitter", "reddit",
        "polymarket", "kalshi",
        "chainalysis", "nansen",
    ]:
        assert required in names


def test_real_source_every_provider_in_factory(ep):
    text = CATEGORIES_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    factory_names = {p["name"] for p in payload["all_providers"]}
    for cat in payload["categories"]:
        for prov in cat["providers"]:
            assert prov["name"] in factory_names


def test_real_source_classes_use_pascal_case(ep):
    text = CATEGORIES_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    for prov in payload["all_providers"]:
        cls = prov["class"]
        assert cls[0].isupper(), f"class {cls!r} not PascalCase"
        assert cls.endswith("Provider"), f"class {cls!r} doesn't end in Provider"


# --- error paths ----------------------------------------------------------


def test_missing_provider_category_class_raises(ep):
    with pytest.raises(ep.ParseError, match="ProviderCategory"):
        ep.build_payload("# no enum here")


def test_category_references_unknown_provider_raises(ep):
    bad = (
        "from enum import Enum\n"
        "class ProviderCategory(str, Enum):\n"
        "    FOO = 'foo'\n"
        "PROVIDER_FACTORY = {'real': RealProvider}\n"
        "CATEGORY_PROVIDERS = {ProviderCategory.FOO: ['real', 'phantom']}\n"
    )
    with pytest.raises(ep.ParseError, match="phantom"):
        ep.build_payload(bad)


def test_category_references_unknown_enum_raises(ep):
    bad = (
        "from enum import Enum\n"
        "class ProviderCategory(str, Enum):\n"
        "    FOO = 'foo'\n"
        "PROVIDER_FACTORY = {'real': RealProvider}\n"
        "CATEGORY_PROVIDERS = {ProviderCategory.BAR: ['real']}\n"
    )
    with pytest.raises(ep.ParseError, match="BAR"):
        ep.build_payload(bad)


def test_handles_attribute_value_in_factory(ep):
    """If a factory value is `Module.Class`, capture the trailing class name."""
    text = (
        "from enum import Enum\n"
        "class ProviderCategory(str, Enum):\n"
        "    FOO = 'foo'\n"
        "PROVIDER_FACTORY = {'real': module.SomeProvider}\n"
        "CATEGORY_PROVIDERS = {ProviderCategory.FOO: ['real']}\n"
    )
    payload = ep.build_payload(text)
    assert payload["all_providers"][0]["class"] == "SomeProvider"
