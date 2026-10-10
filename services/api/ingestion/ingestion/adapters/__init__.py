"""Universal ingress adapters (WS-B1) — the "after adapters" boundary.

Each of the seven ingress families (sdk / webhook / connector / feed / import /
harness / replay — the Envelope-B ``source_type`` vocabulary) is realized by
adapter classes that turn a path's normalized/source record into a
:class:`~shared.observation.envelope.UniversalObservationEnvelope` (Envelope B,
Invariant #1: one observation model after adapters). Adapters *build* envelopes
from evidence the path already holds; they never decide consent, idempotency,
or source trust — the universal ingestion gateway
(``services/api/ingestion/ingestion/gateway.py``) owns those so one trust/privacy spine
applies to every family.

Public surface: the :class:`UniversalIngressAdapter` contract in ``base.py``,
the family registry + lookup helpers in ``registry.py``, and the concrete
adapter classes (``sdk.py`` …) as families converge.
"""

from __future__ import annotations

from ingestion.ingestion.adapters.base import UniversalIngressAdapter
from ingestion.ingestion.adapters.registry import (
    FAMILY_SPECS,
    IngressAdapterFamilySpec,
    REGISTERED_ADAPTERS,
    get_adapter,
    get_family_spec,
    registered_families,
)
from ingestion.ingestion.adapters.sdk import SdkIngressAdapter

__all__ = [
    "FAMILY_SPECS",
    "IngressAdapterFamilySpec",
    "REGISTERED_ADAPTERS",
    "SdkIngressAdapter",
    "UniversalIngressAdapter",
    "get_adapter",
    "get_family_spec",
    "registered_families",
]
