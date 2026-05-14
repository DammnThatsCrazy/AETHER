#!/usr/bin/env python3
"""Generate ``docs/_generated/capabilities.json`` from
``packages/shared/capabilities.ts``.

The capability manifest is returned by ``GET /v1/config`` so SDKs know
which event families, consent purposes, and rails the backend currently
activates. This generator extracts the fields of ``CapabilityManifest``
along with the feature-flag mapping for ``GraphLayerFlags``.

Schema::

    {
      "version": "8.8.0",
      "generated_from": "packages/shared/capabilities.ts",
      "manifest_fields": [
        {"name": "schemaVersion", "type": "string", "optional": false,
         "description": "..."},
        ...
      ],
      "graph_layers": [
        {"name": "agent", "flag": "IG_AGENT_LAYER", "level": "L2",
         "optional": false},
        ...
      ]
    }

Determinism: fields appear in source order. Same input produces
byte-identical output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CAPS_TS = ROOT / "packages" / "shared" / "capabilities.ts"
OUTPUT = ROOT / "docs" / "_generated" / "capabilities.json"

# Match a TypeScript interface block, capturing the body between braces.
INTERFACE_RE = re.compile(
    r"export interface (\w+)\s*\{([^}]+)\}", re.DOTALL
)

# Match a single field with its preceding JSDoc-style comment (if any).
# Three forms recognised:
#   /** description */
#   field: Type;
#   field?: Type;
FIELD_RE = re.compile(
    r"(?:/\*\*\s*(.*?)\s*\*/\s*)?"
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*([^;]+);",
    re.MULTILINE | re.DOTALL,
)

# In GraphLayerFlags, each line has an inline comment like
# "agent: boolean; // IG_AGENT_LAYER (L2)".
LAYER_LINE_RE = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*boolean;\s*(?://\s*(.*))?$",
    re.MULTILINE,
)

# Inline annotation parser: "IG_FLAG_NAME (Lx)" -> ("IG_FLAG_NAME", "Lx").
LAYER_META_RE = re.compile(r"(IG_[A-Z0-9_]+)(?:\s*\((L[\dab]+)\))?")


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def find_interface_body(text: str, name: str) -> str:
    for type_name, body in INTERFACE_RE.findall(text):
        if type_name == name:
            return body
    raise ValueError(f"could not locate `export interface {name}` in capabilities.ts")


def parse_manifest_fields(text: str) -> list[dict]:
    body = find_interface_body(text, "CapabilityManifest")
    fields: list[dict] = []
    for doc, name, opt, ts_type in FIELD_RE.findall(body):
        clean_doc = re.sub(r"\s+", " ", doc.replace("*", "").strip()) if doc else ""
        fields.append({
            "name": name,
            "type": ts_type.strip(),
            "optional": opt == "?",
            "description": clean_doc,
        })
    return fields


def parse_graph_layers(text: str) -> list[dict]:
    body = find_interface_body(text, "GraphLayerFlags")
    layers: list[dict] = []
    for name, opt, annotation in LAYER_LINE_RE.findall(body):
        flag = ""
        level = ""
        if annotation:
            m = LAYER_META_RE.search(annotation)
            if m:
                flag = m.group(1)
                level = m.group(2) or ""
        layers.append({
            "name": name,
            "flag": flag,
            "level": level,
            "optional": opt == "?",
        })
    return layers


def build_payload(text: str) -> dict:
    return {
        "version": read_version(),
        "generated_from": "packages/shared/capabilities.ts",
        "manifest_fields": parse_manifest_fields(text),
        "graph_layers": parse_graph_layers(text),
    }


def main() -> int:
    if not CAPS_TS.exists():
        print(f"error: {CAPS_TS} not found", file=sys.stderr)
        return 1

    text = CAPS_TS.read_text(encoding="utf-8")
    try:
        payload = build_payload(text)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"extract_capabilities: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['manifest_fields'])} fields, "
        f"{len(payload['graph_layers'])} graph layers)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
