"""
Aether Security — Query Pattern Detector

Detects suspicious query patterns that indicate model extraction attempts:
  - Systematic input sweeps (one feature varies, rest constant)
  - Adversarial probing (queries near decision boundaries)
  - High-entropy uniform sampling (random probing of input space)
  - Timing regularity (bot-like fixed-interval queries)

Operates on a per-client sliding window of recent queries.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

import numpy as np

from .config import PatternDetectorConfig

logger = logging.getLogger("aether.security.pattern_detector")


@dataclass
class PatternAnalysis:
    """Result of query pattern analysis for a single client."""

    # Individual signal scores (0.0 = benign, 1.0 = highly suspicious)
    sweep_score: float = 0.0
    similarity_score: float = 0.0
    entropy_score: float = 0.0
    timing_score: float = 0.0

    # Aggregate anomaly score
    anomaly_score: float = 0.0

    # Human-readable flags
    flags: list[str] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return self.anomaly_score > 0.5


@dataclass
class QueryRecord:
    """A single recorded query for pattern analysis."""

    timestamp: float
    feature_vector: np.ndarray
    model_name: str
    api_key: str


class QueryPatternDetector:
    """
    Maintains a sliding window of recent queries per client and computes
    anomaly scores for extraction-like behavior.
    """

    def __init__(self, config: Optional[PatternDetectorConfig] = None):
        self.config = config or PatternDetectorConfig()
        # api_key -> deque of QueryRecord
        self._history: dict[str, deque[QueryRecord]] = defaultdict(
            lambda: deque(maxlen=500)
        )
        self._lock = Lock()

    def record_query(
        self,
        api_key: str,
        features: dict[str, float],
        model_name: str,
    ) -> None:
        """Record a query for later pattern analysis."""
        vec = self._dict_to_vector(features)
        record = QueryRecord(
            timestamp=time.time(),
            feature_vector=vec,
            model_name=model_name,
            api_key=api_key,
        )
        with self._lock:
            self._history[api_key].append(record)

    def analyze(self, api_key: str) -> PatternAnalysis:
        """
        Analyze the recent query history for a client.
        Returns a PatternAnalysis with per-signal scores and an aggregate.
        """
        with self._lock:
            records = list(self._history.get(api_key, []))

        # Filter to analysis window
        cutoff = time.time() - self.config.analysis_window_seconds
        recent = [r for r in records if r.timestamp >= cutoff]

        if len(recent) < self.config.min_queries_for_analysis:
            return PatternAnalysis()

        analysis = PatternAnalysis()

        # 1. Sweep detection
        analysis.sweep_score = self._detect_sweeps(recent)
        if analysis.sweep_score > 0.7:
            analysis.flags.append("systematic_feature_sweep")

        # 2. Input similarity clustering
        analysis.similarity_score = self._detect_similarity_clustering(recent)
        if analysis.similarity_score > 0.7:
            analysis.flags.append("high_input_similarity")

        # 3. Entropy / uniformity analysis
        analysis.entropy_score = self._detect_entropy_probing(recent)
        if analysis.entropy_score > 0.7:
            analysis.flags.append("uniform_random_probing")

        # 4. Timing regularity
        analysis.timing_score = self._detect_timing_regularity(recent)
        if analysis.timing_score > 0.7:
            analysis.flags.append("bot_like_timing")

        # Aggregate with max-weighted mean
        scores = [
            analysis.sweep_score,
            analysis.similarity_score,
            analysis.entropy_score,
            analysis.timing_score,
        ]
        analysis.anomaly_score = 0.4 * max(scores) + 0.6 * (sum(scores) / len(scores))

        if analysis.is_suspicious:
            logger.warning(
                "Suspicious query pattern for %s: score=%.3f flags=%s",
                api_key[:8] + "...",
                analysis.anomaly_score,
                analysis.flags,
            )

        return analysis

    # ------------------------------------------------------------------
    # Signal detectors
    # ------------------------------------------------------------------

    def _detect_sweeps(self, records: list[QueryRecord]) -> float:
        """
        Detect systematic feature sweeps where only 1-2 features vary
        while the rest stay constant.
        """
        if len(records) < 5:
            return 0.0

        vectors = np.array([r.feature_vector for r in records])
        if vectors.shape[1] < 2:
            return 0.0

        # Compute per-feature variance
        variances = np.var(vectors, axis=0)
        total_var = np.sum(variances)
        if total_var < 1e-10:
            return 0.0  # All identical queries — not a sweep

        # Sort variances descending
        sorted_var = np.sort(variances)[::-1]
        top2_var = sorted_var[0] + (sorted_var[1] if len(sorted_var) > 1 else 0)
        concentration = top2_var / total_var

        if concentration > self.config.sweep_variance_ratio:
            return min(1.0, concentration)
        return concentration * 0.5

    def _detect_similarity_clustering(self, records: list[QueryRecord]) -> float:
        """
        Detect when a high fraction of queries are very similar to each other
        (probing near a decision boundary).
        """
        if len(records) < 5:
            return 0.0

        vectors = np.array([r.feature_vector for r in records])

        # Compute pairwise cosine similarities for a sample
        n = min(len(vectors), 50)
        sample = vectors[:n]

        # Normalize
        norms = np.linalg.norm(sample, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normalized = sample / norms

        # Cosine similarity matrix
        sim_matrix = normalized @ normalized.T

        # Count pairs above threshold (excluding diagonal)
        mask = np.triu(np.ones_like(sim_matrix, dtype=bool), k=1)
        high_sim_count = np.sum(sim_matrix[mask] > self.config.similarity_threshold)
        total_pairs = np.sum(mask)

        if total_pairs == 0:
            return 0.0

        ratio = high_sim_count / total_pairs
        if ratio > self.config.similarity_ratio_alert:
            return min(1.0, ratio / self.config.similarity_ratio_alert)
        return ratio * 0.3

    def _detect_entropy_probing(self, records: list[QueryRecord]) -> float:
        """
        Detect near-uniform random sampling of the input space,
        which indicates systematic exploration.
        """
        if len(records) < 10:
            return 0.0

        vectors = np.array([r.feature_vector for r in records])

        # For each feature, compute normalized histogram entropy
        n_features = vectors.shape[1]
        uniformity_scores = []

        n_bins = min(20, max(5, len(records) // 5))

        for col in range(min(n_features, 20)):
            feature_vals = vectors[:, col]
            val_range = np.ptp(feature_vals)
            if val_range < 1e-10:
                continue

            counts, _ = np.histogram(feature_vals, bins=n_bins)
            counts = counts + 1e-10  # avoid log(0)
            probs = counts / counts.sum()

            entropy = -np.sum(probs * np.log2(probs))
            max_entropy = np.log2(n_bins)

            uniformity = entropy / max_entropy if max_entropy > 0 else 0
            uniformity_scores.append(uniformity)

        if not uniformity_scores:
            return 0.0

        avg_uniformity = np.mean(uniformity_scores)

        if avg_uniformity > self.config.entropy_uniformity_threshold:
            return min(1.0, avg_uniformity)
        return avg_uniformity * 0.3

    def _detect_timing_regularity(self, records: list[QueryRecord]) -> float:
        """
        Detect bot-like timing: queries at near-constant intervals.
        Human users have high variance in inter-query timing; bots don't.
        """
        if len(records) < 5:
            return 0.0

        timestamps = [r.timestamp for r in records]
        intervals = np.diff(timestamps)

        if len(intervals) < 3:
            return 0.0

        mean_interval = np.mean(intervals)
        if mean_interval < 1e-6:
            return 0.8  # Burst of queries at near-zero interval

        std_interval = np.std(intervals)
        cv = std_interval / mean_interval  # coefficient of variation

        # Low CV → regular timing → suspicious
        regularity = max(0.0, 1.0 - cv)

        if regularity > self.config.timing_regularity_threshold:
            return min(1.0, regularity)
        return regularity * 0.3

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_vector(features: dict[str, float]) -> np.ndarray:
        """Convert a feature dict to a sorted numpy vector."""
        sorted_keys = sorted(features.keys())
        return np.array([float(features.get(k, 0.0)) for k in sorted_keys])

    def get_client_query_count(self, api_key: str) -> int:
        """Return total recorded queries for a client."""
        with self._lock:
            return len(self._history.get(api_key, []))

    def cleanup_expired(self) -> int:
        """Remove query records older than the analysis window. Returns count removed."""
        cutoff = time.time() - self.config.analysis_window_seconds * 2
        removed = 0
        with self._lock:
            for key in list(self._history.keys()):
                dq = self._history[key]
                before = len(dq)
                while dq and dq[0].timestamp < cutoff:
                    dq.popleft()
                removed += before - len(dq)
                if not dq:
                    del self._history[key]
        return removed
