"""Per-tenant x402 RPC endpoint+key resolution.

The x402 verifier used a single deployment-global RPC URL per chain family
(`COMMERCE_BASE_RPC` / `COMMERCE_SOLANA_RPC`). This resolves the tenant's own
RPC endpoint+key pair from the durable credential authority instead, so a
tenant activates x402 verification with configuration + credentials only.

Atomicity: the credential value is a single JSON document
``{url, api_key, auth_mode}`` — one credential version is exactly one
endpoint+key pair, so a rotated endpoint can never be paired with a stale key.
``auth_mode`` selects how the key is applied:

* ``path``   — key appended to the URL path (e.g. QuickNode/Alchemy style)
* ``header`` — key sent as an ``Authorization: Bearer`` header
* ``query``  — key sent as an ``?apikey=`` query parameter
* ``none``   — the URL is already authenticated / public (local/test only)

Fail-closed: outside local/test, a tenant with no ACTIVE ``rpc_endpoint_pair``
for the (environment, chain) gets ``RpcUnavailableError`` and the verifier
returns the semantic verdict ``verification_unavailable`` — never an
auto-pass, never a silent fall-through to a platform key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from shared.logger.logger import get_logger, metrics

from services.x402.credential_slots import rpc_provider_for_chain

logger = get_logger("aether.x402.rpc_resolver")

RPC_SLOT = "rpc_endpoint_pair"


class RpcUnavailableError(RuntimeError):
    """No usable RPC endpoint+key for the (tenant, environment, chain)."""


@dataclass(frozen=True)
class ResolvedRpc:
    url: str
    api_key: str
    auth_mode: str  # path | header | query | none

    def request_url(self) -> str:
        if self.auth_mode == "path" and self.api_key:
            return self.url.rstrip("/") + "/" + self.api_key
        if self.auth_mode == "query" and self.api_key:
            sep = "&" if "?" in self.url else "?"
            return f"{self.url}{sep}apikey={self.api_key}"
        return self.url

    def headers(self) -> dict[str, str]:
        if self.auth_mode == "header" and self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").strip().lower() in ("local", "test")


def _platform_default(chain: str) -> Optional[ResolvedRpc]:
    """Local/test-only platform default RPC (never used in deployed envs)."""
    from config.settings import settings

    if chain.startswith("eip155:"):
        url = settings.intelligence_graph.commerce_base_rpc
    elif chain.startswith("solana:"):
        url = settings.intelligence_graph.commerce_solana_rpc
    else:
        return None
    return ResolvedRpc(url=url, api_key="", auth_mode="none") if url else None


async def resolve_rpc(tenant_id: str, environment: str, chain: str) -> ResolvedRpc:
    """Resolve the tenant's RPC endpoint+key for a chain (see module docstring)."""
    provider = rpc_provider_for_chain(chain, environment)
    if provider is None:
        raise RpcUnavailableError(f"no RPC provider mapping for chain {chain!r}")

    try:
        from services.providers.credentials.authority import credential_authority

        raw = await credential_authority.get_active_secret(
            tenant_id, provider, environment, RPC_SLOT
        )
    except Exception as exc:  # noqa: BLE001 — classified below
        from shared.common.common import NotFoundError

        if isinstance(exc, NotFoundError):
            raw = None
        else:
            logger.error(
                "rpc resolution failed tenant=%s env=%s chain=%s: %s",
                tenant_id, environment, chain, type(exc).__name__,
            )
            metrics.increment("x402_rpc_resolutions", labels={"source": "error", "chain": chain})
            raise RpcUnavailableError("rpc credential resolution failed") from exc

    if raw:
        try:
            doc = json.loads(raw)
            resolved = ResolvedRpc(
                url=doc["url"],
                api_key=doc.get("api_key", ""),
                auth_mode=doc.get("auth_mode", "none"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RpcUnavailableError(
                "rpc_endpoint_pair is not a valid {url, api_key, auth_mode} document"
            ) from exc
        metrics.increment(
            "x402_rpc_resolutions", labels={"source": "credential_authority", "chain": chain}
        )
        return resolved

    if _is_local_env():
        default = _platform_default(chain)
        if default is not None:
            metrics.increment(
                "x402_rpc_resolutions", labels={"source": "platform_default", "chain": chain}
            )
            return default

    metrics.increment("x402_rpc_resolutions", labels={"source": "missing", "chain": chain})
    raise RpcUnavailableError(
        f"no ACTIVE {RPC_SLOT} for tenant {tenant_id!r} chain {chain!r} "
        f"environment {environment!r}; supply one via "
        f"PUT /v1/providers/credentials/{provider}/slots/{RPC_SLOT}"
    )


__all__ = ["ResolvedRpc", "RpcUnavailableError", "resolve_rpc", "RPC_SLOT"]
