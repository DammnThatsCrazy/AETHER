"""Ingress adapter registry — the canonical map from Envelope-B ``source_type``
family to its adapter(s) and allowed credential classes (WS-B1).

Declares all seven ingress families (the Envelope-B ``source_type`` vocabulary)
with, for each: the blueprint adapter name (the diagram's SDKAdapter /
APIAdapter / …), a description, the credential class(es) that family's ingress
credential may carry (blueprint §11), and — once built — the registered adapter
class. The registry is the single dispatch point the universal ingestion
gateway and the WS-B2..B5 convergence use: a family has a *declared* spec from
day one and a *registered* adapter once its path converges.

Naming reconciliation (recorded here for the registry table and parity test):
the blueprint diagram and TARGET_ARCHITECTURE call the seventh source family
"feed" (Envelope-B ``source_type``) with blueprint adapter name ``APIAdapter``
/ "API-feed" — one concept, one ``source_type``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Type

from shared.observation.envelope import (
    CREDENTIAL_CLASSES,
    SOURCE_TYPES,
    _require_member,
)

from services.ingestion.adapters.base import UniversalIngressAdapter

# Blueprint adapter names (diagram, lines 92-102) per family — a family's spec
# must map onto one of these so the §11 credential authority stays legible.
_BLUEPRINT_ADAPTER_NAMES = {
    "sdk": "SDKAdapter",
    "webhook": "WebhookAdapter",
    "connector": "ConnectorAdapter",
    "feed": "APIAdapter (API-feed)",
    "import": "ImportAdapter",
    "harness": "HarnessAdapter",
    "replay": "ReplayAdapter",
}

# Blueprint §11 credential authority per family. sdk = PUBLIC_CLIENT (the
# "Public SDK credential", observation:write + config:read only); webhook =
# VERIFIED_WEBHOOK; connector = MANAGED_CONNECTOR; feed/import = TENANT_SERVER
# (the "Trusted server API") or AETHER_INTERNAL; harness = AETHER_INTERNAL
# (agent execution is an internal observation); replay = OPERATOR_REPLAY.
_FAMILY_CREDENTIAL_CLASSES = {
    "sdk": ("PUBLIC_CLIENT",),
    "webhook": ("VERIFIED_WEBHOOK",),
    "connector": ("MANAGED_CONNECTOR",),
    "feed": ("TENANT_SERVER", "AETHER_INTERNAL"),
    "import": ("TENANT_SERVER", "AETHER_INTERNAL"),
    "harness": ("AETHER_INTERNAL",),
    "replay": ("OPERATOR_REPLAY",),
}

_FAMILY_DESCRIPTIONS = {
    "sdk": "Browser/mobile SDK (Web, iOS, Android, React Native) via /v1/batch.",
    "webhook": "Provider / public / auth webhooks (provider_runtime, comms, connectors).",
    "connector": "Managed connector pulls + webhooks under an adapter identity (§11).",
    "feed": "Server API feed (API-feed; /v1/ingest/feed, DUNE feeder, external feeds).",
    "import": "Bulk tenant import (services/imports) — analyze/map/validate/commit.",
    "harness": "Agent execution harness / model-runtime observation paths.",
    "replay": "Ingestion-level replay with original-time preservation (Invariant #15).",
}


@dataclass(frozen=True)
class IngressAdapterFamilySpec:
    """Declarative spec for one ingress family (canonical, code-bound).

    ``adapter_class`` is set once the family's adapter ships (see
    ``REGISTERED_ADAPTERS``); until then the family is *declared* with a
    non-empty ``status`` naming the convergence slice.
    """

    source_type: str
    blueprint_adapter: str
    description: str
    allowed_credential_classes: tuple[str, ...]
    adapter_class: Optional[Type[UniversalIngressAdapter]] = None
    status: str = "declared — adapter convergence in WS-B2..WS-B5"

    def __post_init__(self) -> None:
        _require_member(self.source_type, SOURCE_TYPES, "source_type")
        if not self.allowed_credential_classes:
            raise ValueError(f"{self.source_type}: no allowed credential classes declared")
        for cc in self.allowed_credential_classes:
            _require_member(cc, CREDENTIAL_CLASSES, "allowed_credential_classes")


# ── Registry ──────────────────────────────────────────────────────────────────

# Concrete adapters register here by family. Imported once at module load so the
# registry is the single dispatch point (and so a misconfigured adapter fails at
# import time, not first use).
from services.ingestion.adapters.sdk import SdkIngressAdapter  # noqa: E402
from services.ingestion.adapters.replay import ReplayIngressAdapter  # noqa: E402

REGISTERED_ADAPTERS: dict[str, Type[UniversalIngressAdapter]] = {
    "sdk": SdkIngressAdapter,
    "replay": ReplayIngressAdapter,
}

_IMPLEMENTED_STATUS = {
    "sdk": "implemented — SdkIngressAdapter (WS-B1); public SDK credential, "
    "observation:write + config:read",
    "replay": "implemented — ReplayIngressAdapter (WS-B4); OPERATOR_REPLAY "
    "credential, original-time preservation (Invariant #15)",
}

# Family specs in canonical Envelope-B SOURCE_TYPES order.
FAMILY_SPECS: tuple[IngressAdapterFamilySpec, ...] = tuple(
    IngressAdapterFamilySpec(
        source_type=st,
        blueprint_adapter=_BLUEPRINT_ADAPTER_NAMES[st],
        description=_FAMILY_DESCRIPTIONS[st],
        allowed_credential_classes=_FAMILY_CREDENTIAL_CLASSES[st],
        adapter_class=REGISTERED_ADAPTERS.get(st),
        status=_IMPLEMENTED_STATUS.get(
            st, "declared — adapter convergence in WS-B2..WS-B5"
        ),
    )
    for st in SOURCE_TYPES
)


def get_family_spec(source_type: str) -> IngressAdapterFamilySpec:
    """Return the canonical spec for an ingress family (Envelope-B vocabulary)."""
    for spec in FAMILY_SPECS:
        if spec.source_type == source_type:
            return spec
    raise ValueError(
        f"unknown ingress family {source_type!r}; expected one of {sorted(SOURCE_TYPES)}"
    )


def get_adapter(source_type: str) -> Optional[Type[UniversalIngressAdapter]]:
    """Return the registered adapter class for a family, or None if not converged.

    None means the family is *declared* but its path has not yet been routed
    through Envelope B (WS-B2..WS-B5) — never a silent fallback target.
    """
    return REGISTERED_ADAPTERS.get(source_type)


def registered_families() -> tuple[str, ...]:
    """Ingress families that have a registered adapter today (converged)."""
    return tuple(spec.source_type for spec in FAMILY_SPECS if spec.adapter_class is not None)


# ── Import-time invariants (fail fast, never drift) ─────────────────────────

# Every Envelope-B source_type must have exactly one spec (loop above) and every
# registered adapter's family must be one of them, with a matching credential
# class and a resolved blueprint adapter name.
assert set(FAMILY_SPECS[i].source_type for i in range(len(FAMILY_SPECS))) == set(SOURCE_TYPES)
for _st, _adapter in REGISTERED_ADAPTERS.items():
    assert _st in SOURCE_TYPES, f"registered adapter family {_st!r} not in SOURCE_TYPES"
    assert _adapter.family == _st
    assert _adapter.credential_class in _FAMILY_CREDENTIAL_CLASSES[_st], (
        f"{_adapter.__name__} credential {_adapter.credential_class!r} not allowed for "
        f"family {_st!r}: {_FAMILY_CREDENTIAL_CLASSES[_st]}"
    )

# Guard against accidental re-definition drift below this point.
_BLUEPRINT_ADAPTER_NAMES = dict(_BLUEPRINT_ADAPTER_NAMES)  # type: ignore[assignment]
_FAMILY_CREDENTIAL_CLASSES = dict(_FAMILY_CREDENTIAL_CLASSES)  # type: ignore[assignment]
