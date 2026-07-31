"""Payment rail adapter contract — provider-safe seam for payment observability.

``PaymentRailAdapter`` is the blueprint every named payment rail adapter
(Privy, Stripe crypto onramp, Coinbase, MoonPay, Bridge) implements.

INVARIANTS
- Aether OBSERVES payments. Adapters never execute, settle, originate, or
  sign anything and never custody funds.
- Import-safe and offline by default: no provider SDK imports at module load;
  ``httpx`` may only be imported inside methods and only when the tenant has
  configured credentials (never in local mode / tests).
- Secrets live in the BYOK key vault and are never logged, persisted in
  records, or returned in responses — only masked identifiers.
- Provider payloads are sanitized before they reach any store: card numbers,
  bank/routing numbers, IBANs, SSNs, and KYC document fields are rejected
  (stripped) recursively.
- ``not_configured()`` is a typed response, not an exception — a tenant
  without provider credentials gets a structured 409-style answer, never a 500.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, ValidationError

from shared.logger.logger import get_logger
from shared.providers.key_vault import BYOKKeyVault

from services.integrations.providers.payment_rails.models import (
    CANONICAL_STATUS_ORDERING,
    PAYMENT_RAILS_SCHEMA_VERSION,
    FundingSession,
    PaymentRailStatusMap,
    new_id,
    utc_now_iso,
)

logger = get_logger("aether.payment_rails.base")

# ─────────────────────────────────────────────────────────────────────────────
# Sensitive-field reject/redact list
# ─────────────────────────────────────────────────────────────────────────────
# Matched case-insensitively against payload/metadata keys, recursively.
# Matching keys are removed entirely (not masked) so raw payment instruments,
# bank coordinates, KYC identifiers, and secrets never reach stores, logs, or
# responses. Keys that explicitly declare masked/last4 values are kept.

SENSITIVE_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"card[_\s-]?number", r"\bpan\b", r"\bcvv\b", r"\bcvc\b", r"\bcvn\b",
        r"card[_\s-]?holder", r"expiry", r"expiration",
        r"account[_\s-]?number", r"routing[_\s-]?number", r"\biban\b",
        r"\bswift\b", r"\bbic\b", r"sort[_\s-]?code", r"\bclabe\b",
        r"\bssn\b", r"social[_\s-]?security", r"tax[_\s-]?id", r"\bein\b",
        r"date[_\s-]?of[_\s-]?birth", r"\bdob\b", r"birth[_\s-]?date",
        r"kyc", r"document", r"passport", r"driver[_\s-]?licen[cs]e",
        r"national[_\s-]?id", r"id[_\s-]?number", r"selfie",
        r"sender[_\s-]?name", r"beneficiary",
        r"secret", r"token", r"api[_\s-]?key", r"apikey", r"password",
        r"private[_\s-]?key", r"credential", r"authorization", r"bearer",
    ]
]

# Keys explicitly allowed even when a sensitive pattern matches, because they
# are masked-by-construction (display-safe partial references).
_MASKED_SAFE = re.compile(r"(last[_\s-]?4|last[_\s-]?four|masked)", re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    text = str(key)
    if _MASKED_SAFE.search(text):
        return False
    return any(p.search(text) for p in SENSITIVE_KEY_PATTERNS)


def sanitize_payload(value: Any) -> tuple[Any, list[str]]:
    """Recursively strip dict keys matching the sensitive reject list.

    Returns (sanitized_value, stripped_key_names). Key *names* only are
    reported for audit/metrics — never the stripped values.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        stripped: list[str] = []
        for k, v in value.items():
            if is_sensitive_key(k):
                stripped.append(str(k))
                continue
            child, child_stripped = sanitize_payload(v)
            out[k] = child
            stripped.extend(child_stripped)
        return out, stripped
    if isinstance(value, list):
        out_list: list[Any] = []
        stripped = []
        for item in value:
            child, child_stripped = sanitize_payload(item)
            out_list.append(child)
            stripped.extend(child_stripped)
        return out_list, stripped
    return value, []


def sum_amounts(*values: Any) -> Optional[str]:
    """Decimal-safe sum of provider-reported amounts; None when nothing safe."""
    from decimal import Decimal, InvalidOperation

    total: Optional[Any] = None
    for value in values:
        if value in (None, ""):
            continue
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        total = amount if total is None else total + amount
    return str(total) if total is not None else None


def payload_hash(payload: Any) -> str:
    """Stable sha256 over the canonical JSON encoding of a raw provider payload.

    Computed BEFORE sanitization so exact provider redeliveries hash equal and
    mutated payloads reusing an event id are detectable.
    """
    if isinstance(payload, bytes):
        return hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


# ─────────────────────────────────────────────────────────────────────────────
# Provider polling — error classification + credential extraction
# ─────────────────────────────────────────────────────────────────────────────
# Provider-health tokens the poll path records on ``poll_state['health']`` and
# the service persists on the provider account. ``ok`` is the only healthy pull
# state; the rest are degraded/off-ramp classifications.
POLL_HEALTH_OK = "ok"
POLL_HEALTH_NOT_CONFIGURED = "not_configured"
POLL_HEALTH_RATE_LIMITED = "rate_limited"
POLL_HEALTH_AUTH_ERROR = "auth_error"
POLL_HEALTH_CLIENT_ERROR = "client_error"
POLL_HEALTH_SERVER_ERROR = "server_error"
POLL_HEALTH_TIMEOUT = "timeout"
POLL_HEALTH_NETWORK_ERROR = "network_error"
POLL_HEALTH_BAD_RESPONSE = "bad_response"

_HEALTHY_POLL_STATES = frozenset({POLL_HEALTH_OK, "webhook_only"})


class ProviderPollError(Exception):
    """A classified failure of a provider status-poll request.

    ``classification`` is one of the ``POLL_HEALTH_*`` tokens so the caller can
    persist provider health and decide whether to degrade rather than crash.
    Never carries response bodies or secrets — only a short, safe detail.
    """

    def __init__(self, classification: str, detail: str = "", status_code: Optional[int] = None):
        self.classification = classification
        self.status_code = status_code
        super().__init__(detail or classification)


def _extract_secret(credential: Any) -> Optional[str]:
    """Pull a bearer secret from either a raw string or a credential mapping.

    Accepts the vault's raw secret string or a ``{api_key/secret/token/...}``
    mapping (as certification passes). Returns None when nothing usable.
    """
    if credential is None:
        return None
    if isinstance(credential, str):
        return credential or None
    if isinstance(credential, dict):
        for key in ("secret", "api_key", "apiKey", "api-key", "key", "token", "bearer"):
            value = credential.get(key)
            if value:
                return str(value)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Key vault access (payment-rail scoped)
# ─────────────────────────────────────────────────────────────────────────────

_vault: Optional[BYOKKeyVault] = None


def get_payment_rails_vault() -> BYOKKeyVault:
    """Payment-rail key vault — reuses the provider gateway vault when the
    gateway is enabled, otherwise a module-scoped vault instance."""
    global _vault
    if _vault is None:
        try:
            from dependencies.providers import get_provider_gateway
            gateway = get_provider_gateway()
        except Exception:
            gateway = None
        _vault = gateway.key_vault if gateway is not None else BYOKKeyVault()
    return _vault


# ─────────────────────────────────────────────────────────────────────────────
# Typed adapter results
# ─────────────────────────────────────────────────────────────────────────────

class AdapterDescriptor(BaseModel):
    name: str
    display_name: str
    flows: list[str]
    webhook_supported: bool
    polling_supported: bool
    vault_provider_name: str
    schema_version: str = PAYMENT_RAILS_SCHEMA_VERSION


class ParsedProviderEvent(BaseModel):
    """One provider-shaped event normalized to a dedupe-able envelope.

    ``payload`` is sanitized; ``raw_hash`` is computed over the raw payload
    before sanitization so exact redeliveries are detected.
    """

    id: str = Field(default_factory=new_id)
    provider: str
    provider_event_id: str
    event_type: str
    occurred_at: str = Field(default_factory=utc_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_hash: str
    source: str = "webhook"  # webhook | polling
    stripped_keys: list[str] = Field(default_factory=list)


class ConnectionTestResult(BaseModel):
    provider: str
    ok: bool
    status: str  # "ok" | "not_configured" | "error"
    detail: str = ""
    checked_at: str = Field(default_factory=utc_now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# Adapter ABC
# ─────────────────────────────────────────────────────────────────────────────

class PaymentRailAdapter(ABC):
    """Abstract payment rail adapter. Observation-only, import-safe, offline
    by default. External calls happen only when the tenant is configured and
    the process is not in local mode."""

    provider_name: str = ""
    display_name: str = ""
    vault_provider_name: str = ""
    flows: tuple[str, ...] = ()
    webhook_supported: bool = True
    polling_supported: bool = False
    # A provider Aether can only observe via signed webhooks (no pull API).
    # ``webhook_only`` is a SUPPORTED terminal capability, not an unfinished
    # adapter — the connection test resolves to a typed ``webhook_only`` result.
    webhook_only: bool = False
    default_rail: str = "fiat"
    # HMAC scheme: "timestamped_hex" signs f"{timestamp}.{payload}" (Stripe /
    # MoonPay / Privy style); "body_hex" signs the raw body (Coinbase / Bridge
    # style).
    signature_scheme: str = "timestamped_hex"
    # provider-native status → canonical FundingSessionStatus
    STATUS_MAP: dict[str, str] = {}

    # ── Certification / polling declaration (honest, per-adapter) ─────────
    adapter_version: str = "1.0.0"
    # Default provider API base for the pull path; a tenant vault endpoint
    # override wins. Empty for webhook-only providers.
    poll_base_url: str = ""
    # Bounded pagination: never fetch more than this many pages in one sweep.
    poll_max_pages: int = 10
    poll_page_size: int = 50
    cert_supported_operations: tuple[str, ...] = ("webhook_ingest", "normalize", "reconcile")
    cert_unsupported_operations: tuple[str, ...] = ()
    cert_required_credentials: tuple[str, ...] = ("webhook_signing_secret",)
    cert_required_endpoints: tuple[str, ...] = ()
    cert_expected_webhook_headers: tuple[str, ...] = ("signature", "timestamp")
    cert_pagination_model: str = "none"
    cert_retry_policy: str = (
        "exponential backoff (base 0.2s, x2 per attempt), max 3 retries on "
        "429 / 5xx / timeout / network error; honors Retry-After"
    )
    cert_rate_limit_behavior: str = (
        "HTTP 429 classified as rate_limited; honors Retry-After header, else "
        "exponential backoff; bounded retries then degrades provider health"
    )

    def __init__(
        self,
        *,
        http_transport: Any = None,
        http_timeout: float = 15.0,
        sleeper: Optional[Callable[[float], Any]] = None,
        max_retries: int = 3,
        backoff_base: float = 0.2,
    ) -> None:
        """Construct an adapter with an INJECTABLE HTTP transport.

        ``http_transport`` (an ``httpx`` transport such as ``httpx.MockTransport``)
        is threaded into every ``httpx.AsyncClient`` this adapter opens, so tests
        drive the pull path against a mock server with NO live network. Left at
        None in production, ``httpx`` performs real IO. ``sleeper`` lets tests
        skip real backoff waits.
        """
        self._http_transport = http_transport
        self._http_timeout = http_timeout
        self._sleeper: Callable[[float], Any] = sleeper or asyncio.sleep
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = float(backoff_base)

    # ── Descriptor / configuration ────────────────────────────────────────

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            name=self.provider_name,
            display_name=self.display_name,
            flows=list(self.flows),
            webhook_supported=self.webhook_supported,
            polling_supported=self.polling_supported,
            vault_provider_name=self.vault_provider_name,
        )

    async def is_configured(self, tenant_id: str) -> bool:
        """Whether the tenant has stored provider credentials in the vault."""
        try:
            key = await get_payment_rails_vault().get_key(tenant_id, self.vault_provider_name)
        except ValueError:
            return False
        return bool(key)

    def masked_identifier(self, tenant_id: str) -> str:
        """Masked credential reference for display — never key material."""
        return get_payment_rails_vault().masked_identifier(tenant_id, self.vault_provider_name)

    def not_configured(self) -> dict[str, Any]:
        """Typed not-configured response (never an exception / 500)."""
        return {
            "provider": self.provider_name,
            "status": "not_configured",
            "configured": False,
            "handled": False,
            "detail": (
                f"{self.display_name} is not configured for this tenant. "
                f"Store credentials in the key vault under "
                f"'{self.vault_provider_name}'."
            ),
        }

    def _webhook_only_result(self) -> ConnectionTestResult:
        """Typed terminal ``webhook_only`` connection result (a supported state)."""
        return ConnectionTestResult(
            provider=self.provider_name, ok=True, status="webhook_only",
            detail=(
                f"{self.display_name} is webhook-only: signature verification IS "
                "the connection; there is no polling/backfill API to probe."
            ),
        )

    async def test_connection(self, tenant_id: str) -> ConnectionTestResult:
        """Offline-safe connection test. Local mode never performs network IO.

        Webhook-only providers resolve to a typed ``webhook_only`` result once a
        signing secret is configured — that is a finished, supported terminal
        state, not an unimplemented adapter.
        """
        if not await self.is_configured(tenant_id):
            return ConnectionTestResult(
                provider=self.provider_name, ok=False, status="not_configured",
                detail="missing credential (configure the key vault)",
            )
        if self.webhook_only:
            return self._webhook_only_result()
        if _is_local_env():
            return ConnectionTestResult(
                provider=self.provider_name, ok=True, status="ok",
                detail="credential present; live check skipped (local mode)",
            )
        return await self._live_connection_test(tenant_id)

    async def _live_connection_test(self, tenant_id: str) -> ConnectionTestResult:
        """Real provider health ping. Pull adapters override with an authenticated
        GET via the injectable client; webhook-only providers return the typed
        ``webhook_only`` result (there is nothing live to probe)."""
        if self.webhook_only:
            return self._webhook_only_result()
        return ConnectionTestResult(
            provider=self.provider_name, ok=True, status="ok",
            detail="credential present; live check not implemented",
        )

    # ── Webhook verification (HMAC, no provider SDKs) ─────────────────────

    async def verify_webhook(
        self,
        tenant_id: str,
        payload: bytes,
        signature: Optional[str],
        timestamp: Optional[str] = None,
    ) -> bool:
        """Verify a provider webhook signature with the tenant's vault secret.

        HMAC-SHA256 per provider scheme, constant-time compare. Never logs the
        secret or the expected signature.
        """
        if not signature:
            return False
        try:
            secret = await get_payment_rails_vault().get_key(tenant_id, self.vault_provider_name)
        except ValueError:
            return False
        if not secret:
            return False
        if self.signature_scheme == "timestamped_hex":
            if not timestamp:
                return False
            signed_payload = f"{timestamp}.".encode("utf-8") + payload
        else:
            signed_payload = payload
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        provided = signature.strip()
        for prefix in ("v1=", "s=", "sha256="):
            provided = provided.removeprefix(prefix)
        return hmac.compare_digest(expected, provided)

    def native_signature_scheme(self) -> str:
        """Provider-native scheme token for ``signature_verify.verify_signature``.

        Stripe and MoonPay send compound ``t=…,<tag>=…`` headers (parsed
        natively); the others use their declared ``signature_scheme``.
        """
        return {
            "stripe": "stripe_compound",
            "moonpay": "moonpay_compound",
        }.get(self.provider_name, self.signature_scheme)

    # ── Parsing / normalization ───────────────────────────────────────────

    @abstractmethod
    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        """Map a verified webhook payload to ParsedProviderEvents (sanitized)."""

    @abstractmethod
    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        """Normalize one parsed provider event into a canonical FundingSession.

        Returns None for events that do not describe a funding flow (e.g. a
        deposit-address registration).
        """

    def _make_event(
        self,
        *,
        provider_event_id: str,
        event_type: str,
        payload: dict[str, Any],
        raw_hash: Optional[str] = None,
        occurred_at: Optional[str] = None,
        source: str = "webhook",
    ) -> ParsedProviderEvent:
        sanitized, stripped = sanitize_payload(payload)
        return ParsedProviderEvent(
            provider=self.provider_name,
            provider_event_id=str(provider_event_id),
            event_type=event_type,
            occurred_at=occurred_at or utc_now_iso(),
            payload=sanitized,
            raw_hash=raw_hash or payload_hash(payload),
            source=source,
            stripped_keys=stripped,
        )

    # ── Status mapping ────────────────────────────────────────────────────

    def status_map(self) -> PaymentRailStatusMap:
        return PaymentRailStatusMap(
            provider=self.provider_name,  # type: ignore[arg-type]
            statuses=dict(self.STATUS_MAP),  # type: ignore[arg-type]
            ordering=dict(CANONICAL_STATUS_ORDERING),
        )

    def map_status(self, provider_status: Optional[str]) -> str:
        """Provider-native status → canonical status; unknown → 'unresolved'."""
        if not provider_status:
            return "unresolved"
        return self.STATUS_MAP.get(str(provider_status).strip().lower(), "unresolved")

    # ── Polling / status sync ─────────────────────────────────────────────

    async def status_sync(
        self,
        tenant_id: str,
        *,
        records: Optional[list[dict[str, Any]]] = None,
        **params: Any,
    ) -> list[ParsedProviderEvent]:
        """Pull provider truth for open sessions where the provider supports it.

        ``records`` lets callers/tests supply already-fetched provider-shaped
        records (no network). Without records, adapters may poll the provider
        API — only when configured and never in local mode.
        """
        if records is not None:
            return self._parse_poll_records(tenant_id, records, **params)
        if not self.polling_supported:
            return []
        if not await self.is_configured(tenant_id):
            return []
        if _is_local_env():
            return []
        fetched = await self._fetch_poll_records(tenant_id, **params)
        return self._parse_poll_records(tenant_id, fetched, **params)

    def _parse_poll_records(
        self, tenant_id: str, records: list[dict[str, Any]], **params: Any
    ) -> list[ParsedProviderEvent]:
        """Normalize provider-shaped polling records. Override per adapter."""
        return []

    async def _fetch_poll_records(self, tenant_id: str, **params: Any) -> list[dict[str, Any]]:
        """Live polling fetch — httpx imported inside implementations only.

        Pull providers OVERRIDE this. The default (webhook-only / no pull API)
        returns nothing and marks poll health accordingly.
        """
        poll_state = params.get("poll_state")
        if isinstance(poll_state, dict):
            poll_state.setdefault("health", "webhook_only" if self.webhook_only else POLL_HEALTH_OK)
        return []

    # ── Injectable HTTP client + authenticated request execution ──────────

    def _open_http_client(self, *, timeout: Optional[float] = None):
        """Open an ``httpx.AsyncClient`` bound to the injected transport (if any).

        Imported inside the method so module import never pulls in ``httpx`` and
        never touches the network. When ``_http_transport`` is set (tests), all
        requests route to that mock transport — no live IO.
        """
        import httpx

        kwargs: dict[str, Any] = {"timeout": timeout if timeout is not None else self._http_timeout}
        if self._http_transport is not None:
            kwargs["transport"] = self._http_transport
        return httpx.AsyncClient(**kwargs)

    def _retry_delay(self, attempt: int, response: Any) -> float:
        """Backoff seconds for a retry: honor ``Retry-After`` else exponential."""
        if response is not None:
            retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
        return self._backoff_base * (2 ** attempt)

    async def _request_json(
        self, client: Any, request: dict[str, Any], *, poll_state: Optional[dict] = None
    ) -> Any:
        """Execute one authenticated request with retries/backoff/timeout and
        classify the outcome. Returns parsed JSON, or raises ``ProviderPollError``
        with a ``POLL_HEALTH_*`` classification. Never logs secrets or bodies.
        """
        import httpx

        method = str(request.get("method", "GET")).upper()
        url = request["url"]
        headers = request.get("headers") or {}
        params = request.get("params") or {}
        timeout = request.get("timeout", self._http_timeout)

        attempt = 0
        classification = POLL_HEALTH_NETWORK_ERROR
        while True:
            response = None
            try:
                response = await client.request(
                    method, url, headers=headers, params=params, timeout=timeout
                )
            except httpx.TimeoutException:
                classification = POLL_HEALTH_TIMEOUT
            except httpx.HTTPError:
                classification = POLL_HEALTH_NETWORK_ERROR
            else:
                status = response.status_code
                if status == 429 or status >= 500:
                    classification = (
                        POLL_HEALTH_RATE_LIMITED if status == 429 else POLL_HEALTH_SERVER_ERROR
                    )
                    if attempt < self._max_retries:
                        await self._sleeper(self._retry_delay(attempt, response))
                        attempt += 1
                        continue
                    self._mark_health(poll_state, classification)
                    raise ProviderPollError(classification, f"HTTP {status}", status)
                if status in (401, 403):
                    self._mark_health(poll_state, POLL_HEALTH_AUTH_ERROR)
                    raise ProviderPollError(POLL_HEALTH_AUTH_ERROR, f"HTTP {status}", status)
                if status >= 400:
                    self._mark_health(poll_state, POLL_HEALTH_CLIENT_ERROR)
                    raise ProviderPollError(POLL_HEALTH_CLIENT_ERROR, f"HTTP {status}", status)
                try:
                    return response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    self._mark_health(poll_state, POLL_HEALTH_BAD_RESPONSE)
                    raise ProviderPollError(POLL_HEALTH_BAD_RESPONSE, f"invalid JSON: {exc}", status)
            # timeout / network error retry path
            if attempt < self._max_retries:
                await self._sleeper(self._retry_delay(attempt, None))
                attempt += 1
                continue
            self._mark_health(poll_state, classification)
            raise ProviderPollError(classification, "request failed after retries")

    @staticmethod
    def _mark_health(poll_state: Optional[dict], value: str) -> None:
        if isinstance(poll_state, dict):
            poll_state["health"] = value

    async def _require_secret(self, tenant_id: str) -> Optional[str]:
        """Tenant BYOK secret for this provider, or None when unconfigured."""
        try:
            return await get_payment_rails_vault().get_key(tenant_id, self.vault_provider_name)
        except ValueError:
            return None

    async def _resolve_base_url(self, tenant_id: str) -> str:
        """Provider API base — a tenant vault endpoint override wins over the
        adapter default (supports sandbox/regional hosts without code change)."""
        try:
            endpoint = await get_payment_rails_vault().get_endpoint(tenant_id, self.vault_provider_name)
        except Exception:  # pragma: no cover - defensive
            endpoint = None
        return (endpoint or self.poll_base_url or "").rstrip("/")

    def _degraded(self, poll_state: Optional[dict], exc: "ProviderPollError") -> None:
        """Record a classified poll failure without crashing the sweep."""
        logger.warning(
            "payment_rail poll degraded provider=%s class=%s",
            self.provider_name, exc.classification,
        )
        self._mark_health(poll_state, exc.classification)

    def _finish_poll(
        self,
        poll_state: Optional[dict],
        *,
        next_cursor: Optional[str],
        pages: int,
        records: list,
    ) -> None:
        """Persist the resume cursor + counters + health onto ``poll_state`` so
        the service can store them. Health defaults to ``ok`` unless a degrade
        already classified it."""
        if isinstance(poll_state, dict):
            poll_state["next_cursor"] = next_cursor
            poll_state["pages"] = pages
            poll_state["record_count"] = len(records)
            poll_state["health"] = poll_state.get("health") or POLL_HEALTH_OK

    # NOTE: ``build_request`` is intentionally NOT defined on the base. Only pull
    # adapters (Coinbase/MoonPay/Bridge) expose it; webhook-only providers omit
    # it so certification request/auth/tenant-isolation checks correctly SKIP
    # rather than fail — there is no provider request to construct.

    # ── Certification hooks (duck-typed, offline; see shared.certification) ─

    def certification_descriptor(self) -> Any:
        """Honest ``AdapterCertificationDescriptor`` for this adapter.

        ``implementation_state`` is CREDENTIAL_WAITING for every payment rail:
        the code is complete and offline-safe, awaiting only tenant credentials.
        """
        from shared.certification.descriptor import AdapterCertificationDescriptor
        from shared.certification.readiness import CredentialReadiness

        return AdapterCertificationDescriptor(
            provider=self.provider_name,
            domain="payments",
            adapter=type(self).__name__,
            adapter_version=self.adapter_version,
            supported_operations=list(self.cert_supported_operations),
            unsupported_operations=list(self.cert_unsupported_operations),
            required_credentials=list(self.cert_required_credentials),
            required_endpoints=list(self.cert_required_endpoints),
            secret_ref_names=[self.vault_provider_name] if self.vault_provider_name else [],
            expected_webhook_headers=list(self.cert_expected_webhook_headers),
            pagination_model=self.cert_pagination_model,
            streaming_model="webhook" if self.webhook_supported else "none",
            rate_limit_behavior=self.cert_rate_limit_behavior,
            retry_policy=self.cert_retry_policy,
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=True,
        )

    def sanitize_payload(self, payload: Any) -> tuple[Any, list[str]]:
        """Certification/redaction hook: recursively strip sensitive keys."""
        return sanitize_payload(payload)

    def dedupe_key(self, event: Any) -> tuple:
        """Stable idempotency key for an event (duplicate detection)."""
        if isinstance(event, ParsedProviderEvent):
            return (event.provider, event.provider_event_id, event.raw_hash)
        if isinstance(event, dict):
            return (
                event.get("provider"),
                event.get("provider_event_id") or event.get("id"),
                event.get("raw_hash"),
            )
        return (repr(event),)

    def sequence_of(self, event: Any) -> tuple:
        """Total order for out-of-order arrivals (occurred_at, seq, id)."""
        if isinstance(event, ParsedProviderEvent):
            return (event.occurred_at or "", event.provider_event_id or "")
        if isinstance(event, dict):
            return (
                str(event.get("occurred_at") or ""),
                event.get("seq") or 0,
                str(event.get("id") or event.get("provider_event_id") or ""),
            )
        return (str(event),)

    def normalize(self, payload: Any) -> Optional[dict[str, Any]]:
        """Certification hook: webhook payload → canonical, volatile-field-free
        projection. Idempotent for identical input; tolerant of drift/malformed
        input (returns None rather than crashing)."""
        if not isinstance(payload, dict):
            return None
        try:
            events = self.parse_webhook("cert-tenant", payload, payload_hash(payload))
            if not events:
                return None
            session = self.normalize_to_funding_session("cert-tenant", events[0])
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
            return None
        if session is None:
            return None
        data = session.model_dump(mode="json")
        # Drop volatile fields (freshly generated ids/timestamps) so the
        # projection is a stable function of the input — required for the
        # certification idempotent-replay check.
        for volatile in ("id", "created_at", "updated_at", "occurred_at"):
            data.pop(volatile, None)
        return data

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Certification hook: an unconfigured adapter is never healthy."""
        ctx = context or {}
        if not ctx.get("configured"):
            return {"healthy": False, "state": POLL_HEALTH_NOT_CONFIGURED}
        state = ctx.get("provider_health") or ("webhook_only" if self.webhook_only else POLL_HEALTH_OK)
        return {"healthy": state in _HEALTHY_POLL_STATES, "state": state}

    # ── Canonical Aether events ───────────────────────────────────────────

    def normalize_to_aether_events(self, session: FundingSession) -> list[dict[str, Any]]:
        """Canonical payment_* event payloads implied by a funding session.

        payment_initiated is implied by every observed session; completed /
        refunded additionally imply payment_completed; failed / cancelled
        imply payment_failed. Intermediate statuses (submitted/pending/
        unresolved) imply no additional canonical event. The service layer is
        responsible for emitting each event type at most once per session.
        """
        wanted = ["payment_initiated"]
        if session.status in ("completed", "refunded"):
            wanted.append("payment_completed")
        elif session.status in ("failed", "cancelled"):
            wanted.append("payment_failed")
        return [self._canonical_event(session, event_type) for event_type in wanted]

    def _canonical_event(self, session: FundingSession, event_type: str) -> dict[str, Any]:
        properties, _ = sanitize_payload({
            "funding_session_id": session.id,
            "provider": session.provider,
            "provider_detail": session.provider_detail,
            "flow_type": session.flow_type,
            "rail": session.rail,
            "status": session.status,
            "provider_status": session.provider_status,
            "status_reason": session.status_reason,
            "reconciliation_state": session.reconciliation_state,
            "actor_kind": session.actor_kind,
            "agent_id": session.agent_id,
            "org_id": session.org_id,
            "journey_id": session.journey_id,
            "campaign_id": session.campaign_id,
            "source_asset": session.source_asset,
            "source_chain": session.source_chain,
            "source_amount": session.source_amount,
            "fiat_currency": session.fiat_currency,
            "destination_asset": session.destination_asset,
            "destination_chain": session.destination_chain,
            "destination_amount": session.destination_amount,
            "destination_address": session.destination_address,
            "fee_amount": session.fee_amount,
            "fee_currency": session.fee_currency,
            "provider_session_id": session.provider_session_id,
            "provider_transaction_id": session.provider_transaction_id,
            "provider_customer_ref": session.provider_customer_ref,
            "tx_hash": session.tx_hash,
            "schema_version": PAYMENT_RAILS_SCHEMA_VERSION,
        })
        return {
            "event_type": event_type,
            "event_family": "commerce",
            "tenant_id": session.tenant_id,
            "user_id": session.user_id,
            "session_id": session.session_id,
            "occurred_at": session.occurred_at,
            "properties": {k: v for k, v in properties.items() if v is not None},
        }

    # ── Side records (optional per adapter) ───────────────────────────────

    def extract_deposit_address(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[dict[str, Any]]:
        """DepositAddress-shaped dict when the event registers one, else None."""
        return None

    def extract_virtual_account(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[dict[str, Any]]:
        """VirtualAccount-shaped dict when the event describes one, else None."""
        return None

    # ── Audit / health hooks ──────────────────────────────────────────────

    def audit_record(
        self, tenant_id: str, action: str, detail: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Sanitized audit entry for adapter-level occurrences (signature
        rejections, hash conflicts, downgrade attempts, sync runs)."""
        sanitized_detail, _ = sanitize_payload(detail or {})
        return {
            "id": new_id(),
            "tenant_id": tenant_id,
            "provider": self.provider_name,
            "action": action,
            "detail": sanitized_detail,
            "occurred_at": utc_now_iso(),
        }

    async def health_context(self, tenant_id: str, enabled: bool) -> dict[str, Any]:
        """Configuration facts for PaymentRailHealth computation (safe only)."""
        configured = await self.is_configured(tenant_id)
        return {
            "provider": self.provider_name,
            "configured": configured,
            "enabled": enabled,
            "webhook_supported": self.webhook_supported,
            "polling_supported": self.polling_supported,
            "credential_ref": self.masked_identifier(tenant_id) if configured else None,
        }
