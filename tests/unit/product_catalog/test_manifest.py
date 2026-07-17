"""Manifest validation, node conversion, and dry-run diff (pure, no I/O)."""
from __future__ import annotations

import pytest

from services.product_catalog.manifest import dry_run_diff, manifest_to_nodes, validate_manifest


def _manifest() -> dict:
    return {
        "version": 2,
        "product": {"stable_id": "checkoutly", "display_name": "Checkoutly"},
        "areas": [
            {"stable_id": "payments", "display_name": "Payments"},
        ],
        "features": [
            {"stable_id": "one-click", "display_name": "One-Click Pay", "area_id": "payments"},
            {"stable_id": "invoicing", "display_name": "Invoicing"},
        ],
        "surfaces": [
            {"stable_id": "checkout-page", "display_name": "Checkout Page", "feature_id": "one-click"},
        ],
        "controls": [
            {"stable_id": "pay-button", "display_name": "Pay Button", "surface_id": "checkout-page"},
        ],
        "outcomes": [
            {"stable_id": "payment-succeeded", "display_name": "Payment Succeeded", "feature_id": "one-click"},
            {"stable_id": "nps-up", "display_name": "NPS Up"},
        ],
    }


class TestValidateManifest:
    def test_happy_path_has_no_errors(self):
        assert validate_manifest(_manifest()) == []

    def test_non_mapping_document(self):
        assert validate_manifest([1, 2]) == ["manifest must be a mapping"]

    def test_missing_product(self):
        errors = validate_manifest({"areas": []})
        assert any("product: required" in e for e in errors)

    def test_missing_stable_id_and_display_name(self):
        doc = _manifest()
        doc["areas"][0] = {"display_name": ""}
        errors = validate_manifest(doc)
        assert any("areas[0]" in e and "stable_id" in e for e in errors)
        assert any("areas[0]" in e and "display_name" in e for e in errors)

    def test_duplicate_stable_ids_rejected(self):
        doc = _manifest()
        doc["features"].append({"stable_id": "payments", "display_name": "Dup"})
        errors = validate_manifest(doc)
        assert any("duplicate stable_id 'payments'" in e for e in errors)

    def test_dangling_parent_reference_rejected(self):
        doc = _manifest()
        doc["surfaces"][0]["feature_id"] = "ghost"
        errors = validate_manifest(doc)
        assert any("surfaces[0]" in e and "'ghost'" in e for e in errors)

    def test_unknown_top_level_and_entry_fields_rejected(self):
        doc = _manifest()
        doc["widgets"] = []
        doc["controls"][0]["clicks"] = 9
        errors = validate_manifest(doc)
        assert any("unknown top-level key(s) ['widgets']" in e for e in errors)
        assert any("controls[0]: unknown field(s) ['clicks']" in e for e in errors)

    def test_bad_status_and_version_rejected(self):
        doc = _manifest()
        doc["version"] = 0
        doc["features"][0]["status"] = "on-fire"
        errors = validate_manifest(doc)
        assert any("version must be an integer >= 1" in e for e in errors)
        assert any("features[0]: status 'on-fire'" in e for e in errors)


class TestManifestToNodes:
    def test_invalid_manifest_raises(self):
        with pytest.raises(ValueError, match="invalid manifest"):
            manifest_to_nodes({"product": {}}, tenant_id="t1")

    def test_nodes_kinds_parents_and_paths(self):
        nodes = {n.stable_id: n for n in manifest_to_nodes(_manifest(), tenant_id="t1")}
        assert set(nodes) == {
            "checkoutly", "payments", "one-click", "invoicing", "checkout-page", "pay-button",
        }
        product = nodes["checkoutly"]
        assert product.kind == "product" and product.parent_id is None
        assert product.path == "checkoutly"

        area = nodes["payments"]
        assert area.kind == "product_area" and area.parent_id == "checkoutly"
        assert area.path == "checkoutly/payments"

        feature = nodes["one-click"]
        assert feature.kind == "feature" and feature.parent_id == "payments"
        assert feature.path == "checkoutly/payments/one-click"

        # Feature without an area parents to the product.
        assert nodes["invoicing"].parent_id == "checkoutly"
        assert nodes["invoicing"].path == "checkoutly/invoicing"

        surface = nodes["checkout-page"]
        assert surface.kind == "surface" and surface.parent_id == "one-click"
        assert surface.path == "checkoutly/payments/one-click/checkout-page"

        control = nodes["pay-button"]
        assert control.kind == "control" and control.parent_id == "checkout-page"
        assert control.path == "checkoutly/payments/one-click/checkout-page/pay-button"

        # Every node carries the tenant and manifest version.
        assert all(n.tenant_id == "t1" and n.version == 2 for n in nodes.values())

    def test_outcomes_fold_into_feature_and_product_metadata(self):
        nodes = {n.stable_id: n for n in manifest_to_nodes(_manifest(), tenant_id="t1")}
        feature_outcomes = nodes["one-click"].metadata["outcomes"]
        assert [o["stable_id"] for o in feature_outcomes] == ["payment-succeeded"]
        product_outcomes = nodes["checkoutly"].metadata["outcomes"]
        assert [o["stable_id"] for o in product_outcomes] == ["nps-up"]


class TestDryRunDiff:
    def test_diff_against_empty_catalog_is_all_added(self):
        desired = manifest_to_nodes(_manifest(), tenant_id="t1")
        diff = dry_run_diff(desired, [])
        assert diff["added"] == sorted(n.stable_id for n in desired)
        assert diff["changed"] == diff["removed"] == diff["unchanged"] == []

    def test_diff_detects_changed_removed_unchanged(self):
        desired = manifest_to_nodes(_manifest(), tenant_id="t1")
        existing = [n.model_copy(deep=True) for n in desired]
        # Change one, remove one from desired, keep the rest identical.
        existing_by_id = {n.stable_id: n for n in existing}
        existing_by_id["pay-button"].display_name = "Old Button"
        trimmed_desired = [n for n in desired if n.stable_id != "invoicing"]
        diff = dry_run_diff(trimmed_desired, list(existing_by_id.values()))
        assert diff["added"] == []
        assert diff["changed"] == ["pay-button"]
        assert diff["removed"] == ["invoicing"]
        assert "checkoutly" in diff["unchanged"]
