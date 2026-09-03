"""temporal360 — the contextual time projection (context-360 program, Phase 2).

Converges the ``temporal360`` registry row to ``implemented``: workstream T2.1
built the :mod:`~services.temporal360.history_replay` knowledge-time authority
(resolving the row's ``graph_history_replay`` pending authority), and T2.2/T2.3
ship the projection provider (:mod:`~services.temporal360.provider`) plus its
surface. A 360 is an intelligence projection over canonical Aether truth —
never a competing system of record (ADR-010); temporal360 is a pure read over
the graph's bitemporal truth.
"""

from __future__ import annotations

from services.temporal360.history_replay import (
    GraphHistoryReplay,
    KnownState,
    SubjectEvent,
    SubjectHistory,
)
from services.temporal360.provider import (
    LedgerTemporalReader,
    OUTPUT_SECTIONS,
    SUPPORTED_TEMPORAL_MODES,
    Temporal360Provider,
    TemporalReader,
    register_provider,
)

__all__ = [
    "GraphHistoryReplay",
    "KnownState",
    "LedgerTemporalReader",
    "OUTPUT_SECTIONS",
    "SUPPORTED_TEMPORAL_MODES",
    "SubjectEvent",
    "SubjectHistory",
    "Temporal360Provider",
    "TemporalReader",
    "register_provider",
]
