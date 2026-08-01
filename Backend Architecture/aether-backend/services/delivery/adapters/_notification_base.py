"""Shared base for the mobile / notification push + email provider adapters.

APNs, FCM, Web Push (VAPID) and email share one honesty contract:

  * Secrets resolve from the credential platform (``byok:notification:<slot>``),
    never from source or logs.
  * When no real credential is configured, a **provider-shaped local fake** stands
    in — but ONLY in a ``local``/``dev`` environment. In an ``integration``/
    ``staging``/``production`` environment a missing credential fails closed with
    ``ConfigurationError``; the fake is impossible in production, matching
    ``production_fake_forbidden: true`` in ``config/credential_contracts.yaml``.
  * A receipt records provider-*acceptance*, never delivery/open/read. The fake
    external_id is provider-shaped and clearly local; it is never ``sim-``-prefixed
    (which ``AdapterReceipt`` rejects outright), so a fake can never masquerade as a
    verified remote id, yet it also can never be mistaken for one at a glance.

The network transport is **injectable** so the request-construction and
response-mapping logic is unit-testable without a live provider. Live sends to
Apple/Google/SES are externally blocked (no provider credentials/reachability in
this session) — see ``reports/mobile-productization/external-blockers.json``.
"""
from __future__ import annotations

import uuid
from abc import abstractmethod
from typing import Any, Awaitable, Callable, Optional

from config.settings import Environment, settings
from shared.credentials.service import byok_ref
from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
)

logger = get_logger("aether.delivery.adapters.notification")

# (method, url, headers, body_bytes) -> (http_status, response_json_with_headers)
Transport = Callable[
    [str, str, dict[str, str], bytes],
    Awaitable[tuple[int, dict[str, Any]]],
]

# Environments where a provider fake may stand in for a missing credential.
# Everything else (integration/staging/production) fails closed.
_FAKE_ALLOWED_ENVS = (Environment.LOCAL, Environment.DEV)


async def _aiohttp_transport(
    method: str, url: str, headers: dict[str, str], body: bytes
) -> tuple[int, dict[str, Any]]:
    """Default live transport — POSTs to the real provider via aiohttp.

    Only exercised in a deployed environment with a real credential; unit tests
    inject a stub transport instead. Response headers are folded into the returned
    dict under ``_headers`` (lower-cased) so header-carried ids (APNs ``apns-id``,
    Web Push ``location``) survive the generic signature.
    """
    try:
        import aiohttp
    except ImportError as exc:  # pragma: no cover - deploy-only path
        raise ConfigurationError(
            "aiohttp is required for live notification delivery"
        ) from exc

    async with aiohttp.ClientSession() as session:  # pragma: no cover - deploy-only
        async with session.request(
            method,
            url,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {"_raw": data}
            data["_headers"] = {k.lower(): v for k, v in resp.headers.items()}
            return status, data


class NotificationProviderAdapter(ProviderAdapter):
    """Base for APNs / FCM / Web Push / email adapters (fake-or-real, prod-guarded)."""

    #: byok slot suffix — resolves to ``byok:notification:<credential_slot>``.
    credential_slot: str = ""

    def __init__(self, transport: Optional[Transport] = None) -> None:
        self._transport: Transport = transport or _aiohttp_transport

    # ── credential / fake / production guard ─────────────────────────────
    @property
    def secret_reference(self) -> str:
        return byok_ref("notification", self.credential_slot)

    def _fake_allowed(self) -> bool:
        return settings.env in _FAKE_ALLOWED_ENVS

    def _guard_fake(self) -> None:
        if not self._fake_allowed():
            raise ConfigurationError(
                f"{self.adapter_name}: no credential configured for "
                f"{self.secret_reference!r} and the provider fake is forbidden in "
                f"env={settings.env.value}. Provision the credential "
                f"(config/credential_contracts.yaml) — a missing credential is not a "
                f"delivery, and a fake is never a production sender."
            )

    def _fake_external_id(self) -> str:
        return f"{self.adapter_name}-local-{uuid.uuid4().hex}"

    def _fake_receipt(self, recipient: str) -> AdapterReceipt:
        ext = self._fake_external_id()
        logger.info(
            "notification provider fake accepted (env=%s adapter=%s) — provider-shaped "
            "local acceptance, NOT a real delivery",
            settings.env.value,
            self.adapter_name,
        )
        return AdapterReceipt(
            external_id=ext,
            raw_response={
                "fake": True,
                "provider": self.adapter_name,
                "env": settings.env.value,
                "recipient_present": bool(recipient),
            },
            http_status=202,
        )

    def _resolve_credential(
        self, credential: Optional[str], provider_config: dict[str, Any]
    ) -> Optional[str]:
        return credential or provider_config.get("credential")

    # ── redacted push content ────────────────────────────────────────────
    def _push_alert(
        self, payload: dict[str, Any], provider_config: dict[str, Any]
    ) -> tuple[str, str]:
        """Title + body for a push alert. Body is redacted unless the caller opted
        into full content — push payloads are redacted by default."""
        title = payload.get("title", "Aether")
        if provider_config.get("allow_full_content"):
            body = payload.get("body") or payload.get("summary", "")
        else:
            body = payload.get("redacted_body") or "You have a new update."
        return title, body

    # ── dispatch ─────────────────────────────────────────────────────────
    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        recipient = self._recipient(provider_config)
        if not recipient:
            raise ConfigurationError(
                f"{self.adapter_name}: provider_config missing a recipient/device token"
            )
        token = self._resolve_credential(credential, provider_config)
        if not token:
            # No real credential → provider fake, and only outside prod-shaped envs.
            self._guard_fake()
            return self._fake_receipt(recipient)
        method, url, headers, body = self._build_request(
            payload, provider_config, token, idempotency_key
        )
        status, data = await self._transport(method, url, headers, body)
        self._raise_for_status(status, data)
        return self._map_success(status, data, provider_config, idempotency_key)

    def _raise_for_status(self, status: int, data: dict[str, Any]) -> None:
        if status == 429:
            raise RetryableProviderError(
                f"{self.adapter_name} rate-limited: HTTP 429", http_status=429
            )
        if status >= 500:
            raise RetryableProviderError(
                f"{self.adapter_name} server error: HTTP {status}", http_status=status
            )
        if status >= 400:
            raise ProviderError(
                f"{self.adapter_name} client error: HTTP {status} — {data}",
                http_status=status,
            )

    # ── subclass hooks ───────────────────────────────────────────────────
    @abstractmethod
    def _recipient(self, provider_config: dict[str, Any]) -> str:
        """The provider recipient identifier (device token / endpoint / address)."""

    @abstractmethod
    def _build_request(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        token: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str, dict[str, str], bytes]:
        """Return ``(method, url, headers, body_bytes)`` for the live request."""

    @abstractmethod
    def _map_success(
        self,
        status: int,
        data: dict[str, Any],
        provider_config: dict[str, Any],
        idempotency_key: Optional[str],
    ) -> AdapterReceipt:
        """Map a 2xx provider response to an ``AdapterReceipt`` with a real id."""
