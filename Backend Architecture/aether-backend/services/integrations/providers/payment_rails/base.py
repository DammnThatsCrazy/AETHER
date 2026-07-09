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

import hashlib
import hmac
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

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
    default_rail: str = "fiat"
    # HMAC scheme: "timestamped_hex" signs f"{timestamp}.{payload}" (Stripe /
    # MoonPay / Privy style); "body_hex" signs the raw body (Coinbase / Bridge
    # style).
    signature_scheme: str = "timestamped_hex"
    # provider-native status → canonical FundingSessionStatus
    STATUS_MAP: dict[str, str] = {}

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

    async def test_connection(self, tenant_id: str) -> ConnectionTestResult:
        """Offline-safe connection test. Local mode never performs network IO."""
        if not await self.is_configured(tenant_id):
            return ConnectionTestResult(
                provider=self.provider_name, ok=False, status="not_configured",
                detail="missing credential (configure the key vault)",
            )
        if _is_local_env():
            return ConnectionTestResult(
                provider=self.provider_name, ok=True, status="ok",
                detail="credential present; live check skipped (local mode)",
            )
        return await self._live_connection_test(tenant_id)

    async def _live_connection_test(self, tenant_id: str) -> ConnectionTestResult:
        """Override for a real provider ping (httpx imported inside only)."""
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
        """Live polling fetch — httpx imported inside implementations only."""
        return []

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
