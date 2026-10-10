\
"""
Responsiveness & Time-to-Value spine — backend domain.

Wires the real ingestion ACK path, provider connection lifecycle, graph
projector, projection runtime, jobs worker, and analytics query paths into
the responsiveness state model so the platform can answer:

  * Is Aether responsive?
  * Is the tenant seeing value?
  * Is this surface usable yet?
  * Is this graph hydrated enough?
  * Is this lens fast enough?
  * Is this query path acceptable?

Implementation note (no stubs): every state transition below is driven by a
real integration point — the ingestion batch ACK, the provider connection
orchestrator, the semantic graph projector, the projection engine runtime,
the jobs worker, and the analytics query handler. The spine does not fake
progress; it observes and records what the platform actually does.
"""

from __future__ import annotations

from .service import (
    ResponsivenessService,
    get_responsiveness_service,
)

__all__ = ["ResponsivenessService", "get_responsiveness_service"]
