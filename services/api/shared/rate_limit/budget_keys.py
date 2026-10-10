"""
Aether Shared — Distributed Budget Key Schema

Redis key construction for multi-axis extraction budgets.
Keys follow the pattern: aether:exbudget:{axis}:{identifier}:{window}:{bucket}

Axes:
    api_key, tenant, ip, device, identity_cluster, graph_cluster,
    model_family, endpoint, batch_privilege
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional


class BudgetAxis(str, Enum):
    """Budget enforcement axes — each tracks a different identity dimension."""
    API_KEY = "api_key"
    TENANT = "tenant"
    IP = "ip"
    IP_PREFIX = "ip_prefix"
    DEVICE = "device"
    IDENTITY_CLUSTER = "identity_cluster"
    GRAPH_CLUSTER = "graph_cluster"
    MODEL_FAMILY = "model_family"
    ENDPOINT = "endpoint"
    BATCH_PRIVILEGE = "batch_privilege"


class BudgetWindow(str, Enum):
    """Time windows for budget enforcement."""
    MINUTE = "1m"
    HOUR = "1h"
    DAY = "1d"


# Window durations in seconds
WINDOW_SECONDS: dict[BudgetWindow, int] = {
    BudgetWindow.MINUTE: 60,
    BudgetWindow.HOUR: 3600,
    BudgetWindow.DAY: 86400,
}

# Redis key prefix
KEY_PREFIX = "aether:exbudget"


def budget_key(
    axis: BudgetAxis,
    identifier: str,
    window: BudgetWindow,
    now: Optional[float] = None,
) -> str:
    """Build a Redis key for a budget counter.

    The bucket suffix ensures counters auto-rotate with each window.
    """
    ts = now or time.time()
    bucket = int(ts // WINDOW_SECONDS[window])
    return f"{KEY_PREFIX}:{axis.value}:{identifier}:{window.value}:{bucket}"


def budget_key_ttl(window: BudgetWindow) -> int:
    """TTL for a budget key — slightly longer than the window to prevent premature expiry."""
    return WINDOW_SECONDS[window] + 10


def feature_fingerprint_key(axis: BudgetAxis, identifier: str) -> str:
    """Key for tracking unique feature fingerprints (HyperLogLog)."""
    return f"{KEY_PREFIX}:fp:{axis.value}:{identifier}"


def model_enumeration_key(axis: BudgetAxis, identifier: str) -> str:
    """Key for tracking distinct models queried (set)."""
    return f"{KEY_PREFIX}:models:{axis.value}:{identifier}"


def entropy_budget_key(axis: BudgetAxis, identifier: str) -> str:
    """Key for tracking entropy budget consumption."""
    return f"{KEY_PREFIX}:entropy:{axis.value}:{identifier}"


def confidence_disclosure_key(axis: BudgetAxis, identifier: str) -> str:
    """Key for tracking confidence disclosure budget."""
    return f"{KEY_PREFIX}:disclosure:{axis.value}:{identifier}"


def cluster_aggregate_key(cluster_id: str, window: BudgetWindow) -> str:
    """Key for cluster-wide aggregate budget counters."""
    ts = time.time()
    bucket = int(ts // WINDOW_SECONDS[window])
    return f"{KEY_PREFIX}:cluster:{cluster_id}:{window.value}:{bucket}"
