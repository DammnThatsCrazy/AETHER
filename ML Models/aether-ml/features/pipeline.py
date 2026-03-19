"""
Aether ML -- Batch and Streaming Feature Computation Pipeline

Orchestrates feature computation for all 9 Aether models:
  Edge (<100ms): Intent Prediction, Bot Detection, Session Scorer
  Server:        Identity Resolution, Journey Prediction, Churn Prediction,
                 LTV Prediction, Anomaly Detection, Campaign Attribution

Reads from:   S3 Parquet (batch) or local files (development)
Writes to:    S3 Parquet (offline training) and Redis (online serving)
Orchestrated: SageMaker Processing Jobs (batch), ECS Fargate (streaming)
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger("aether.ml.features.pipeline")


# =============================================================================
# PIPELINE CONFIGURATION
# =============================================================================


class FeaturePipelineConfig(BaseModel):
    """Configuration for a feature engineering pipeline run."""

    input_path: str  # S3 path (s3://bucket/prefix) or local path to raw events
    output_path: str  # S3 path or local path for computed feature artefacts
    feature_groups: list[str] = Field(
        default_factory=lambda: [
            "session_features",
            "behavioral_features",
            "identity_features",
            "journey_features",
            "attribution_features",
            "anomaly_features",
            "web3_features",
        ]
    )
    start_date: str | None = None  # YYYY-MM-DD filter lower bound
    end_date: str | None = None  # YYYY-MM-DD filter upper bound
    batch_size: int = 10_000
    write_online: bool = False  # Push latest features to Redis
    write_offline: bool = True  # Persist computed features to output_path
    redis_url: str = "redis://aether-cache.internal:6379"
    online_ttl_seconds: int = 3600
    s3_region: str = "us-east-1"
    tenant_id: str | None = None


# =============================================================================
# BATCH FEATURE PIPELINE
# =============================================================================


class FeaturePipeline:
    """Orchestrates batch feature computation for all 9 Aether models.

    Typical usage::

        config = FeaturePipelineConfig(
            input_path="s3://aether-data-lake/events/",
            output_path="s3://aether-features/",
            feature_groups=["session_features", "identity_features"],
        )
        pipeline = FeaturePipeline(config)
        results = pipeline.run()
    """

    # Canonical feature-group names and their computation methods
    _GROUP_METHODS: dict[str, str] = {
        "session_features": "compute_session_features",
        "behavioral_features": "compute_behavioral_features",
        "identity_features": "compute_identity_features",
        "journey_features": "compute_journey_features",
        "attribution_features": "compute_attribution_features",
        "anomaly_features": "compute_anomaly_features",
        "web3_features": "compute_web3_features",
    }

    def __init__(self, config: FeaturePipelineConfig) -> None:
        self.config = config

    # =========================================================================
    # PUBLIC INTERFACE
    # =========================================================================

    def run(self) -> dict[str, pd.DataFrame]:
        """Execute the full pipeline, return a dict of computed feature DataFrames.

        Only the feature groups listed in ``config.feature_groups`` are computed.
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting batch feature pipeline  input=%s  groups=%s",
            self.config.input_path,
            self.config.feature_groups,
        )

        events = self._load_events()
        if events.empty:
            logger.warning("No events loaded -- returning empty results")
            return {}

        logger.info("Loaded %d raw events (%d columns)", len(events), len(events.columns))

        results: dict[str, pd.DataFrame] = {}
        for group_name in self.config.feature_groups:
            method_name = self._GROUP_METHODS.get(group_name)
            if method_name is None:
                logger.warning("Unknown feature group '%s' -- skipping", group_name)
                continue

            method = getattr(self, method_name)
            try:
                df = method(events)
                results[group_name] = df
                logger.info(
                    "Computed %-25s  rows=%d  cols=%d",
                    group_name,
                    len(df),
                    len(df.columns),
                )
            except Exception:
                logger.exception("Failed to compute feature group '%s'", group_name)

        # Persist
        if self.config.write_offline:
            for group_name, df in results.items():
                if not df.empty:
                    self._save_features(group_name, df)

        if self.config.write_online:
            self._push_online_features(results)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info("Feature pipeline complete in %.1fs  groups=%d", elapsed, len(results))
        return results

    # =========================================================================
    # FEATURE GROUP COMPUTATIONS
    # =========================================================================

    def compute_session_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Session-level features for edge models (intent, bot, session scorer).

        Returns one row per ``session_id`` with columns:
            click_count, scroll_depth, time_on_page, pages_viewed,
            session_duration, device_type, started_hour, started_dayofweek,
            is_weekend, is_mobile, events_per_minute, click_rate, is_bounce,
            has_conversion, has_form_submit.
        """
        if "session_id" not in events.columns:
            logger.warning("Missing 'session_id' column -- returning empty session features")
            return pd.DataFrame()

        # Ensure timestamp is datetime
        events = self._ensure_datetime(events, "timestamp")

        agg = events.groupby("session_id").agg(
            event_count=("timestamp", "count"),
            page_count=("type", lambda s: int((s == "page").sum())),
            click_count=("type", lambda s: int((s == "click").sum())),
            session_start=("timestamp", "min"),
            session_end=("timestamp", "max"),
        ).reset_index()

        agg["session_duration_s"] = (
            (agg["session_end"] - agg["session_start"]).dt.total_seconds().clip(lower=0.0)
        )

        # Scroll depth (max per session)
        if "scroll_depth" in events.columns:
            scroll = events.groupby("session_id")["scroll_depth"].max().reset_index()
            scroll.columns = ["session_id", "max_scroll_depth"]
            agg = agg.merge(scroll, on="session_id", how="left")
            agg["max_scroll_depth"] = agg["max_scroll_depth"].fillna(0.0)
        else:
            agg["max_scroll_depth"] = 0.0

        # Unique pages
        if "page_url" in events.columns:
            pages = events.groupby("session_id")["page_url"].nunique().reset_index()
            pages.columns = ["session_id", "unique_pages"]
            agg = agg.merge(pages, on="session_id", how="left")
        else:
            agg["unique_pages"] = agg["page_count"]

        # Temporal features
        agg["started_hour"] = agg["session_start"].dt.hour
        agg["started_dayofweek"] = agg["session_start"].dt.dayofweek
        agg["is_weekend"] = agg["started_dayofweek"].isin([5, 6]).astype(np.int8)

        # Device features
        if "device_type" in events.columns:
            device = events.groupby("session_id")["device_type"].first().reset_index()
            agg = agg.merge(device, on="session_id", how="left")
            agg["is_mobile"] = (agg["device_type"] == "mobile").astype(np.int8)
        else:
            agg["device_type"] = "unknown"
            agg["is_mobile"] = np.int8(0)

        # Conversion / form submit flags
        agg["has_conversion"] = events.groupby("session_id")["type"].transform(
            lambda s: int((s == "conversion").any())
        ).groupby(events["session_id"]).first().values if "type" in events.columns else 0

        # Derived rates
        eps = 1e-6
        agg["events_per_minute"] = agg["event_count"] / (agg["session_duration_s"] / 60.0 + eps)
        agg["click_rate"] = agg["click_count"] / (agg["page_count"].clip(lower=1))
        agg["is_bounce"] = (agg["page_count"] <= 1).astype(np.int8)

        # Drop intermediate columns
        agg = agg.drop(columns=["session_start", "session_end"], errors="ignore")

        return agg

    def compute_behavioral_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Behavioral biometric features for bot detection.

        Returns one row per ``session_id`` with columns:
            mouse_speed_mean, mouse_speed_std, click_interval_mean,
            click_interval_std, scroll_pattern_entropy,
            keystroke_timing_variance, action_type_entropy,
            js_execution_time.
        """
        if "session_id" not in events.columns:
            return pd.DataFrame()

        events = self._ensure_datetime(events, "timestamp")

        def _session_biometrics(group: pd.DataFrame) -> pd.Series:
            time_diffs = group["timestamp"].diff().dt.total_seconds().dropna()

            # Mouse trajectory speed
            mouse_speed_mean = 0.0
            mouse_speed_std = 0.0
            if {"mouse_x", "mouse_y"}.issubset(group.columns):
                dx = group["mouse_x"].diff().dropna()
                dy = group["mouse_y"].diff().dropna()
                dt = time_diffs.iloc[: len(dx)] if len(time_diffs) >= len(dx) else time_diffs
                displacement = np.sqrt(dx.values ** 2 + dy.values[: len(dx)] ** 2)
                speed = displacement / (dt.values[: len(displacement)] + 1e-9)
                if len(speed) > 0:
                    mouse_speed_mean = float(np.nanmean(speed))
                    mouse_speed_std = float(np.nanstd(speed)) if len(speed) > 1 else 0.0

            # Click intervals
            click_events = group[group.get("type", pd.Series(dtype=str)) == "click"]
            click_intervals = click_events["timestamp"].diff().dt.total_seconds().dropna()
            click_interval_mean = float(click_intervals.mean()) if len(click_intervals) > 0 else 0.0
            click_interval_std = float(click_intervals.std()) if len(click_intervals) > 1 else 0.0

            # Scroll pattern entropy
            scroll_entropy = 0.0
            if "scroll_depth" in group.columns:
                scroll_vals = group["scroll_depth"].dropna()
                if len(scroll_vals) > 1:
                    diffs = scroll_vals.diff().dropna().abs()
                    if diffs.sum() > 0:
                        probs = diffs / diffs.sum()
                        scroll_entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))

            # Keystroke timing variance
            keystroke_var = 0.0
            if "type" in group.columns:
                keypress_events = group[group["type"] == "keypress"]
                if len(keypress_events) > 2:
                    key_intervals = keypress_events["timestamp"].diff().dt.total_seconds().dropna()
                    keystroke_var = float(key_intervals.var()) if len(key_intervals) > 1 else 0.0

            # Action type entropy
            action_entropy = 0.0
            if "type" in group.columns:
                probs = group["type"].value_counts(normalize=True).values
                action_entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))

            # JS execution time (average if available)
            js_exec_time = 0.0
            if "js_execution_time" in group.columns:
                vals = group["js_execution_time"].dropna()
                js_exec_time = float(vals.mean()) if len(vals) > 0 else 0.0

            return pd.Series(
                {
                    "mouse_speed_mean": mouse_speed_mean,
                    "mouse_speed_std": mouse_speed_std,
                    "click_interval_mean": click_interval_mean,
                    "click_interval_std": click_interval_std,
                    "scroll_pattern_entropy": scroll_entropy,
                    "keystroke_timing_variance": keystroke_var,
                    "action_type_entropy": action_entropy,
                    "js_execution_time": js_exec_time,
                }
            )

        features = events.groupby("session_id").apply(_session_biometrics).reset_index()
        return features

    def compute_identity_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """User-level features for identity resolution, churn, and LTV models.

        Returns one row per ``identity_id`` with columns:
            visit_frequency, conversion_rate, tenure_days,
            monetary_value, frequency, recency_days,
            total_sessions, total_events, avg_session_duration,
            avg_pages_per_session, is_active_30d, is_churned.
        """
        # Resolve identity column
        id_col = self._resolve_identity_column(events)
        if id_col is None:
            logger.warning("No identity column found -- returning empty identity features")
            return pd.DataFrame()

        events = self._ensure_datetime(events, "timestamp")

        # First aggregate at session level if we have session_id
        if "session_id" in events.columns and id_col != "session_id":
            session_agg = events.groupby(["session_id", id_col]).agg(
                session_event_count=("timestamp", "count"),
                session_start=("timestamp", "min"),
                session_end=("timestamp", "max"),
                session_has_conversion=(
                    "type",
                    lambda s: int((s == "conversion").any()) if "type" in s.name or True else 0,
                ),
                session_page_count=(
                    "type",
                    lambda s: int((s == "page").sum()),
                ),
            ).reset_index()

            session_agg["session_duration_s"] = (
                (session_agg["session_end"] - session_agg["session_start"])
                .dt.total_seconds()
                .clip(lower=0.0)
            )

            # Roll up to identity level
            now = pd.Timestamp.utcnow().tz_localize(None)
            identity_agg = session_agg.groupby(id_col).agg(
                total_sessions=("session_id", "nunique"),
                total_events=("session_event_count", "sum"),
                avg_session_duration=("session_duration_s", "mean"),
                total_conversions=("session_has_conversion", "sum"),
                first_seen=("session_start", "min"),
                last_seen=("session_end", "max"),
                avg_pages_per_session=("session_page_count", "mean"),
            ).reset_index()
        else:
            now = pd.Timestamp.utcnow().tz_localize(None)
            identity_agg = events.groupby(id_col).agg(
                total_sessions=("session_id", "nunique") if "session_id" in events.columns else ("timestamp", "count"),
                total_events=("timestamp", "count"),
                first_seen=("timestamp", "min"),
                last_seen=("timestamp", "max"),
            ).reset_index()
            identity_agg["avg_session_duration"] = 0.0
            identity_agg["total_conversions"] = 0
            identity_agg["avg_pages_per_session"] = 0.0

        identity_agg.rename(columns={id_col: "identity_id"}, inplace=True)

        # Derived features
        identity_agg["tenure_days"] = (now - identity_agg["first_seen"]).dt.days.clip(lower=0)
        identity_agg["recency_days"] = (now - identity_agg["last_seen"]).dt.days.clip(lower=0)
        identity_agg["visit_frequency"] = identity_agg["total_sessions"] / (
            identity_agg["tenure_days"] + 1
        )
        identity_agg["conversion_rate"] = identity_agg["total_conversions"] / (
            identity_agg["total_sessions"].clip(lower=1)
        )

        # Monetary value (if conversion_value column exists)
        if "conversion_value" in events.columns:
            monetary = events.groupby(id_col)["conversion_value"].sum().reset_index()
            monetary.columns = ["identity_id", "monetary_value"]
            identity_agg = identity_agg.merge(monetary, on="identity_id", how="left")
            identity_agg["monetary_value"] = identity_agg["monetary_value"].fillna(0.0)
        else:
            identity_agg["monetary_value"] = 0.0

        # RFM alias
        identity_agg["frequency"] = identity_agg["total_sessions"]

        # Churn flags
        identity_agg["is_active_30d"] = (identity_agg["recency_days"] <= 30).astype(np.int8)
        identity_agg["is_churned"] = (identity_agg["recency_days"] > 30).astype(np.int8)

        # Drop raw timestamp columns
        identity_agg = identity_agg.drop(columns=["first_seen", "last_seen"], errors="ignore")

        return identity_agg

    def compute_journey_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Ordered event sequences for journey prediction (LSTM + Attention).

        Returns a DataFrame with columns:
            identity_id, session_id, event_type, page_category,
            channel, device_type, timestamp, event_index.
        """
        id_col = self._resolve_identity_column(events) or "session_id"
        events = self._ensure_datetime(events, "timestamp")
        events_sorted = events.sort_values([id_col, "timestamp"]).copy()

        journey = pd.DataFrame()
        journey["identity_id"] = events_sorted[id_col]

        if "session_id" in events_sorted.columns:
            journey["session_id"] = events_sorted["session_id"]

        journey["event_type"] = events_sorted.get("type", pd.Series("unknown", index=events_sorted.index))
        journey["timestamp"] = events_sorted["timestamp"]

        # Page categorisation
        if "page_url" in events_sorted.columns:
            journey["page_category"] = events_sorted["page_url"].apply(self._categorize_page)
        elif "properties_url" in events_sorted.columns:
            journey["page_category"] = events_sorted["properties_url"].apply(self._categorize_page)
        else:
            journey["page_category"] = "other"

        journey["channel"] = events_sorted.get("utm_source", pd.Series("direct", index=events_sorted.index))
        journey["device_type"] = events_sorted.get("device_type", pd.Series("desktop", index=events_sorted.index))

        # Positional encoding within each identity's journey
        journey["event_index"] = journey.groupby("identity_id").cumcount()

        return journey.reset_index(drop=True)

    def compute_attribution_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Touchpoint sequences for campaign attribution (Shapley-based).

        Returns a DataFrame with columns:
            journey_id, identity_id, touchpoint_index, channel,
            campaign_id, timestamp, converted, conversion_value,
            time_decay_weight.
        """
        events = self._ensure_datetime(events, "timestamp")
        id_col = self._resolve_identity_column(events) or "session_id"

        if "type" not in events.columns:
            logger.warning("Missing 'type' column -- returning empty attribution features")
            return pd.DataFrame()

        # Identify converting identities
        conversions = events[events["type"] == "conversion"]
        if conversions.empty:
            logger.info("No conversion events found -- returning empty attribution features")
            return pd.DataFrame()

        touchpoints: list[dict[str, Any]] = []
        journey_counter = 0

        for identity_val, conv_rows in conversions.groupby(id_col):
            for _, conv_event in conv_rows.iterrows():
                journey_counter += 1
                journey_id = f"journey_{journey_counter}"
                conv_time = conv_event["timestamp"]
                conv_value = conv_event.get("conversion_value", 0.0)

                # All events for this identity up to and including conversion
                mask = (events[id_col] == identity_val) & (events["timestamp"] <= conv_time)
                user_events = events.loc[mask].sort_values("timestamp")

                if user_events.empty:
                    continue

                # Time-decay weights (more recent -> higher weight)
                timestamps = user_events["timestamp"]
                span_seconds = max((timestamps.max() - timestamps.min()).total_seconds(), 1.0)
                decay_weights = ((timestamps - timestamps.min()).dt.total_seconds() / span_seconds).values

                for idx, (_, evt) in enumerate(user_events.iterrows()):
                    touchpoints.append(
                        {
                            "journey_id": journey_id,
                            "identity_id": str(identity_val),
                            "touchpoint_index": idx,
                            "channel": self._derive_channel(evt),
                            "campaign_id": evt.get("utm_campaign", ""),
                            "timestamp": evt["timestamp"],
                            "converted": int(evt["type"] == "conversion"),
                            "conversion_value": float(conv_value) if evt["type"] == "conversion" else 0.0,
                            "time_decay_weight": float(decay_weights[idx]),
                        }
                    )

        return pd.DataFrame(touchpoints)

    def compute_anomaly_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Aggregate traffic features for anomaly detection.

        Computes per-time-window (hourly) aggregations:
            requests_per_minute, error_rate, unique_ips, unique_sessions,
            unique_visitors, conversion_rate, avg_response_time,
            p95_response_time, bot_ratio.
        """
        events = self._ensure_datetime(events, "timestamp")

        if events.empty:
            return pd.DataFrame()

        events = events.set_index("timestamp").sort_index()

        # Hourly resampling
        agg_dict: dict[str, tuple[str, Any]] = {}

        # Traffic volume (use any available column for counting)
        count_col = "session_id" if "session_id" in events.columns else events.columns[0]
        agg_dict["traffic_volume"] = (count_col, "count")

        if "session_id" in events.columns:
            agg_dict["unique_sessions"] = ("session_id", "nunique")

        if "anonymous_id" in events.columns:
            agg_dict["unique_visitors"] = ("anonymous_id", "nunique")
        elif "user_id" in events.columns:
            agg_dict["unique_visitors"] = ("user_id", "nunique")

        if "ip_address" in events.columns:
            agg_dict["unique_ips"] = ("ip_address", "nunique")

        if "response_time" in events.columns:
            agg_dict["avg_response_time"] = ("response_time", "mean")
            agg_dict["p95_response_time"] = ("response_time", lambda s: s.quantile(0.95) if len(s) > 0 else 0.0)

        hourly = events.resample("1h").agg(**agg_dict).reset_index()
        hourly.rename(columns={"timestamp": "window_start"}, inplace=True)

        # Derived rates
        hourly["requests_per_minute"] = hourly["traffic_volume"] / 60.0

        # Error rate (fraction of error-type events per window)
        if "type" in events.columns:
            error_rate = (
                events["type"]
                .eq("error")
                .resample("1h")
                .mean()
                .reset_index()
            )
            error_rate.columns = ["window_start", "error_rate"]
            hourly = hourly.merge(error_rate, on="window_start", how="left")
            hourly["error_rate"] = hourly["error_rate"].fillna(0.0)

            # Conversion rate
            conv_rate = (
                events["type"]
                .eq("conversion")
                .resample("1h")
                .mean()
                .reset_index()
            )
            conv_rate.columns = ["window_start", "conversion_rate"]
            hourly = hourly.merge(conv_rate, on="window_start", how="left")
            hourly["conversion_rate"] = hourly["conversion_rate"].fillna(0.0)

        # Bot ratio (if is_bot flag exists)
        if "is_bot" in events.columns:
            bot_ratio = (
                events["is_bot"]
                .astype(float)
                .resample("1h")
                .mean()
                .reset_index()
            )
            bot_ratio.columns = ["window_start", "bot_ratio"]
            hourly = hourly.merge(bot_ratio, on="window_start", how="left")
            hourly["bot_ratio"] = hourly["bot_ratio"].fillna(0.0)

        return hourly

    def compute_web3_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Web3 wallet and on-chain features for wallet-aware models.

        Returns one row per ``wallet_address`` with columns:
            tx_count, unique_chains, total_gas_used, unique_interactions,
            wallet_age_days, tx_frequency, avg_gas_per_tx.
        """
        if "type" in events.columns:
            web3_events = events[events["type"].isin(["wallet", "transaction"])].copy()
        else:
            web3_events = events.copy()

        if web3_events.empty:
            return pd.DataFrame()

        # Resolve wallet address column
        addr_col: str | None = None
        for candidate in ("wallet_address", "address", "from_address"):
            if candidate in web3_events.columns:
                addr_col = candidate
                break

        if addr_col is None:
            logger.warning("No wallet address column found -- returning empty web3 features")
            return pd.DataFrame()

        web3_events = self._ensure_datetime(web3_events, "timestamp")
        web3_events[addr_col] = web3_events[addr_col].str.lower()

        agg_dict: dict[str, tuple[str, Any]] = {
            "tx_count": ("timestamp", "count"),
            "first_tx": ("timestamp", "min"),
            "last_tx": ("timestamp", "max"),
        }

        if "chain_id" in web3_events.columns:
            agg_dict["unique_chains"] = ("chain_id", "nunique")
        if "gas_used" in web3_events.columns:
            agg_dict["total_gas_used"] = ("gas_used", "sum")
        if "to_address" in web3_events.columns:
            agg_dict["unique_interactions"] = ("to_address", "nunique")

        wallet_agg = web3_events.groupby(addr_col).agg(**agg_dict).reset_index()
        wallet_agg.rename(columns={addr_col: "wallet_address"}, inplace=True)

        # Derived features
        wallet_agg["wallet_age_days"] = (
            (wallet_agg["last_tx"] - wallet_agg["first_tx"]).dt.days.clip(lower=0)
        )
        wallet_agg["tx_frequency"] = wallet_agg["tx_count"] / (
            wallet_agg["wallet_age_days"] + 1
        )

        if "total_gas_used" in wallet_agg.columns:
            wallet_agg["avg_gas_per_tx"] = wallet_agg["total_gas_used"] / (
                wallet_agg["tx_count"].clip(lower=1)
            )

        wallet_agg = wallet_agg.drop(columns=["first_tx", "last_tx"], errors="ignore")
        return wallet_agg

    # =========================================================================
    # DATA I/O
    # =========================================================================

    def _load_events(self) -> pd.DataFrame:
        """Load raw events from S3 (Parquet) or local filesystem.

        Supports:
            - ``s3://bucket/prefix`` -- reads all Parquet files under prefix
            - Local directory -- reads all ``*.parquet`` files
            - Local single file -- CSV or Parquet
        """
        path = self.config.input_path

        if path.startswith("s3://"):
            return self._load_from_s3(path)

        local_path = Path(path)
        if not local_path.exists():
            logger.error("Input path does not exist: %s", path)
            return pd.DataFrame()

        if local_path.is_dir():
            parquet_files = list(local_path.glob("**/*.parquet"))
            if parquet_files:
                frames = [pd.read_parquet(f) for f in parquet_files]
                return pd.concat(frames, ignore_index=True)
            csv_files = list(local_path.glob("**/*.csv"))
            if csv_files:
                frames = [pd.read_csv(f) for f in csv_files]
                return pd.concat(frames, ignore_index=True)
            logger.warning("No Parquet or CSV files found in %s", path)
            return pd.DataFrame()

        if local_path.suffix == ".parquet":
            return pd.read_parquet(local_path)
        if local_path.suffix == ".csv":
            return pd.read_csv(local_path)

        logger.warning("Unsupported file format: %s", local_path.suffix)
        return pd.DataFrame()

    def _load_from_s3(self, s3_path: str) -> pd.DataFrame:
        """Load Parquet files from an S3 path with optional date filtering."""
        import boto3

        # Parse s3://bucket/prefix
        parts = s3_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""

        s3 = boto3.client("s3", region_name=self.config.s3_region)
        paginator = s3.get_paginator("list_objects_v2")
        frames: list[pd.DataFrame] = []

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                if not key.endswith(".parquet"):
                    continue

                # Optional date filtering on partition keys (dt=YYYY-MM-DD)
                if self.config.start_date or self.config.end_date:
                    if not self._key_in_date_range(key):
                        continue

                response = s3.get_object(Bucket=bucket, Key=key)
                buf = io.BytesIO(response["Body"].read())
                frames.append(pd.read_parquet(buf))

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def _save_features(self, feature_group: str, df: pd.DataFrame) -> str:
        """Save computed features to the output path (S3 or local).

        Returns the path where features were written.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.config.output_path

        if path.startswith("s3://"):
            return self._save_to_s3(feature_group, df, today)

        # Local filesystem
        out_dir = Path(path) / feature_group / f"dt={today}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "data.parquet"
        df.to_parquet(out_file, index=False)
        logger.info("Saved %d rows to %s", len(df), out_file)
        return str(out_file)

    def _save_to_s3(self, feature_group: str, df: pd.DataFrame, date_str: str) -> str:
        """Write a DataFrame as Parquet to S3."""
        import boto3

        parts = self.config.output_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""

        key = f"{prefix}{feature_group}/dt={date_str}/data.parquet"
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)

        s3 = boto3.client("s3", region_name=self.config.s3_region)
        s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        full_path = f"s3://{bucket}/{key}"
        logger.info("Saved %d rows to %s", len(df), full_path)
        return full_path

    def _push_online_features(self, results: dict[str, pd.DataFrame]) -> None:
        """Push latest features to Redis for real-time serving."""
        import redis as redis_lib
        import json as json_mod

        client = redis_lib.from_url(self.config.redis_url, decode_responses=True)
        ttl = self.config.online_ttl_seconds
        pushed = 0

        # Push identity features
        if "identity_features" in results:
            for _, row in results["identity_features"].iterrows():
                entity_id = row.get("identity_id", "")
                if entity_id:
                    features = row.drop(labels=["identity_id"], errors="ignore").to_dict()
                    key = f"features:identity:{entity_id}"
                    client.setex(key, ttl, json_mod.dumps(features, default=str))
                    pushed += 1

        # Push session features (latest snapshot)
        if "session_features" in results:
            for _, row in results["session_features"].iterrows():
                session_id = row.get("session_id", "")
                if session_id:
                    features = row.drop(labels=["session_id"], errors="ignore").to_dict()
                    key = f"features:session:{session_id}"
                    client.setex(key, ttl, json_mod.dumps(features, default=str))
                    pushed += 1

        logger.info("Pushed %d feature records to Redis", pushed)

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _ensure_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
        """Ensure a column is datetime64; convert in-place if needed."""
        if col in df.columns and not pd.api.types.is_datetime64_any_dtype(df[col]):
            df = df.copy()
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
        return df

    @staticmethod
    def _resolve_identity_column(events: pd.DataFrame) -> str | None:
        """Find the best identity column available in the DataFrame."""
        for candidate in ("identity_id", "user_id", "anonymous_id"):
            if candidate in events.columns:
                return candidate
        return None

    @staticmethod
    def _categorize_page(url: Any) -> str:
        """Classify a URL into a semantic page category."""
        if not isinstance(url, str):
            return "other"
        url_lower = url.lower()
        categories: dict[str, list[str]] = {
            "product": ["/product", "/item", "/listing"],
            "category": ["/category", "/collection", "/shop"],
            "cart": ["/cart", "/basket"],
            "checkout": ["/checkout", "/payment"],
            "account": ["/account", "/profile", "/settings"],
            "blog": ["/blog", "/article", "/post"],
            "home": ["/home", "/index"],
            "search": ["/search", "/results"],
            "pricing": ["/pricing", "/plans"],
        }
        for cat, patterns in categories.items():
            if any(p in url_lower for p in patterns):
                return cat
        # Root path heuristic
        if url_lower.rstrip("/") == "" or url_lower.endswith("/index.html"):
            return "home"
        return "other"

    @staticmethod
    def _derive_channel(event: Any) -> str:
        """Derive the marketing channel from event UTM parameters and referrer."""
        utm_source = str(event.get("utm_source", "") or "")
        utm_medium = str(event.get("utm_medium", "") or "")
        referrer = str(event.get("referrer_domain", "") or "")

        if utm_medium in ("cpc", "ppc"):
            return "paid_search"
        if "paid" in utm_medium and "social" in utm_medium:
            return "social_paid"
        if utm_medium == "social":
            return "social_organic"
        if utm_medium == "email":
            return "email"
        if utm_medium == "display":
            return "display"
        if utm_medium == "affiliate":
            return "affiliate"

        search_engines = ("google", "bing", "yahoo", "duckduckgo", "baidu")
        if any(se in referrer.lower() for se in search_engines):
            return "organic_search"

        social_domains = ("facebook", "twitter", "linkedin", "instagram", "tiktok", "reddit")
        if any(sd in referrer.lower() for sd in social_domains):
            return "social_organic"

        if referrer:
            return "referral"

        return "direct"

    def _key_in_date_range(self, key: str) -> bool:
        """Check if an S3 partition key falls within the configured date range."""
        for part in key.split("/"):
            if part.startswith("dt="):
                dt_str = part.split("=", 1)[1]
                if self.config.start_date and dt_str < self.config.start_date:
                    return False
                if self.config.end_date and dt_str > self.config.end_date:
                    return False
                return True
        # No date partition found -- include by default
        return True
