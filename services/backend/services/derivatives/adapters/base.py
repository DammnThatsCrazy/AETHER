"""Read-only derivatives venue adapter contract.

An adapter observes one venue (or one venue family). It never places,
amends, or cancels anything; validate_config refuses any credential whose
authority exceeds read_only. Implementation status must be honest — an
adapter without live provider validation may never claim PROVIDER_LIVE.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.foundation import require_read_only_authority


class DerivativesAdapter(ABC):
    adapter_id: str = ""
    display_name: str = ""
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLDED
    capabilities: tuple[str, ...] = ()
    supported_instrument_types: tuple[str, ...] = ()
    authentication_model: str = "api_key_read_only"
    known_limitations: str = ""

    def descriptor(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "display_name": self.display_name,
            "implementation_status": self.implementation_status.value
            if hasattr(self.implementation_status, "value") else str(self.implementation_status),
            "capabilities": list(self.capabilities),
            "supported_instrument_types": list(self.supported_instrument_types),
            "authentication_model": self.authentication_model,
            "known_limitations": self.known_limitations,
            "execution_by_aether": False,
        }

    def validate_config(self, config: dict[str, Any]) -> None:
        """Refuse anything beyond read-only credential authority."""
        require_read_only_authority(config.get("authority_type", "read_only"))

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Read-only connectivity probe. Never mutates provider state."""

    @abstractmethod
    async def pull_events(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Pull canonical observation events from the venue.

        Returns (events, new_checkpoint). Must be idempotent per checkpoint:
        the same checkpoint always yields the same events. Checkpoints must
        advance monotonically.
        """
