"""SdkIngressAdapter — the SDK family adapter (WS-B1, the first converged family).

Maps an accepted, validated SDK event (the flat normalized payload produced by
``services/ingestion/validation.build_normalized_payload``, plus the temporal
envelope stamp) to a :class:`UniversalObservationEnvelope`. It is the canonical
identity for the family that ``/v1/batch`` routes through when the WS-A5
envelope flag is ON; the low-level mapping
(``services/ingestion/observation_envelope.build_sdk_observation_envelope``)
stays as the delegate so the two can never drift.

Credential class: ``PUBLIC_CLIENT`` — the blueprint's "Public SDK credential"
(§11), a publishable browser/mobile SDK credential scoped to
``observation:write`` + ``config:read`` and never to graph/identity/export/
admin/billing. The gateway stamps it (with the adapter identity) as the
envelope's provenance / trust basis.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from shared.observation.envelope import UniversalObservationEnvelope

from services.ingestion.adapters.base import UniversalIngressAdapter
from services.ingestion.observation_envelope import (
    build_sdk_observation_envelope as _build_sdk_observation_envelope,
)

DEFAULT_SDK_INGRESS_PATH = "/v1/batch"


class SdkIngressAdapter(UniversalIngressAdapter):
    """SDK-family adapter: validated Envelope-A SDK event -> Envelope B."""

    adapter_id = "sdk"
    family = "sdk"
    credential_class = "PUBLIC_CLIENT"
    adapter_version = "1.0.0"
    description = (
        "Browser/mobile SDK (Web, iOS, Android, React Native) via /v1/batch. "
        "Public SDK credential scoped observation:write + config:read (blueprint "
        "§11). Maps the validated flat normalized payload to a "
        "UniversalObservationEnvelope; the universal ingestion gateway stamps "
        "credential/source-trust provenance."
    )

    def build_observation_envelope(
        self,
        normalized: Mapping[str, Any],
        *,
        ingress_path: Optional[str] = None,
    ) -> Optional[UniversalObservationEnvelope]:
        """Delegate to the canonical SDK mapping (single implementation)."""
        return _build_sdk_observation_envelope(
            normalized,
            ingress_path=ingress_path or DEFAULT_SDK_INGRESS_PATH,
        )
