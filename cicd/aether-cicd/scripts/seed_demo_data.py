#!/usr/bin/env python3
"""
Aether Demo Environment -- Data Seeding Script

Populates the demo environment with realistic sample data so that
sales, BD, and growth teams can demonstrate Aether's capabilities
to prospects.

Usage:
    python seed_demo_data.py --url https://demo.aether.io --api-key <key>
    python seed_demo_data.py --url https://demo.aether.io --api-key <key> --clear-existing

Data categories seeded:
  - Identity profiles (50 synthetic users with traits, segments)
  - Web3 wallets (10 wallets across EVM/SVM/BTC)
  - SDK events (500 events: page views, tracks, identifies, wallet connections)
  - DeFi positions (30 positions across multiple protocols)
  - Portfolio snapshots (cross-chain portfolio data)
  - Campaign data (3 sample campaigns with engagement metrics)
  - Analytics aggregates (7-day trend data for dashboard charts)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("DEMO_URL", "https://demo.aether.io")
API_KEY = os.environ.get("DEMO_API_KEY", "demo_api_key_placeholder")

HEADERS: Dict[str, str] = {}


def _headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
    }


def _post(path: str, payload: Any) -> bool:
    """POST JSON to demo API. Returns True on success."""
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=30)
        if resp.status_code >= 400:
            print(f"  WARN: {path} returned {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"  WARN: {path} failed: {exc}")
        return False


def _delete(path: str) -> bool:
    """DELETE against demo API. Returns True on success."""
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.delete(url, headers=_headers(), timeout=30)
        return resp.status_code < 400
    except requests.RequestException:
        return False


# ---------------------------------------------------------------------------
# DATA GENERATORS
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn",
    "Skyler", "Dakota", "Reese", "Finley", "Emery", "Rowan", "Hayden", "Blake",
    "Cameron", "Drew", "Eden", "Harper", "Jamie", "Kendall", "Logan", "Nico",
    "Parker", "Remy", "Sage", "Tatum", "Val", "Winter", "Yael", "Zion",
    "Adrian", "Briar", "Charlie", "Devon", "Ellis", "Frankie", "Gray", "Hollis",
    "Indigo", "Jules", "Kit", "Lane", "Marlowe", "Noel", "Oakley", "Peyton",
    "Raven", "Sterling",
]

LAST_NAMES = [
    "Chen", "Patel", "Kim", "Garcia", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas",
    "Jackson", "White", "Harris", "Martin", "Thompson", "Robinson", "Clark",
    "Lewis", "Lee", "Walker", "Hall", "Allen", "Young", "King", "Wright",
    "Lopez", "Hill", "Scott", "Green", "Adams", "Baker", "Nelson", "Carter",
    "Mitchell", "Perez", "Roberts", "Turner", "Phillips", "Campbell", "Parker",
    "Evans", "Edwards", "Collins", "Stewart", "Sanchez",
]

SEGMENTS = [
    "Power Trader", "DeFi Whale", "NFT Collector", "Casual User",
    "Institutional", "Yield Farmer", "Cross-Chain Explorer",
    "Governance Participant", "New User", "Dormant",
]

EVM_ADDRESSES = [
    "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68",
    "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
    "0x8315177aB297bA92A06054cE80a67Ed4DBd7ed3a",
    "0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8",
    "0xDA9dfA130Df4dE4673b89022EE50ff26f6EA73Cf",
]

SVM_ADDRESSES = [
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
]

BTC_ADDRESSES = [
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
    "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c",
]

DEFI_PROTOCOLS = [
    {"name": "Uniswap V3", "category": "dex", "vm": "evm", "chain_id": 1},
    {"name": "AAVE V3", "category": "lending", "vm": "evm", "chain_id": 1},
    {"name": "Lido", "category": "liquid_staking", "vm": "evm", "chain_id": 1},
    {"name": "GMX V2", "category": "perpetuals", "vm": "evm", "chain_id": 42161},
    {"name": "Curve", "category": "dex", "vm": "evm", "chain_id": 1},
    {"name": "Jupiter", "category": "router", "vm": "svm", "chain_id": 101},
    {"name": "Marinade", "category": "liquid_staking", "vm": "svm", "chain_id": 101},
    {"name": "Raydium", "category": "dex", "vm": "svm", "chain_id": 101},
    {"name": "Drift", "category": "perpetuals", "vm": "svm", "chain_id": 101},
    {"name": "Wormhole", "category": "bridge", "vm": "evm", "chain_id": 1},
    {"name": "EigenLayer", "category": "restaking", "vm": "evm", "chain_id": 1},
    {"name": "Yearn V3", "category": "yield", "vm": "evm", "chain_id": 1},
    {"name": "Compound V3", "category": "lending", "vm": "evm", "chain_id": 1},
    {"name": "PancakeSwap", "category": "dex", "vm": "evm", "chain_id": 56},
    {"name": "Stargate", "category": "bridge", "vm": "evm", "chain_id": 1},
]

EVENT_TYPES = [
    "page_view", "track", "identify", "wallet_connect", "wallet_disconnect",
    "swap", "supply", "borrow", "stake", "bridge_initiate", "bridge_complete",
    "nft_buy", "nft_sell", "vote", "claim_rewards",
]

PAGES = [
    "/dashboard", "/portfolio", "/swap", "/earn", "/bridge", "/governance",
    "/nfts", "/settings", "/profile", "/analytics", "/positions", "/history",
]


def _random_timestamp(days_back: int = 7) -> str:
    """Generate a random ISO timestamp within the last N days."""
    now = datetime.now(timezone.utc)
    delta = timedelta(seconds=random.randint(0, days_back * 86400))
    ts = now - delta
    return ts.isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# SEED FUNCTIONS
# ---------------------------------------------------------------------------

def seed_identity_profiles(count: int = 50) -> int:
    """Seed synthetic identity profiles with traits and segments."""
    print(f"\n--- Seeding {count} identity profiles ---")
    success = 0
    for i in range(count):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[i % len(LAST_NAMES)]
        profile = {
            "userId": _uid(),
            "traits": {
                "firstName": first,
                "lastName": last,
                "email": f"{first.lower()}.{last.lower()}@demo-user.io",
                "plan": random.choice(["free", "pro", "enterprise"]),
                "signupDate": _random_timestamp(days_back=90),
                "totalTransactions": random.randint(5, 2000),
                "totalVolumeUSD": round(random.uniform(500, 2_000_000), 2),
                "preferredChain": random.choice(["ethereum", "solana", "polygon", "arbitrum", "bsc"]),
                "walletCount": random.randint(1, 5),
                "kycVerified": random.choice([True, False]),
                "country": random.choice(["US", "GB", "DE", "JP", "SG", "KR", "AU", "CA", "FR", "BR"]),
            },
            "segments": random.sample(SEGMENTS, k=random.randint(1, 3)),
            "timestamp": _random_timestamp(days_back=30),
        }
        if _post("/v1/identify", profile):
            success += 1
    print(f"  Created {success}/{count} identity profiles")
    return success


def seed_wallets(count: int = 10) -> int:
    """Seed wallet connection events across EVM/SVM/BTC."""
    print(f"\n--- Seeding {count} wallet connections ---")
    success = 0

    wallets = []
    # EVM wallets
    for addr in EVM_ADDRESSES:
        wallets.append({
            "address": addr,
            "vm": "evm",
            "chainId": random.choice([1, 137, 42161, 10, 8453]),
            "walletType": random.choice(["metamask", "coinbase_wallet", "rabby", "ledger"]),
            "classification": random.choice(["hot", "cold", "smart"]),
        })
    # SVM wallets
    for addr in SVM_ADDRESSES:
        wallets.append({
            "address": addr,
            "vm": "svm",
            "chainId": 101,
            "walletType": random.choice(["phantom", "solflare", "backpack"]),
            "classification": "hot",
        })
    # BTC wallets
    for addr in BTC_ADDRESSES:
        wallets.append({
            "address": addr,
            "vm": "bitcoin",
            "chainId": 0,
            "walletType": random.choice(["unisat", "xverse", "leather"]),
            "classification": "hot",
        })

    for wallet in wallets[:count]:
        event = {
            "type": "wallet_connect",
            "userId": _uid(),
            "properties": wallet,
            "timestamp": _random_timestamp(days_back=7),
        }
        if _post("/v1/track", event):
            success += 1
    print(f"  Connected {success}/{count} wallets")
    return success


def seed_events(count: int = 500) -> int:
    """Seed SDK events: page views, tracks, wallet interactions."""
    print(f"\n--- Seeding {count} SDK events ---")
    success = 0
    batch_size = 50
    batch: List[Dict] = []

    for i in range(count):
        event_type = random.choice(EVENT_TYPES)
        event: Dict[str, Any] = {
            "type": event_type,
            "userId": _uid(),
            "timestamp": _random_timestamp(days_back=7),
            "properties": {},
        }

        if event_type == "page_view":
            event["properties"] = {
                "path": random.choice(PAGES),
                "referrer": random.choice(["google.com", "twitter.com", "direct", "discord.gg", ""]),
                "sessionId": _uid(),
                "duration": random.randint(5, 600),
            }
        elif event_type == "swap":
            event["properties"] = {
                "protocol": random.choice(["Uniswap V3", "Jupiter", "PancakeSwap", "Curve"]),
                "tokenIn": random.choice(["ETH", "USDC", "SOL", "WBTC"]),
                "tokenOut": random.choice(["USDC", "DAI", "WETH", "USDT"]),
                "amountInUSD": round(random.uniform(100, 50_000), 2),
                "slippage": round(random.uniform(0.1, 2.0), 2),
            }
        elif event_type in ("supply", "borrow"):
            event["properties"] = {
                "protocol": random.choice(["AAVE V3", "Compound V3"]),
                "token": random.choice(["ETH", "USDC", "DAI", "WBTC"]),
                "amountUSD": round(random.uniform(1000, 200_000), 2),
                "apy": round(random.uniform(1.5, 12.0), 2),
            }
        elif event_type == "stake":
            event["properties"] = {
                "protocol": random.choice(["Lido", "Marinade", "EigenLayer", "Rocket Pool"]),
                "token": random.choice(["ETH", "SOL"]),
                "amountUSD": round(random.uniform(500, 100_000), 2),
            }
        elif event_type in ("bridge_initiate", "bridge_complete"):
            event["properties"] = {
                "protocol": random.choice(["Wormhole", "Stargate", "Across"]),
                "sourceChain": random.choice(["ethereum", "polygon", "arbitrum"]),
                "destChain": random.choice(["solana", "optimism", "base"]),
                "token": random.choice(["USDC", "ETH", "WBTC"]),
                "amountUSD": round(random.uniform(500, 50_000), 2),
            }
        elif event_type in ("nft_buy", "nft_sell"):
            event["properties"] = {
                "marketplace": random.choice(["OpenSea", "Blur", "Magic Eden", "Tensor"]),
                "collection": random.choice(["BAYC", "Azuki", "DeGods", "Pudgy Penguins"]),
                "priceUSD": round(random.uniform(50, 25_000), 2),
            }
        else:
            event["properties"] = {
                "action": event_type,
                "value": round(random.uniform(10, 10_000), 2),
            }

        batch.append(event)

        if len(batch) >= batch_size:
            if _post("/v1/batch", {"events": batch}):
                success += len(batch)
            batch = []

    # Flush remaining
    if batch:
        if _post("/v1/batch", {"events": batch}):
            success += len(batch)

    print(f"  Seeded {success}/{count} events")
    return success


def seed_defi_positions(count: int = 30) -> int:
    """Seed DeFi position data across multiple protocols."""
    print(f"\n--- Seeding {count} DeFi positions ---")
    success = 0

    for i in range(count):
        protocol = DEFI_PROTOCOLS[i % len(DEFI_PROTOCOLS)]
        position: Dict[str, Any] = {
            "userId": _uid(),
            "protocol": protocol["name"],
            "category": protocol["category"],
            "vm": protocol["vm"],
            "chainId": protocol["chain_id"],
            "positionType": "active",
            "valueUSD": round(random.uniform(1_000, 250_000), 2),
            "timestamp": _random_timestamp(days_back=7),
        }

        if protocol["category"] in ("lending",):
            position["apy"] = round(random.uniform(2.0, 15.0), 2)
            position["healthFactor"] = round(random.uniform(1.2, 5.0), 2)
            position["assets"] = [
                {"token": "ETH", "amount": round(random.uniform(1, 50), 4), "valueUSD": position["valueUSD"]},
            ]
        elif protocol["category"] in ("dex",):
            position["apy"] = round(random.uniform(5.0, 80.0), 2)
            position["assets"] = [
                {"token": "ETH", "amount": round(random.uniform(1, 20), 4), "valueUSD": position["valueUSD"] / 2},
                {"token": "USDC", "amount": round(position["valueUSD"] / 2, 2), "valueUSD": position["valueUSD"] / 2},
            ]
            position["pnl"] = round(random.uniform(-5_000, 20_000), 2)
        elif protocol["category"] in ("perpetuals",):
            position["leverage"] = random.choice([2, 3, 5, 10, 20])
            position["pnl"] = round(random.uniform(-10_000, 50_000), 2)
            position["assets"] = [
                {"token": "ETH", "amount": round(random.uniform(1, 100), 4), "valueUSD": position["valueUSD"]},
            ]
        elif protocol["category"] in ("liquid_staking", "restaking"):
            position["apy"] = round(random.uniform(3.0, 8.0), 2)
            position["assets"] = [
                {"token": random.choice(["stETH", "mSOL", "rETH"]),
                 "amount": round(random.uniform(5, 200), 4),
                 "valueUSD": position["valueUSD"]},
            ]
        elif protocol["category"] in ("bridge",):
            position["assets"] = [
                {"token": "USDC", "amount": round(position["valueUSD"], 2), "valueUSD": position["valueUSD"]},
            ]
        else:
            position["apy"] = round(random.uniform(3.0, 25.0), 2)
            position["assets"] = [
                {"token": "USDC", "amount": round(position["valueUSD"], 2), "valueUSD": position["valueUSD"]},
            ]

        if _post("/v1/track", {"type": "defi_position", "userId": position["userId"], "properties": position, "timestamp": position["timestamp"]}):
            success += 1

    print(f"  Seeded {success}/{count} DeFi positions")
    return success


def seed_portfolio_snapshots(count: int = 10) -> int:
    """Seed portfolio snapshots with cross-chain breakdowns."""
    print(f"\n--- Seeding {count} portfolio snapshots ---")
    success = 0

    for i in range(count):
        total = round(random.uniform(50_000, 500_000), 2)
        eth_pct = random.uniform(0.3, 0.6)
        sol_pct = random.uniform(0.1, 0.3)
        btc_pct = 1.0 - eth_pct - sol_pct

        snapshot = {
            "userId": _uid(),
            "totalValueUSD": total,
            "timestamp": _random_timestamp(days_back=7),
            "chains": [
                {"chainId": 1, "name": "Ethereum", "valueUSD": round(total * eth_pct, 2)},
                {"chainId": 137, "name": "Polygon", "valueUSD": round(total * eth_pct * 0.1, 2)},
                {"chainId": 42161, "name": "Arbitrum", "valueUSD": round(total * eth_pct * 0.15, 2)},
                {"chainId": 101, "name": "Solana", "valueUSD": round(total * sol_pct, 2)},
                {"chainId": 0, "name": "Bitcoin", "valueUSD": round(total * btc_pct, 2)},
            ],
            "tokens": [
                {"symbol": "ETH", "balance": round(total * eth_pct / 3200, 4), "valueUSD": round(total * eth_pct, 2)},
                {"symbol": "SOL", "balance": round(total * sol_pct / 180, 2), "valueUSD": round(total * sol_pct, 2)},
                {"symbol": "BTC", "balance": round(total * btc_pct / 65000, 6), "valueUSD": round(total * btc_pct, 2)},
                {"symbol": "USDC", "balance": round(random.uniform(1000, 50000), 2), "valueUSD": round(random.uniform(1000, 50000), 2)},
            ],
        }

        if _post("/v1/track", {"type": "portfolio_snapshot", "userId": snapshot["userId"], "properties": snapshot, "timestamp": snapshot["timestamp"]}):
            success += 1

    print(f"  Seeded {success}/{count} portfolio snapshots")
    return success


def seed_campaigns(count: int = 3) -> int:
    """Seed sample marketing campaigns with engagement metrics."""
    print(f"\n--- Seeding {count} campaigns ---")
    success = 0

    campaigns = [
        {
            "name": "DeFi Power Users - Yield Optimization",
            "status": "active",
            "channel": "in_app",
            "targetSegment": "DeFi Whale",
            "startDate": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            "metrics": {
                "sent": 1250, "delivered": 1180, "opened": 890,
                "clicked": 340, "converted": 78,
                "conversionRate": 6.24, "revenueUSD": 45_600,
            },
        },
        {
            "name": "Cross-Chain Bridge Promotion",
            "status": "active",
            "channel": "push_notification",
            "targetSegment": "Cross-Chain Explorer",
            "startDate": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
            "metrics": {
                "sent": 3400, "delivered": 3200, "opened": 1560,
                "clicked": 780, "converted": 156,
                "conversionRate": 4.88, "revenueUSD": 92_300,
            },
        },
        {
            "name": "New User Onboarding Flow",
            "status": "completed",
            "channel": "email",
            "targetSegment": "New User",
            "startDate": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(),
            "endDate": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "metrics": {
                "sent": 5600, "delivered": 5400, "opened": 2700,
                "clicked": 1350, "converted": 540,
                "conversionRate": 10.0, "revenueUSD": 128_500,
            },
        },
    ]

    for campaign in campaigns[:count]:
        campaign["campaignId"] = _uid()
        if _post("/v1/campaigns", campaign):
            success += 1

    print(f"  Seeded {success}/{count} campaigns")
    return success


def seed_analytics_aggregates() -> int:
    """Seed 7-day trend data for dashboard charts."""
    print("\n--- Seeding analytics aggregates (7-day trends) ---")
    success = 0

    now = datetime.now(timezone.utc)
    for day_offset in range(7):
        day = now - timedelta(days=day_offset)
        date_str = day.strftime("%Y-%m-%d")

        aggregate = {
            "date": date_str,
            "metrics": {
                "dailyActiveUsers": random.randint(800, 2500),
                "totalEvents": random.randint(5000, 25000),
                "totalTransactions": random.randint(300, 3000),
                "totalVolumeUSD": round(random.uniform(500_000, 5_000_000), 2),
                "newUsers": random.randint(50, 300),
                "walletsConnected": random.randint(100, 800),
                "uniqueProtocols": random.randint(15, 45),
                "avgSessionDuration": random.randint(120, 900),
                "bounceRate": round(random.uniform(15.0, 45.0), 1),
                "retention7d": round(random.uniform(30.0, 65.0), 1),
            },
            "chainBreakdown": {
                "ethereum": round(random.uniform(30, 50), 1),
                "solana": round(random.uniform(15, 30), 1),
                "polygon": round(random.uniform(5, 15), 1),
                "arbitrum": round(random.uniform(5, 15), 1),
                "bsc": round(random.uniform(3, 10), 1),
                "bitcoin": round(random.uniform(5, 15), 1),
            },
        }

        if _post("/v1/analytics/aggregate", aggregate):
            success += 1

    print(f"  Seeded {success}/7 daily aggregates")
    return success


def clear_demo_data() -> None:
    """Clear existing demo data before re-seeding."""
    print("\n--- Clearing existing demo data ---")
    endpoints = [
        "/v1/demo/clear/identities",
        "/v1/demo/clear/events",
        "/v1/demo/clear/campaigns",
        "/v1/demo/clear/analytics",
    ]
    for endpoint in endpoints:
        result = _delete(endpoint)
        status = "OK" if result else "SKIP"
        print(f"  {status}: {endpoint}")
    print("  Clear complete (non-existent endpoints are skipped)")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    global BASE_URL, API_KEY

    parser = argparse.ArgumentParser(description="Seed Aether demo environment with sample data")
    parser.add_argument("--url", default=BASE_URL, help="Demo API base URL")
    parser.add_argument("--api-key", default=API_KEY, help="Demo API key")
    parser.add_argument("--clear-existing", action="store_true", help="Clear existing demo data first")
    parser.add_argument("--profiles", type=int, default=50, help="Number of identity profiles")
    parser.add_argument("--wallets", type=int, default=10, help="Number of wallets")
    parser.add_argument("--events", type=int, default=500, help="Number of SDK events")
    parser.add_argument("--defi-positions", type=int, default=30, help="Number of DeFi positions")
    parser.add_argument("--portfolios", type=int, default=10, help="Number of portfolio snapshots")
    parser.add_argument("--campaigns", type=int, default=3, help="Number of campaigns")

    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")
    API_KEY = args.api_key

    print("=" * 60)
    print("  Aether Demo Data Seeder")
    print(f"  Target: {BASE_URL}")
    print(f"  Time:   {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    start = time.time()

    if args.clear_existing:
        clear_demo_data()

    totals = {
        "profiles": seed_identity_profiles(args.profiles),
        "wallets": seed_wallets(args.wallets),
        "events": seed_events(args.events),
        "defi_positions": seed_defi_positions(args.defi_positions),
        "portfolios": seed_portfolio_snapshots(args.portfolios),
        "campaigns": seed_campaigns(args.campaigns),
        "analytics_days": seed_analytics_aggregates(),
    }

    elapsed = time.time() - start

    print(f"\n{'=' * 60}")
    print("  SEED COMPLETE")
    print(f"  Duration: {elapsed:.1f}s")
    for category, count in totals.items():
        print(f"  {category}: {count}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
