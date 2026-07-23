"""Semantic classifier provider abstraction.

Text classification runs behind a pluggable provider so production model backends
can be swapped in without touching the pipeline. The factory FAILS CLOSED: when
configured for a production/multilingual model but credentials are absent it
returns :class:`DisabledProvider` (which abstains) — never a keyword fallback
masquerading as the production model. The deterministic provider (tool-less, no
network) remains the default for CI, replay and structured events.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class SemanticClassifierProvider(ABC):
    """A text-classification backend. Tool-less: no execution authority."""

    name: str = "abstract"

    @abstractmethod
    def available(self) -> bool:
        """True when this provider can classify text right now."""

    def abstention_reason(self) -> str | None:
        return None


class DeterministicClassifierProvider(SemanticClassifierProvider):
    """Keyword/structured deterministic classifier — the CI/replay default."""

    name = "deterministic-semantic-classifier@1.0.0"

    def available(self) -> bool:
        return True


class DisabledProvider(SemanticClassifierProvider):
    """Fail-closed provider: always unavailable, always abstains."""

    name = "disabled"

    def __init__(self, reason: str = "provider_disabled") -> None:
        self._reason = reason

    def available(self) -> bool:
        return False

    def abstention_reason(self) -> str | None:
        return self._reason


class ProductionModelProvider(SemanticClassifierProvider):
    """External model provider. Only constructed when credentials are present."""

    def __init__(self, endpoint: str, api_key: str, *, multilingual: bool = False) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self.name = (
            "multilingual-semantic-model@1.0.0"
            if multilingual
            else "production-semantic-model@1.0.0"
        )

    def available(self) -> bool:
        return bool(self._endpoint and self._api_key)


def get_classifier_provider(
    settings, tenant_id: str | None = None
) -> SemanticClassifierProvider:
    """Resolve the configured provider, failing closed without credentials.

    Canary routing: a tenant listed in ``semantic.canary_tenants`` resolves the
    candidate (production) provider instead of the primary — with exactly the
    same fail-closed behavior, so a credential-less canary abstains via
    :class:`DisabledProvider` rather than degrading to keywords. Every other
    tenant (and any call without a tenant) keeps the primary provider.
    """
    semantic = getattr(settings, "semantic", None)
    if tenant_id is not None and tenant_id in (getattr(semantic, "canary_tenants", None) or []):
        return _resolve_mode("production")
    return _resolve_mode((getattr(semantic, "classifier_provider", "") or "").lower())


def get_shadow_provider(settings) -> SemanticClassifierProvider | None:
    """Resolve the shadow-mode candidate provider, or None when shadow is off.

    ``semantic.shadow_provider`` names a provider mode ('' = off). The candidate
    resolves through the same fail-closed ladder as the primary; a candidate
    without credentials resolves to :class:`DisabledProvider` (it abstains in
    the comparison — it never fabricates a shadow classification).
    """
    mode = (getattr(getattr(settings, "semantic", None), "shadow_provider", "") or "").lower()
    if not mode:
        return None
    return _resolve_mode(mode)


def _resolve_mode(mode: str) -> SemanticClassifierProvider:
    """Shared fail-closed mode ladder for primary, canary and shadow resolution."""
    if mode in ("", "deterministic"):
        return DeterministicClassifierProvider()
    if mode == "disabled":
        return DisabledProvider("provider_disabled_by_config")
    if mode in ("production", "multilingual"):
        endpoint = os.getenv("SEMANTIC_MODEL_ENDPOINT", "")
        api_key = os.getenv("SEMANTIC_MODEL_API_KEY", "")
        if not (endpoint and api_key):
            # FAIL CLOSED — never silently degrade a production request to keywords.
            return DisabledProvider("provider_disabled_missing_credentials")
        return ProductionModelProvider(endpoint, api_key, multilingual=(mode == "multilingual"))
    return DisabledProvider(f"provider_disabled_unknown_mode:{mode}")
