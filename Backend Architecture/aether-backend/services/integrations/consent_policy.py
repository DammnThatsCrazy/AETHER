"""Stable integration-facing facade for the consent processing authority."""
from services.consent.integration_governance import (
    evaluate_connector_processing,
    get_integration_consent_policy,
    integration_governance_descriptor,
    normalize_connector_type,
)

__all__ = [
    "evaluate_connector_processing",
    "get_integration_consent_policy",
    "integration_governance_descriptor",
    "normalize_connector_type",
]
