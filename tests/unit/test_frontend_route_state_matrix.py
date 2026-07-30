from __future__ import annotations

from scripts import validate_frontend_route_state_matrix as matrix


def test_matrix_inventory_matches_current_application_routes() -> None:
    report = matrix.build_report()

    assert report["inventory_errors"] == []
    assert report["total_data_bearing_routes"] == sum(report["route_counts"].values())


def test_matrix_published_totals_match_explicit_automated_assertions() -> None:
    report = matrix.build_report()
    document = matrix.MATRIX.read_text(encoding="utf-8")
    total = report["total_data_bearing_routes"]
    labels = {
        "loading": "Explicit loading-state assertions",
        "empty": "Empty-state assertions",
        "error": "Error/unavailable assertions",
        "populated": "Populated-state assertions",
    }
    for state, label in labels.items():
        assert f"| {label} | {report['metrics'][state]} / {total} " in document
    assert (
        "| Critical routes with both empty and error assertions | "
        f"{report['critical_empty_and_error']} / {report['critical_routes']} "
    ) in document
