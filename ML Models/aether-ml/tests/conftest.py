"""
Aether ML -- Pytest fixtures with synthetic data for all 9 model types.

Provides reusable (X, y) tuples appropriate for each model:
  Edge:   intent_data, bot_data, session_data
  Server: churn_data, ltv_data, identity_data,
          journey_data, anomaly_data, attribution_data

Also provides raw_events fixture for feature-engineering tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest


# =============================================================================
# EDGE MODEL FIXTURES
# =============================================================================


@pytest.fixture
def intent_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for intent prediction (multi-class classification).

    Features match IntentPrediction.FEATURE_NAMES.
    Labels are integers 0..3 representing 4 intent classes.
    """
    rng = np.random.default_rng(42)
    n = 500

    X = pd.DataFrame(
        {
            "click_count": rng.integers(0, 50, n),
            "scroll_depth": rng.uniform(0, 1, n),
            "time_on_page": rng.uniform(1, 300, n),
            "pages_viewed": rng.integers(1, 20, n),
            "last_action_encoded": rng.integers(0, 5, n),
            "session_duration": rng.uniform(10, 1800, n),
            "device_type_encoded": rng.integers(0, 3, n),
        }
    )
    y = pd.Series(rng.integers(0, 4, n), name="target")
    return X, y


@pytest.fixture
def bot_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for bot detection (binary classification).

    Features match BotDetection.FEATURE_NAMES.
    Labels are 0 (human) or 1 (bot).
    """
    rng = np.random.default_rng(42)
    n = 500
    n_bots = int(n * 0.15)
    n_humans = n - n_bots

    # Human rows: natural variance
    human = pd.DataFrame(
        {
            "mouse_speed_mean": rng.exponential(1.5, n_humans),
            "mouse_speed_std": rng.exponential(0.8, n_humans),
            "click_interval_mean": rng.lognormal(1.5, 0.8, n_humans),
            "click_interval_std": rng.exponential(500, n_humans),
            "scroll_pattern_entropy": rng.uniform(2, 5, n_humans),
            "keystroke_timing_variance": rng.exponential(0.5, n_humans),
            "session_duration": rng.exponential(300, n_humans),
            "page_views": rng.integers(1, 20, n_humans).astype(float),
            "unique_pages": rng.integers(1, 15, n_humans).astype(float),
            "js_execution_time": rng.exponential(50, n_humans),
            "has_webdriver": rng.choice([0, 1], n_humans, p=[0.95, 0.05]).astype(float),
            "user_agent_anomaly_score": rng.uniform(0, 0.3, n_humans),
        }
    )
    # Bot rows: mechanical patterns
    bot = pd.DataFrame(
        {
            "mouse_speed_mean": rng.uniform(0, 0.2, n_bots),
            "mouse_speed_std": rng.uniform(0, 0.1, n_bots),
            "click_interval_mean": rng.uniform(0.05, 0.5, n_bots),
            "click_interval_std": rng.uniform(0, 50, n_bots),
            "scroll_pattern_entropy": rng.uniform(0, 0.5, n_bots),
            "keystroke_timing_variance": rng.uniform(0, 0.05, n_bots),
            "session_duration": rng.uniform(5, 30, n_bots),
            "page_views": rng.integers(50, 200, n_bots).astype(float),
            "unique_pages": rng.integers(1, 3, n_bots).astype(float),
            "js_execution_time": rng.uniform(0, 5, n_bots),
            "has_webdriver": rng.choice([0, 1], n_bots, p=[0.3, 0.7]).astype(float),
            "user_agent_anomaly_score": rng.uniform(0.5, 1.0, n_bots),
        }
    )

    X = pd.concat([human, bot], ignore_index=True)
    y = pd.Series([0] * n_humans + [1] * n_bots, name="is_bot")

    idx = rng.permutation(len(X))
    return X.iloc[idx].reset_index(drop=True), y.iloc[idx].reset_index(drop=True)


@pytest.fixture
def session_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for session scoring (binary classification).

    Features match SessionScorer.FEATURE_NAMES.
    Labels are 0 (did not convert) or 1 (converted).
    """
    rng = np.random.default_rng(42)
    n = 500

    X = pd.DataFrame(
        {
            "page_views": rng.integers(1, 20, n).astype(float),
            "unique_pages": rng.integers(1, 15, n).astype(float),
            "session_duration": rng.exponential(300, n),
            "scroll_depth_mean": rng.uniform(0, 1, n),
            "click_count": rng.integers(0, 30, n).astype(float),
            "form_interactions": rng.integers(0, 5, n).astype(float),
            "search_queries": rng.integers(0, 3, n).astype(float),
            "product_views": rng.integers(0, 10, n).astype(float),
            "add_to_cart_count": rng.integers(0, 3, n).astype(float),
            "time_to_first_interaction": rng.exponential(30, n),
        }
    )
    # Conversion correlates with engagement
    logit = (
        X["page_views"] * 0.1
        + X["scroll_depth_mean"] * 2
        + X["add_to_cart_count"] * 1.5
        - 3
    )
    prob = 1 / (1 + np.exp(-logit))
    y = pd.Series((rng.random(n) < prob).astype(int), name="converted")
    return X, y


# =============================================================================
# SERVER MODEL FIXTURES
# =============================================================================


@pytest.fixture
def churn_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for churn prediction (binary classification).

    Features match ChurnPrediction.FEATURE_COLS.
    Labels are 0 (retained) or 1 (churned in 30 days).
    """
    rng = np.random.default_rng(42)
    n = 500

    X = pd.DataFrame(
        {
            "days_since_last_visit": rng.exponential(10, n),
            "visit_frequency_30d": rng.exponential(2, n),
            "session_count_30d": rng.integers(0, 30, n).astype(float),
            "avg_session_duration": rng.exponential(120, n),
            "page_views_trend": rng.normal(0, 0.3, n),
            "conversion_count_30d": rng.integers(0, 5, n).astype(float),
            "support_tickets": rng.integers(0, 5, n).astype(float),
            "email_open_rate": rng.uniform(0, 1, n),
            "days_since_signup": rng.integers(1, 365, n).astype(float),
            "lifetime_value": rng.exponential(200, n),
        }
    )
    # Churn correlates with inactivity
    logit = (
        -2
        + X["days_since_last_visit"] * 0.05
        - X["session_count_30d"] * 0.1
        + X["support_tickets"] * 0.5
    )
    prob = 1 / (1 + np.exp(-logit))
    y = pd.Series((rng.random(n) < prob).astype(int), name="churned")
    return X, y


@pytest.fixture
def ltv_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for LTV prediction (regression).

    Features match LTVPrediction.FEATURE_COLS.
    Target is lifetime value in dollars.
    """
    rng = np.random.default_rng(42)
    n = 400

    X = pd.DataFrame(
        {
            "monetary_value": rng.exponential(50, n),
            "frequency": rng.exponential(2, n),
            "recency": rng.exponential(30, n),
            "T": rng.exponential(90, n),
            "avg_order_value": rng.exponential(50, n),
            "purchase_count_90d": rng.integers(0, 10, n).astype(float),
            "days_since_first_purchase": rng.integers(1, 365, n).astype(float),
            "product_categories_count": rng.integers(1, 10, n).astype(float),
            "discount_usage_rate": rng.uniform(0, 1, n),
            "referral_count": rng.integers(0, 5, n).astype(float),
        }
    )
    # LTV correlates with monetary value and frequency
    y = (
        X["monetary_value"] * 3.0
        + X["frequency"] * 20
        + X["avg_order_value"] * 1.5
        + rng.normal(0, 30, n)
    ).clip(lower=0)
    y = pd.Series(y.values, name="ltv_90d")
    return X, y


@pytest.fixture
def identity_data() -> tuple[pd.DataFrame, pd.Series]:
    """Synthetic data for identity resolution (binary classification).

    Features match IdentityResolution.FEATURE_COLS.
    Labels are 0 (different person) or 1 (same person).
    """
    rng = np.random.default_rng(42)
    n = 300

    X = pd.DataFrame(
        {
            "feature_similarity_score": rng.uniform(0, 1, n),
            "email_hash_match": rng.choice([0, 1], n).astype(float),
            "device_fingerprint_similarity": rng.uniform(0, 1, n),
            "ip_proximity": rng.uniform(0, 1, n),
            "session_overlap_ratio": rng.uniform(0, 1, n),
            "behavioral_similarity": rng.uniform(0, 1, n),
            "cookie_match": rng.choice([0, 1], n).astype(float),
        }
    )
    y = pd.Series(rng.choice([0, 1], n, p=[0.6, 0.4]).astype(float), name="same_identity")
    return X, y


@pytest.fixture
def journey_data() -> pd.DataFrame:
    """Synthetic event stream for journey prediction.

    Returns a DataFrame with columns: identity_id, timestamp,
    event_type, page_category.
    """
    rng = np.random.default_rng(42)
    n = 200
    n_identities = 20

    identity_ids = [f"user_{rng.integers(0, n_identities)}" for _ in range(n)]
    base_time = datetime(2025, 1, 1)
    timestamps = [base_time + timedelta(seconds=int(i * 60 + rng.integers(0, 30))) for i in range(n)]
    event_types = rng.choice(
        ["page_view", "click", "scroll", "form_submit", "conversion"],
        n,
        p=[0.35, 0.25, 0.2, 0.1, 0.1],
    )
    page_categories = rng.choice(
        ["home", "product", "cart", "checkout", "pricing", "blog"],
        n,
    )

    return pd.DataFrame(
        {
            "identity_id": identity_ids,
            "timestamp": timestamps,
            "event_type": event_types,
            "page_category": page_categories,
        }
    )


@pytest.fixture
def anomaly_data() -> pd.DataFrame:
    """Synthetic data for anomaly detection (unsupervised).

    Features match AnomalyDetection.FEATURE_COLS.
    """
    rng = np.random.default_rng(42)
    n = 500

    X = pd.DataFrame(
        {
            "requests_per_minute": rng.exponential(100, n),
            "error_rate": rng.beta(1, 50, n),
            "avg_response_time": rng.exponential(200, n),
            "unique_ips": rng.integers(10, 500, n).astype(float),
            "unique_user_agents": rng.integers(5, 100, n).astype(float),
            "payload_size_mean": rng.exponential(1000, n),
            "geographic_entropy": rng.uniform(0, 5, n),
            "new_endpoints_accessed": rng.integers(0, 20, n).astype(float),
            "failed_auth_rate": rng.beta(1, 30, n),
            "time_since_last_spike": rng.exponential(3600, n),
        }
    )
    return X


@pytest.fixture
def attribution_data() -> pd.DataFrame:
    """Synthetic touchpoint data for campaign attribution.

    Returns a DataFrame with conversion journeys and touchpoints.
    """
    rng = np.random.default_rng(42)
    records: list[dict[str, Any]] = []
    base_time = datetime(2025, 1, 1)
    channels = ["organic_search", "paid_search", "email", "social_organic", "direct", "display"]

    for conv_id in range(50):
        n_touches = rng.integers(2, 8)
        conv_value = float(rng.exponential(100))
        for touch_idx in range(n_touches):
            records.append(
                {
                    "conversion_id": f"conv_{conv_id:03d}",
                    "identity_id": f"user_{conv_id % 20:03d}",
                    "timestamp": base_time + timedelta(days=conv_id, hours=touch_idx),
                    "channel": rng.choice(channels),
                    "campaign_id": f"camp_{rng.integers(0, 10):03d}",
                    "conversion_value": conv_value if touch_idx == n_touches - 1 else 0.0,
                }
            )

    return pd.DataFrame(records)


# =============================================================================
# FEATURE ENGINEERING FIXTURES
# =============================================================================


@pytest.fixture
def raw_events() -> pd.DataFrame:
    """Synthetic raw event stream for feature-pipeline tests.

    Contains columns: session_id, user_id, type, timestamp, page_url,
    scroll_depth, mouse_x, mouse_y, device_type, ip_address.
    """
    rng = np.random.default_rng(42)
    n_sessions = 50
    events_per_session = 15
    records: list[dict[str, Any]] = []
    base_time = datetime(2025, 1, 1)

    event_types = ["page", "click", "scroll", "keypress", "form_submit", "conversion"]
    event_probs = [0.25, 0.25, 0.2, 0.15, 0.1, 0.05]

    for s_idx in range(n_sessions):
        session_id = f"sess_{s_idx:04d}"
        user_id = f"user_{s_idx % 20:04d}"
        device = rng.choice(["desktop", "mobile", "tablet"])
        n_events = rng.integers(5, events_per_session * 2)
        session_start = base_time + timedelta(hours=s_idx)

        for e_idx in range(n_events):
            etype = rng.choice(event_types, p=event_probs)
            ts = session_start + timedelta(seconds=int(e_idx * rng.integers(1, 30)))
            records.append(
                {
                    "session_id": session_id,
                    "identity_id": user_id,
                    "type": etype,
                    "timestamp": ts,
                    "page_url": f"/page-{rng.integers(1, 20)}",
                    "scroll_depth": float(rng.uniform(0, 100)) if etype == "scroll" else None,
                    "mouse_x": float(rng.integers(0, 1920)),
                    "mouse_y": float(rng.integers(0, 1080)),
                    "device_type": device,
                    "ip_address": f"192.168.{rng.integers(0,256)}.{rng.integers(0,256)}",
                }
            )

    return pd.DataFrame(records)


class SyntheticDataFactory:
    @staticmethod
    def session_events(n_sessions: int = 10, seed: int = 42) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rows: list[dict[str, Any]] = []
        base_time = datetime(2025, 1, 1)
        for session_idx in range(n_sessions):
            session_id = f"sess_{session_idx:03d}"
            event_count = int(rng.integers(5, 12))
            for event_idx in range(event_count):
                event_type = str(rng.choice(['page_view', 'click', 'scroll', 'conversion'], p=[0.4, 0.35, 0.2, 0.05]))
                rows.append({
                    'session_id': session_id,
                    'timestamp': base_time + timedelta(minutes=session_idx, seconds=event_idx * 15),
                    'event_type': event_type,
                    'page_url': f"/page-{rng.integers(1,5)}",
                    'scroll_depth': float(rng.uniform(0, 100)) if event_type == 'scroll' else 0.0,
                })
        return pd.DataFrame(rows)
