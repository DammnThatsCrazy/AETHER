from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import ci_check_identity_continuity as chk

ROOT = Path(__file__).resolve().parents[2]


def _copy(tmp_path: Path) -> Path:
    for rel in (chk.CONTRACT_DIR, chk.FRONTEND_DIR):
        shutil.copytree(ROOT / rel, tmp_path / rel)
    for rel in (chk.EXPLAINABILITY, chk.ROUTES):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_repository_passes_both_gates() -> None:
    assert chk.gate1(ROOT) == [] and chk.gate6(ROOT) == []


def test_missing_contract_is_reported(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / chk.CONTRACT_DIR / "identity-edge.json").unlink()
    assert any("identity-edge.json" in e for e in chk.gate1(root))


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / chk.CONTRACT_DIR / "sdk-contract.json").write_text("{not json", encoding="utf-8")
    assert any("not valid JSON" in e for e in chk.gate1(root))


def test_index_missing_contract_is_reported(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / chk.CONTRACT_DIR / "index.json").write_text('{"contracts": []}', encoding="utf-8")
    assert any("index.json missing contracts" in e for e in chk.gate1(root))


def test_missing_frontend_surface_is_reported(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / chk.FRONTEND_DIR / "SdkHealth.tsx").unlink()
    assert any("SdkHealth.tsx" in e for e in chk.gate6(root))


@pytest.mark.parametrize("rel,marker", [(chk.EXPLAINABILITY, "activation_status"), (chk.ROUTES, "review-queue")])
def test_removed_backend_marker_is_reported(tmp_path: Path, rel: str, marker: str) -> None:
    root = _copy(tmp_path)
    path = root / rel
    path.write_text(path.read_text(encoding="utf-8").replace(marker, "x_removed"), encoding="utf-8")
    assert any(marker in e for e in chk.gate6(root))


def test_main_exit_codes(tmp_path: Path) -> None:
    assert chk.main(["--root", str(ROOT)]) == 0
    assert chk.main(["--root", str(tmp_path)]) == 1  # empty tree fails closed
