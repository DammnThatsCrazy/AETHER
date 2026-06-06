#!/usr/bin/env python3
"""Generate ``docs/_generated/providers.json`` from the provider registry.

The provider matrix is one of Aether's most-shared reference pages
(every integrator needs to know which providers we wrap and whether
they need an API key). The canonical source of truth is::

    Backend Architecture/aether-backend/shared/providers/categories.py

This generator parses that module with ``ast`` and emits a JSON catalog
with each ProviderCategory enum value paired with its concrete provider
adapters and their Python class names.

Schema::

    {
      "version": "8.9.0",
      "generated_from": "...categories.py",
      "category_enum_values": [
        {"name": "BLOCKCHAIN_RPC", "value": "blockchain_rpc"},
        ...
      ],
      "categories": [
        {
          "enum_name": "BLOCKCHAIN_RPC",
          "value": "blockchain_rpc",
          "providers": [
            {"name": "quicknode", "class": "QuickNodeProvider"},
            ...
          ]
        },
        ...
      ],
      "all_providers": [
        {"name": "quicknode", "class": "QuickNodeProvider"},
        ...
      ]
    }

Determinism: enum values appear in source order; categories appear in
the order of their CATEGORY_PROVIDERS declaration. Same input produces
byte-identical output.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORIES_PY = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "providers"
    / "categories.py"
)
OUTPUT = ROOT / "docs" / "_generated" / "providers.json"


class ParseError(Exception):
    """Raised when the source doesn't match the expected shape."""


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _find_class_def(tree: ast.AST, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_assignment(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        target_names: list[str] = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
        elif isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if name in target_names:
            return node.value
    return None


def parse_category_enum(tree: ast.AST) -> list[dict]:
    """Walk ``class ProviderCategory(str, Enum)`` and return its members."""
    cls = _find_class_def(tree, "ProviderCategory")
    if cls is None:
        raise ParseError("class ProviderCategory(str, Enum) not found")
    members: list[dict] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    members.append({"name": target.id, "value": stmt.value.value})
    if not members:
        raise ParseError("ProviderCategory has no enum members")
    return members


def parse_provider_factory(tree: ast.AST) -> dict[str, str]:
    """Return {provider_name: ClassName} from the PROVIDER_FACTORY dict."""
    value = _find_assignment(tree, "PROVIDER_FACTORY")
    if not isinstance(value, ast.Dict):
        raise ParseError("PROVIDER_FACTORY must be a dict literal")
    out: dict[str, str] = {}
    for k, v in zip(value.keys, value.values):
        if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            continue
        if isinstance(v, ast.Name):
            out[k.value] = v.id
        elif isinstance(v, ast.Attribute):
            out[k.value] = v.attr
        else:
            out[k.value] = "<unknown>"
    return out


def parse_category_providers(tree: ast.AST, enum_lookup: dict[str, str]) -> list[dict]:
    """Return categories in source order with their provider names.

    ``enum_lookup`` maps ProviderCategory.NAME -> 'string_value' so the
    output exposes both the enum member and its serialised form.
    """
    value = _find_assignment(tree, "CATEGORY_PROVIDERS")
    if not isinstance(value, ast.Dict):
        raise ParseError("CATEGORY_PROVIDERS must be a dict literal")
    categories: list[dict] = []
    for k, v in zip(value.keys, value.values):
        # Keys are ProviderCategory.NAME — pull the attribute name.
        if not isinstance(k, ast.Attribute) or not isinstance(k.value, ast.Name):
            continue
        if k.value.id != "ProviderCategory":
            continue
        enum_name = k.attr
        if enum_name not in enum_lookup:
            raise ParseError(
                f"CATEGORY_PROVIDERS references ProviderCategory.{enum_name}, "
                f"but that enum member doesn't exist"
            )
        if not isinstance(v, ast.List):
            raise ParseError(
                f"CATEGORY_PROVIDERS[{enum_name}] must be a list literal"
            )
        names: list[str] = []
        for elt in v.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
        categories.append({
            "enum_name": enum_name,
            "value": enum_lookup[enum_name],
            "provider_names": names,
        })
    return categories


def build_payload(text: str) -> dict:
    tree = ast.parse(text)
    enum_members = parse_category_enum(tree)
    enum_lookup = {m["name"]: m["value"] for m in enum_members}

    factory = parse_provider_factory(tree)
    raw_categories = parse_category_providers(tree, enum_lookup)

    # Validate every name in CATEGORY_PROVIDERS exists in PROVIDER_FACTORY.
    missing = [
        name
        for cat in raw_categories
        for name in cat["provider_names"]
        if name not in factory
    ]
    if missing:
        raise ParseError(
            f"CATEGORY_PROVIDERS references provider(s) not in "
            f"PROVIDER_FACTORY: {sorted(set(missing))}"
        )

    categories = [
        {
            "enum_name": cat["enum_name"],
            "value": cat["value"],
            "providers": [
                {"name": name, "class": factory[name]}
                for name in cat["provider_names"]
            ],
        }
        for cat in raw_categories
    ]

    # Flat list in source-declaration order from PROVIDER_FACTORY.
    all_providers = [
        {"name": name, "class": cls} for name, cls in factory.items()
    ]

    return {
        "version": read_version(),
        "generated_from": "Backend Architecture/aether-backend/shared/providers/categories.py",
        "category_enum_values": enum_members,
        "categories": categories,
        "all_providers": all_providers,
    }


def main() -> int:
    if not CATEGORIES_PY.exists():
        print(f"error: {CATEGORIES_PY} not found", file=sys.stderr)
        return 1

    text = CATEGORIES_PY.read_text(encoding="utf-8")
    try:
        payload = build_payload(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"extract_providers: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['all_providers'])} providers across "
        f"{len(payload['categories'])} categories)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
