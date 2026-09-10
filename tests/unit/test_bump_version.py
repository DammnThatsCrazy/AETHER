import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "bump_version.py"
SPEC = importlib.util.spec_from_file_location("bump_version", MODULE_PATH)
assert SPEC and SPEC.loader
bump_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump_version)


def test_update_package_json_preserves_unicode_and_compact_arrays(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text(
        '{\n  "name": "@aether/example",\n  "version": "8.12.0",\n'
        '  "description": "Aether — example",\n  "files": ["dist"],\n'
        '  "dependencies": {"@aether/shared": "^8.12.0"}\n}\n'
    )

    bump_version.update_package_json(package, "0.1.0")

    text = package.read_text()
    assert "Aether — example" in text
    assert '"files": ["dist"]' in text
    assert json.loads(text)["dependencies"]["@aether/shared"] == "^0.1.0"


def test_update_expo_app_preserves_formatting(tmp_path: Path) -> None:
    app = tmp_path / "app.json"
    app.write_text('{\n  "expo": {\n    "version": "8.12.0",\n    "plugins": ["expo-secure-store"]\n  }\n}\n')

    bump_version.update_expo_app(app, "0.1.0")

    assert '"plugins": ["expo-secure-store"]' in app.read_text()
    assert json.loads(app.read_text())["expo"]["version"] == "0.1.0"
