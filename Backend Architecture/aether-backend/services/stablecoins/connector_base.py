"""Shared primitives for concrete Stablecoin Intelligence ingestion connectors.

The connectors in ``evm_connector.py`` / ``solana_connector.py`` /
``price_feed.py`` are the first CONCRETE implementations of the
``StablecoinProviderConnector`` seam declared in ``polling.py``. They are
turnkey / credential-waiting: the decode + cursor + reorg + backfill logic is
complete and offline-safe, and the only thing standing between them and live
data is a configured RPC endpoint (a credential, in ``services/onchain``).

This module holds the pieces every connector shares:

* ``StablecoinRpcClient`` — the injectable read-only RPC seam. ``RPCGateway``
  satisfies it structurally, and tests inject an in-memory mock server, so NO
  live network is ever required in CI.
* ``StablecoinConnectorError`` + ``classify_rpc_error`` — provider-error and
  rate-limit classification (mirrors the payment-rail ``POLL_HEALTH_*`` tokens).
* cursor encode/decode + ``StablecoinConnectorCursorRepository`` — durable
  block/slot checkpoint persistence for restart-safe resume.
* per-chain confirmation/finality depths.
* ``ConnectorCertificationMixin`` — honest CREDENTIAL_WAITING descriptor plus the
  duck-typed certification hooks ``shared.certification`` probes.

Nothing here signs, submits, routes, or simulates a transaction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from repositories.repos import BaseRepository
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import CredentialReadiness
from shared.common.common import utc_now
from shared.temporal import to_iso_utc

# ─────────────────────────────────────────────────────────────────────────────
# Injectable RPC seam
# ─────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class StablecoinRpcClient(Protocol):
    """Read-only JSON-RPC client contract.

    ``services.onchain.rpc_gateway.RPCGateway`` satisfies this structurally
    (same ``execute`` signature). Tests inject an in-memory mock implementing
    this Protocol so the connectors never touch a live network. Implementations
    MUST be read-only; connectors never call a write/execute method.
    """

    async def execute(
        self,
        chain_id: str,
        method: str,
        params: Optional[list[Any]] = None,
        vm_type: str = "evm",
    ) -> dict: ...


# ─────────────────────────────────────────────────────────────────────────────
# Provider-error + rate-limit classification
# ─────────────────────────────────────────────────────────────────────────────

CONNECTOR_OK = "ok"
CONNECTOR_NOT_CONFIGURED = "not_configured"
CONNECTOR_RATE_LIMITED = "rate_limited"
CONNECTOR_AUTH_ERROR = "auth_error"
CONNECTOR_CLIENT_ERROR = "client_error"
CONNECTOR_SERVER_ERROR = "server_error"
CONNECTOR_TIMEOUT = "timeout"
CONNECTOR_NETWORK_ERROR = "network_error"
CONNECTOR_BAD_RESPONSE = "bad_response"
CONNECTOR_CHAIN_MISMATCH = "chain_mismatch"

_HEALTHY_CONNECTOR_STATES = frozenset({CONNECTOR_OK})


class StablecoinConnectorError(Exception):
    """A classified read-only RPC failure.

    ``classification`` is one of the ``CONNECTOR_*`` tokens so the polling
    scheduler can persist provider health and degrade rather than crash. It
    never carries response bodies or secrets — only a short, safe detail.
    """

    def __init__(self, classification: str, detail: str = "", status_code: Optional[int] = None) -> None:
        self.classification = classification
        self.status_code = status_code
        super().__init__(f"{classification}: {detail}" if detail else classification)


def classify_rpc_error(exc: BaseException) -> str:
    """Map an RPC transport/protocol exception onto a ``CONNECTOR_*`` token.

    Works without importing ``httpx`` at module load: HTTP status errors are
    recognized by a ``response.status_code`` attribute; timeout/network errors
    by exception class name; the ``RPCGateway`` sentinels by message.
    """
    if isinstance(exc, StablecoinConnectorError):
        return exc.classification

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return CONNECTOR_RATE_LIMITED
        if status in (401, 403):
            return CONNECTOR_AUTH_ERROR
        if status >= 500:
            return CONNECTOR_SERVER_ERROR
        if status >= 400:
            return CONNECTOR_CLIENT_ERROR

    name = type(exc).__name__.lower()
    if "timeout" in name:
        return CONNECTOR_TIMEOUT
    if "connect" in name or "network" in name or "transport" in name:
        return CONNECTOR_NETWORK_ERROR

    message = str(exc).lower()
    if "not configured" in message or "endpoint not configured" in message:
        return CONNECTOR_NOT_CONFIGURED
    if "not allowed" in message:
        return CONNECTOR_CLIENT_ERROR
    if "rate" in message and "limit" in message:
        return CONNECTOR_RATE_LIMITED
    if "rpc call failed" in message or "invalid" in message:
        return CONNECTOR_BAD_RESPONSE
    return CONNECTOR_NETWORK_ERROR


async def guarded_rpc(
    rpc: StablecoinRpcClient,
    chain_id: str,
    method: str,
    params: Optional[list[Any]] = None,
    *,
    vm_type: str = "evm",
) -> dict:
    """Call ``rpc.execute`` and re-raise any failure as a classified
    ``StablecoinConnectorError`` so the caller degrades health deterministically."""
    try:
        response = await rpc.execute(chain_id, method, params or [], vm_type=vm_type)
    except StablecoinConnectorError:
        raise
    except Exception as exc:  # transport/protocol errors are classified, never leaked
        raise StablecoinConnectorError(classify_rpc_error(exc), f"{method} failed") from exc
    if not isinstance(response, dict):
        raise StablecoinConnectorError(CONNECTOR_BAD_RESPONSE, f"{method} returned non-dict")
    if response.get("error"):
        raise StablecoinConnectorError(CONNECTOR_BAD_RESPONSE, f"{method} error")
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Per-chain confirmation / finality policy
# ─────────────────────────────────────────────────────────────────────────────

# Confirmation depth after which an EVM log is treated as safely confirmed for
# emission. Finalization to FinalityState.FINALIZED remains the finality
# verifier's job; the connector only emits at/below this confirmed head so a
# shallow reorg cannot surface an un-reorg-checked observation.
EVM_CONFIRMATION_DEPTHS: dict[str, int] = {
    "1": 12,        # ethereum mainnet
    "8453": 15,     # base
    "10": 20,       # optimism
    "42161": 20,    # arbitrum
    "137": 128,     # polygon pos
}
DEFAULT_EVM_CONFIRMATIONS = 12

# Solana commitment depths (slots). Below "confirmed" depth a slot can still be
# on a minority fork; "finalized" depth is the rooted supermajority horizon.
SOLANA_CONFIRMED_SLOTS = 1
SOLANA_FINALIZED_SLOTS = 32


def evm_confirmations_for(chain_id: str, default: int = DEFAULT_EVM_CONFIRMATIONS) -> int:
    return EVM_CONFIRMATION_DEPTHS.get(str(chain_id), default)


# ─────────────────────────────────────────────────────────────────────────────
# Cursor encode/decode + durable checkpoint repository
# ─────────────────────────────────────────────────────────────────────────────


def encode_cursor(state: Mapping[str, Any]) -> str:
    """Serialize connector cursor state to a compact, deterministic string.

    The scheduler persists this opaque string on its polling checkpoint and
    passes it back on the next pull, giving restart-safe resume even without the
    connector's own durable checkpoint.
    """
    return json.dumps(dict(state), sort_keys=True, separators=(",", ":"))


def decode_cursor(cursor: str) -> Optional[dict[str, Any]]:
    """Parse a cursor string; return ``None`` for empty/garbage (fresh start)."""
    if not cursor:
        return None
    try:
        value = json.loads(cursor)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class StablecoinConnectorCursorRepository(BaseRepository):
    """Durable per-(tenant, deployment) connector cursor + reorg anchor state.

    This is the connector's own checkpoint, independent of the string cursor the
    scheduler threads through ``poll_provider``. Either source makes resume
    restart-safe; together they are belt-and-braces. Rows are JSONB blobs (no
    Alembic migration required); in local mode they live in the shared in-memory
    store like every other stablecoin checkpoint table.
    """

    def __init__(self) -> None:
        super().__init__("stablecoin_connector_cursors")

    async def load(self, cursor_key: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(cursor_key)

    async def save(self, cursor_key: str, state: Mapping[str, Any]) -> dict[str, Any]:
        record = {"cursor_key": cursor_key, **dict(state), "updated_at": to_iso_utc(utc_now())}
        existing = await self.find_by_id(cursor_key)
        if existing:
            return await self.update(cursor_key, {**existing, **record})
        return await self.insert(cursor_key, record)


# ─────────────────────────────────────────────────────────────────────────────
# Hex / address helpers
# ─────────────────────────────────────────────────────────────────────────────

ZERO_ADDRESS = "0x" + "0" * 40
ZERO_TOPIC = "0x" + "0" * 64


def hex_to_int(value: Any) -> int:
    """Parse a JSON-RPC quantity (``0x``-hex, decimal string, or int)."""
    if isinstance(value, bool):
        raise ValueError(f"invalid quantity: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    raise ValueError(f"invalid quantity: {value!r}")


def topic_to_address(topic: Any) -> str:
    """Last 20 bytes of a 32-byte indexed topic → checksum-agnostic address."""
    text = str(topic or "")
    if text.startswith("0x") and len(text) >= 42:
        return "0x" + text[-40:]
    return text


def iso_from_unix(ts: int) -> str:
    """Canonical UTC ISO string from a chain unix timestamp (seconds)."""
    return to_iso_utc(datetime.fromtimestamp(int(ts), tz=timezone.utc))


def atomic_from_answer(answer_atomic: int, decimals: int) -> Decimal:
    """Decimal price from an integer feed answer + feed decimals. NEVER float."""
    return Decimal(int(answer_atomic)).scaleb(-int(decimals))


# ─────────────────────────────────────────────────────────────────────────────
# Secret redaction (certification sanitize hook)
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_KEY_RE = re.compile(
    r"(authorization|bearer|api[_\-]?key|apikey|secret|token|password|"
    r"private[_\-]?key|credential|x[_\-]?api[_\-]?key)",
    re.IGNORECASE,
)


def redact_secrets(value: Any) -> Any:
    """Recursively drop secret-like keys from a payload before it is stored/logged."""
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items() if not _SECRET_KEY_RE.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Certification mixin (honest CREDENTIAL_WAITING descriptor + duck-typed hooks)
# ─────────────────────────────────────────────────────────────────────────────


class ConnectorCertificationMixin:
    """Shared certification surface for the concrete chain/price connectors.

    Subclasses declare their capability matrix via the ``cert_*`` class fields
    and get an honest ``AdapterCertificationDescriptor`` (CREDENTIAL_WAITING) for
    free, plus the offline duck-typed hooks ``shared.certification`` probes.
    """

    # Overridden per connector.
    provider: str = "stablecoin_connector"
    domain: str = "stablecoin_chain"
    adapter_version: str = "1.0.0"
    cert_supported_operations: tuple[str, ...] = ()
    cert_unsupported_operations: tuple[str, ...] = ()
    cert_required_credentials: tuple[str, ...] = ("rpc_endpoint_url",)
    cert_required_endpoints: tuple[str, ...] = ()
    cert_pagination_model: str = "cursor"
    cert_rate_limit_behavior: str = (
        "HTTP 429 classified as rate_limited; RPCGateway sliding-window limiter "
        "enforces max_rps; classified errors degrade provider health without crashing"
    )
    cert_retry_policy: str = (
        "bounded per-pull block/slot span; classified rate_limited/5xx/timeout "
        "errors surface as degraded provider health for scheduler retry on next poll"
    )

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        """Honest capability record. ``implementation_state`` is
        CREDENTIAL_WAITING: the connector is code-complete and offline-safe,
        awaiting only a configured RPC endpoint."""
        return AdapterCertificationDescriptor(
            provider=self.provider,
            domain=self.domain,
            adapter=type(self).__name__,
            adapter_version=self.adapter_version,
            supported_operations=list(self.cert_supported_operations),
            unsupported_operations=list(self.cert_unsupported_operations),
            required_credentials=list(self.cert_required_credentials),
            required_endpoints=list(self.cert_required_endpoints),
            secret_ref_names=list(self.cert_required_credentials),
            pagination_model=self.cert_pagination_model,
            streaming_model="none",
            rate_limit_behavior=self.cert_rate_limit_behavior,
            retry_policy=self.cert_retry_policy,
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=True,
        )

    # ── offline certification hooks ──────────────────────────────────────────

    def sanitize_payload(self, payload: Any) -> Any:
        """Redact secret-like keys from a raw payload (certification hook)."""
        return redact_secrets(payload)

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """An unconfigured connector is never healthy (certification hook)."""
        ctx = context or {}
        if not ctx.get("configured"):
            return {"healthy": False, "state": CONNECTOR_NOT_CONFIGURED}
        state = str(ctx.get("provider_health") or CONNECTOR_OK)
        return {"healthy": state in _HEALTHY_CONNECTOR_STATES, "state": state}


__all__ = [
    "StablecoinRpcClient",
    "StablecoinConnectorError",
    "classify_rpc_error",
    "guarded_rpc",
    "CONNECTOR_OK",
    "CONNECTOR_NOT_CONFIGURED",
    "CONNECTOR_RATE_LIMITED",
    "CONNECTOR_AUTH_ERROR",
    "CONNECTOR_CLIENT_ERROR",
    "CONNECTOR_SERVER_ERROR",
    "CONNECTOR_TIMEOUT",
    "CONNECTOR_NETWORK_ERROR",
    "CONNECTOR_BAD_RESPONSE",
    "CONNECTOR_CHAIN_MISMATCH",
    "EVM_CONFIRMATION_DEPTHS",
    "DEFAULT_EVM_CONFIRMATIONS",
    "SOLANA_CONFIRMED_SLOTS",
    "SOLANA_FINALIZED_SLOTS",
    "evm_confirmations_for",
    "encode_cursor",
    "decode_cursor",
    "StablecoinConnectorCursorRepository",
    "ZERO_ADDRESS",
    "ZERO_TOPIC",
    "hex_to_int",
    "topic_to_address",
    "iso_from_unix",
    "atomic_from_answer",
    "redact_secrets",
    "ConnectorCertificationMixin",
]
