"""
AWS Client Factory — centralised boto3 session management.
Provides lazy-initialised, cached clients with graceful fallback
when credentials are unavailable (demo/CI mode).
"""

from __future__ import annotations

import os
from typing import Any, Optional


# ── Stub mode detection ────────────────────────────────────────────────
# If AETHER_STUB_AWS=1 or boto3 is unavailable, all client calls
# return None so operational scripts can fall back to illustrative data.

def _stub_mode_enabled() -> bool:
    return os.environ.get("AETHER_STUB_AWS", "0") == "1"

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
    )
    BOTO_AVAILABLE = True
except ImportError:
    BOTO_AVAILABLE = False
    # Provide type stubs so the rest of the codebase can import names
    BotoCoreError = Exception  # type: ignore[misc]
    ClientError = Exception    # type: ignore[misc]
    NoCredentialsError = Exception  # type: ignore[misc]


class AWSClientFactory:
    """Lazy, cached boto3 client/resource factory.

    Features:
      - Per-service client caching (don't create a new client every call)
      - Configurable region, profile, retries
      - Graceful stub mode for demo / CI environments
    """

    def __init__(
        self,
        region: str = "us-east-1",
        profile: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.region = region
        self.profile = profile
        self.max_retries = max_retries
        self._session: Any = None
        self._clients: dict[str, Any] = {}

    @property
    def is_stub(self) -> bool:
        return _stub_mode_enabled() or not BOTO_AVAILABLE

    def _get_session(self) -> Any:
        if self._session is None and not self.is_stub:
            kwargs: dict[str, Any] = {"region_name": self.region}
            if self.profile:
                kwargs["profile_name"] = self.profile
            self._session = boto3.Session(**kwargs)
        return self._session

    def client(self, service: str, region: Optional[str] = None) -> Any:
        """Get or create a boto3 client for *service*.

        Returns None in stub mode — callers must handle this.
        """
        if self.is_stub:
            return None

        cache_key = f"{service}:{region or self.region}"
        if cache_key not in self._clients:
            session = self._get_session()
            config = BotoConfig(
                retries={"max_attempts": self.max_retries, "mode": "adaptive"},
                connect_timeout=5,
                read_timeout=30,
            )
            self._clients[cache_key] = session.client(
                service,
                region_name=region or self.region,
                config=config,
            )
        return self._clients[cache_key]

    def safe_call(self, service: str, method: str, **kwargs: Any) -> Optional[dict]:
        """Execute a boto3 API call with error handling.

        Returns the response dict or None on failure.
        Logs errors via shared.runner.log().
        """
        cl = self.client(service)
        if cl is None:
            return None
        try:
            fn = getattr(cl, method)
            return fn(**kwargs)
        except Exception as e:
            from shared.runner import log
            log(f"AWS API error ({service}.{method}): {e}", tag="AWS")
            return None


# ── Module-level singleton ─────────────────────────────────────────────
# All scripts import this instance.

aws_client = AWSClientFactory(
    region=os.environ.get("AWS_REGION", "us-east-1"),
    profile=os.environ.get("AWS_PROFILE"),
)
