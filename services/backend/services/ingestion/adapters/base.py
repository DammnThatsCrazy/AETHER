"""UniversalIngressAdapter — the contract every ingress adapter implements.

WS-B1. An adapter sits at the "after adapters" boundary of Invariant #1: every
ingress family (sdk / webhook / connector / feed / import / harness / replay)
turns the record its path holds into a
:class:`~shared.observation.envelope.UniversalObservationEnvelope` (Envelope B),
and the universal ingestion gateway validates + stamps what adapters produce.

The adapter declares its own provenance up front as class attributes:

* ``adapter_id`` — the concrete adapter implementation identity (stamped into
  ``provenance.adapter``).
* ``family`` — the Envelope-B ``source_type`` vocabulary member this adapter
  belongs to (the registry is keyed by family).
* ``credential_class`` — the Envelope-B credential-class vocabulary member the
  adapter's ingress credential carries (the gateway stamps it into
  ``provenance.credential_class`` as the trust basis).
* ``adapter_version`` — the adapter implementation version.

Scope boundary (deliberate, per the Envelope-B module docstring): building an
envelope is the adapter's only job. Consent/privacy policy, idempotency,
sequencing, source-trust evaluation and durability ordering are the gateway's —
so the same trust/privacy spine applies to every family instead of each path
re-deciding it. A misconfigured concrete adapter (unknown family / credential
class / missing adapter_id) fails loudly at import time.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping, Optional

from shared.observation.envelope import (
    CREDENTIAL_CLASSES,
    SOURCE_TYPES,
    UniversalObservationEnvelope,
)


def _validate_concrete(cls: type["UniversalIngressAdapter"]) -> None:
    """Fail-fast checks for concrete (non-abstract) adapter classes.

    Runs at class-creation time so a typo'd family or credential class can
    never register silently and then drift at runtime.
    """
    family = cls.family
    if family not in SOURCE_TYPES:
        raise ValueError(
            f"{cls.__name__}.family {family!r} not in the Envelope-B source_type "
            f"vocabulary: {sorted(SOURCE_TYPES)}"
        )
    credential = cls.credential_class
    if credential not in CREDENTIAL_CLASSES:
        raise ValueError(
            f"{cls.__name__}.credential_class {credential!r} not in the Envelope-B "
            f"credential-class vocabulary: {sorted(CREDENTIAL_CLASSES)}"
        )
    if not getattr(cls, "adapter_id", None):
        raise ValueError(f"{cls.__name__} must declare a non-empty adapter_id")
    if not getattr(cls, "description", None):
        raise ValueError(f"{cls.__name__} must declare a non-empty description")


class UniversalIngressAdapter(ABC):
    """Base class for universal ingress adapters (WS-B1).

    Concrete subclasses declare ``adapter_id`` / ``family`` / ``credential_class``
    / ``adapter_version`` / ``description`` and implement
    :meth:`build_observation_envelope`.
    """

    adapter_id: ClassVar[str] = ""
    family: ClassVar[str] = ""
    credential_class: ClassVar[str] = ""
    adapter_version: ClassVar[str] = "1.0.0"
    description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            _validate_concrete(cls)

    @abstractmethod
    def build_observation_envelope(
        self,
        normalized: Mapping[str, Any],
        *,
        ingress_path: Optional[str] = None,
    ) -> Optional[UniversalObservationEnvelope]:
        """Build the canonical Envelope-B observation for this family.

        ``normalized`` is the record the path already holds (for the SDK family,
        the validated flat normalized payload produced by
        ``services/ingestion/validation.build_normalized_payload``).

        Returns None (not raise) when the record cannot supply the envelope's
        required core — callers degrade to the flat path with a warning so the
        adapter can never take its ingress path down.
        """
        raise NotImplementedError
