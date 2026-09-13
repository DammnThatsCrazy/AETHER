"""
Multi-touch campaign attribution using Shapley values.

Supports five attribution methodologies:
  - **shapley**: Data-driven Shapley value attribution computing the marginal
    contribution of each channel across all possible coalitions.
  - **last_touch**: 100 % credit to the final touchpoint before conversion.
  - **first_touch**: 100 % credit to the first touchpoint in the journey.
  - **linear**: Equal credit split across all touchpoints.
  - **time_decay**: Exponential time-decay weighting with configurable half-life.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from common.src.base import AetherModel, DeploymentTarget, ModelMetadata, ModelType

logger = logging.getLogger("aether.ml.server.attribution")


class CampaignAttribution(AetherModel):
    """
    Multi-touch campaign attribution model.

    During ``train()`` the model ingests raw touchpoint-level journey data,
    computes channel coalitions and conversion rates, and derives Shapley
    values for each observed channel.

    During ``predict()`` the model returns per-channel attribution scores for
    new journey data.

    Parameters
    ----------
    method : str
        Default attribution method.  One of ``"shapley"``, ``"last_touch"``,
        ``"first_touch"``, ``"linear"``, ``"time_decay"``.
    """

    SUPPORTED_METHODS: list[str] = [
        "shapley",
        "last_touch",
        "first_touch",
        "linear",
        "time_decay",
    ]

    model_type_name: str = "campaign_attribution"

    def __init__(self, method: str = "shapley", version: str = "1.0.0") -> None:
        super().__init__(ModelType.CAMPAIGN_ATTRIBUTION, version)
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported method '{method}'. Choose from {self.SUPPORTED_METHODS}."
            )
        self.method = method

        # Populated during train()
        self._channel_shapley: dict[str, float] = {}
        self._conversion_rates: dict[frozenset[str], float] = {}
        self._channels: list[str] = []
        self._total_conversions: int = 0
        self._total_revenue: float = 0.0

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Compute channel coalitions and Shapley values from journey data.

        Parameters
        ----------
        X : pd.DataFrame
            Touchpoint-level data with columns:
              - ``journey_id``: unique journey identifier.
              - ``touchpoint``: touchpoint name / label.
              - ``channel``: marketing channel name.
              - ``timestamp``: touchpoint timestamp.
              - ``converted``: boolean indicating whether the journey converted.
        y : pd.Series, optional
            If provided, used as the conversion indicator instead of the
            ``converted`` column in *X*.

        Returns
        -------
        dict[str, float]
            Training metrics including per-channel Shapley values.
        """
        if y is not None:
            X = X.copy()
            X["converted"] = y.values

        required_cols = {"journey_id", "touchpoint", "channel", "timestamp", "converted"}
        missing = required_cols - set(X.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Discover channels
        self._channels = sorted(X["channel"].unique().tolist())

        # Build per-journey channel sets and conversion labels
        journey_groups = X.groupby("journey_id")
        touchpoint_sequences: list[list[str]] = []
        conversions: list[bool] = []

        for journey_id, group in journey_groups:
            group_sorted = group.sort_values("timestamp")
            channels_in_journey = group_sorted["channel"].tolist()
            converted = bool(group_sorted["converted"].any())
            touchpoint_sequences.append(channels_in_journey)
            conversions.append(converted)

        conversions_arr = np.array(conversions)

        # Compute coalition -> conversion rate mapping
        self._conversion_rates = self._build_coalition_rates(
            touchpoint_sequences, conversions_arr
        )

        # Compute Shapley values
        self._channel_shapley = self._compute_shapley_values(
            touchpoint_sequences, conversions_arr
        )

        # Summary metrics
        self._total_conversions = int(conversions_arr.sum())
        self._total_revenue = float(
            X.loc[X["converted"].astype(bool), "journey_id"]
            .drop_duplicates()
            .shape[0]
        )

        metrics: dict[str, float] = {
            "n_journeys": float(len(touchpoint_sequences)),
            "n_conversions": float(self._total_conversions),
            "conversion_rate": float(conversions_arr.mean()),
            "n_channels": float(len(self._channels)),
        }
        for ch, sv in self._channel_shapley.items():
            metrics[f"shapley_{ch}"] = sv

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"attribution-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_ECS,
            metrics=metrics,
            feature_columns=self._channels,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "method": self.method,
                "channels": self._channels,
            },
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction / Attribution
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Return attribution scores per channel for journeys in *X*.

        Uses the currently configured ``self.method``.

        Parameters
        ----------
        X : pd.DataFrame
            Same schema as ``train()`` input.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns ``journey_id``, ``channel``, and
            ``attribution_score``.
        """
        if not self.is_trained:
            raise RuntimeError("Model has not been trained yet.")

        required_cols = {"journey_id", "channel", "timestamp", "converted"}
        missing = required_cols - set(X.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        journey_groups = X.groupby("journey_id")
        sequences: list[list[str]] = []
        conversions: list[bool] = []
        journey_ids: list[Any] = []

        for journey_id, group in journey_groups:
            group_sorted = group.sort_values("timestamp")
            sequences.append(group_sorted["channel"].tolist())
            conversions.append(bool(group_sorted["converted"].any()))
            journey_ids.append(journey_id)

        conversions_arr = np.array(conversions)

        # Dispatch to the appropriate attribution method
        if self.method == "shapley":
            channel_scores = self._apply_shapley(sequences, conversions_arr)
        elif self.method == "last_touch":
            channel_scores = self._last_touch_attribution(sequences, conversions_arr)
        elif self.method == "first_touch":
            channel_scores = self._first_touch_attribution(sequences, conversions_arr)
        elif self.method == "linear":
            channel_scores = self._linear_attribution(sequences, conversions_arr)
        elif self.method == "time_decay":
            channel_scores = self._time_decay_attribution(sequences, conversions_arr)
        else:
            raise ValueError(f"Unknown method: {self.method}")

        # Build result DataFrame
        rows: list[dict[str, Any]] = []
        for i, journey_id in enumerate(journey_ids):
            seq_channels = set(sequences[i])
            for ch in seq_channels:
                rows.append(
                    {
                        "journey_id": journey_id,
                        "channel": ch,
                        "attribution_score": channel_scores.get(ch, 0.0),
                    }
                )

        return pd.DataFrame(rows)

    # --------------------------------------------------------------------- #
    # Shapley Value Computation
    # --------------------------------------------------------------------- #

    def _compute_shapley_values(
        self,
        touchpoint_sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[str, float]:
        """
        Compute exact Shapley values for each channel.

        For each channel *i* the Shapley value is:

            phi_i = SUM over S (subset not containing i)
                |S|! * (|N|-|S|-1)! / |N|!
                * [v(S union {i}) - v(S)]

        where ``v(S)`` is the coalition value (conversion rate when the
        coalition *S* of channels is present).

        Parameters
        ----------
        touchpoint_sequences : list[list[str]]
            Channel sequences for all journeys.
        conversions : np.ndarray
            Boolean conversion labels aligned with *touchpoint_sequences*.

        Returns
        -------
        dict[str, float]
            Mapping from channel name to its Shapley value.
        """
        all_channels = sorted(set(ch for seq in touchpoint_sequences for ch in seq))
        n = len(all_channels)

        if n == 0:
            return {}

        shapley: dict[str, float] = {ch: 0.0 for ch in all_channels}
        factorial_n = math.factorial(n)

        for channel in all_channels:
            others = [c for c in all_channels if c != channel]

            for size in range(0, n):
                # All subsets of `others` with this size
                weight = (
                    math.factorial(size)
                    * math.factorial(n - size - 1)
                    / factorial_n
                )
                for subset in combinations(others, size):
                    coalition_without = frozenset(subset)
                    coalition_with = coalition_without | {channel}

                    v_without = self._coalition_value(
                        coalition_without, touchpoint_sequences, conversions
                    )
                    v_with = self._coalition_value(
                        coalition_with, touchpoint_sequences, conversions
                    )
                    shapley[channel] += weight * (v_with - v_without)

        return shapley

    def _coalition_value(
        self,
        coalition: frozenset[str],
        touchpoint_sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> float:
        """
        Return the conversion rate for journeys whose channel set is a
        superset of *coalition*.

        If cached, return the cached result; otherwise compute from raw data.
        """
        if coalition in self._conversion_rates:
            return self._conversion_rates[coalition]

        # Journeys that contain at least all channels in the coalition
        mask = np.array(
            [coalition.issubset(set(seq)) for seq in touchpoint_sequences]
        )
        if mask.sum() == 0:
            rate = 0.0
        else:
            rate = float(conversions[mask].mean())

        self._conversion_rates[coalition] = rate
        return rate

    def _build_coalition_rates(
        self,
        touchpoint_sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[frozenset[str], float]:
        """Pre-compute conversion rates for observed channel coalitions."""
        rates: dict[frozenset[str], float] = {}
        coalition_counts: dict[frozenset[str], list[bool]] = defaultdict(list)

        for seq, conv in zip(touchpoint_sequences, conversions):
            key = frozenset(set(seq))
            coalition_counts[key].append(bool(conv))

        for coalition, conv_list in coalition_counts.items():
            rates[coalition] = float(np.mean(conv_list))

        return rates

    def _apply_shapley(
        self,
        sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[str, float]:
        """Apply pre-computed Shapley values (from training) to score channels."""
        return dict(self._channel_shapley)

    # --------------------------------------------------------------------- #
    # Heuristic Attribution Methods
    # --------------------------------------------------------------------- #

    def _last_touch_attribution(
        self,
        sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[str, float]:
        """100 % credit to the last touchpoint before conversion."""
        credits: dict[str, float] = defaultdict(float)
        for seq, conv in zip(sequences, conversions):
            if conv and seq:
                credits[seq[-1]] += 1.0
        total = sum(credits.values()) or 1.0
        return {ch: v / total for ch, v in credits.items()}

    def _first_touch_attribution(
        self,
        sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[str, float]:
        """100 % credit to the first touchpoint in the journey."""
        credits: dict[str, float] = defaultdict(float)
        for seq, conv in zip(sequences, conversions):
            if conv and seq:
                credits[seq[0]] += 1.0
        total = sum(credits.values()) or 1.0
        return {ch: v / total for ch, v in credits.items()}

    def _linear_attribution(
        self,
        sequences: list[list[str]],
        conversions: np.ndarray,
    ) -> dict[str, float]:
        """Equal credit split across all touchpoints in a journey."""
        credits: dict[str, float] = defaultdict(float)
        for seq, conv in zip(sequences, conversions):
            if conv and seq:
                share = 1.0 / len(seq)
                for ch in seq:
                    credits[ch] += share
        total = sum(credits.values()) or 1.0
        return {ch: v / total for ch, v in credits.items()}

    def _time_decay_attribution(
        self,
        sequences: list[list[str]],
        conversions: np.ndarray,
        half_life: float = 7.0,
    ) -> dict[str, float]:
        """
        Exponential time-decay attribution.

        Touchpoints closer to the conversion event receive higher credit.
        The weight decays by half every ``half_life`` positions from the end.

        Parameters
        ----------
        sequences : list[list[str]]
            Channel sequences.
        conversions : np.ndarray
            Conversion labels.
        half_life : float
            Number of positions for the weight to halve.

        Returns
        -------
        dict[str, float]
            Normalised channel attribution scores.
        """
        credits: dict[str, float] = defaultdict(float)

        for seq, conv in zip(sequences, conversions):
            if not conv or not seq:
                continue

            n = len(seq)
            weights = np.array(
                [2.0 ** (-(n - 1 - i) / half_life) for i in range(n)]
            )
            weights /= weights.sum()

            for i, ch in enumerate(seq):
                credits[ch] += float(weights[i])

        total = sum(credits.values()) or 1.0
        return {ch: v / total for ch, v in credits.items()}

    # --------------------------------------------------------------------- #
    # Reporting
    # --------------------------------------------------------------------- #

    def get_channel_report(self) -> pd.DataFrame:
        """
        Produce a summary report of per-channel attribution.

        Returns
        -------
        pd.DataFrame
            Columns: ``channel``, ``attributed_conversions``,
            ``attributed_revenue``, ``roas``.
        """
        if not self.is_trained:
            raise RuntimeError("Model has not been trained yet.")

        rows: list[dict[str, Any]] = []
        total_shapley = sum(max(v, 0) for v in self._channel_shapley.values()) or 1.0

        for ch in self._channels:
            sv = max(self._channel_shapley.get(ch, 0.0), 0.0)
            share = sv / total_shapley

            attributed_conversions = share * self._total_conversions
            attributed_revenue = share * self._total_revenue

            rows.append(
                {
                    "channel": ch,
                    "attributed_conversions": round(attributed_conversions, 2),
                    "attributed_revenue": round(attributed_revenue, 2),
                    "roas": round(attributed_revenue / max(sv, 1e-10), 4),
                }
            )

        report = pd.DataFrame(rows)
        report = report.sort_values("attributed_conversions", ascending=False)
        return report.reset_index(drop=True)

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import json

        path.mkdir(parents=True, exist_ok=True)

        (path / "channel_shapley.json").write_text(
            json.dumps(self._channel_shapley, indent=2)
        )
        (path / "channels.json").write_text(json.dumps(self._channels, indent=2))

        # Serialise coalition rates (frozenset keys -> sorted list keys)
        serialisable_rates = {
            json.dumps(sorted(k)): v for k, v in self._conversion_rates.items()
        }
        (path / "conversion_rates.json").write_text(
            json.dumps(serialisable_rates, indent=2)
        )

        (path / "config.json").write_text(
            json.dumps(
                {
                    "method": self.method,
                    "total_conversions": self._total_conversions,
                    "total_revenue": self._total_revenue,
                },
                indent=2,
            )
        )

        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))

        logger.info(f"Saved campaign attribution model to {path}")

    def load(self, path: Path) -> None:
        import json

        self._channel_shapley = json.loads(
            (path / "channel_shapley.json").read_text()
        )
        self._channels = json.loads((path / "channels.json").read_text())

        raw_rates = json.loads((path / "conversion_rates.json").read_text())
        self._conversion_rates = {
            frozenset(json.loads(k)): v for k, v in raw_rates.items()
        }

        config = json.loads((path / "config.json").read_text())
        self.method = config["method"]
        self._total_conversions = config["total_conversions"]
        self._total_revenue = config["total_revenue"]

        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )

        self.is_trained = True
        logger.info(f"Loaded campaign attribution model from {path}")

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "mean_attribution": float(y_pred.mean()),
        }
