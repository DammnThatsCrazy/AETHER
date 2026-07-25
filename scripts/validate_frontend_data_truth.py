#!/usr/bin/env python3
"""Enforce Aether, Kyber, and Demo frontend data-truth boundaries.

The default check is source-only and does not require Node dependencies.
``--build-bundles`` additionally creates explicit production builds and scans
their emitted JavaScript, HTML, and CSS. Missing bundle directories are a
failure when ``--bundles`` is requested; the bundle gate must never silently
skip itself.

Aether and Kyber are production tenant/operator apps: ``src/mocks`` and
``src/fixtures`` are prohibited outright. The demo app has a different
contract — synthetic data is its purpose, so those directories are permitted in
its source — but ``VITE_DEMO_ENV`` must stay explicit (no default), and the
fixture and MSW modules must be statically unreachable from any build whose
canonical deployment profile forbids compiled-in synthetic data.
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

# --- Demo app -------------------------------------------------------------
# frontend/demo is the closed synthetic demo SPA. Its source may hold mocks and
# fixtures; what it may not do is default to them or emit them where the
# canonical deployment profile forbids it.
DEMO_APP_ROOT = ROOT / "frontend" / "demo"
DEMO_ENV_VAR = "VITE_DEMO_ENV"
# Canonical profile names the demo SPA can legitimately run as, per
# config/deployment_profiles.yaml (local-mocked runs demo-spa + mock-data-msw,
# demo-static runs synthetic-precomputed-data, demo-live runs a synthetic
# tenant against a shared non-production backend).
CANONICAL_DEMO_ENVIRONMENTS = ("local-mocked", "demo-static", "demo-live")
# Profiles allowed to ship compiled-in synthetic fixture data.
DEMO_SYNTHETIC_DATASET_ENVIRONMENTS = ("local-mocked", "demo-static")
DEMO_BUNDLE_PROFILE_STAMP = "aether-demo-env"
# Only local-mocked may emit the MSW worker; nothing else may.
DEMO_MOCK_BUNDLE_TOKENS = (
    "mockServiceWorker",
    "msw/browser",
    "setupWorker",
    "onUnhandledRequest",
    "Mock Service Worker",
)
# Fixture literals that must never reach a bundle built for a profile whose
# data comes from a backend rather than from src/data/fixtures.ts.
DEMO_FIXTURE_BUNDLE_TOKENS = (
    "data/fixtures",
    "tenant_demo_orbit",
    "Orbit Commerce",
    "Maya Chen",
    "Cart Abandonment Recovery",
)
DEMO_ENV_DEFAULT_RES = (
    # `import.meta.env.VITE_DEMO_ENV ?? '<anything>'`
    re.compile(rf"{DEMO_ENV_VAR}[^\n;]*?(?:\?\?|\|\|)\s*['\"]"),
    # Any fallback to a profile literal, however the value was read first.
    re.compile(
        r"(?:\?\?|\|\|)\s*['\"](?:local-mocked|demo-static|demo-live)['\"]"
    ),
)
DEMO_ENVIRONMENT_LIST_RE = re.compile(
    r"DEMO_ENVIRONMENTS\s*(?::[^=\n]*)?=\s*\[(?P<items>[^\]]*)\]"
)
DEMO_QUOTED_VALUE_RE = re.compile(r"['\"]([^'\"]+)['\"]")
DEMO_STATIC_WORKER_GUARD_RE = re.compile(
    rf"import\.meta\.env\.{DEMO_ENV_VAR}\s*===\s*['\"]local-mocked['\"]"
)
DEMO_WORKER_IMPORT_RE = re.compile(r"""import\s*\(\s*['\"][^'\"]*mocks/""")
DEMO_BUNDLE_STAMP_RE = re.compile(
    rf"""<meta[^>]*name=['\"]{DEMO_BUNDLE_PROFILE_STAMP}['\"][^>]*content=['\"](?P<value>[^'\"]*)['\"]"""
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
    # The demo SPA is built under its strictest profile: demo-live must contain
    # neither the MSW worker nor the fixture module.
    DEMO_ENV_VAR: "demo-live",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Aether/Kyber/Demo frontend source and bundle data-truth boundaries"
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


def _demo_source_files(app_root: Path) -> list[Path]:
    """Yield demo source and runtime-affecting configuration files."""
    files: list[Path] = []
    runtime_root = app_root / "src"
    if runtime_root.is_dir():
        files.extend(
            path
            for path in runtime_root.rglob("*")
            if path.is_file() and path.suffix in SOURCE_SUFFIXES
        )
    for pattern in ("vite.config.*", "vitest.config.*", ".env", ".env.*", "index.html"):
        files.extend(path for path in app_root.glob(pattern) if path.is_file())
    return sorted(set(files))


def _declared_demo_environments(text: str) -> tuple[str, ...] | None:
    match = DEMO_ENVIRONMENT_LIST_RE.search(text)
    if match is None:
        return None
    return tuple(DEMO_QUOTED_VALUE_RE.findall(match.group("items")))


def _check_demo_profile_declaration(
    path: Path, root: Path, *, label: str
) -> list[dict[str, object]]:
    """Require a fail-closed, canonical ``VITE_DEMO_ENV`` declaration."""
    if not path.is_file():
        return [_finding(path, 0, f"demo {label} is missing; {DEMO_ENV_VAR} is unenforced", root)]

    findings: list[dict[str, object]] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "throw" not in text:
        findings.append(
            _finding(
                path,
                1,
                f"demo {label} must fail closed on an unset or unknown {DEMO_ENV_VAR}",
                root,
            )
        )
    declared = _declared_demo_environments(text)
    if declared is None:
        findings.append(
            _finding(path, 1, f"demo {label} declares no DEMO_ENVIRONMENTS list", root)
        )
    elif tuple(declared) != CANONICAL_DEMO_ENVIRONMENTS:
        findings.append(
            _finding(
                path,
                1,
                "demo profile list drifted from the canonical deployment profiles "
                + f"({', '.join(CANONICAL_DEMO_ENVIRONMENTS)})",
                root,
            )
        )
    return findings


def scan_demo_source(
    *, root: Path = ROOT, app_root: Path | None = None
) -> list[dict[str, object]]:
    """Scan the demo SPA under its own contract.

    ``mocks`` and ``fixtures`` directories are permitted here — they are the
    demo app's purpose — but the environment variable that selects them must be
    explicit, and the mock entrypoint must be statically eliminable.
    """
    app_root = app_root or DEMO_APP_ROOT
    if not app_root.is_dir():
        return [
            _finding(
                app_root,
                0,
                "demo frontend directory is missing; demo data-truth scan was not executed",
                root,
            )
        ]

    findings: list[dict[str, object]] = []
    for path in _demo_source_files(app_root):
        if is_test_path(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        seen_lines: set[int] = set()
        for pattern in DEMO_ENV_DEFAULT_RES:
            for match in pattern.finditer(text):
                line = _line_number(text, match.start())
                if line in seen_lines:
                    continue
                seen_lines.add(line)
                findings.append(
                    _finding(
                        path,
                        line,
                        f"{DEMO_ENV_VAR} must be explicit and must not have an implicit default",
                        root,
                    )
                )

    findings.extend(
        _check_demo_profile_declaration(
            app_root / "src" / "lib" / "env.ts", root, label="environment module"
        )
    )
    findings.extend(
        _check_demo_profile_declaration(
            app_root / "vite.config.ts", root, label="vite config"
        )
    )

    entrypoint = app_root / "src" / "main.tsx"
    if not entrypoint.is_file():
        findings.append(_finding(entrypoint, 0, "demo entrypoint is missing", root))
    else:
        text = entrypoint.read_text(encoding="utf-8", errors="ignore")
        match = DEMO_WORKER_IMPORT_RE.search(text)
        if match and not DEMO_STATIC_WORKER_GUARD_RE.search(text):
            findings.append(
                _finding(
                    entrypoint,
                    _line_number(text, match.start()),
                    "demo mock worker import must be guarded by a statically eliminable "
                    + f"import.meta.env.{DEMO_ENV_VAR} === 'local-mocked' comparison",
                    root,
                )
            )

    index_html = app_root / "index.html"
    if not index_html.is_file():
        findings.append(_finding(index_html, 0, "demo index.html is missing", root))
    elif DEMO_BUNDLE_PROFILE_STAMP not in index_html.read_text(
        encoding="utf-8", errors="ignore"
    ):
        findings.append(
            _finding(
                index_html,
                1,
                f"demo index.html must stamp the resolved profile as "
                f"<meta name=\"{DEMO_BUNDLE_PROFILE_STAMP}\"> so the bundle gate cannot be blinded",
                root,
            )
        )

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


def scan_demo_bundle(
    *,
    root: Path = ROOT,
    bundle_root: Path | None = None,
    require_bundles: bool = True,
) -> list[dict[str, object]]:
    """Scan an emitted demo bundle against the profile it was built for.

    The profile is read from the build-time ``index.html`` stamp. An unstamped
    or unknown bundle is a finding and is then scanned under the strictest
    profile, so the gate can never be skipped by dropping the stamp.
    """
    bundle_root = bundle_root or (DEMO_APP_ROOT / "dist")
    findings: list[dict[str, object]] = []
    if not bundle_root.is_dir():
        if require_bundles:
            findings.append(
                _finding(
                    bundle_root,
                    0,
                    "demo bundle directory is missing; build scan was not executed",
                    root,
                )
            )
        return findings

    bundle_files = [
        path
        for path in sorted(bundle_root.rglob("*"))
        if path.is_file() and path.suffix in BUNDLE_SUFFIXES
    ]
    if not bundle_files:
        if require_bundles:
            findings.append(
                _finding(
                    bundle_root,
                    0,
                    "demo bundle contains no scannable JavaScript, HTML, or CSS",
                    root,
                )
            )
        return findings

    index_html = bundle_root / "index.html"
    profile: str | None = None
    if index_html.is_file():
        stamp = DEMO_BUNDLE_STAMP_RE.search(
            index_html.read_text(encoding="utf-8", errors="ignore")
        )
        if stamp is not None:
            profile = stamp.group("value").strip()
    if profile not in CANONICAL_DEMO_ENVIRONMENTS:
        findings.append(
            _finding(
                index_html,
                1,
                f"demo bundle does not declare a resolved {DEMO_ENV_VAR} profile stamp; "
                "scanned under the strictest profile",
                root,
            )
        )
        profile = "demo-live"

    banned: list[str] = []
    if profile != "local-mocked":
        banned.extend(DEMO_MOCK_BUNDLE_TOKENS)
    if profile not in DEMO_SYNTHETIC_DATASET_ENVIRONMENTS:
        banned.extend(DEMO_FIXTURE_BUNDLE_TOKENS)

    for path in bundle_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in banned:
            if token in text:
                findings.append(
                    _finding(
                        path,
                        1,
                        f"banned demo bundle token for profile {profile}: {token}",
                        root,
                    )
                )
    return sorted(
        findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["reason"]))
    )


def build_production_bundles(root: Path = ROOT) -> int:
    env = os.environ.copy()
    env.update(PRODUCTION_BUILD_ENV)
    workspaces = [
        "packages/shared",
        "packages/web",
        *(f"frontend/{app}" for app in APP_NAMES),
        "frontend/demo",
    ]
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
    findings.extend(scan_demo_source())

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
            findings.extend(scan_demo_bundle())
    elif args.bundles:
        findings.extend(scan_bundles())
        findings.extend(scan_demo_bundle())

    findings = sorted(
        findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["reason"]))
    )
    report = {
        "status": "pass" if not findings else "fail",
        "checks": {
            "source": True,
            "demo_source": True,
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
