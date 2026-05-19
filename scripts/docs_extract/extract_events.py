#!/usr/bin/env python3
"""Generate ``docs/_generated/events.json`` from ``packages/shared/events.ts``.

The Event Registry doc page is one of the most-linked references in the
Aether docs (every integrator reads it). Hand-maintaining it next to the
canonical TypeScript union guarantees drift. This generator parses the
SDK's events module and emits a structured JSON catalog with every event
type, the family it belongs to, and the consent purpose required to
transport it.

Schema of the output::

    {
      "version": "8.8.0",
      "generated_from": "packages/shared/events.ts",
      "schema_version": "1.0.0",
      "families": ["core", "identity", "consent", ...],
      "consent_purposes": ["analytics", "marketing", ...],
      "events": [
        {
          "name": "track",
          "family": "core",
          "consent_purpose": "analytics",
          "section_comment": "Core analytics"
        },
        ...
      ]
    }

Determinism: events appear in source order. Re-running on the same input
produces byte-identical output.

The parser is intentionally regex-based (no TS toolchain) because the
patterns we extract are simple enough that a full AST is overkill and
would add a dependency. If the source ever changes shape in a way the
regexes can't handle, the parser raises a clear error rather than
silently producing partial output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVENTS_TS = ROOT / "packages" / "shared" / "events.ts"
SCHEMA_VERSION_TS = ROOT / "packages" / "shared" / "schema-version.ts"
OUTPUT = ROOT / "docs" / "_generated" / "events.json"

# Match an `export type Foo = | 'a' | 'b' | 'c'` union, capturing the body.
UNION_RE = re.compile(
    r"export\s+type\s+(\w+)\s*=\s*(?:\n|\r\n)?((?:\s*(?://[^\n]*\n)?\s*\|\s*'[^']+'(?:\s*\n)?)+)\s*;",
    re.MULTILINE,
)

# Inside a union body: match either a comment line or a 'value' member.
UNION_MEMBER_RE = re.compile(r"\|\s*'([^']+)'")
UNION_COMMENT_RE = re.compile(r"//\s*(.+)")

# Match an `export const NAME: Record<...> = { ... };` block, capturing
# the body between the braces.
RECORD_RE = re.compile(
    r"export\s+const\s+(\w+)\s*:\s*Record<[^>]+>\s*=\s*\{([^}]*)\}\s*;",
    re.DOTALL,
)

# Each key: value entry inside a Record body. Keys may be unquoted
# identifiers or string literals; values are always string literals here.
RECORD_ENTRY_RE = re.compile(r"(?:'([^']+)'|(\w+))\s*:\s*'([^']+)'")


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def read_schema_version() -> str:
    if not SCHEMA_VERSION_TS.exists():
        return "unknown"
    text = SCHEMA_VERSION_TS.read_text(encoding="utf-8")
    match = re.search(r"['\"]([\d.]+)['\"]", text)
    return match.group(1) if match else "unknown"


def parse_union(text: str, name: str) -> list[str]:
    """Return the ordered list of string-literal members of `export type NAME = | 'a' | 'b'`."""
    for type_name, body in UNION_RE.findall(text):
        if type_name == name:
            return [m for m in UNION_MEMBER_RE.findall(body)]
    raise ValueError(f"could not locate `export type {name} = ...` union in events.ts")


def parse_union_with_section_comments(text: str, name: str) -> list[tuple[str, str]]:
    """Return [(member, section_comment), ...] preserving source order.

    Section comments are the ``// Foo`` lines that appear inside the union
    body just before a group of members. Each member inherits the most
    recent comment seen before it. The first comment for each member is
    captured; if no comment precedes any members, the comment is ``""``.
    """
    for type_name, body in UNION_RE.findall(text):
        if type_name != name:
            continue
        out: list[tuple[str, str]] = []
        current_section = ""
        for line in body.splitlines():
            comment = UNION_COMMENT_RE.search(line)
            if comment and "|" not in line:
                current_section = comment.group(1).strip()
                continue
            member = UNION_MEMBER_RE.search(line)
            if member:
                out.append((member.group(1), current_section))
        return out
    raise ValueError(f"could not locate `export type {name} = ...` union in events.ts")


def parse_record(text: str, name: str) -> dict[str, str]:
    """Parse `export const NAME: Record<...> = { ... }` into a dict."""
    for const_name, body in RECORD_RE.findall(text):
        if const_name == name:
            out: dict[str, str] = {}
            for quoted, unquoted, value in RECORD_ENTRY_RE.findall(body):
                key = quoted or unquoted
                out[key] = value
            return out
    raise ValueError(f"could not locate `export const {name}: Record<...>` in events.ts")


def build_payload(text: str) -> dict:
    event_types = parse_union_with_section_comments(text, "EventType")
    families = parse_union(text, "EventFamily")
    event_family = parse_record(text, "EVENT_FAMILY")
    event_consent = parse_record(text, "EVENT_CONSENT_PURPOSE")

    # Sanity: every event type must have a family and consent purpose.
    missing_family = [e for e, _ in event_types if e not in event_family]
    if missing_family:
        raise ValueError(f"EVENT_FAMILY missing entries for: {missing_family}")
    missing_consent = [e for e, _ in event_types if e not in event_consent]
    if missing_consent:
        raise ValueError(f"EVENT_CONSENT_PURPOSE missing entries for: {missing_consent}")

    consent_purposes = sorted(set(event_consent.values()))

    events = [
        {
            "name": name,
            "family": event_family[name],
            "consent_purpose": event_consent[name],
            "section_comment": comment,
        }
        for name, comment in event_types
    ]

    return {
        "version": read_version(),
        "generated_from": "packages/shared/events.ts",
        "schema_version": read_schema_version(),
        "families": families,
        "consent_purposes": consent_purposes,
        "events": events,
    }


def main() -> int:
    if not EVENTS_TS.exists():
        print(f"error: {EVENTS_TS} not found", file=sys.stderr)
        return 1

    text = EVENTS_TS.read_text(encoding="utf-8")
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
        f"extract_events: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['events'])} events across {len(payload['families'])} families)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
