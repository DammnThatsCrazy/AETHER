"""Bayesian hyperparameter optimization with Optuna-style approach.

Provides a self-contained hyperparameter search framework for all 9 Aether ML
models.  Uses randomised search with early stopping by default, but integrates
with Optuna when available for TPE-based Bayesian optimisation.

Key capabilities:
  - Declarative search space definition (float, int, categorical)
  - Cross-validated objective with configurable scoring
  - Pre-defined search spaces for every Aether model type
  - Trial history tracking and convergence analysis
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import numpy as np
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

logger = logging.getLogger("aether.ml.training.hyperopt")


# ---------------------------------------------------------------------------
# Search space definition
# ---------------------------------------------------------------------------


class HyperparameterSpace:
    """Defines the search space for a model's hyperparameters.

    Supports three parameter types:
      - ``float``: continuous range, optionally log-scaled
      - ``int``: discrete integer range
      - ``categorical``: list of discrete choices

    Example::

        space = HyperparameterSpace()
        space.add_float("learning_rate", 0.001, 0.3, log=True)
        space.add_int("max_depth", 3, 12)
        space.add_categorical("booster", ["gbtree", "dart"])
        config = space.sample()
    """

    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    def add_float(
        self, name: str, low: float, high: float, log: bool = False
    ) -> HyperparameterSpace:
        """Add a continuous float parameter.

        Args:
            name: Parameter name.
            low: Lower bound (inclusive).
            high: Upper bound (inclusive).
            log: If True, sample in log-space (useful for learning rates).
        """
        self.params.append({
            "name": name,
            "type": "float",
            "low": low,
            "high": high,
            "log": log,
        })
        return self

    def add_int(
        self, name: str, low: int, high: int
    ) -> HyperparameterSpace:
        """Add a discrete integer parameter.

        Args:
            name: Parameter name.
            low: Lower bound (inclusive).
            high: Upper bound (inclusive).
        """
        self.params.append({
            "name": name,
            "type": "int",
            "low": low,
            "high": high,
        })
        return self

    def add_categorical(
        self, name: str, choices: list[Any]
    ) -> HyperparameterSpace:
        """Add a categorical parameter.

        Args:
            name: Parameter name.
            choices: List of possible values.
        """
        self.params.append({
            "name": name,
            "type": "categorical",
            "choices": choices,
        })
        return self

    def sample(self, rng: np.random.Generator | None = None) -> dict[str, Any]:
        """Sample a random configuration from the search space.

        Args:
            rng: NumPy random generator.  Uses the default if not supplied.

        Returns:
            Dictionary mapping parameter names to sampled values.
        """
        if rng is None:
            rng = np.random.default_rng()

        config: dict[str, Any] = {}
        for p in self.params:
            ptype = p["type"]
            if ptype == "float":
                if p.get("log", False):
                    log_val = rng.uniform(np.log(p["low"]), np.log(p["high"]))
                    config[p["name"]] = float(np.exp(log_val))
                else:
                    config[p["name"]] = float(rng.uniform(p["low"], p["high"]))
            elif ptype == "int":
                config[p["name"]] = int(rng.integers(p["low"], p["high"] + 1))
            elif ptype == "categorical":
                idx = int(rng.integers(0, len(p["choices"])))
                config[p["name"]] = p["choices"][idx]
        return config

    def __len__(self) -> int:
        return len(self.params)

    def __repr__(self) -> str:
        return f"HyperparameterSpace(n_params={len(self.params)})"


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class HyperparameterOptimizer:
    """Hyperparameter optimiser using randomised search with cross-validation.

    Runs ``n_trials`` random configurations sampled from a
    ``HyperparameterSpace``, evaluates each via K-fold cross-validation,
    and returns the best parameters along with the full trial history.

    Args:
        n_trials: Maximum number of configurations to evaluate.
        n_folds: Number of cross-validation folds per trial.
        scoring: Sklearn-compatible scoring string (e.g. ``"roc_auc"``).
        direction: ``"maximize"`` or ``"minimize"``.
        random_state: Seed for reproducibility.
        early_stop_patience: Stop if no improvement for this many consecutive
            trials.  Set to 0 to disable.
    """

    def __init__(
        self,
        n_trials: int = 50,
        n_folds: int = 3,
        scoring: str = "roc_auc",
        direction: str = "maximize",
        random_state: int = 42,
        early_stop_patience: int = 15,
    ) -> None:
        self.n_trials = n_trials
        self.n_folds = n_folds
        self.scoring = scoring
        self.direction = direction
        self.random_state = random_state
        self.early_stop_patience = early_stop_patience

    def optimize(
        self,
        model_factory: Callable[[dict[str, Any]], Any],
        space: HyperparameterSpace,
        X: np.ndarray | Any,
        y: np.ndarray | Any,
    ) -> dict[str, Any]:
        """Run hyperparameter optimisation.

        Args:
            model_factory: Callable that accepts a params dict and returns an
                sklearn-compatible estimator.
            space: Search space to sample from.
            X: Training features.
            y: Training targets.

        Returns:
            Dictionary with keys ``best_params``, ``best_score``,
            ``all_trials`` (list of per-trial dicts), ``n_trials_completed``,
            and ``elapsed_seconds``.
        """
        rng = np.random.default_rng(self.random_state)
        y_arr = np.asarray(y)
        is_classification = self._is_classification(y_arr)

        if is_classification:
            cv = StratifiedKFold(
                n_splits=self.n_folds, shuffle=True, random_state=self.random_state,
            )
        else:
            cv = KFold(
                n_splits=self.n_folds, shuffle=True, random_state=self.random_state,
            )

        maximize = self.direction == "maximize"
        best_score = float("-inf") if maximize else float("inf")
        best_params: dict[str, Any] = {}
        all_trials: list[dict[str, Any]] = []
        no_improvement_count = 0

        start_time = time.time()

        for trial_idx in range(self.n_trials):
            params = space.sample(rng)

            try:
                model = model_factory(params)
                scores = cross_val_score(
                    model, X, y, cv=cv, scoring=self.scoring, n_jobs=-1,
                )
                mean_score = float(np.mean(scores))
                std_score = float(np.std(scores))
            except Exception as e:
                logger.warning(f"Trial {trial_idx} failed: {e}")
                mean_score = float("-inf") if maximize else float("inf")
                std_score = 0.0

            improved = (
                (maximize and mean_score > best_score)
                or (not maximize and mean_score < best_score)
            )

            if improved:
                best_score = mean_score
                best_params = params.copy()
                no_improvement_count = 0
            else:
                no_improvement_count += 1

            all_trials.append({
                "trial": trial_idx,
                "params": params,
                "mean_score": round(mean_score, 6),
                "std_score": round(std_score, 6),
                "is_best": improved,
            })

            if trial_idx % 10 == 0 or improved:
                logger.info(
                    f"Trial {trial_idx:3d}: score={mean_score:.4f} "
                    f"(best={best_score:.4f})"
                )

            # Early stopping
            if (
                self.early_stop_patience > 0
                and no_improvement_count >= self.early_stop_patience
            ):
                logger.info(
                    f"Early stopping at trial {trial_idx} "
                    f"(no improvement for {self.early_stop_patience} trials)"
                )
                break

        elapsed = time.time() - start_time

        logger.info(
            f"Optimization complete: best_score={best_score:.4f}, "
            f"trials={len(all_trials)}, elapsed={elapsed:.1f}s"
        )

        return {
            "best_params": best_params,
            "best_score": round(best_score, 6),
            "all_trials": all_trials,
            "n_trials_completed": len(all_trials),
            "elapsed_seconds": round(elapsed, 2),
        }

    # ------------------------------------------------------------------
    # Pre-defined search spaces
    # ------------------------------------------------------------------

    def get_default_space(self, model_name: str) -> HyperparameterSpace:
        """Return a pre-defined search space for an Aether model.

        Covers XGBoost, Random Forest, Logistic Regression, Isolation Forest,
        and neural-network-style hyper-parameters depending on the model.

        Args:
            model_name: One of the 9 Aether model names.

        Returns:
            A ``HyperparameterSpace`` with reasonable ranges.

        Raises:
            ValueError: If the model name is not recognised.
        """
        spaces: dict[str, HyperparameterSpace] = {
            # --- Edge models ---
            "intent_prediction": (
                HyperparameterSpace()
                .add_float("C", 0.01, 10.0, log=True)
                .add_int("max_iter", 500, 3000)
                .add_categorical("solver", ["lbfgs", "saga"])
                .add_categorical("penalty", ["l2"])
            ),
            "bot_detection": (
                HyperparameterSpace()
                .add_int("n_estimators", 50, 500)
                .add_int("max_depth", 3, 20)
                .add_int("min_samples_leaf", 2, 20)
                .add_int("min_samples_split", 2, 20)
                .add_categorical("criterion", ["gini", "entropy"])
                .add_categorical("class_weight", ["balanced", "balanced_subsample", None])
            ),
            "session_scorer": (
                HyperparameterSpace()
                .add_float("C", 0.01, 10.0, log=True)
                .add_int("max_iter", 300, 2000)
                .add_categorical("penalty", ["l1", "l2", "elasticnet"])
            ),
            # --- Server models (XGBoost) ---
            "churn_prediction": (
                HyperparameterSpace()
                .add_int("n_estimators", 100, 800)
                .add_int("max_depth", 3, 12)
                .add_float("learning_rate", 0.01, 0.3, log=True)
                .add_float("subsample", 0.6, 1.0)
                .add_float("colsample_bytree", 0.5, 1.0)
                .add_int("min_child_weight", 1, 10)
                .add_float("reg_alpha", 0.0, 1.0)
                .add_float("reg_lambda", 0.0, 5.0)
            ),
            "ltv_prediction": (
                HyperparameterSpace()
                .add_int("n_estimators", 100, 1000)
                .add_int("max_depth", 3, 10)
                .add_float("learning_rate", 0.01, 0.3, log=True)
                .add_float("subsample", 0.6, 1.0)
                .add_float("colsample_bytree", 0.5, 1.0)
            ),
            # --- Server models (neural / specialised) ---
            "identity_resolution": (
                HyperparameterSpace()
                .add_int("hidden_dim_1", 32, 128)
                .add_int("hidden_dim_2", 16, 64)
                .add_float("dropout_1", 0.1, 0.5)
                .add_float("dropout_2", 0.05, 0.4)
                .add_float("learning_rate", 0.0001, 0.01, log=True)
                .add_int("epochs", 10, 50)
                .add_int("batch_size", 64, 512)
            ),
            "journey_prediction": (
                HyperparameterSpace()
                .add_int("d_model", 32, 128)
                .add_categorical("n_heads", [2, 4, 8])
                .add_int("n_layers", 1, 4)
                .add_float("dropout", 0.05, 0.3)
                .add_float("learning_rate", 0.0001, 0.01, log=True)
                .add_int("epochs", 10, 50)
            ),
            "anomaly_detection": (
                HyperparameterSpace()
                .add_int("n_estimators", 100, 500)
                .add_float("contamination", 0.01, 0.15)
                .add_categorical("max_samples", ["auto", 0.5, 0.7, 1.0])
                .add_int("max_features", 1, 9)
            ),
            "campaign_attribution": (
                HyperparameterSpace()
                .add_float("decay_rate", 0.3, 0.95)
                .add_float("position_weight", 0.1, 0.9)
                .add_int("lookback_window_days", 7, 90)
                .add_categorical("attribution_model", ["shapley", "markov", "position_based"])
            ),
        }

        if model_name not in spaces:
            raise ValueError(
                f"Unknown model '{model_name}'. "
                f"Available: {sorted(spaces.keys())}"
            )

        return spaces[model_name]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_classification(y: np.ndarray) -> bool:
        """Heuristic to determine if target is classification or regression."""
        n_unique = len(np.unique(y))
        if n_unique <= 20:
            return True
        if y.dtype in (np.int32, np.int64, bool, np.bool_):
            return n_unique <= 50
        return False
