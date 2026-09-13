"""Payment Rail Observability V1 — named provider adapters only.

Aether observes, normalizes, and reconciles funding flows across exactly
five named providers. There is no generic webhook fallback: an unknown
provider is a 404, never a permissive catch-all. Aether never executes or
settles payments, custodies funds, or signs transactions.
"""

from __future__ import annotations

from shared.common.common import NotFoundError

from services.integrations.providers.payment_rails.base import PaymentRailAdapter
from services.integrations.providers.payment_rails.bridge import BridgeAdapter
from services.integrations.providers.payment_rails.coinbase import CoinbaseAdapter
from services.integrations.providers.payment_rails.moonpay import MoonPayAdapter
from services.integrations.providers.payment_rails.privy import PrivyAdapter
from services.integrations.providers.payment_rails.stripe_onramp import StripeOnrampAdapter

# Literal registry — exactly the five named providers, nothing dynamic.
ADAPTERS: dict[str, PaymentRailAdapter] = {
    "privy": PrivyAdapter(),
    "stripe": StripeOnrampAdapter(),
    "coinbase": CoinbaseAdapter(),
    "moonpay": MoonPayAdapter(),
    "bridge": BridgeAdapter(),
}

PROVIDER_NAMES: tuple[str, ...] = tuple(ADAPTERS)


def get_adapter(provider: str) -> PaymentRailAdapter:
    """Resolve a named adapter; unknown providers are NotFound (no fallback)."""
    adapter = ADAPTERS.get(str(provider).strip().lower())
    if adapter is None:
        raise NotFoundError(f"Unknown payment rail provider: {provider}")
    return adapter
