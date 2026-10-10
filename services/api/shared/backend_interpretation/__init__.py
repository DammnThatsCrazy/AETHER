"""WS-D — Backend-interpretation shared primitives and mechanisms.

The SDK + Universal Ingestion Alignment blueprint's *backend-interpretation*
slice (canonical typed relationships with evidence lineage, an episode engine,
a durable outcome truth store, Section-25 evidence dedupe, Silver-boundary
temporal envelopes, first-class correlation, exact-decimal Silver money, and
derived-truth mutation governance).

Every behavior-changing mechanism in this package is gated behind a NEW
default-OFF settings flag (see ``config/settings.py``
``BackendInterpretationConfig`` and
``docs/architecture/BACKEND_INTERPRETATION_WS_D.md``). With all flags OFF the
package is inert: none of these helpers are reachable from any production
ingestion / Silver / graph path, so runtime parity is preserved.

Modules:

* ``primitives`` — typed :class:`RelationshipFact`, :class:`EpisodeRecord` and
  :class:`OutcomeTruthRecord` carriers (reusing canonical
  :class:`EvidenceRef` / :class:`EntityRef` / :class:`CorrelationBlock`).
* ``dedupe`` — Section-25 evidence dedupe (one canonical outcome, many
  evidence refs).
* ``stores`` — durable truth stores for the primitive carriers, backed by
  ``shared.store.get_store`` (Redis/in-memory, same seam as
  ``ai_execution_facts``).
* ``governance`` — derived-truth mutation-gateway governance helpers that ride
  ``AETHER_MUTATION_GATEWAY_MODE``.

``flags`` lives at package import (function-local ``get_settings()`` reads so
this cross-cutting package never drags the full settings graph into a service
that only touches one primitive).
"""

from __future__ import annotations

from shared.backend_interpretation.primitives import (
    EpisodeRecord,
    OutcomeTruthRecord,
    RelationshipFact,
    ValidityWindow,
)

__all__ = [
    "EpisodeRecord",
    "OutcomeTruthRecord",
    "RelationshipFact",
    "ValidityWindow",
]
