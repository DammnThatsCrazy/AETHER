"""
Aether Agent Layer — Backend Run Client

Worker-side httpx client for the backend execution-bridge callback path:

    POST {AETHER_BACKEND_URL}/v1/agent/runs/{run_id}/status

Authenticates with the worker service credential (AETHER_WORKER_TOKEN), which
must carry the ``agent:run_update`` permission — ordinary operator tokens are
rejected by the backend so workers cannot be spoofed.

Fail-safe by design: transient transport errors and 5xx responses are retried
with backoff, and the client NEVER raises out of ``post_run_status`` — a
callback failure must not crash a worker mid-task. The return value tells the
caller whether the backend accepted the update.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("aether.runtime.backend_client")

BACKEND_URL_ENV = "AETHER_BACKEND_URL"
WORKER_TOKEN_ENV = "AETHER_WORKER_TOKEN"

_DEFAULT_TIMEOUT_S = float(os.getenv("AETHER_BACKEND_TIMEOUT_S", "10"))
_DEFAULT_MAX_RETRIES = int(os.getenv("AETHER_BACKEND_MAX_RETRIES", "3"))
_RETRY_BACKOFF_S = float(os.getenv("AETHER_BACKEND_RETRY_BACKOFF_S", "0.5"))


class BackendRunClient:
    """Posts worker run status updates back to the Aether backend."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv(BACKEND_URL_ENV, "")).rstrip("/")
        self.token = token if token is not None else os.getenv(WORKER_TOKEN_ENV, "")
        self.timeout_s = timeout_s
        self.max_retries = max(1, max_retries)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def post_run_status(
        self,
        run_id: str,
        status: str,
        output: Optional[dict[str, Any]] = None,
        error: str = "",
        tenant_id: str = "",
        worker_id: str = "",
        heartbeat_at: Optional[str] = None,
    ) -> bool:
        """Report running/completed/failed/retry for a run. Never raises.

        The backend scopes the run lookup to the tenant resolved from the
        worker credential; ``tenant_id`` is sent for log correlation only.
        """
        if not self.configured:
            logger.warning(
                "Backend run callback skipped (AETHER_BACKEND_URL not set): run=%s status=%s",
                run_id, status,
            )
            return False
        try:
            import httpx
        except ImportError:
            logger.error("Backend run callback skipped (httpx not installed): run=%s", run_id)
            return False

        url = f"{self.base_url}/v1/agent/runs/{run_id}/status"
        body: dict[str, Any] = {"status": status, "error": error, "worker_id": worker_id}
        if output is not None:
            body["output"] = output
        if heartbeat_at:
            body["heartbeat_at"] = heartbeat_at

        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.post(url, json=body, headers=self._headers(), timeout=self.timeout_s)
                if response.status_code < 400:
                    logger.info(
                        "Run status reported: run=%s status=%s tenant=%s http=%s",
                        run_id, status, tenant_id, response.status_code,
                    )
                    return True
                if response.status_code < 500:
                    # 4xx is not transient (bad credential / unknown run /
                    # illegal transition) — retrying cannot help.
                    logger.error(
                        "Run status rejected: run=%s status=%s http=%s",
                        run_id, status, response.status_code,
                    )
                    return False
                logger.warning(
                    "Run status attempt %d/%d got %s: run=%s",
                    attempt, self.max_retries, response.status_code, run_id,
                )
            except Exception as exc:
                logger.warning(
                    "Run status attempt %d/%d failed: run=%s error=%s",
                    attempt, self.max_retries, run_id, type(exc).__name__,
                )
            if attempt < self.max_retries:
                time.sleep(_RETRY_BACKOFF_S * attempt)
        logger.error(
            "Run status callback exhausted retries: run=%s status=%s tenant=%s",
            run_id, status, tenant_id,
        )
        return False


_client: BackendRunClient | None = None


def get_backend_client() -> BackendRunClient:
    """Process-wide client (reads env once; workers restart to reconfigure)."""
    global _client
    if _client is None:
        _client = BackendRunClient()
    return _client
