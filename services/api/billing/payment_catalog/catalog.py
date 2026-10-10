"""Canonical PaymentScan card-linked catalog seed for V1."""
from __future__ import annotations
from dataclasses import dataclass, field

SEEN_AT = "2026-07-10T00:00:00.000Z"
PAYMENTSCAN_URL = "https://paymentscan.xyz/"

@dataclass(frozen=True)
class PaymentCatalogEntity:
    id: str
    source: str
    entity_type: str
    display_name: str
    slug: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    status: str = "active"
    source_url: str = PAYMENTSCAN_URL
    first_seen_at: str = SEEN_AT
    last_seen_at: str = SEEN_AT

def e(t: str, name: str, slug: str, *aliases: str) -> PaymentCatalogEntity:
    return PaymentCatalogEntity(id=f"{t}:{slug}", source="paymentscan", entity_type=t, display_name=name, slug=slug, aliases=tuple(aliases))

PAYMENTSCAN_CARD_PROGRAMS = (
    e("card_program", "RedotPay", "redotpay", "Red.Pay", "Redot Pay"), e("card_program", "KAST", "kast"),
    e("card_program", "EtherFi", "etherfi", "ether.fi"), e("card_program", "Plasma One", "plasma_one"),
    e("card_program", "Karta", "karta"), e("card_program", "Tria", "tria"), e("card_program", "Gnosis", "gnosis", "Gnosis Pay"),
    e("card_program", "Cypher", "cypher"), e("card_program", "Kolo", "kolo"), e("card_program", "Ready", "ready"),
    e("card_program", "BFinance", "bfinance"), e("card_program", "MetaMask", "metamask", "MetaMask Card"),
    e("card_program", "Holyheld", "holyheld"), e("card_program", "Bitget Wallet", "bitget_wallet"), e("card_program", "Avici", "avici"),
    e("card_program", "SafePal", "safepal"), e("card_program", "Solayer", "solayer"), e("card_program", "Avalanche Card", "avalanche_card"),
    e("card_program", "Exa", "exa"), e("card_program", "Tuyo", "tuyo"), e("card_program", "Solflare", "solflare"),
    e("card_program", "Phantom Cash", "phantom_cash"), e("card_program", "Hyperbeat", "hyperbeat"),
)
PAYMENTSCAN_ISSUERS = tuple(e("issuer", name, slug) for name, slug in (("Rain","rain"),("Wirex","wirex"),("Bridge","bridge"),("UR","ur"),("Kulipa","kulipa"),("Immersve","immersve")))
PAYMENT_NETWORKS = (e("payment_network", "Visa", "visa"), e("payment_network", "Mastercard", "mastercard", "MasterCard"), e("payment_network", "Unknown", "unknown"))
CHAINS = tuple(e("chain", n, n.lower().replace(" ", "_")) for n in ("Ethereum", "TRON", "BSC", "Optimism", "Solana", "Arbitrum", "Base", "Other", "Unknown"))
CURRENCIES = tuple(e("currency", n, n.lower().replace(" ", "_")) for n in ("USDC", "USDT", "EURe", "GBPe", "USD24", "liquidUSD", "Other", "Unknown"))
PAYMENTSCAN_CATALOG_SEED = PAYMENTSCAN_CARD_PROGRAMS + PAYMENTSCAN_ISSUERS + PAYMENT_NETWORKS + CHAINS + CURRENCIES
ALIAS_TO_SLUG = {k.lower(): v for item in PAYMENTSCAN_CATALOG_SEED for k, v in ((item.display_name, item.slug), (item.slug, item.slug), *[(a, item.slug) for a in item.aliases])}

def resolve_slug(value: str) -> str | None:
    return ALIAS_TO_SLUG.get(value.strip().lower())
