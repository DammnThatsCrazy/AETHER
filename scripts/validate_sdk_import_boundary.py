#!/usr/bin/env python3
"""SDK import-boundary gate (SDK thinness).

The Aether client SDKs are thin: they talk to the canonical backend over the
network (api.aether.io / ingest.aether.so) and must NEVER import backend
implementation code. The internal trees — the deployed Python monolith
(``Backend Architecture/aether-backend``) and the two legacy TypeScript
duplicates (``Data Ingestion Layer/``, ``Data Lake Architecture/``) — are not
importable by SDK client surfaces.

This gate is shrink-only: the committed allowlist
(``scripts/allowlists/sdk_internal_import_allowlist.json``) names every SDK
surface file that today references an internal implementation target. The
allowlist is seeded EMPTY because today's SDK surfaces scan clean. Both
directions fail: an SDK file that NEWLY imports an internal target, and an
allowlist entry that no longer references an internal target (remove it —
shrink-only). Do not weaken the scanner to clear an offender.

Scan surfaces (client SDKs only — ``packages/brand`` and ``packages/python`` are
not SDK client surfaces):
  packages/{web,server,react-native,mobile-core,mobile-ui}/src
  packages/ios/Sources/AetherSDK
  packages/android/src

Forbidden internal targets are DERIVED at run time from the ``name`` fields of
every ``package.json`` under ``Backend Architecture/**``, ``Data Ingestion
Layer/**`` and ``Data Lake Architecture/**`` (the legacy trees), plus static
root-path markers for trees that ship no ``package.json``.

Usage:
  python scripts/validate_sdk_import_boundary.py        # validate (CI gate)
  python scripts/validate_sdk_import_boundary.py --seed # rewrite allowlist
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "allowlists" / "sdk_internal_import_allowlist.json"

# SDK client surfaces that must stay thin (src/ dirs + native SDK source dirs).
_SDK_SURFACE_DIRS = (
    "packages/web/src",
    "packages/server/src",
    "packages/react-native/src",
    "packages/mobile-core/src",
    "packages/mobile-ui/src",
    "packages/ios/Sources/AetherSDK",
    "packages/android/src",
)

# Legacy/internal trees whose package.json ``name`` fields become forbidden
# specifiers. Backend Architecture has no package.json, so its canonical root
# name is pinned as a static root-path marker below.
_INTERNAL_TREE_ROOTS = (
    "Backend Architecture",
    "Data Ingestion Layer",
    "Data Lake Architecture",
)

# Root-path markers: canonical dir basename (Backend Architecture/aether-backend)
# plus the legacy root names, in case a ``package.json`` disappears or a build
# references a root by its directory name rather than its package name.
_STATIC_ROOT_MARKERS = (
    "aether-backend",
    "aether-datalake-backend",
    "Backend Architecture",
    "Data Ingestion Layer",
    "Data Lake Architecture",
)

# Allowed non-relative specifiers for SDK client surfaces (shared + sibling SDK
# packages). Everything relative (``./``, ``../``) stays inside the package and
# is allowed by design.
_ALLOWED_BARE = ("@aether/shared", "@aether/web", "@aether/react-native",
                 "@aether/mobile-core", "@aether/mobile-ui", "@aether/server")

# language file extension -> (import-specifier extractor, target normalizer)
_TS_SUFFIXES = (".ts", ".tsx")
_SWIFT_SUFFIX = ".swift"
_KOTLIN_SUFFIX = ".kt"

# TS: ``from 'x'`` / ``import 'x'`` / ``import('x')`` / ``require('x')``
_TS_IMPORT_RES = (
    re.compile(r"""\b(?:from|import)\s+["']([^"']+)["']"""),
    re.compile(r"""import\s*\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""require\s*\(\s*["']([^"']+)["']\s*\)"""),
)
# Swift + Kotlin: ``import <module>`` on its own line.
_NATIVE_IMPORT_RE = re.compile(r"""^\s*(?:@_exported\s+)?import\s+([A-Za-z0-9_.]+)""")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def forbidden_internal_targets() -> set[str]:
    """Derive the set of internal import targets from the legacy trees.

    Reads the ``name`` of every ``package.json`` under the internal trees and
    unions the static root-path markers (covering the trees with no
    ``package.json`` — notably the Python monolith).
    """
    targets: set[str] = set(_STATIC_ROOT_MARKERS)
    for root in _INTERNAL_TREE_ROOTS:
        proc = _git("ls-files", f"{root}/**/package.json", f"{root}/package.json")
        if proc.returncode != 0:
            continue
        for rel in proc.stdout.splitlines():
            pkg = ROOT / rel
            if not pkg.is_file():
                continue
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = data.get("name")
            if isinstance(name, str) and name:
                targets.add(name)
    return targets


def _is_relative(specifier: str) -> bool:
    return specifier.startswith(("./", "../", "/")) or specifier in {".", ".."}


def _is_allowed_bare(specifier: str) -> bool:
    """True iff a non-relative specifier names a sanctioned sibling SDK package."""
    return any(specifier == allowed or specifier.startswith(allowed + "/") for allowed in _ALLOWED_BARE)


def _target_is_internal(specifier: str, forbidden: set[str]) -> bool:
    """True iff a non-relative specifier names an internal implementation target.

    For TS a bare specifier like ``@aether/logger`` or ``aether-backend`` (or a
    subpath ``@aether/logger/foo``) is internal. Native (Swift/Kotlin) imports
    use dot/plain module names, so the comparison is tolerant of ``/`` vs ``.``
    separators and ``@``-scoping punctuation.
    """
    normalized = specifier.lstrip("@").replace("/", ".").lower()
    for target in forbidden:
        t = target.lstrip("@").replace("/", ".").lower()
        if normalized == t or normalized.startswith(t + "."):
            return True
    return False


def _offender_for_target(rel_path: str, target: str, kind: str) -> str:
    return f"{rel_path}: {kind} {target!r}"


def _scan_file(path: Path, rel: str, forbidden: set[str]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    offenders: list[str] = []
    if path.suffix in _TS_SUFFIXES:
        for regex in _TS_IMPORT_RES:
            for match in regex.finditer(text):
                specifier = match.group(1).strip()
                if _is_relative(specifier) or _is_allowed_bare(specifier):
                    continue
                if _target_is_internal(specifier, forbidden):
                    offenders.append(_offender_for_target(rel, specifier, "TS import"))
    elif path.suffix == _SWIFT_SUFFIX or path.suffix == _KOTLIN_SUFFIX:
        for line in text.splitlines():
            match = _NATIVE_IMPORT_RE.match(line)
            if not match:
                continue
            module = match.group(1)
            if _target_is_internal(module, forbidden):
                kind = "Swift import" if path.suffix == _SWIFT_SUFFIX else "Kotlin import"
                offenders.append(_offender_for_target(rel, module, kind))
    return offenders


def _scan_package_deps(pkg_rel: str, forbidden: set[str]) -> list[str]:
    pkg = ROOT / pkg_rel
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    offenders: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section, {})
        if not isinstance(deps, dict):
            continue
        for name in deps:
            if _is_relative(name) or _is_allowed_bare(name):
                continue
            if name in forbidden:
                offenders.append(_offender_for_target(pkg_rel, name, f"{section} key"))
    return offenders


def _skip_dir(rel_dir: str) -> bool:
    """Skip vendored/build trees that are not authored SDK source."""
    return any(part in rel_dir.split("/") for part in ("node_modules", "dist", "build", ".git"))


def scan() -> set[str]:
    """Return the set of SDK surface files referencing an internal target."""
    forbidden = forbidden_internal_targets()
    offenders: set[str] = set()

    for base in _SDK_SURFACE_DIRS:
        root = ROOT / base
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if _skip_dir(path.parent.relative_to(ROOT).as_posix()):
                continue
            if path.name == "package.json":
                offenders.update(_scan_package_deps(rel, forbidden))
                continue
            if path.suffix not in _TS_SUFFIXES and path.suffix not in {
                _SWIFT_SUFFIX,
                _KOTLIN_SUFFIX,
            }:
                continue
            offenders.update(_scan_file(path, rel, forbidden))

    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="rewrite the allowlist from the current scan (shrink-only contract)",
    )
    args = parser.parse_args()

    actual = scan()

    if args.seed:
        ALLOWLIST.parent.mkdir(parents=True, exist_ok=True)
        ALLOWLIST.write_text(json.dumps(sorted(actual), indent=2) + "\n")
        print(f"seeded SDK internal-import allowlist: {len(actual)} offender(s)")
        return 0

    allowlist = set(json.loads(ALLOWLIST.read_text())) if ALLOWLIST.exists() else set()
    errors: list[str] = []
    for entry in sorted(actual - allowlist):
        errors.append(
            "NEW SDK import of a legacy/backend internal target — SDKs must stay "
            f"thin (talk to api.aether.io / ingest.aether.so): {entry}"
        )
    for entry in sorted(allowlist - actual):
        errors.append(f"allowlist entry no longer references an internal target — REMOVE it (shrink-only): {entry}")

    if errors:
        print("SDK IMPORT-BOUNDARY VIOLATIONS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"SDK import boundary OK: {len(actual)} internal-target references frozen (SDK thinness)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
