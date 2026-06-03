"""Connector registry — single source of truth for available connectors."""
from __future__ import annotations

from services.integrations.connectors.adapters import ALL_CONNECTORS
from services.integrations.connectors.base import BaseConnector

CONNECTORS: dict[str, BaseConnector] = {c.connector_type: c() for c in ALL_CONNECTORS}


def get_connector(connector_type: str) -> BaseConnector | None:
    return CONNECTORS.get(connector_type)


def list_descriptors() -> list[dict]:
    return [c.descriptor().model_dump() for c in CONNECTORS.values()]
