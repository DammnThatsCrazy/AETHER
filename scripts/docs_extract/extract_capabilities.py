#!/usr/bin/env python3
"""Generate ``docs/_generated/capabilities.json`` from
``packages/shared/capabilities.ts``.

The capability manifest is returned by ``GET /v1/config`` so SDKs know
which event families, consent purposes, and rails the backend currently
activates. This generator extracts the fields of ``CapabilityManifest``
along with the feature-flag mapping for ``GraphLayerFlags``.

Schema::

    {
      "version": "8.9.0",
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

# Match the header `export interface NAME {`. The body itself is then
# extracted via a balance-aware scan rather than a regex, because TS
# interfaces routinely contain nested inline object types (e.g.
# ``featureFlags?: { key: string; enabled: boolean }[]``) that a
# ``[^}]+`` group would mis-match.
INTERFACE_HEADER_RE = re.compile(r"export interface (\w+)\s*\{")

# JSDoc immediately preceding a field: ``/** description */``.
JSDOC_RE = re.compile(r"/\*\*\s*(.*?)\s*\*/", re.DOTALL)

# Field declaration: ``name(?)?: <type>``. The type runs until the
# semicolon at brace depth zero — extracted by ``_split_fields`` below.
FIELD_HEAD_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*(.*)$", re.DOTALL)

# In GraphLayerFlags, each line has an inline comment like
# "agent: boolean; // IG_AGENT_LAYER (L2)".
LAYER_LINE_RE = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*boolean;\s*(?://\s*(.*))?$",
    re.MULTILINE,
)

# Inline annotation parser: "IG_FLAG_NAME (Lx)" -> ("IG_FLAG_NAME", "Lx").
LAYER_META_RE = re.compile(r"(IG_[A-Z0-9_]+)(?:\s*\((L[\dab]+)\))?")


def _read_interface_body(text: str, name: str) -> str | None:
    """Return the body of `export interface NAME { ... }` or None.

    Walks the source character-by-character starting from the opening
    brace, tracking brace depth so that nested ``{ ... }`` inside type
    expressions is treated as part of the body rather than as a closer.
    """
    for m in INTERFACE_HEADER_RE.finditer(text):
        if m.group(1) != name:
            continue
        i = m.end()  # position just after the `{`
        depth = 1
        start = i
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i]
            i += 1
        # Reached EOF before matching close — malformed source.
        return None
    return None


def _split_fields(body: str) -> list[tuple[str, str]]:
    """Split an interface body into (raw_chunk, terminator) tuples.

    Each chunk is the text up to a semicolon at brace/bracket/angle
    depth zero. Comments are preserved on the chunk so the field
    parser can pick up any preceding JSDoc.
    """
    chunks: list[tuple[str, str]] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch in "{[<":
            depth += 1
        elif ch in "}]>":
            depth -= 1
        elif ch == ";" and depth == 0:
            chunks.append(("".join(buf), ";"))
            buf = []
            i += 1
            continue
        elif ch == "/" and i + 1 < n and body[i + 1] == "*":
            # Skip block-comment content but preserve it in buf so the
            # preceding-JSDoc parser still works.
            end = body.find("*/", i + 2)
            if end == -1:
                end = n
            else:
                end += 2
            buf.append(body[i:end])
            i = end
            continue
        elif ch == "/" and i + 1 < n and body[i + 1] == "/":
            # Line comment — also preserve.
            end = body.find("\n", i)
            if end == -1:
                end = n
            buf.append(body[i:end])
            i = end
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        chunks.append((tail, ""))  # no trailing `;`
    return chunks


def _parse_field(chunk: str) -> dict | None:
    """Parse one ``[/** doc */] name(?)?: <type>`` chunk."""
    doc = ""
    doc_match = JSDOC_RE.search(chunk)
    if doc_match:
        doc = re.sub(r"\s+", " ", doc_match.group(1).replace("*", "").strip())
        chunk = chunk[doc_match.end():]

    # Strip line comments and trailing whitespace lines.
    chunk = re.sub(r"//[^\n]*", "", chunk).strip()
    if not chunk:
        return None

    head = FIELD_HEAD_RE.match(chunk)
    if not head:
        return None
    return {
        "name": head.group(1),
        "type": head.group(3).strip(),
        "optional": head.group(2) == "?",
        "description": doc,
    }


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def find_interface_body(text: str, name: str) -> str:
    body = _read_interface_body(text, name)
    if body is None:
        raise ValueError(f"could not locate `export interface {name}` in capabilities.ts")
    return body


def parse_manifest_fields(text: str) -> list[dict]:
    body = find_interface_body(text, "CapabilityManifest")
    fields: list[dict] = []
    for chunk, _ in _split_fields(body):
        parsed = _parse_field(chunk)
        if parsed is not None:
            fields.append(parsed)
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
