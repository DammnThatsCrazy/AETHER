"""Provider-record -> AetherEvent normalization.

:class:`EventNormalizer` is the deterministic, network-free translation seam:
it takes ONE :class:`RawProviderRecord` and returns a :class:`NormalizationResult`
containing zero or more provider-neutral :class:`AetherEvent`\ s.

Determinism is a hard contract here — a normalizer must never depend on
wall-clock time, randomness, or provider I/O, so the same raw record always
yields the same events (idempotent re-normalization for replay/debug). In
particular, a normalizer MUST set ``AetherEvent.event_id`` deterministically
(the envelope's default is a random ``uuid4().hex`` — see :mod:`.events`), for
example from ``raw.idempotency_key``, so the full output is byte-identical
across replays. Anything a normalizer cannot translate must be surfaced
explicitly via ``dropped`` (with enough detail to audit, e.g.
``"<record_id>:<provider_record_type>"``) rather than silently skipped.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.integration_contracts.events import AetherEvent, RawProviderRecord


class NormalizationResult(BaseModel):
    """The outcome of normalizing one raw provider record.

    ``dropped`` carries ids-or-short-reasons for anything that could not be
    normalized — never silent. A convention is ``f"{record_id}:{provider_record_type}"``
    so an operator can trace a drop back to the offending record.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[AetherEvent] = Field(default_factory=list)
    skipped: int = 0
    dropped: list[str] = Field(default_factory=list)
    normalizer_version: str = "1"


class EventNormalizer(Protocol):
    """Deterministic, synchronous translation of a raw record into events."""

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult: ...


__all__ = [
    "EventNormalizer",
    "NormalizationResult",
]
