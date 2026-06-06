#!/usr/bin/env python3
"""Generate ``docs/_generated/consent.json`` from ``packages/shared/consent.ts``.

The canonical consent model is the single most-cited compliance reference
(GDPR/SOC2 review packs all link to it). This generator emits the five
canonical purposes plus their human descriptions extracted from the
docblock above the ``ConsentPurpose`` union.

Schema::

    {
      "version": "8.9.0",
      "generated_from": "packages/shared/consent.ts",
      "purposes": [
        { "name": "analytics", "description": "..." },
        ...
      ],
      "state_fields": ["analytics", "marketing", "web3", "agent", "commerce",
                       "updatedAt", "policyVersion"]
    }

Determinism: purposes appear in source order. Same input produces
byte-identical output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONSENT_TS = ROOT / "packages" / "shared" / "consent.ts"
OUTPUT = ROOT / "docs" / "_generated" / "consent.json"

# ``- name: description`` lines inside the ConsentPurpose docblock.
DOC_LINE_RE = re.compile(r"^\s*\*\s*-\s*([a-z][a-z0-9_]*):\s*(.+?)\s*$")
UNION_RE = re.compile(r"export type ConsentPurpose\s*=\s*((?:\s*\|\s*'[^']+')+)\s*;", re.DOTALL)
MEMBER_RE = re.compile(r"\|\s*'([^']+)'")
INTERFACE_RE = re.compile(
    r"export interface ConsentState\s*\{([^}]+)\}", re.DOTALL
)
FIELD_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\??\s*:", re.MULTILINE)


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def parse_descriptions(text: str) -> dict[str, str]:
    """Extract `- name: description` lines from the docblock."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = DOC_LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_purposes(text: str) -> list[str]:
    m = UNION_RE.search(text)
    if not m:
        raise ValueError("could not locate ConsentPurpose union in consent.ts")
    return MEMBER_RE.findall(m.group(1))


def parse_state_fields(text: str) -> list[str]:
    m = INTERFACE_RE.search(text)
    if not m:
        raise ValueError("could not locate ConsentState interface in consent.ts")
    return FIELD_RE.findall(m.group(1))


def build_payload(text: str) -> dict:
    purposes = parse_purposes(text)
    descriptions = parse_descriptions(text)
    state_fields = parse_state_fields(text)

    missing = [p for p in purposes if p not in descriptions]
    if missing:
        raise ValueError(
            f"ConsentPurpose union lists {missing} but the docblock has no "
            f"description for them. Update the comment above the union."
        )

    return {
        "version": read_version(),
        "generated_from": "packages/shared/consent.ts",
        "purposes": [
            {"name": p, "description": descriptions[p]} for p in purposes
        ],
        "state_fields": state_fields,
    }


def main() -> int:
    if not CONSENT_TS.exists():
        print(f"error: {CONSENT_TS} not found", file=sys.stderr)
        return 1

    text = CONSENT_TS.read_text(encoding="utf-8")
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
        f"extract_consent: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['purposes'])} purposes, "
        f"{len(payload['state_fields'])} state fields)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
