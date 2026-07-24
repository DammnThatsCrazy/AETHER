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


def test_bundle_modes_are_mutually_exclusive() -> None:
    try:
        validator.parse_args(["--bundles", "--build-bundles"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse must reject this combination
        raise AssertionError("bundle modes were not mutually exclusive")
