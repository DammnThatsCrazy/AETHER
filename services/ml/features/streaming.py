"""
Aether ML -- Real-Time Streaming Feature Computation

Processes individual events from Kafka/Kinesis in real time, maintains
sliding-window aggregations in memory, and pushes computed features to
Redis for low-latency online serving.

Deployed as: ECS Fargate long-running service.

Usage::

    processor = StreamingFeatureProcessor(
        feature_store_url="redis://aether-cache.internal:6379",
        window_size=300,
    )
    features = processor.process_event(event_dict)
    processor.flush_to_store("session:abc123", features)
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger("aether.ml.features.streaming")


# =============================================================================
# STREAMING WINDOW
# =============================================================================


class StreamingWindow:
    """Sliding/tumbling window for real-time aggregation over keyed time-series.

    Maintains a buffer of ``(timestamp, value)`` pairs per key. Values
    outside the window are lazily evicted on read.

    Args:
        window_size_seconds: Width of the window in seconds (default 300 = 5 min).
        slide_seconds: Minimum interval between eviction sweeps (default 60).
            A smaller slide makes aggregates more precise but costs more CPU.
    """

    def __init__(
        self,
        window_size_seconds: int = 300,
        slide_seconds: int = 60,
    ) -> None:
        self.window_size_seconds = window_size_seconds
        self.slide_seconds = slide_seconds
        # key -> list of (timestamp_float, value_float)
        self._buffers: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self._last_evict: dict[str, float] = {}

    def add(self, key: str, value: float, timestamp: float | None = None) -> None:
        """Append a value to the window for *key*.

        Args:
            key: Entity identifier (e.g. session_id, ip_address).
            value: Numeric observation.
            timestamp: Event epoch timestamp. Defaults to ``time.time()``.
        """
        ts = timestamp if timestamp is not None else time.time()
        self._buffers[key].append((ts, value))

        # Periodic eviction to bound memory
        last = self._last_evict.get(key, 0.0)
        if ts - last >= self.slide_seconds:
            self._evict_expired(key, ts)

    def get_aggregate(self, key: str, agg: str = "mean") -> float:
        """Compute an aggregate over the current window for *key*.

        Supported aggregations: ``mean``, ``sum``, ``count``,
        ``min``, ``max``, ``std``.

        Returns 0.0 if there are no values in the window.
        """
        now = time.time()
        self._evict_expired(key, now)

        values = [v for _, v in self._buffers.get(key, [])]
        if not values:
            return 0.0

        if agg == "mean":
            return float(np.mean(values))
        if agg == "sum":
            return float(np.sum(values))
        if agg == "count":
            return float(len(values))
        if agg == "min":
            return float(np.min(values))
        if agg == "max":
            return float(np.max(values))
        if agg == "std":
            return float(np.std(values)) if len(values) > 1 else 0.0

        raise ValueError(f"Unsupported aggregation: '{agg}'")

    def get_all_aggregates(self, key: str) -> dict[str, float]:
        """Return all supported aggregates for *key* in a single pass."""
        now = time.time()
        self._evict_expired(key, now)

        values = [v for _, v in self._buffers.get(key, [])]
        if not values:
            return {
                "mean": 0.0,
                "sum": 0.0,
                "count": 0.0,
                "min": 0.0,
                "max": 0.0,
                "std": 0.0,
            }

        arr = np.array(values)
        return {
            "mean": float(arr.mean()),
            "sum": float(arr.sum()),
            "count": float(len(arr)),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "std": float(arr.std()) if len(arr) > 1 else 0.0,
        }

    @property
    def active_keys(self) -> int:
        """Number of keys currently tracked."""
        return len(self._buffers)

    def expire_stale_keys(self, max_idle_seconds: float = 3600.0) -> int:
        """Remove keys whose newest value is older than *max_idle_seconds*.

        Returns the number of keys removed.
        """
        now = time.time()
        expired = 0
        for key in list(self._buffers.keys()):
            buf = self._buffers[key]
            if not buf or (now - buf[-1][0]) > max_idle_seconds:
                del self._buffers[key]
                self._last_evict.pop(key, None)
                expired += 1
        return expired

    def _evict_expired(self, key: str, current_time: float) -> None:
        """Remove entries outside the window for *key*."""
        cutoff = current_time - self.window_size_seconds
        buf = self._buffers.get(key)
        if buf is None:
            return

        # Binary-ish fast path: if first entry is within window, nothing to evict
        if buf and buf[0][0] >= cutoff:
            self._last_evict[key] = current_time
            return

        # Find the first entry within the window
        idx = 0
        for i, (ts, _) in enumerate(buf):
            if ts >= cutoff:
                idx = i
                break
        else:
            idx = len(buf)

        if idx > 0:
            self._buffers[key] = buf[idx:]

        self._last_evict[key] = current_time


# =============================================================================
# STREAMING FEATURE PROCESSOR
# =============================================================================


class StreamingFeatureProcessor:
    """Processes events in real time for online feature computation.

    Maintains per-session and global state via ``StreamingWindow`` instances
    and simple counters. Computes features incrementally and can flush
    results to Redis.

    Args:
        feature_store_url: Redis connection URL for online feature storage.
            Set to ``None`` to disable automatic persistence.
        window_size: Window width in seconds for sliding aggregations
            (default 300 = 5 minutes).
    """

    def __init__(
        self,
        feature_store_url: str | None = None,
        window_size: int = 300,
    ) -> None:
        self.feature_store_url = feature_store_url
        self.window_size = window_size

        # Per-metric sliding windows
        self.windows: dict[str, StreamingWindow] = defaultdict(
            lambda: StreamingWindow(window_size_seconds=window_size)
        )

        # Simple per-entity counters
        self.counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Last-seen timestamps per entity
        self.last_seen: dict[str, float] = {}

        # Per-session state for incremental computation
        self._session_state: dict[str, dict[str, Any]] = {}

        # Global anomaly counters (keyed by time bucket)
        self._anomaly_state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"event_count": 0, "error_count": 0, "unique_sessions": set(), "unique_ips": set()}
        )

        # Redis client (lazy init)
        self._redis: Any = None

    # =========================================================================
    # EVENT PROCESSING
    # =========================================================================

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process a single event, update internal state, return computed features.

        The returned dict merges session-level, behavioral, and anomaly
        features so the caller can decide what to serve or persist.
        """
        session_id: str = event.get("session_id", event.get("sessionId", ""))
        event_type: str = event.get("type", "")
        timestamp: float = self._extract_timestamp(event)

        features: dict[str, Any] = {
            "session_id": session_id,
            "event_type": event_type,
            "processed_at": time.time(),
        }

        # Session-level features
        if session_id:
            session_features = self.compute_realtime_session_features(session_id, event)
            features.update(session_features)

            # Behavioral biometrics (only if mouse/click data present)
            if any(k in event for k in ("mouse_x", "mouse_y", "mouse_velocity")):
                behavioral = self.compute_realtime_behavioral_features(session_id, event)
                features.update(behavioral)

        # Anomaly detection counters
        anomaly_features = self.compute_realtime_anomaly_features(event)
        features.update(anomaly_features)

        # Track last seen
        self.last_seen[session_id] = timestamp

        return features

    # =========================================================================
    # REAL-TIME FEATURE COMPUTATIONS
    # =========================================================================

    def compute_realtime_session_features(
        self, session_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Incrementally update and return session-level features.

        Tracks: event_count, page_count, click_count, max_scroll_depth,
        session_duration_s, events_per_minute, unique_pages, has_conversion,
        is_bounce, click_rate.
        """
        if session_id not in self._session_state:
            self._session_state[session_id] = {
                "start_time": self._extract_timestamp(event),
                "event_count": 0,
                "page_count": 0,
                "click_count": 0,
                "scroll_events": 0,
                "max_scroll_depth": 0.0,
                "error_count": 0,
                "has_conversion": False,
                "unique_pages": set(),
            }

        state = self._session_state[session_id]
        event_type = event.get("type", "")
        timestamp = self._extract_timestamp(event)

        state["event_count"] += 1
        state["last_event_time"] = timestamp

        if event_type == "page":
            state["page_count"] += 1
            url = event.get("page_url", event.get("url", ""))
            if url:
                state["unique_pages"].add(url)

        elif event_type == "click":
            state["click_count"] += 1

        elif event_type == "scroll":
            state["scroll_events"] += 1
            depth = event.get("scroll_depth", event.get("depth", 0.0))
            if isinstance(depth, (int, float)):
                # Normalise if depth is in 0-100 range
                normalised = depth / 100.0 if depth > 1.0 else float(depth)
                state["max_scroll_depth"] = max(state["max_scroll_depth"], normalised)

        elif event_type == "conversion":
            state["has_conversion"] = True

        elif event_type == "error":
            state["error_count"] += 1

        # Compute derived features
        duration_s = max(timestamp - state["start_time"], 0.0)
        page_count = max(state["page_count"], 1)

        return {
            "session_event_count": state["event_count"],
            "session_page_count": state["page_count"],
            "session_click_count": state["click_count"],
            "session_max_scroll_depth": state["max_scroll_depth"],
            "session_duration_s": duration_s,
            "session_events_per_minute": state["event_count"] / max(duration_s / 60.0, 0.01),
            "session_unique_pages": len(state["unique_pages"]),
            "session_has_conversion": int(state["has_conversion"]),
            "session_is_bounce": int(state["page_count"] <= 1),
            "session_click_rate": state["click_count"] / page_count,
            "session_error_count": state["error_count"],
        }

    def compute_realtime_behavioral_features(
        self, session_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Incrementally update and return behavioral biometric features.

        Uses sliding windows over mouse velocity, click intervals, and
        scroll patterns.
        """
        timestamp = self._extract_timestamp(event)
        features: dict[str, Any] = {}

        # Mouse velocity
        mouse_x = event.get("mouse_x")
        mouse_y = event.get("mouse_y")
        if mouse_x is not None and mouse_y is not None:
            # If a pre-computed velocity is available, use it
            velocity = event.get("mouse_velocity")
            if velocity is None:
                # Approximate from position delta (requires prior state)
                prev = self._session_state.get(session_id, {})
                prev_x = prev.get("_last_mouse_x")
                prev_y = prev.get("_last_mouse_y")
                prev_t = prev.get("_last_mouse_t")
                if prev_x is not None and prev_y is not None and prev_t is not None:
                    dx = float(mouse_x) - float(prev_x)
                    dy = float(mouse_y) - float(prev_y)
                    dt = timestamp - prev_t
                    velocity = math.sqrt(dx ** 2 + dy ** 2) / max(dt, 0.001)
                # Store current position for next delta
                if session_id in self._session_state:
                    self._session_state[session_id]["_last_mouse_x"] = mouse_x
                    self._session_state[session_id]["_last_mouse_y"] = mouse_y
                    self._session_state[session_id]["_last_mouse_t"] = timestamp

            if velocity is not None:
                self.windows["mouse_velocity"].add(session_id, float(velocity), timestamp)

        # Click intervals
        event_type = event.get("type", "")
        if event_type == "click":
            click_key = f"click_ts:{session_id}"
            last_click_ts = self.last_seen.get(click_key)
            if last_click_ts is not None:
                interval = timestamp - last_click_ts
                self.windows["click_interval"].add(session_id, interval, timestamp)
            self.last_seen[click_key] = timestamp

        # Scroll depth deltas for entropy approximation
        if event_type == "scroll":
            depth = event.get("scroll_depth", event.get("depth", 0.0))
            if isinstance(depth, (int, float)):
                self.windows["scroll_delta"].add(session_id, float(depth), timestamp)

        # Aggregate from windows
        mouse_agg = self.windows["mouse_velocity"].get_all_aggregates(session_id)
        features["rt_mouse_speed_mean"] = mouse_agg["mean"]
        features["rt_mouse_speed_std"] = mouse_agg["std"]

        click_agg = self.windows["click_interval"].get_all_aggregates(session_id)
        features["rt_click_interval_mean"] = click_agg["mean"]
        features["rt_click_interval_std"] = click_agg["std"]

        scroll_agg = self.windows["scroll_delta"].get_all_aggregates(session_id)
        features["rt_scroll_pattern_entropy"] = self._approx_entropy(
            self.windows["scroll_delta"], session_id
        )

        return features

    def compute_realtime_anomaly_features(self, event: dict[str, Any]) -> dict[str, Any]:
        """Update and return global anomaly detection counters.

        Aggregates per 5-minute time bucket: event_count, error_count,
        unique_sessions, unique_ips.
        """
        timestamp = self._extract_timestamp(event)
        # 5-minute bucket key
        bucket = int(timestamp // 300) * 300
        bucket_key = str(bucket)

        state = self._anomaly_state[bucket_key]
        state["event_count"] += 1

        if event.get("type") == "error":
            state["error_count"] += 1

        session_id = event.get("session_id", event.get("sessionId", ""))
        if session_id:
            state["unique_sessions"].add(session_id)

        ip_address = event.get("ip_address", event.get("ip", ""))
        if ip_address:
            state["unique_ips"].add(ip_address)

        # Evict old buckets (keep last 12 = 1 hour of 5-min buckets)
        self._evict_old_anomaly_buckets(bucket, keep_count=12)

        event_count = state["event_count"]
        return {
            "anomaly_bucket": bucket_key,
            "anomaly_event_count": event_count,
            "anomaly_error_count": state["error_count"],
            "anomaly_error_rate": state["error_count"] / max(event_count, 1),
            "anomaly_unique_sessions": len(state["unique_sessions"]),
            "anomaly_unique_ips": len(state["unique_ips"]),
            "anomaly_requests_per_minute": event_count / 5.0,
        }

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def get_session_state(self, session_id: str) -> dict[str, Any]:
        """Return current accumulated state for a session.

        Returns an empty dict if the session has not been seen.
        """
        state = self._session_state.get(session_id, {})
        if not state:
            return {}

        # Serialise sets for JSON compatibility
        result = {}
        for k, v in state.items():
            if isinstance(v, set):
                result[k] = list(v)
            elif k.startswith("_"):
                continue  # skip internal keys
            else:
                result[k] = v
        return result

    def flush_to_store(self, entity_id: str, features: dict[str, Any]) -> None:
        """Push computed features to Redis under the given entity key.

        Features are stored as a JSON hash at ``features:{entity_id}``
        with a TTL of ``window_size * 4`` seconds.

        Args:
            entity_id: Redis key suffix (e.g. ``"session:abc123"``).
            features: Feature dict to persist.
        """
        if self.feature_store_url is None:
            return

        client = self._get_redis_client()
        if client is None:
            return

        key = f"features:{entity_id}"
        ttl = self.window_size * 4  # Keep features for 4x the window

        try:
            # Merge with existing features (append, don't overwrite)
            existing_raw = client.get(key)
            if existing_raw:
                existing = json.loads(existing_raw)
                existing.update(features)
                features = existing

            # Remove non-serialisable values
            clean = {
                k: v for k, v in features.items()
                if not isinstance(v, (set, frozenset))
            }

            client.setex(key, ttl, json.dumps(clean, default=str))
        except Exception as exc:
            logger.warning("Failed to flush features to Redis key '%s': %s", key, exc)

    def expire_idle_sessions(self, max_idle_seconds: float = 3600.0) -> int:
        """Remove session state for sessions idle longer than *max_idle_seconds*.

        Returns the number of sessions removed.
        """
        now = time.time()
        expired = 0
        for session_id in list(self._session_state.keys()):
            last = self.last_seen.get(session_id, 0.0)
            if now - last > max_idle_seconds:
                del self._session_state[session_id]
                self.last_seen.pop(session_id, None)
                expired += 1

        # Also expire window keys
        for window in self.windows.values():
            expired += window.expire_stale_keys(max_idle_seconds)

        if expired > 0:
            logger.info("Expired %d idle sessions/keys", expired)
        return expired

    def get_stats(self) -> dict[str, Any]:
        """Return operational statistics about the processor."""
        return {
            "active_sessions": len(self._session_state),
            "tracked_entities": len(self.last_seen),
            "window_keys": {
                name: window.active_keys for name, window in self.windows.items()
            },
            "anomaly_buckets": len(self._anomaly_state),
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _extract_timestamp(event: dict[str, Any]) -> float:
        """Extract a float epoch timestamp from an event dict.

        Supports ISO-8601 strings, epoch floats/ints, and ``datetime`` objects.
        Falls back to ``time.time()`` if no timestamp is found.
        """
        raw = event.get("timestamp")
        if raw is None:
            return time.time()
        if isinstance(raw, (int, float)):
            # Heuristic: if > 1e12 assume milliseconds
            return raw / 1000.0 if raw > 1e12 else float(raw)
        if isinstance(raw, datetime):
            return raw.timestamp()
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, TypeError):
                return time.time()
        return time.time()

    def _approx_entropy(self, window: StreamingWindow, key: str) -> float:
        """Approximate Shannon entropy from windowed values.

        Bins the absolute deltas and computes the entropy of the
        resulting probability distribution.
        """
        values = [v for _, v in window._buffers.get(key, [])]
        if len(values) < 3:
            return 0.0

        diffs = np.abs(np.diff(values))
        if diffs.sum() == 0:
            return 0.0

        # Simple histogram-based entropy (10 bins)
        counts, _ = np.histogram(diffs, bins=10)
        probs = counts / counts.sum()
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log2(probs)))

    def _get_redis_client(self) -> Any:
        """Lazy-initialise and return a Redis client."""
        if self._redis is None and self.feature_store_url is not None:
            try:
                import redis as redis_lib

                self._redis = redis_lib.from_url(
                    self.feature_store_url, decode_responses=True
                )
            except Exception as exc:
                logger.warning("Failed to connect to Redis: %s", exc)
                return None
        return self._redis

    def _evict_old_anomaly_buckets(self, current_bucket: int, keep_count: int = 12) -> None:
        """Remove anomaly buckets older than *keep_count* windows."""
        cutoff = current_bucket - (keep_count * 300)
        for bucket_key in list(self._anomaly_state.keys()):
            try:
                if int(bucket_key) < cutoff:
                    del self._anomaly_state[bucket_key]
            except ValueError:
                pass


# ------------------------------------------------------------------
# Legacy processor wrappers expected by the ML tests
# ------------------------------------------------------------------


class SessionFeatureProcessor:
    def __init__(self) -> None:
        self._processor = StreamingFeatureProcessor()
        self._sessions = self._processor._session_state

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        flat_event = {**event, **event.get('properties', {})}
        if flat_event.get('type') == 'track' and flat_event.get('event') == 'click':
            flat_event['type'] = 'click'
        if flat_event.get('type') == 'track' and flat_event.get('event') == 'scroll_depth':
            flat_event['type'] = 'scroll'
            flat_event['scroll_depth'] = flat_event.get('depth', flat_event.get('scroll_depth', 0.0))
        if flat_event.get('type') == 'page' and 'url' in flat_event:
            flat_event['page_url'] = flat_event['url']
        result = self._processor.compute_realtime_session_features(event.get('sessionId', event.get('session_id', '')), flat_event)
        return {
            'event_count': result['session_event_count'],
            'page_count': result['session_page_count'],
            'click_count': result['session_click_count'],
            'max_scroll_depth': result['session_max_scroll_depth'],
        }


class IdentityFeatureProcessor:
    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        identity_id = event.get('anonymousId') or event.get('identity_id') or 'anonymous'
        session_id = event.get('sessionId') or event.get('session_id') or 'unknown'
        state = self._state.setdefault(identity_id, {'sessions': set(), 'events': 0})
        state['sessions'].add(session_id)
        state['events'] += 1
        return {'total_sessions': len(state['sessions']), 'total_events': state['events']}


class WalletFeatureProcessor:
    def __init__(self) -> None:
        self._wallets: dict[str, dict[str, Any]] = {}

    def process_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if event.get('type') != 'transaction':
            return None
        props = event.get('properties', {})
        address = props.get('address') or event.get('address')
        if not address:
            return None
        state = self._wallets.setdefault(address, {'tx_count': 0, 'chains': set()})
        state['tx_count'] += 1
        if props.get('chainId') is not None:
            state['chains'].add(props['chainId'])
        return {'tx_count': state['tx_count'], 'unique_chains': len(state['chains'])}


class _AggregateState:
    def __init__(self) -> None:
        self.values: list[float] = []
        self.last_updated: float = time.time()


class WindowedAggregator:
    def __init__(self, window_seconds: int = 300) -> None:
        self.window_seconds = window_seconds
        self._states: dict[str, dict[str, _AggregateState]] = defaultdict(dict)

    def update(self, entity_id: str, metric: str, value: float) -> None:
        state = self._states[entity_id].setdefault(metric, _AggregateState())
        state.values.append(float(value))
        state.last_updated = time.time()

    def get_features(self, entity_id: str) -> dict[str, float]:
        features: dict[str, float] = {}
        for metric, state in self._states.get(entity_id, {}).items():
            features[f'{metric}_count'] = len(state.values)
            features[f'{metric}_sum'] = float(sum(state.values))
        return features

    def expire_stale(self, max_idle_seconds: float = 3600.0) -> int:
        now = time.time()
        expired = 0
        for entity_id in list(self._states.keys()):
            metrics = self._states[entity_id]
            if metrics and all((now - metric_state.last_updated) > max_idle_seconds for metric_state in metrics.values()):
                del self._states[entity_id]
                expired += 1
        return expired

    @property
    def entity_count(self) -> int:
        return len(self._states)
