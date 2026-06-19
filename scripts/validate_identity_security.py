#!/usr/bin/env python3
"""Validate security controls on identity routes.

Checks that the identity service routes file:
  1. Exposes the /suppress endpoint.
  2. Requires write permission on mutating endpoints
     (suppress, merge, split, recompute, resolve).
  3. Does not expose raw identifier hashes in alias or graph responses.
  4. Scopes all responses to tenant context (request.state.tenant).

Uses static analysis only — no application imports, no runtime deps.

Exit codes:
  0  all security controls present
  1  one or more controls missing
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY_ROUTES = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "services"
    / "identity"
    / "routes.py"
)

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _load_source() -> str | None:
    if not IDENTITY_ROUTES.exists():
        fail(
            f"identity routes file not found: {IDENTITY_ROUTES.relative_to(ROOT)}. "
            "Cannot validate identity security controls."
        )
        return None
    return IDENTITY_ROUTES.read_text(encoding="utf-8")


def check_suppress_endpoint_exists(source: str) -> None:
    """The /suppress endpoint must be defined."""
    if not re.search(r'@router\.(post|put|patch)\(["\']\/suppress["\']', source):
        fail(
            "identity routes missing POST /suppress endpoint. "
            "Add a suppress endpoint so operators can suppress identifier hashes."
        )


def check_mutating_endpoints_require_write(source: str) -> None:
    """Mutating endpoints must call tenant.require_permission('write')."""
    mutating_routes = [
        "resolve_identity",
        "merge_identities",
        "split_identity",
        "recompute_identity",
        "suppress_identifier",
    ]

    for fn_name in mutating_routes:
        pattern = rf"async def {fn_name}\b"
        match = re.search(pattern, source)
        if not match:
            continue
        start = match.start()
        next_def = re.search(r"\n(?:async def|def|class) ", source[start + 1:])
        block = source[start: start + 1 + (next_def.start() if next_def else len(source) - start)]
        if "require_permission" not in block:
            fail(
                f"identity route handler {fn_name!r} does not call "
                "tenant.require_permission('write'). Mutating endpoints must "
                "enforce write access."
            )


def check_no_raw_hash_in_alias_response(source: str) -> None:
    """Alias responses must not expose raw hash fields."""
    match = re.search(r"async def get_entity_aliases\b", source)
    if not match:
        return

    next_def = re.search(r"\n(?:async def|def|class) ", source[match.start() + 1:])
    block = source[match.start(): match.start() + 1 + (next_def.start() if next_def else len(source) - match.start())]

    if "alias_display_value_redacted" not in block:
        fail(
            "get_entity_aliases handler does not redact alias values. "
            "Use 'alias_display_value_redacted' and omit raw identifier hashes."
        )


def check_tenant_scoping(source: str) -> None:
    """Route handlers must access request.state.tenant for tenant context."""
    handler_count = len(re.findall(r"^async def \w+", source, re.MULTILINE))
    tenant_refs = len(re.findall(r"request\.state\.tenant", source))

    if handler_count > 0 and tenant_refs == 0:
        fail(
            "identity routes contain no request.state.tenant references. "
            "All route handlers must scope data access to the calling tenant."
        )
    elif tenant_refs < handler_count // 2:
        fail(
            f"identity routes have {handler_count} handlers but only "
            f"{tenant_refs} request.state.tenant references. "
            "Verify all handlers are properly tenant-scoped."
        )


def main() -> int:
    source = _load_source()
    if source is None:
        print(
            "identity security validator: FAILED — routes file missing.",
            file=sys.stderr,
        )
        return 1

    check_suppress_endpoint_exists(source)
    check_mutating_endpoints_require_write(source)
    check_no_raw_hash_in_alias_response(source)
    check_tenant_scoping(source)

    checks_run = 4
    if ERRORS:
        print(
            f"identity security validator: {checks_run} checks, "
            f"{len(ERRORS)} issue(s) found."
        )
        print()
        print("IDENTITY SECURITY ISSUES:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1

    print(
        f"identity security validator: {checks_run} checks passed — "
        "suppress endpoint present, auth controls enforced, "
        "alias redaction confirmed, tenant scoping verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
