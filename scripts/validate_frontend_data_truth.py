#!/usr/bin/env python3
"""Enforce Aether and Kyber frontend data-truth boundaries.

The default check is source-only and does not require Node dependencies.
``--build-bundles`` additionally creates explicit production builds and scans
their emitted JavaScript, HTML, and CSS. Missing bundle directories are a
failure when ``--bundles`` is requested; the bundle gate must never silently
skip itself.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
APP_NAMES = ("aether", "kyber")
APP_ROOTS = tuple(ROOT / "frontend" / app for app in APP_NAMES)
RUNTIME_ROOTS = tuple(app_root / "src" for app_root in APP_ROOTS)
BUNDLE_ROOTS = tuple(app_root / "dist" for app_root in APP_ROOTS)
PUBLIC_WORKERS = tuple(
    app_root / "public" / "mockServiceWorker.js" for app_root in APP_ROOTS
)
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
BUNDLE_SUFFIXES = {".js", ".html", ".css"}

# This is intentionally a narrow path allowlist. Runtime ``src/mocks`` and
# ``src/fixtures`` directories are not test-only, even if their current callers
# happen to be tests.
TEST_DIRECTORY_NAMES = {"test", "tests", "test-support", "__tests__"}
TEST_FILENAME_RE = re.compile(
    r"\.(?:test|spec|stories)\.(?:[cm]?[jt]sx?)$", re.IGNORECASE
)
PROHIBITED_SOURCE_DIRECTORIES = {"mocks", "fixtures"}

SOURCE_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("msw/browser", re.compile(r"msw/browser")),
    ("setupWorker", re.compile(r"\bsetupWorker\b")),
    ("isLocalMocked", re.compile(r"\bisLocalMocked\b")),
    ("MockModeBanner", re.compile(r"\bMockModeBanner\b")),
    ("local-mocked", re.compile(r"\blocal-mocked\b")),
    ("tenant_demo_001", re.compile(r"\btenant_demo_001\b")),
    ("tenant_kyber_mock", re.compile(r"\btenant_kyber_mock\b")),
    ("Alex Reeves", re.compile(r"\bAlex Reeves\b")),
    ("alex@acme.io", re.compile(r"\balex@acme\.io\b", re.IGNORECASE)),
    ("ak_mock", re.compile(r"\bak_mock[A-Za-z0-9_-]*\b")),
    ("mock_access_token", re.compile(r"\bmock_access_token\b")),
    ("mock_refresh", re.compile(r"\bmock_refresh\b")),
    ("runtime MOCK_* identifier", re.compile(r"\bMOCK_[A-Z0-9_]+\b")),
)
BUNDLE_TOKENS = (
    "mockServiceWorker",
    "tenant_demo_001",
    "tenant_kyber_mock",
    "Alex Reeves",
    "alex@acme.io",
    "ak_mock",
    "mock_access_token",
    "mock_refresh",
    "dep_discord_support_001",
    "imp_customers_001",
)

IMPORT_SPECIFIER_RE = re.compile(
    r"""
    (?:
        \bfrom\s* |
        \bimport\s*(?:\(\s*)? |
        \brequire\s*\(\s*
    )
    ["'](?P<specifier>[^"']+)["']
    """,
    re.VERBOSE,
)

PRODUCTION_BUILD_ENV = {
    "VITE_AETHER_ENV": "production",
    "VITE_KYBER_ENV": "production",
    "VITE_API_BASE_URL": "https://api.invalid",
    "VITE_AETHER_ENDPOINT": "https://api.invalid",
    "VITE_WS_BASE_URL": "wss://api.invalid",
    "VITE_GRAPHQL_URL": "https://api.invalid/v1/analytics/graphql",
    "VITE_OIDC_AUTHORITY": "https://identity.invalid",
    "VITE_OIDC_CLIENT_ID": "frontend-data-truth-build",
    "VITE_OIDC_REDIRECT_URI": "https://app.invalid/callback",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Aether/Kyber production source and bundle data-truth boundaries"
    )
    bundle_mode = parser.add_mutually_exclusive_group()
    bundle_mode.add_argument(
        "--bundles",
        action="store_true",
        help="scan existing production bundles and fail if either dist directory is missing",
    )
    bundle_mode.add_argument(
        "--build-bundles",
        action="store_true",
        help="build Aether and Kyber with explicit production configuration, then scan them",
    )
    return parser.parse_args(argv)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_test_path(path: Path, root: Path = ROOT) -> bool:
    """Return whether ``path`` is in the documented test-only allowlist."""
    rel = path.relative_to(root)
    return (
        any(part in TEST_DIRECTORY_NAMES for part in rel.parts)
        or TEST_FILENAME_RE.search(path.name) is not None
    )


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(path: Path, line: int, reason: str, root: Path) -> dict[str, object]:
    return {"path": _relative(path, root), "line": line, "reason": reason}


def _runtime_files(runtime_roots: Iterable[Path]) -> Iterable[Path]:
    for runtime_root in runtime_roots:
        if not runtime_root.exists():
            continue
        for path in sorted(runtime_root.rglob("*")):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES:
                yield path


def _config_files(app_roots: Iterable[Path]) -> Iterable[Path]:
    """Yield runtime-affecting files outside ``src`` that guardrails must scan."""
    for app_root in app_roots:
        for pattern in ("vite.config.*", ".env", ".env.*"):
            for path in sorted(app_root.glob(pattern)):
                if path.is_file():
                    yield path


def _scan_source_path(path: Path, root: Path) -> list[dict[str, object]]:
    if is_test_path(path, root):
        return []

    rel_parts = set(path.relative_to(root).parts)
    prohibited_dirs = sorted(rel_parts & PROHIBITED_SOURCE_DIRECTORIES)
    if prohibited_dirs:
        return [
            _finding(
                path,
                1,
                "production source is stored under prohibited "
                + "/".join(prohibited_dirs)
                + " directory",
                root,
            )
        ]

    findings: list[dict[str, object]] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    seen: set[tuple[int, str]] = set()
    for label, pattern in SOURCE_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            line = _line_number(text, match.start())
            key = (line, label)
            if key not in seen:
                findings.append(
                    _finding(path, line, f"banned runtime token: {label}", root)
                )
                seen.add(key)

    for match in IMPORT_SPECIFIER_RE.finditer(text):
        specifier = match.group("specifier")
        parts = set(PureImportPath.parts(specifier))
        if parts & PROHIBITED_SOURCE_DIRECTORIES:
            line = _line_number(text, match.start())
            key = (line, "runtime import from mocks/fixtures")
            if key not in seen:
                findings.append(
                    _finding(
                        path,
                        line,
                        "runtime import from mocks/fixtures",
                        root,
                    )
                )
                seen.add(key)
    return findings


def scan_source(
    *,
    root: Path = ROOT,
    runtime_roots: Iterable[Path] | None = None,
    app_roots: Iterable[Path] | None = None,
    public_workers: Iterable[Path] | None = None,
) -> list[dict[str, object]]:
    runtime_roots = tuple(runtime_roots or RUNTIME_ROOTS)
    app_roots = tuple(app_roots or APP_ROOTS)
    public_workers = tuple(public_workers or PUBLIC_WORKERS)
    findings: list[dict[str, object]] = []

    for worker in public_workers:
        if worker.exists():
            findings.append(
                _finding(worker, 1, "public mockServiceWorker.js is prohibited", root)
            )

    source_files = sorted(
        {*_runtime_files(runtime_roots), *_config_files(app_roots)}
    )
    # Source trees contain hundreds of small files. Parallel reads keep the
    # validator fast on networked/macOS workspaces without changing its
    # deterministic, sorted report.
    max_workers = min(16, max(1, len(source_files)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for path_findings in executor.map(
            lambda path: _scan_source_path(path, root), source_files
        ):
            findings.extend(path_findings)

    return sorted(
        findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["reason"]))
    )


class PureImportPath:
    """Normalize slash-delimited module specifiers without filesystem access."""

    @staticmethod
    def parts(specifier: str) -> tuple[str, ...]:
        return tuple(part for part in specifier.replace("\\", "/").split("/") if part)


def scan_bundles(
    *,
    root: Path = ROOT,
    bundle_roots: Iterable[Path] | None = None,
    require_bundles: bool = True,
) -> list[dict[str, object]]:
    bundle_roots = tuple(bundle_roots or BUNDLE_ROOTS)
    findings: list[dict[str, object]] = []
    for bundle_root in bundle_roots:
        if not bundle_root.is_dir():
            if require_bundles:
                findings.append(
                    _finding(
                        bundle_root,
                        0,
                        "production bundle directory is missing; build scan was not executed",
                        root,
                    )
                )
            continue

        bundle_files = [
            path
            for path in sorted(bundle_root.rglob("*"))
            if path.is_file() and path.suffix in BUNDLE_SUFFIXES
        ]
        if not bundle_files and require_bundles:
            findings.append(
                _finding(
                    bundle_root,
                    0,
                    "production bundle contains no scannable JavaScript, HTML, or CSS",
                    root,
                )
            )
            continue

        for path in bundle_files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in BUNDLE_TOKENS:
                if token in text:
                    findings.append(
                        _finding(
                            path,
                            1,
                            f"banned production bundle token: {token}",
                            root,
                        )
                    )
    return sorted(
        findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["reason"]))
    )


def build_production_bundles(root: Path = ROOT) -> int:
    env = os.environ.copy()
    env.update(PRODUCTION_BUILD_ENV)
    workspaces = ["packages/shared", "packages/web", *(f"frontend/{app}" for app in APP_NAMES)]
    for workspace in workspaces:
        proc = subprocess.run(
            ["npm", "run", "build", f"--workspace={workspace}"],
            cwd=root,
            env=env,
        )
        if proc.returncode:
            return proc.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    findings = scan_source()

    build_status = 0
    if args.build_bundles:
        build_status = build_production_bundles()
        if build_status:
            findings.append(
                {
                    "path": "frontend",
                    "line": 0,
                    "reason": f"production frontend build failed with exit code {build_status}",
                }
            )
        else:
            findings.extend(scan_bundles())
    elif args.bundles:
        findings.extend(scan_bundles())

    findings = sorted(
        findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["reason"]))
    )
    report = {
        "status": "pass" if not findings else "fail",
        "checks": {
            "source": True,
            "bundles": bool(args.bundles or args.build_bundles),
            "bundles_built": bool(args.build_bundles and build_status == 0),
        },
        "finding_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(report, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
