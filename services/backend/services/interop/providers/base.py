"""Protocol-neutral interoperability provider adapter contract.

An adapter observes one protocol deployment family. It never relays,
routes, retries, or recovers messages; its output is canonical observation
dicts consumed by the correlation engine. Implementation status must be
honest — no adapter may claim PROVIDER_LIVE without live provider
validation evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus


class InteropProviderAdapter(ABC):
    provider_id: str = ""
    provider_kind: str = "unknown"
    display_name: str = ""
    protocol_products: tuple[str, ...] = ("messaging",)
    supported_versions: tuple[str, ...] = ()
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLDED
    capabilities: tuple[str, ...] = ()
    known_limitations: str = ""

    def descriptor(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "display_name": self.display_name,
            "protocol_products": list(self.protocol_products),
            "supported_versions": list(self.supported_versions),
            "implementation_status": self.implementation_status.value
            if hasattr(self.implementation_status, "value") else str(self.implementation_status),
            "capabilities": list(self.capabilities),
            "known_limitations": self.known_limitations,
            "execution_by_aether": False,
        }

    @abstractmethod
    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Scan for new observations from the last checkpoint.

        Returns (observations, new_checkpoint). Observations are canonical
        phase dicts: {correlation_key, phase, endpoint_ref, observed_at, ...}.
        Checkpoints advance monotonically; re-scanning the same checkpoint
        must be idempotent.
        """

    @abstractmethod
    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Decode one raw provider log into a canonical observation dict, or
        None when the log is not a protocol event this adapter understands."""

    def derive_path(self, observation: dict[str, Any]) -> str:
        source = observation.get("source_network_id", "unknown")
        destination = observation.get("destination_network_id", "unknown")
        return f"{self.provider_id}:{source}->{destination}"

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.provider_id}: security policy snapshots require provider "
            "credentials/RPC access (credential-gated)"
        )
