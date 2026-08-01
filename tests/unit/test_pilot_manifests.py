"""Every pilot manifest validates against schema + semantics (offline).

Retroactively guards the pre-existing ``usdc-observation`` example under CI and
pins the new ``financial-observation`` example as an observe-only, secret-free,
shadow-mode manifest whose provider selections resolve in the certification
matrix.
"""

from __future__ import annotations

import json

import yaml

from scripts import validate_pilot_manifest as vpm


def _schema() -> dict:
    return json.loads(vpm.DEFAULT_SCHEMA.read_text(encoding="utf-8"))


def _examples() -> list:
    return sorted(vpm.EXAMPLES_DIR.glob("*.yaml"))


def test_every_example_manifest_validates():
    schema = _schema()
    paths = _examples()
    assert paths, "no example manifests found under config/pilot/examples"
    for path in paths:
        result = vpm.validate_manifest(path, schema, strict_providers=True)
        assert result["passed"], f"{path.name} failed: {result['errors']}"


def test_financial_observation_is_present():
    assert (vpm.EXAMPLES_DIR / "financial-observation.yaml").exists()


def test_financial_observation_is_observe_only():
    path = vpm.EXAMPLES_DIR / "financial-observation.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert manifest["mode"] == "observation"
    assert manifest["shadow_mode"] is True

    # No delivery/execution/settlement/reward entitlement may be enabled.
    for ent in manifest.get("entitlements", []):
        if ent.get("name") in vpm._DELIVERY_ENTITLEMENTS:
            assert ent.get("enabled") is False, f"{ent['name']} must not be enabled"

    assert (manifest.get("rewards") or {}).get("enabled") is not True


def test_financial_observation_provider_cross_check_resolves():
    path = vpm.EXAMPLES_DIR / "financial-observation.yaml"
    result = vpm.validate_manifest(path, _schema(), strict_providers=True)
    assert result["passed"], result["errors"]
    # The provider cross-check note proves selections resolve in the matrix.
    assert any("provider cross-check OK" in note for note in result["notes"]), result["notes"]


def test_financial_observation_covers_the_full_financial_cohort():
    path = vpm.EXAMPLES_DIR / "financial-observation.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    selected = {(p["domain"], p["provider"]) for p in manifest["providers"]}
    assert selected == {
        ("payments", "privy"),
        ("payments", "stripe_onramp"),
        ("payments", "coinbase"),
        ("payments", "moonpay"),
        ("payments", "bridge"),
        ("stablecoin_chain", "evm"),
        ("stablecoin_chain", "svm"),
    }
