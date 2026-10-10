"""
Aether Security — Canary Input Detector

Generates hidden probe inputs ("canaries") that should never occur in
legitimate traffic. If a canary input is observed, it strongly indicates
automated scraping or systematic input-space exploration.

Canary design:
  - Generated from a secret seed → only Aether knows the canary set
  - Feature vectors have specific "impossible" or rare patterns
    (e.g., contradictory feature combinations, out-of-distribution values)
  - Matching uses L2 distance with a configurable tolerance
  - On detection: throttle, block, or alert

The canary set is regenerated at startup from the secret seed,
ensuring consistency across restarts.
"""

from __future__ import annotations

import collections
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .config import CanaryConfig

logger = logging.getLogger("aether.security.canary")


@dataclass
class CanaryDetection:
    """Result of a canary check."""

    is_canary: bool = False
    canary_id: Optional[int] = None
    distance: float = float("inf")
    action: str = "none"  # "throttle", "block", "alert"


@dataclass
class CanaryTrigger:
    """Record of a canary detection event."""

    api_key: str
    ip_address: str
    canary_id: int
    timestamp: float
    distance: float


class CanaryInputDetector:
    """
    Generates and detects canary inputs.

    The canary set is a fixed collection of synthetic feature vectors
    generated deterministically from a secret seed. Any query matching
    a canary (within tolerance) triggers a defensive response.
    """

    def __init__(self, config: Optional[CanaryConfig] = None):
        self.config = config or CanaryConfig()
        self._canaries: list[np.ndarray] = []
        self._triggers: collections.deque[CanaryTrigger] = collections.deque(maxlen=10_000)
        self._cooldown_map: dict[str, float] = {}  # api_key → cooldown_until

    def generate_canaries(self, n_features: int) -> None:
        """
        Generate the canary set for a given feature dimensionality.

        Args:
            n_features: Number of features in the model's input space.
        """
        seed_bytes = self.config.secret_seed.encode("utf-8")
        seed_hash = hashlib.sha256(seed_bytes).digest()
        seed_int = int.from_bytes(seed_hash[:8], "big")

        rng = np.random.default_rng(seed_int)

        self._canaries = []
        for i in range(self.config.num_canaries):
            # Generate canary with a mix of strategies:
            # 1. Some canaries are near-zero (sparse probing)
            # 2. Some canaries have extreme values (boundary probing)
            # 3. Some canaries have contradictory feature patterns
            strategy = i % 3

            if strategy == 0:
                # Sparse: mostly zero with a few extreme values
                vec = np.zeros(n_features)
                n_nonzero = max(1, n_features // 10)
                indices = rng.choice(n_features, size=n_nonzero, replace=False)
                vec[indices] = rng.uniform(-3.0, 3.0, size=n_nonzero)
            elif strategy == 1:
                # Extreme: all features at unusual magnitudes
                vec = rng.uniform(2.0, 5.0, size=n_features)
                signs = rng.choice([-1, 1], size=n_features)
                vec = vec * signs
            else:
                # Patterned: alternating high/low (rare in natural data)
                vec = np.empty(n_features)
                vec[::2] = rng.uniform(1.5, 3.0, size=len(vec[::2]))
                vec[1::2] = rng.uniform(-3.0, -1.5, size=len(vec[1::2]))

            self._canaries.append(vec)

        logger.info(
            "Generated %d canary inputs for %d-dimensional feature space",
            len(self._canaries),
            n_features,
        )

    def check(
        self,
        features: dict[str, float],
        api_key: str = "",
        ip_address: str = "",
    ) -> CanaryDetection:
        """
        Check if a query matches any canary input.

        Args:
            features: Input feature dictionary.
            api_key: Client API key (for cooldown tracking).
            ip_address: Client IP (for logging).

        Returns:
            CanaryDetection result.
        """
        if not self._canaries:
            return CanaryDetection()

        vec = self._dict_to_vector(features)

        # Pad or truncate to match canary dimensionality
        canary_dim = len(self._canaries[0])
        if len(vec) < canary_dim:
            vec = np.pad(vec, (0, canary_dim - len(vec)))
        elif len(vec) > canary_dim:
            vec = vec[:canary_dim]

        for idx, canary in enumerate(self._canaries):
            distance = np.linalg.norm(vec - canary)
            normalized_distance = distance / max(1.0, np.linalg.norm(canary))

            if normalized_distance < self.config.match_tolerance:
                self._record_trigger(api_key, ip_address, idx, normalized_distance)
                return CanaryDetection(
                    is_canary=True,
                    canary_id=idx,
                    distance=float(normalized_distance),
                    action=self.config.action,
                )

        return CanaryDetection()

    def is_in_cooldown(self, api_key: str) -> bool:
        """Check if a client is in canary-triggered cooldown."""
        cooldown_until = self._cooldown_map.get(api_key, 0)
        return time.time() < cooldown_until

    def get_trigger_count(self, api_key: str) -> int:
        """Return number of canary triggers for a given API key."""
        return sum(1 for t in self._triggers if t.api_key == api_key)

    def get_all_triggers(self) -> list[CanaryTrigger]:
        """Return all canary trigger events (for monitoring)."""
        return list(self._triggers)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_trigger(
        self,
        api_key: str,
        ip_address: str,
        canary_id: int,
        distance: float,
    ) -> None:
        """Record a canary trigger and apply cooldown."""
        trigger = CanaryTrigger(
            api_key=api_key,
            ip_address=ip_address,
            canary_id=canary_id,
            timestamp=time.time(),
            distance=distance,
        )
        self._triggers.append(trigger)
        self._cooldown_map[api_key] = time.time() + self.config.cooldown_seconds

        logger.warning(
            "CANARY TRIGGERED: api_key=%s ip=%s canary_id=%d distance=%.4f action=%s",
            api_key[:8] + "..." if api_key else "unknown",
            ip_address,
            canary_id,
            distance,
            self.config.action,
        )

    @staticmethod
    def _dict_to_vector(features: dict[str, float]) -> np.ndarray:
        """Convert a feature dict to a sorted numpy vector."""
        sorted_keys = sorted(features.keys())
        return np.array([float(features.get(k, 0.0)) for k in sorted_keys])
