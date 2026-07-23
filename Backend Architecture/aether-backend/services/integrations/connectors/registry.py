"""Connector registry — single source of truth for available connectors."""
from __future__ import annotations

from services.integrations.connectors.adapters import ALL_CONNECTORS
from services.integrations.connectors.base import BaseConnector
from services.integrations.consent_policy import integration_governance_descriptor

CONNECTORS: dict[str, BaseConnector] = {c.connector_type: c() for c in ALL_CONNECTORS}


def get_connector(connector_type: str) -> BaseConnector | None:
    return CONNECTORS.get(connector_type)


def descriptor_for(connector_type: str) -> dict | None:
    connector = get_connector(connector_type)
    if connector is None:
        return None
    return {
        **connector.descriptor().model_dump(),
        **integration_governance_descriptor(connector_type),
    }


def list_descriptors() -> list[dict]:
    return [
        descriptor
        for connector_type in CONNECTORS
        if (descriptor := descriptor_for(connector_type)) is not None
    ]
