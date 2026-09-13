"""Product / price mapping loader.

Mappings come from ``STRIPE_PRODUCT_MAPPING_JSON`` / ``STRIPE_PRICE_MAPPING_JSON``
(JSON env, optional). With no config (local dev) the catalog is empty and every
billable usage dimension is reported as ``unmapped`` — never an error.
"""
from __future__ import annotations

import json
from typing import Any

from config.settings import settings
from shared.logger.logger import get_logger

from services.billing.providers.base import ProductPriceMapping

logger = get_logger("aether.billing.providers.mappings")

# Billable usage dimensions the platform meters. Used to report which dimensions
# still need a provider price mapping before external billing can be enabled.
KNOWN_USAGE_DIMENSIONS: tuple[str, ...] = (
    "ingestion_events",
    "entity_resolution",
    "graph_operations",
    "profile_queries",
    "recommendations",
    "decisions",
    "actions",
    "dispatches",
    "outcomes",
    "playbooks",
    "audit_exports",
    "integrations",
)


def _safe_load_json(raw: str, label: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        # Never crash startup on malformed mapping config; log and treat as empty.
        logger.warning("invalid %s JSON; treating as empty mapping", label)
        return {}


def load_mappings() -> list[ProductPriceMapping]:
    """Build the mapping catalog from configured product/price JSON."""
    cfg = settings.external_billing
    products = _safe_load_json(cfg.stripe_product_mapping_json, "STRIPE_PRODUCT_MAPPING_JSON")
    prices = _safe_load_json(cfg.stripe_price_mapping_json, "STRIPE_PRICE_MAPPING_JSON")

    mappings: list[ProductPriceMapping] = []
    # Product mappings keyed by package_id.
    for package_id, provider_product_id in products.items():
        mappings.append(ProductPriceMapping(
            package_id=str(package_id),
            provider_product_id=str(provider_product_id) if provider_product_id else None,
            status="mapped" if provider_product_id else "unmapped",
        ))
    # Price mappings keyed by "{plan_tier}" or "{plan_tier}:{usage_dimension}".
    for key, provider_price_id in prices.items():
        plan_tier, _, usage_dimension = str(key).partition(":")
        mappings.append(ProductPriceMapping(
            package_id=plan_tier,
            plan_tier=plan_tier,
            usage_dimension=usage_dimension or None,
            provider_price_id=str(provider_price_id) if provider_price_id else None,
            status="mapped" if provider_price_id else "unmapped",
        ))
    return mappings


def mapping_status_summary(mappings: list[ProductPriceMapping]) -> dict[str, Any]:
    mapped_dimensions = {
        m.usage_dimension for m in mappings if m.usage_dimension and m.status == "mapped"
    }
    unmapped = [d for d in KNOWN_USAGE_DIMENSIONS if d not in mapped_dimensions]
    return {
        "total_mappings": len(mappings),
        "mapped": sum(1 for m in mappings if m.status == "mapped"),
        "unmapped": sum(1 for m in mappings if m.status != "mapped"),
        "unmapped_usage_dimensions": unmapped,
        "all_dimensions_mapped": not unmapped,
    }
