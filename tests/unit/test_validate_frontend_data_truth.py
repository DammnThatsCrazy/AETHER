from __future__ import annotations

from pathlib import Path

from scripts import validate_frontend_data_truth as validator


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(tmp_path: Path) -> list[dict[str, object]]:
    app_root = tmp_path / "frontend" / "aether"
    return validator.scan_source(
        root=tmp_path,
        runtime_roots=[app_root / "src"],
        app_roots=[app_root],
        public_workers=[app_root / "public" / "mockServiceWorker.js"],
    )


def test_test_only_allowlist_is_narrow(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/aether/src/test/query.test.ts",
        "import { rows } from '../fixtures/rows'; const token = 'local-mocked';",
    )
    _write(
        tmp_path / "frontend/aether/src/widget.stories.tsx",
        "import { rows } from './fixtures/rows';",
    )
    _write(
        tmp_path / "frontend/aether/src/fixtures/rows.ts",
        "export const rows = [{ id: 'tenant_demo_001' }];",
    )

    findings = _scan(tmp_path)

    assert len(findings) == 1
    assert findings[0]["path"] == "frontend/aether/src/fixtures/rows.ts"
    assert "prohibited" in str(findings[0]["reason"])


def test_runtime_imports_and_tokens_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/aether/src/query.ts",
        """
        import {
          rows,
        } from './fixtures/rows';
        const lazy = import('./mocks/browser');
        export const mode = isLocalMocked() ? 'local-mocked' : 'live';
        export const tenant = 'tenant_demo_001';
        export const record = MOCK_TENANT;
        """,
    )

    findings = _scan(tmp_path)
    reasons = [str(finding["reason"]) for finding in findings]

    assert reasons.count("runtime import from mocks/fixtures") == 2
    assert "banned runtime token: isLocalMocked" in reasons
    assert "banned runtime token: local-mocked" in reasons
    assert "banned runtime token: tenant_demo_001" in reasons
    assert "banned runtime token: runtime MOCK_* identifier" in reasons


def test_runtime_affecting_vite_and_env_files_are_scanned(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/aether/vite.config.ts",
        "export const mode = 'local-mocked';",
    )
    _write(
        tmp_path / "frontend/aether/.env.example",
        "VITE_AETHER_ENV=local-mocked\n",
    )

    findings = _scan(tmp_path)

    assert {finding["path"] for finding in findings} == {
        "frontend/aether/.env.example",
        "frontend/aether/vite.config.ts",
    }


def test_public_mock_worker_is_prohibited(tmp_path: Path) -> None:
    _write(
        tmp_path / "frontend/aether/public/mockServiceWorker.js",
        "/* legacy */",
    )

    findings = _scan(tmp_path)

    assert findings == [
        {
            "path": "frontend/aether/public/mockServiceWorker.js",
            "line": 1,
            "reason": "public mockServiceWorker.js is prohibited",
        }
    ]


def test_bundle_scan_fails_closed_when_output_is_missing(tmp_path: Path) -> None:
    bundle_root = tmp_path / "frontend/aether/dist"

    findings = validator.scan_bundles(
        root=tmp_path,
        bundle_roots=[bundle_root],
    )

    assert findings == [
        {
            "path": "frontend/aether/dist",
            "line": 0,
            "reason": "production bundle directory is missing; build scan was not executed",
        }
    ]


def test_bundle_scan_reports_known_synthetic_literals(tmp_path: Path) -> None:
    bundle_root = tmp_path / "frontend/aether/dist"
    _write(
        bundle_root / "assets/index.js",
        "const worker = 'mockServiceWorker'; const tenant = 'tenant_demo_001';",
    )

    findings = validator.scan_bundles(
        root=tmp_path,
        bundle_roots=[bundle_root],
    )

    assert [finding["reason"] for finding in findings] == [
        "banned production bundle token: mockServiceWorker",
        "banned production bundle token: tenant_demo_001",
    ]


DEMO_ENV_MODULE = """
export const DEMO_ENVIRONMENTS = ['local-mocked', 'demo-static', 'demo-live'] as const;
export function assertDemoEnv(value: string | undefined) {
  if (!value) throw new Error('VITE_DEMO_ENV is required and has no default.');
  return value;
}
"""
DEMO_VITE_CONFIG = """
const DEMO_ENVIRONMENTS = ['local-mocked', 'demo-static', 'demo-live'] as const;
const demoEnv = loadEnv(mode, __dirname, 'VITE_').VITE_DEMO_ENV;
if (!demoEnv) throw new Error('VITE_DEMO_ENV is required and has no default.');
"""
DEMO_MAIN = """
if (import.meta.env.VITE_DEMO_ENV === 'local-mocked') {
  const { worker } = await import('./mocks/browser');
}
"""
DEMO_INDEX_HTML = '<meta name="aether-demo-env" content="%VITE_DEMO_ENV%" />'


def _demo_app(tmp_path: Path, overrides: dict[str, str] | None = None) -> Path:
    """Write a minimal compliant demo app, with per-test replacements."""
    app_root = tmp_path / "frontend" / "demo"
    files = {
        "src/lib/env.ts": DEMO_ENV_MODULE,
        "vite.config.ts": DEMO_VITE_CONFIG,
        "src/main.tsx": DEMO_MAIN,
        "index.html": DEMO_INDEX_HTML,
    }
    files.update(overrides or {})
    for relative, text in files.items():
        _write(app_root / relative, text)
    return app_root


def _scan_demo(tmp_path: Path, overrides: dict[str, str]) -> list[dict[str, object]]:
    app_root = _demo_app(tmp_path, overrides)
    return validator.scan_demo_source(root=tmp_path, app_root=app_root)


def test_demo_source_permits_mocks_and_fixture_directories(tmp_path: Path) -> None:
    app_root = _demo_app(tmp_path)
    _write(app_root / "src/mocks/browser.ts", "export const worker = setupWorker();")
    _write(app_root / "src/data/fixtures.ts", "export const DEMO_TENANT = { name: 'Orbit' };")

    assert validator.scan_demo_source(root=tmp_path, app_root=app_root) == []


def test_demo_source_rejects_implicit_env_default(tmp_path: Path) -> None:
    findings = _scan_demo(
        tmp_path,
        {
            "src/lib/env.ts": DEMO_ENV_MODULE
            + "const v = import.meta.env.VITE_DEMO_ENV ?? 'local-mocked';\n"
        },
    )

    assert [finding["reason"] for finding in findings] == [
        "VITE_DEMO_ENV must be explicit and must not have an implicit default"
    ]
    assert findings[0]["path"] == "frontend/demo/src/lib/env.ts"


def test_demo_source_rejects_a_default_reintroduced_indirectly(tmp_path: Path) -> None:
    findings = _scan_demo(
        tmp_path,
        {
            "src/lib/env.ts": DEMO_ENV_MODULE
            + "const raw = import.meta.env.VITE_DEMO_ENV;\nconst v = raw || 'local-mocked';\n"
        },
    )

    assert [finding["reason"] for finding in findings] == [
        "VITE_DEMO_ENV must be explicit and must not have an implicit default"
    ]


def test_demo_source_rejects_unguarded_mock_worker_import(tmp_path: Path) -> None:
    findings = _scan_demo(
        tmp_path,
        {"src/main.tsx": "if (isLocalMocked()) { await import('./mocks/browser'); }\n"},
    )

    assert len(findings) == 1
    assert "statically eliminable" in str(findings[0]["reason"])
    assert findings[0]["path"] == "frontend/demo/src/main.tsx"


def test_demo_source_rejects_profile_list_drift(tmp_path: Path) -> None:
    findings = _scan_demo(
        tmp_path,
        {
            "src/lib/env.ts": DEMO_ENV_MODULE.replace(
                "'local-mocked', 'demo-static', 'demo-live'",
                "'local-mocked', 'local-live', 'staging', 'production'",
            )
        },
    )

    assert [finding["reason"] for finding in findings] == [
        "demo profile list drifted from the canonical deployment profiles "
        "(local-mocked, demo-static, demo-live)"
    ]


def test_demo_source_requires_fail_closed_declarations(tmp_path: Path) -> None:
    findings = _scan_demo(
        tmp_path,
        {"vite.config.ts": DEMO_VITE_CONFIG.replace("if (!demoEnv) throw new Error", "if (0) log")},
    )

    assert [finding["reason"] for finding in findings] == [
        "demo vite config must fail closed on an unset or unknown VITE_DEMO_ENV"
    ]


def test_demo_source_requires_bundle_profile_stamp(tmp_path: Path) -> None:
    findings = _scan_demo(tmp_path, {"index.html": "<html><body></body></html>"})

    assert len(findings) == 1
    assert "must stamp the resolved profile" in str(findings[0]["reason"])


def test_demo_source_fails_closed_when_app_is_missing(tmp_path: Path) -> None:
    findings = validator.scan_demo_source(
        root=tmp_path, app_root=tmp_path / "frontend" / "demo"
    )

    assert [finding["reason"] for finding in findings] == [
        "demo frontend directory is missing; demo data-truth scan was not executed"
    ]


def _demo_bundle(tmp_path: Path, profile: str | None, asset: str) -> Path:
    bundle_root = tmp_path / "frontend/demo/dist"
    stamp = (
        f'<meta name="aether-demo-env" content="{profile}" />' if profile is not None else ""
    )
    _write(bundle_root / "index.html", f"<html><head>{stamp}</head></html>")
    _write(bundle_root / "assets/index.js", asset)
    return bundle_root


def test_demo_bundle_permits_fixtures_in_local_mocked(tmp_path: Path) -> None:
    bundle_root = _demo_bundle(
        tmp_path,
        "local-mocked",
        "const t = 'tenant_demo_orbit'; navigator.serviceWorker.register('/mockServiceWorker.js');",
    )

    assert validator.scan_demo_bundle(root=tmp_path, bundle_root=bundle_root) == []


def test_demo_bundle_rejects_mock_worker_outside_local_mocked(tmp_path: Path) -> None:
    bundle_root = _demo_bundle(
        tmp_path, "demo-static", "const t = 'tenant_demo_orbit'; setupWorker();"
    )

    findings = validator.scan_demo_bundle(root=tmp_path, bundle_root=bundle_root)

    assert [finding["reason"] for finding in findings] == [
        "banned demo bundle token for profile demo-static: setupWorker"
    ]


def test_demo_bundle_rejects_fixtures_in_demo_live(tmp_path: Path) -> None:
    bundle_root = _demo_bundle(
        tmp_path, "demo-live", "const t = 'tenant_demo_orbit'; const e = 'Maya Chen';"
    )

    findings = validator.scan_demo_bundle(root=tmp_path, bundle_root=bundle_root)

    assert [finding["reason"] for finding in findings] == [
        "banned demo bundle token for profile demo-live: Maya Chen",
        "banned demo bundle token for profile demo-live: tenant_demo_orbit",
    ]


def test_demo_bundle_without_profile_stamp_uses_strictest_profile(tmp_path: Path) -> None:
    bundle_root = _demo_bundle(tmp_path, None, "const t = 'tenant_demo_orbit';")

    findings = validator.scan_demo_bundle(root=tmp_path, bundle_root=bundle_root)
    reasons = [str(finding["reason"]) for finding in findings]

    assert any("does not declare a resolved VITE_DEMO_ENV profile stamp" in r for r in reasons)
    assert "banned demo bundle token for profile demo-live: tenant_demo_orbit" in reasons


def test_demo_bundle_scan_fails_closed_when_output_is_missing(tmp_path: Path) -> None:
    findings = validator.scan_demo_bundle(
        root=tmp_path, bundle_root=tmp_path / "frontend/demo/dist"
    )

    assert findings == [
        {
            "path": "frontend/demo/dist",
            "line": 0,
            "reason": "demo bundle directory is missing; build scan was not executed",
        }
    ]


def test_repository_frontend_source_is_clean() -> None:
    assert validator.scan_source() == []
    assert validator.scan_demo_source() == []


def test_legacy_mock_cleanup_modules_are_not_flagged() -> None:
    modules = [
        validator.ROOT / "frontend" / app / "src/lib/browser/legacy-mock-cleanup.ts"
        for app in validator.APP_NAMES
    ]
    assert all(module.is_file() for module in modules)

    findings = validator.scan_source(
        root=validator.ROOT,
        runtime_roots=[module.parent for module in modules],
        app_roots=[module.parent for module in modules],
        public_workers=[module.parent / "mockServiceWorker.js" for module in modules],
    )

    assert findings == []


def test_bundle_modes_are_mutually_exclusive() -> None:
    try:
        validator.parse_args(["--bundles", "--build-bundles"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse must reject this combination
        raise AssertionError("bundle modes were not mutually exclusive")
