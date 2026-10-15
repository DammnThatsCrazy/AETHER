"""WS-D correlation observation seam (item 6 / Invariant #12).

Correlation is first-class when it is REGISTERED, not merely carried on one
row. :func:`register_correlation_from_observation` folds one normalized
observation record (Envelope-B ``model_dump()`` shape) into the durable
:class:`~shared.backend_interpretation.stores.CorrelationRegistry` family for
its ``correlation_id``, accumulating the observation id, an evidence ref and
the causation/source context.

Written ONLY when ``correlation_first_class_enabled`` is ON; the registry
(:class:`CorrelationRegistry`) is inert otherwise. The function is safe to call
when the observation has no correlation block (returns ``None``).
"""

from __future__ import annotations

from typing import Any, Optional

from shared.backend_interpretation.flags import correlation_first_class_enabled
from shared.backend_interpretation.stores import CorrelationRegistry


async def register_correlation_from_observation(
    tenant_id: str,
    record: dict[str, Any],
    registry: Optional[CorrelationRegistry] = None,
) -> Optional[dict[str, Any]]:
    """Register one observation's correlation family (flag-gated).

    Returns the merged registry row when a correlation family was registered,
    ``None`` when the flag is OFF or the record carries no correlation id.
    """
    if not correlation_first_class_enabled():
        return None
    correlation = record.get("correlation")
    if not isinstance(correlation, dict):
        return None
    correlation_id = correlation.get("correlation_id") or correlation.get(
        "causation_id"
    )
    if not isinstance(correlation_id, str) or not correlation_id:
        return None
    causation_id = correlation.get("causation_id")
    event_block = record.get("event") if isinstance(record.get("event"), dict) else {}
    observation_id = event_block.get("id") or record.get("event_id")
    source_block = record.get("source") if isinstance(record.get("source"), dict) else {}
    source = source_block.get("type") or record.get("source_type")

    evidence_ref: Optional[dict[str, Any]] = None
    if observation_id:
        evidence_ref = {
            "id": str(observation_id),
            "type": "event",
            "source": source or "sdk",
        }
    store = registry or CorrelationRegistry()
    return await store.register(
        tenant_id=tenant_id,
        correlation_id=str(correlation_id),
        observation_id=str(observation_id) if observation_id else None,
        evidence_ref=evidence_ref,
        causation_id=causation_id,
        source=source,
    )


__all__ = ["register_correlation_from_observation"]
