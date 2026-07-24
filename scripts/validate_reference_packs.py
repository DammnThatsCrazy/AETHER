#!/usr/bin/env python3
"""Agent-access reference pack gate.

Validates every pack in ``config/agent_access_reference_packs/`` against the pack
schema owned by
``Backend Architecture/aether-backend/services/agent_access_intelligence/reference_packs.py``.
The schema is imported from that loader rather than restated here, so the CI gate
and the runtime loader can never drift apart about what a valid pack is.

Checked per pack: required fields present, ``schema_version`` correct, ``pack_id``
non-empty and equal to the filename stem, ``provider_id``/``display_name``/
``pack_version`` non-empty, ``pack_status`` known, ``grounded_in`` present for
reference packs, ``capability_kind_defaults`` drawn from ``CapabilityKind``,
``naming_hints`` well-formed, and ``approved_scope_baselines`` a
``{grant_id: [scope, ...]}`` mapping consistent with the declared
``baseline_status``. Across packs: no duplicate ``pack_id``.

Why this is a gate and not a warning: ``approved_scope_baselines`` is passed
verbatim to ``provider_framework.compute_permission_findings``, which defaults a
missing grant to ``[]``. A pack that fails to parse therefore does not fail closed
in any useful sense — it removes a provider's baselines. This script fails the
build instead.

Read-only: parses YAML and prints. It never writes or reformats a pack.

Usage:
  python scripts/validate_reference_packs.py                 # validate the repo packs
  python scripts/validate_reference_packs.py --dir <path>    # validate another dir
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
DEFAULT_PACK_DIR = ROOT / "config" / "agent_access_reference_packs"


def _load_schema_module():
    """Import the pack loader, failing loudly if it cannot be imported.

    A swallowed ImportError here would turn this gate into a no-op that reports
    success, which is worse than no gate at all.
    """
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("AETHER_ENV", "local")
    from services.agent_access_intelligence import reference_packs  # noqa: E402

    return reference_packs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate agent-access reference packs.")
    parser.add_argument(
        "--dir",
        dest="directory",
        default=str(DEFAULT_PACK_DIR),
        help="pack directory to validate (default: config/agent_access_reference_packs)",
    )
    args = parser.parse_args()

    try:
        rp = _load_schema_module()
    except Exception as exc:  # pragma: no cover - environment/import failure
        print(
            "REFERENCE PACK GATE COULD NOT RUN — failed to import the pack loader "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 1

    import yaml  # noqa: E402  (imported after BACKEND path setup, same as the loader)

    pack_dir = Path(args.directory).resolve()
    if not pack_dir.is_dir():
        print(f"REFERENCE PACK VIOLATIONS:\n  - pack directory not found: {pack_dir}", file=sys.stderr)
        return 1

    paths = sorted(p for p in pack_dir.iterdir() if p.suffix in rp.PACK_SUFFIXES and p.is_file())
    if not paths:
        print(
            f"REFERENCE PACK VIOLATIONS:\n  - no packs found in {pack_dir} "
            f"(expected at least one *.yaml)",
            file=sys.stderr,
        )
        return 1

    errors: list[str] = []
    seen: dict[str, str] = {}
    statuses: dict[str, int] = {}
    valid = 0

    # Every pack is checked; the gate reports ALL violations, not just the first,
    # so one broken pack does not hide the next.
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: unreadable pack ({type(exc).__name__}: {exc})")
            continue

        pack_errors = rp.pack_violations(data, path.name, path.stem)
        errors.extend(pack_errors)

        pack_id = data.get("pack_id") if isinstance(data, dict) else None
        if isinstance(pack_id, str) and pack_id:
            if pack_id in seen:
                errors.append(
                    f"{path.name}: duplicate pack_id {pack_id!r} — already declared by {seen[pack_id]}"
                )
            else:
                seen[pack_id] = path.name
        if not pack_errors:
            valid += 1
            status = data.get("pack_status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1

    if errors:
        print("REFERENCE PACK VIOLATIONS:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            f"\n{len(errors)} violation(s) across {len(paths)} pack file(s) in {pack_dir}",
            file=sys.stderr,
        )
        return 1

    summary = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
    print(f"reference packs OK: {valid} pack(s) validated ({summary}) in {pack_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
