"""The Neptune relabel selects only catalog vertices that are not yet platform owned."""

from __future__ import annotations

from graph.platform_vertex_owners import to_relabel


def test_only_unrelabelled_catalog_vertices_are_selected():
    pending = to_relabel([
        ("chain:eip155:1", {"tenantId": ["public"], "tenant_id": ["public"]}),
        ("card_program:redotpay", {"tenantId": ["platform"], "tenant_id": ["tenant-a"]}),
        ("payment_network:visa", {}),
        ("card_issuer:issuer-1", {"tenantId": ["platform"], "tenant_id": ["platform"]}),
        ("tenant-a:chain:base", {"tenantId": ["tenant-a"], "tenant_id": ["tenant-a"]}),
    ])

    assert [vertex_id for vertex_id, _ in pending] == [
        "chain:eip155:1", "card_program:redotpay", "payment_network:visa",
    ]
    assert pending[0][1] == {"tenantId": "public", "tenant_id": "public"}


def test_derivatives_venue_and_market_vertices_are_selected():
    pending = to_relabel([
        ("market_venue:hyperliquid", {"tenant_id": ["platform"]}),
        ("derivative_market:hl:btc-perp", {"tenantId": ["tenant-a"], "tenant_id": ["platform"]}),
        ("trading_account:dacct_1", {"tenantId": ["tenant-a"], "tenant_id": ["tenant-a"]}),
    ])

    assert [vertex_id for vertex_id, _ in pending] == [
        "market_venue:hyperliquid", "derivative_market:hl:btc-perp",
    ]
