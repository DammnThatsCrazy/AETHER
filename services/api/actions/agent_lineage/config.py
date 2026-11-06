"""Engine configuration. Budgets bound what is processed/returned, never what is known."""
from __future__ import annotations

from dataclasses import dataclass

from shared.agent_lineage import vocabulary as vocab

PROJECTION_VERSION = "1.0.0"


@dataclass(frozen=True)
class LineageConfig:
    #: Deepest delegation level processed. Must cover the durable minimum; levels
    #: beyond it are reported as ``depth_limited`` and the summary is truncated.
    max_depth: int = 64
    #: A node is ``active`` when it was seen within this window of the evidence ``as_of``.
    active_window_seconds: float = 3600.0
    #: Probabilistic (infrastructure-correlated) attribution gates.
    prob_min_linked: int = 3
    prob_min_share: float = 0.8
    #: Cluster emission bounds.
    min_cluster_size: int = 5
    max_clusters_per_principal: int = 200
    swarm_bucket_seconds: float = 60.0
    sample_ids: int = 5
    evidence_ref_sample: int = 8
    #: Restatement log keeps per-row entries up to this many; the rest is counted.
    restatement_row_log_cap: int = 1000

    def __post_init__(self) -> None:
        if self.max_depth < vocab.MIN_DURABLE_DELEGATION_DEPTH:
            raise ValueError(
                f"max_depth must be >= {vocab.MIN_DURABLE_DELEGATION_DEPTH} "
                "(minimum durable delegation depth)"
            )
        if not 0.5 < self.prob_min_share <= 1.0:
            raise ValueError("prob_min_share must be in (0.5, 1.0]")


DEFAULT_CONFIG = LineageConfig()
