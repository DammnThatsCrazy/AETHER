"""Production monitoring: drift detection, performance tracking, monitoring pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger("aether.monitoring")


# =============================================================================
# DRIFT RESULT
# =============================================================================


@dataclass
class DriftResult:
    """Result of a single drift check on one feature."""

    feature: str
    metric: str  # "psi", "ks", "js_divergence", "chi_squared"
    value: float
    threshold: float
    is_drifted: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DRIFT DETECTOR
# =============================================================================


class DriftDetector:
    """Statistical drift detection for numeric and categorical features.

    Supports Population Stability Index (PSI), Kolmogorov-Smirnov test,
    Jensen-Shannon divergence, and Chi-squared test.
    """

    def __init__(
        self,
        psi_threshold: float = 0.2,
        ks_threshold: float = 0.05,
        js_threshold: float = 0.1,
    ) -> None:
        self.psi_threshold = psi_threshold
        self.ks_threshold = ks_threshold
        self.js_threshold = js_threshold

    def compute_psi(
        self, reference: np.ndarray, current: np.ndarray, bins: int = 10
    ) -> float:
        """Population Stability Index.

        Measures the shift between two distributions by comparing their binned
        frequency proportions. Values above 0.2 typically indicate significant
        distribution change.

        Args:
            reference: Reference (training) distribution samples.
            current: Current (production) distribution samples.
            bins: Number of quantile-based bins.

        Returns:
            The PSI value (non-negative float).
        """
        try:
            bin_edges = np.quantile(reference, np.linspace(0, 1, bins + 1))
            bin_edges = np.unique(bin_edges)
            if len(bin_edges) < 3:
                bin_edges = np.linspace(
                    float(np.min(reference)), float(np.max(reference)), bins + 1
                )

            ref_hist = np.histogram(reference, bins=bin_edges)[0].astype(float)
            cur_hist = np.histogram(current, bins=bin_edges)[0].astype(float)

            # Normalise to proportions and guard against log(0)
            ref_pct = np.clip(ref_hist / ref_hist.sum(), 1e-6, None)
            cur_pct = np.clip(cur_hist / cur_hist.sum(), 1e-6, None)

            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
        except Exception:
            psi = 0.0

        return round(psi, 6)

    def compute_ks_test(
        self, reference: np.ndarray, current: np.ndarray
    ) -> tuple[float, float]:
        """Kolmogorov-Smirnov two-sample test.

        Args:
            reference: Reference distribution samples.
            current: Current distribution samples.

        Returns:
            Tuple of (statistic, p_value).
        """
        result = stats.ks_2samp(reference, current)
        return round(float(result.statistic), 6), round(float(result.pvalue), 6)

    def compute_js_divergence(
        self, reference: np.ndarray, current: np.ndarray, bins: int = 10
    ) -> float:
        """Jensen-Shannon divergence.

        A symmetric and bounded (0-1 when using log base 2) measure of
        divergence between two distributions.

        Args:
            reference: Reference distribution samples.
            current: Current distribution samples.
            bins: Number of histogram bins.

        Returns:
            JS divergence value.
        """
        try:
            combined = np.concatenate([reference, current])
            bin_edges = np.linspace(
                float(np.min(combined)), float(np.max(combined)), bins + 1
            )

            ref_hist = np.histogram(reference, bins=bin_edges)[0].astype(float)
            cur_hist = np.histogram(current, bins=bin_edges)[0].astype(float)

            ref_pct = ref_hist / ref_hist.sum()
            cur_pct = cur_hist / cur_hist.sum()

            # Guard against zeros
            ref_pct = np.clip(ref_pct, 1e-10, None)
            cur_pct = np.clip(cur_pct, 1e-10, None)

            m = 0.5 * (ref_pct + cur_pct)

            kl_ref = float(np.sum(ref_pct * np.log(ref_pct / m)))
            kl_cur = float(np.sum(cur_pct * np.log(cur_pct / m)))

            js = 0.5 * kl_ref + 0.5 * kl_cur
        except Exception:
            js = 0.0

        return round(js, 6)

    def compute_chi_squared(
        self, reference: pd.Series, current: pd.Series
    ) -> tuple[float, float]:
        """Chi-squared test for categorical features.

        Args:
            reference: Reference category counts or raw labels.
            current: Current category counts or raw labels.

        Returns:
            Tuple of (chi2_statistic, p_value).
        """
        all_categories = sorted(set(reference.unique()) | set(current.unique()))

        ref_counts = reference.value_counts()
        cur_counts = current.value_counts()

        ref_freq = np.array(
            [ref_counts.get(c, 0) for c in all_categories], dtype=float
        )
        cur_freq = np.array(
            [cur_counts.get(c, 0) for c in all_categories], dtype=float
        )

        # Normalise to proportions for the expected distribution
        ref_expected = ref_freq / ref_freq.sum() if ref_freq.sum() > 0 else ref_freq

        try:
            chi2, p_value = stats.chisquare(cur_freq, f_exp=ref_expected * cur_freq.sum() + 1e-10)
        except Exception:
            chi2, p_value = 0.0, 1.0

        return round(float(chi2), 6), round(float(p_value), 6)

    def detect_drift(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
        numeric_features: list[str],
        categorical_features: list[str] | None = None,
    ) -> list[DriftResult]:
        """Run all drift checks on the given features.

        For each numeric feature: computes PSI, KS test, and JS divergence.
        For each categorical feature: computes chi-squared test.

        Args:
            reference_df: Reference (training) dataframe.
            current_df: Current (production) dataframe.
            numeric_features: Column names for numeric features.
            categorical_features: Column names for categorical features.

        Returns:
            List of DriftResult objects (one per metric per feature).
        """
        if categorical_features is None:
            categorical_features = []

        results: list[DriftResult] = []

        for col in numeric_features:
            if col not in reference_df.columns or col not in current_df.columns:
                logger.warning(f"Feature '{col}' missing from one of the dataframes, skipping")
                continue

            ref = reference_df[col].dropna().values
            cur = current_df[col].dropna().values

            if len(ref) == 0 or len(cur) == 0:
                continue

            # PSI
            psi_val = self.compute_psi(ref, cur)
            results.append(
                DriftResult(
                    feature=col,
                    metric="psi",
                    value=psi_val,
                    threshold=self.psi_threshold,
                    is_drifted=psi_val > self.psi_threshold,
                )
            )

            # KS test
            ks_stat, ks_pval = self.compute_ks_test(ref, cur)
            results.append(
                DriftResult(
                    feature=col,
                    metric="ks",
                    value=ks_pval,
                    threshold=self.ks_threshold,
                    is_drifted=ks_pval < self.ks_threshold,
                )
            )

            # JS divergence
            js_val = self.compute_js_divergence(ref, cur)
            results.append(
                DriftResult(
                    feature=col,
                    metric="js_divergence",
                    value=js_val,
                    threshold=self.js_threshold,
                    is_drifted=js_val > self.js_threshold,
                )
            )

        for col in categorical_features:
            if col not in reference_df.columns or col not in current_df.columns:
                logger.warning(f"Feature '{col}' missing from one of the dataframes, skipping")
                continue

            ref_series = reference_df[col].dropna()
            cur_series = current_df[col].dropna()

            if len(ref_series) == 0 or len(cur_series) == 0:
                continue

            chi2_stat, chi2_pval = self.compute_chi_squared(ref_series, cur_series)
            results.append(
                DriftResult(
                    feature=col,
                    metric="chi_squared",
                    value=chi2_pval,
                    threshold=self.ks_threshold,  # Reuse significance threshold
                    is_drifted=chi2_pval < self.ks_threshold,
                )
            )

        drifted_count = sum(1 for r in results if r.is_drifted)
        logger.info(
            f"Drift detection complete: {len(results)} checks, {drifted_count} drifted"
        )
        return results


# =============================================================================
# PERFORMANCE MONITOR
# =============================================================================


class PerformanceMonitor:
    """Tracks model performance metrics over time.

    Records snapshots of model metrics and detects degradation relative to
    a stored baseline.
    """

    def __init__(self, baseline_metrics: dict[str, float]) -> None:
        self.baseline = baseline_metrics
        self.history: list[dict[str, Any]] = []

    def record(
        self, metrics: dict[str, float], timestamp: datetime | None = None
    ) -> None:
        """Record a performance snapshot.

        Args:
            metrics: Dictionary of metric_name -> value.
            timestamp: When the metrics were observed. Defaults to now.
        """
        ts = timestamp or datetime.utcnow()
        entry: dict[str, Any] = {"timestamp": ts.isoformat(), "metrics": dict(metrics)}
        self.history.append(entry)
        logger.debug(f"Recorded performance snapshot at {ts.isoformat()}")

    def check_degradation(
        self, current_metrics: dict[str, float], threshold_pct: float = 10.0
    ) -> list[dict[str, Any]]:
        """Check if any metric degraded beyond threshold compared to baseline.

        Degradation is measured as the percentage drop from the baseline value.
        Only metrics present in both baseline and current_metrics are checked.

        Args:
            current_metrics: Current metric values.
            threshold_pct: Percentage drop that constitutes degradation.

        Returns:
            List of dicts describing each degraded metric, including
            'metric', 'baseline', 'current', 'degradation_pct'.
        """
        degraded: list[dict[str, Any]] = []

        for metric, baseline_val in self.baseline.items():
            if metric not in current_metrics:
                continue
            if baseline_val == 0:
                continue

            current_val = current_metrics[metric]
            degradation_pct = ((baseline_val - current_val) / abs(baseline_val)) * 100

            if degradation_pct > threshold_pct:
                degraded.append(
                    {
                        "metric": metric,
                        "baseline": round(baseline_val, 6),
                        "current": round(current_val, 6),
                        "degradation_pct": round(degradation_pct, 2),
                    }
                )

        return degraded

    def get_trend(self, metric: str, window: int = 10) -> dict[str, Any]:
        """Get trend (slope, direction) for a metric over recent history.

        Performs a simple linear regression over the most recent *window*
        snapshots to estimate whether the metric is improving, declining,
        or stable.

        Args:
            metric: Name of the metric to analyse.
            window: Number of recent snapshots to consider.

        Returns:
            Dict with 'slope', 'direction' ("improving", "declining", "stable"),
            'data_points', and 'values'.
        """
        recent = self.history[-window:] if len(self.history) > window else self.history
        values: list[float] = []

        for entry in recent:
            if metric in entry["metrics"]:
                values.append(entry["metrics"][metric])

        if len(values) < 2:
            return {
                "slope": 0.0,
                "direction": "insufficient_data",
                "data_points": len(values),
                "values": values,
            }

        x = np.arange(len(values), dtype=float)
        y = np.array(values, dtype=float)
        slope, _intercept, _r, _p, _se = stats.linregress(x, y)

        if abs(slope) < 1e-6:
            direction = "stable"
        elif slope > 0:
            direction = "improving"
        else:
            direction = "declining"

        return {
            "slope": round(float(slope), 6),
            "direction": direction,
            "data_points": len(values),
            "values": values,
        }


# =============================================================================
# MONITORING PIPELINE
# =============================================================================


class MonitoringPipeline:
    """Orchestrates all monitoring checks for all models.

    Combines drift detection and performance monitoring into a single
    pipeline that produces a summary with alerts.
    """

    def __init__(self, models: list[str] | None = None) -> None:
        self.models = models or []
        self.drift_detector = DriftDetector()
        self.performance_monitors: dict[str, PerformanceMonitor] = {}

    def run(
        self,
        reference_data: dict[str, pd.DataFrame],
        current_data: dict[str, pd.DataFrame],
        model_metrics: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Run full monitoring pipeline across models.

        Args:
            reference_data: Mapping of model_name -> reference DataFrame.
            current_data: Mapping of model_name -> current DataFrame.
            model_metrics: Mapping of model_name -> {
                "current": {metric: value},
                "baseline": {metric: value},
                "numeric_features": [str],
                "categorical_features": [str]  (optional)
            }.

        Returns:
            Summary dict keyed by model name containing drift results,
            performance degradation details, and an overall status.
        """
        summary: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "models": {},
            "alerts": [],
        }

        model_names = set(reference_data.keys()) | set(current_data.keys())
        if self.models:
            model_names = model_names & set(self.models)

        for model_name in sorted(model_names):
            logger.info(f"Running monitoring for model: {model_name}")
            model_summary: dict[str, Any] = {"drift": [], "performance": [], "status": "healthy"}

            # --- Drift detection ---
            if model_name in reference_data and model_name in current_data:
                metrics_cfg = model_metrics.get(model_name, {})
                numeric_feats: list[str] = metrics_cfg.get("numeric_features", [])
                cat_feats: list[str] = metrics_cfg.get("categorical_features", [])

                drift_results = self.drift_detector.detect_drift(
                    reference_data[model_name],
                    current_data[model_name],
                    numeric_features=numeric_feats,
                    categorical_features=cat_feats,
                )
                drifted = [r for r in drift_results if r.is_drifted]
                model_summary["drift"] = [
                    {
                        "feature": r.feature,
                        "metric": r.metric,
                        "value": r.value,
                        "threshold": r.threshold,
                        "is_drifted": r.is_drifted,
                    }
                    for r in drift_results
                ]

                if len(drifted) > 0:
                    model_summary["status"] = "drift_detected"
                    summary["alerts"].append(
                        {
                            "model": model_name,
                            "type": "drift",
                            "count": len(drifted),
                            "features": [r.feature for r in drifted],
                        }
                    )

            # --- Performance monitoring ---
            if model_name in model_metrics:
                cfg = model_metrics[model_name]
                baseline = cfg.get("baseline", {})
                current = cfg.get("current", {})

                if baseline and current:
                    if model_name not in self.performance_monitors:
                        self.performance_monitors[model_name] = PerformanceMonitor(
                            baseline_metrics=baseline
                        )

                    monitor = self.performance_monitors[model_name]
                    monitor.record(current)

                    degraded = monitor.check_degradation(current)
                    model_summary["performance"] = degraded

                    if degraded:
                        model_summary["status"] = "degraded"
                        summary["alerts"].append(
                            {
                                "model": model_name,
                                "type": "performance_degradation",
                                "degraded_metrics": degraded,
                            }
                        )

            summary["models"][model_name] = model_summary

        total_alerts = len(summary["alerts"])
        logger.info(
            f"Monitoring pipeline complete: {len(summary['models'])} models checked, "
            f"{total_alerts} alerts raised"
        )
        return summary


# =============================================================================
# EXTRACTION DEFENSE MONITOR
# =============================================================================


class ExtractionDefenseMonitor:
    """
    Monitors extraction defense mesh health and effectiveness.

    Extends the monitoring pipeline with:
    - Query behavior drift (normal vs extraction-like patterns)
    - Extraction signal histograms
    - Policy action rates
    - Batch misuse trends
    - Cluster-level anomaly metrics
    """

    def __init__(self) -> None:
        self._signal_history: list[dict[str, Any]] = []
        self._policy_actions: dict[str, int] = {}
        self._batch_requests: list[dict[str, Any]] = []
        self._blocked_count: int = 0
        self._total_count: int = 0

    def record_extraction_event(
        self,
        risk_score: float,
        band: str,
        signals: list[dict[str, Any]],
        policy_action: str,
        model_name: str = "",
        is_batch: bool = False,
    ) -> None:
        """Record an extraction defense event for monitoring."""
        self._total_count += 1
        self._policy_actions[policy_action] = self._policy_actions.get(policy_action, 0) + 1

        if policy_action in ("deny", "restrict"):
            self._blocked_count += 1

        self._signal_history.append({
            "risk_score": risk_score,
            "band": band,
            "signal_count": len(signals),
            "policy_action": policy_action,
            "model_name": model_name,
            "timestamp": datetime.utcnow().isoformat(),
        })

        if is_batch:
            self._batch_requests.append({
                "model_name": model_name,
                "policy_action": policy_action,
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Trim history
        if len(self._signal_history) > 10000:
            self._signal_history = self._signal_history[-5000:]
        if len(self._batch_requests) > 1000:
            self._batch_requests = self._batch_requests[-500:]

    def get_summary(self) -> dict[str, Any]:
        """Return extraction defense monitoring summary."""
        recent = self._signal_history[-1000:]

        band_distribution: dict[str, int] = {}
        signal_counts: dict[str, int] = {}
        for entry in recent:
            band = entry.get("band", "unknown")
            band_distribution[band] = band_distribution.get(band, 0) + 1

        avg_risk = (
            sum(e["risk_score"] for e in recent) / len(recent) if recent else 0.0
        )

        return {
            "total_requests": self._total_count,
            "blocked_requests": self._blocked_count,
            "block_rate_pct": round(
                self._blocked_count / max(self._total_count, 1) * 100, 2
            ),
            "policy_actions": dict(self._policy_actions),
            "band_distribution": band_distribution,
            "avg_risk_score": round(avg_risk, 2),
            "batch_requests": len(self._batch_requests),
            "recent_events": len(recent),
        }

    def check_anomalies(self) -> list[dict[str, Any]]:
        """Check for extraction defense anomalies."""
        alerts: list[dict[str, Any]] = []
        recent = self._signal_history[-100:]

        if not recent:
            return alerts

        # High block rate alert
        recent_blocks = sum(
            1 for e in recent if e.get("policy_action") in ("deny", "restrict")
        )
        block_rate = recent_blocks / len(recent)
        if block_rate > 0.3:
            alerts.append({
                "type": "high_block_rate",
                "value": round(block_rate * 100, 1),
                "message": f"Block rate {block_rate:.0%} in last {len(recent)} requests",
            })

        # High average risk alert
        avg_risk = sum(e["risk_score"] for e in recent) / len(recent)
        if avg_risk > 40:
            alerts.append({
                "type": "elevated_risk",
                "value": round(avg_risk, 1),
                "message": f"Average risk score {avg_risk:.1f} in last {len(recent)} requests",
            })

        # Red band spike
        red_count = sum(1 for e in recent if e.get("band") == "red")
        if red_count > 5:
            alerts.append({
                "type": "red_band_spike",
                "value": red_count,
                "message": f"{red_count} red-band events in last {len(recent)} requests",
            })

        return alerts
