"""Aether Python Server Client — batched event observation with consent and retry.

Security invariants:
  - execution_by_aether is never set (Aether observes, never executes)
  - credit and location require explicit grant(); grant_all() excludes them
  - properties are scrubbed of sensitive fields before transmission
  - no secrets or raw payloads are logged
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    import httpx as _httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

from .queue import EventQueue
from .scrubber import scrub_sensitive_fields

_EXPLICIT_OPT_IN = frozenset({"credit", "location"})
_ALL_PURPOSES = frozenset({
    "analytics", "marketing", "personalization", "web3",
    "agent", "commerce", "credit", "location",
})
_DEFAULT_ENDPOINT = "https://ingest.aether.so/v1/batch"


class AetherServerClient:
    """
    Thread-safe server-side event observation client.

    Basic usage::

        client = AetherServerClient(write_key="wk_...", consent={"analytics": True})
        client.track(user_id="u_123", event_type="api_request_observed",
                     properties={"path": "/api/data", "status_code": 200})
        client.flush()
    """

    def __init__(
        self,
        write_key: str,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        consent: dict[str, bool] | None = None,
        flush_at: int = 100,
        flush_interval_s: float = 5.0,
        max_queue_size: int = 1000,
        timeout_s: float = 10.0,
    ) -> None:
        self._write_key = write_key
        self._endpoint = endpoint
        self._consent: dict[str, bool] = {p: False for p in _ALL_PURPOSES}
        if consent:
            for k, v in consent.items():
                if k in _ALL_PURPOSES:
                    self._consent[k] = bool(v)
        self._flush_at = flush_at
        self._flush_interval_s = flush_interval_s
        self._timeout_s = timeout_s
        self._queue = EventQueue(max_size=max_queue_size)
        self._lock = threading.Lock()
        self._events_delivered = 0
        self._events_failed = 0
        self._flush_errors = 0
        self._last_flush_at: str | None = None
        self._last_error: str | None = None
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._shutdown_event = threading.Event()
        self._flush_thread.start()

    # ------------------------------------------------------------------
    # Consent management
    # ------------------------------------------------------------------

    def grant(self, purposes: list[str]) -> None:
        """Grant consent for the specified purposes."""
        with self._lock:
            for p in purposes:
                if p in _ALL_PURPOSES:
                    self._consent[p] = True

    def grant_all(self) -> None:
        """Grant all purposes that do not require explicit opt-in (credit/location excluded)."""
        self.grant([p for p in _ALL_PURPOSES if p not in _EXPLICIT_OPT_IN])

    def revoke(self, purposes: list[str]) -> None:
        """Revoke consent for the specified purposes."""
        with self._lock:
            for p in purposes:
                if p in _ALL_PURPOSES:
                    self._consent[p] = False

    def get_consent(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._consent)

    # ------------------------------------------------------------------
    # Event tracking
    # ------------------------------------------------------------------

    def track(
        self,
        *,
        event_type: str,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        properties: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        timestamp: str | None = None,
        message_id: str | None = None,
    ) -> None:
        """Queue a single event for batched delivery."""
        scrubbed = scrub_sensitive_fields(properties or {})
        event: dict[str, Any] = {
            "type": event_type,
            "messageId": message_id or str(uuid.uuid4()),
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "properties": scrubbed,
        }
        if user_id:
            event["userId"] = user_id
        if anonymous_id:
            event["anonymousId"] = anonymous_id
        if context:
            event["context"] = context

        with self._lock:
            enqueued = self._queue.enqueue([event])
            size = self._queue.size

        if not enqueued:
            return
        if size >= self._flush_at:
            self._do_flush()

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Flush all queued events synchronously."""
        self._do_flush()

    def shutdown(self) -> None:
        """Flush remaining events and stop the background flush thread."""
        self._shutdown_event.set()
        self._flush_thread.join(timeout=30)
        self._do_flush()

    def health(self) -> dict[str, Any]:
        return {
            "queue_size": self._queue.size,
            "events_delivered": self._events_delivered,
            "events_failed": self._events_failed,
            "flush_errors": self._flush_errors,
            "last_flush_at": self._last_flush_at,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        while not self._shutdown_event.wait(timeout=self._flush_interval_s):
            self._do_flush()

    def _do_flush(self) -> None:
        if not _HAS_HTTPX:
            return
        with self._lock:
            granted = [p for p, v in self._consent.items() if v]
            batch = self._queue.dequeue_ready()

        while batch is not None:
            try:
                resp = _httpx.post(
                    self._endpoint,
                    json={"events": batch.events, "consents": granted},
                    headers={
                        "Authorization": f"Bearer {self._write_key}",
                        "X-Aether-Source": "python-server-sdk",
                    },
                    timeout=self._timeout_s,
                )
                if resp.is_success:
                    self._events_delivered += len(batch.events)
                    self._last_flush_at = datetime.now(timezone.utc).isoformat()
                elif resp.status_code >= 500 or resp.status_code == 429:
                    self._queue.requeue(batch)
                    self._events_failed += len(batch.events)
                else:
                    self._events_failed += len(batch.events)
            except Exception as exc:
                self._flush_errors += 1
                self._last_error = str(exc)
                self._queue.requeue(batch)

            with self._lock:
                batch = self._queue.dequeue_ready()
