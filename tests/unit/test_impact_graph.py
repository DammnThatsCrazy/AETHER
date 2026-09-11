from __future__ import annotations

from scripts.lib.impact_graph import (
    build_impact_index,
    compare_shadow_scopes,
    load_impact_graph,
)
from scripts.lib.verification_router import load_router_registry


def test_canonical_graph_binds_to_router_and_test_registry():
    graph = load_impact_graph()
    assert {"verification-router", "impact-graph", "telemetry", "delivery-orchestrator", "environment-authorities", "hosted-delivery", "application-runtime", "kyber-readiness", "infrastructure-runtime", "verification-and-documentation"} <= set(graph.components)
    assert graph.contracts["test-suite-registry"].registry_ref == "config/test_suites.yaml"
    assert len(graph.test_suites) > 7
    assert "deployable:repository-doctor" in graph.nodes


def test_index_is_deterministic_and_transitive():
    router = load_router_registry("config/verification_router.yaml")
    graph = load_impact_graph(router=router)
    first = build_impact_index(
        [
            "config/verification_router.yaml",
            "scripts/lib/impact_graph.py",
            "config/verification_router.yaml",
        ],
        graph,
        router=router,
    )
    second = build_impact_index(
        ["scripts/lib/impact_graph.py", "config/verification_router.yaml"],
        graph,
        router=router,
    )
    assert first == second
    assert first["direct_nodes"] == [
        "component:impact-graph",
        "component:verification-router",
        "contract:verification-router",
    ]
    assert set(first["impacted_contracts"]) >= {
        "impact-graph-index", "telemetry-contract", "test-suite-registry", "verification-router",
    }
    assert set(first["impacted_deployables"]) >= {"repository-doctor", "delivery-workflows"}


def test_unresolved_paths_are_visible_and_escalate_router_lane():
    result = build_impact_index(["unregistered/new-component.py"])
    assert result["direct_nodes"] == []
    assert result["unresolved_paths"] == ["unregistered/new-component.py"]
    assert result["router"]["minimum_lane"] == "integration"
    assert result["router"]["selected_lane"] == "integration"


def test_shared_contract_change_selects_registered_transitive_consumers():
    result = build_impact_index(["packages/shared/contracts/event-registry.json"])
    assert "shared-runtime-contracts" in result["impacted_contracts"]
    assert set(result["router"]["selected_checks"]) >= {
        "sdk-shared",
        "frontend-aether",
        "frontend-kyber",
    }


def test_shadow_comparison_distinguishes_targeted_miss_and_legacy_broad_result():
    expected = {"component:a", "contract:a", "deployable:a"}
    assert (
        compare_shadow_scopes(
            expected_nodes=expected,
            targeted_nodes={"component:a", "contract:a"},
            legacy_nodes=expected,
        ).classification
        == "targeted_miss"
    )
    assert (
        compare_shadow_scopes(
            expected_nodes=expected,
            targeted_nodes=expected,
            legacy_nodes=expected | {"component:unrelated"},
        ).classification
        == "legacy_broad_result"
    )
    assert (
        compare_shadow_scopes(
            expected_nodes=expected,
            targeted_nodes=expected,
            legacy_nodes=expected,
        ).classification
        == "equivalent"
    )
