"""Inbound connector framework + 14 disabled-by-default adapters."""
from services.integrations.connectors.routes import admin_router, router

__all__ = ["router", "admin_router"]
