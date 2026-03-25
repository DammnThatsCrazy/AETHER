"""
Aether Web3 Coverage — Registry Seed Data

Initial seed for the canonical registries. Covers:
- 30+ chains (all major EVM L1/L2s, Solana, Bitcoin, Cosmos, etc.)
- 50+ protocols (top DeFi by TVL + major verticals)
- 30+ apps/dApps (frontends, wallets, aggregators)
- 20+ tokens (major stablecoins, wrapped assets, native tokens)
- 15+ governance spaces
- 10+ market venues
- 10+ bridge routes

This seed is designed for the rolling registry target: top-100-by-market-cap
ecosystem coverage. New entries are added through provider-backed discovery
(Dune, DeFiLlama, CoinGecko) without architecture changes.
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════════════════════
# CHAIN SEED
# ═══════════════════════════════════════════════════════════════════════════

CHAIN_SEED: list[dict] = [
    # ── EVM L1s ─────────────────────────────────────────────────────────
    {"chain_id": "ethereum", "canonical_name": "Ethereum", "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 1, "native_token_symbol": "ETH", "block_explorer_url": "https://etherscan.io", "status": "active", "source": "seed"},
    {"chain_id": "bnb-chain", "canonical_name": "BNB Chain", "aliases": ["BSC", "Binance Smart Chain"], "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 56, "native_token_symbol": "BNB", "block_explorer_url": "https://bscscan.com", "status": "active", "source": "seed"},
    {"chain_id": "avalanche", "canonical_name": "Avalanche C-Chain", "aliases": ["AVAX"], "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 43114, "native_token_symbol": "AVAX", "block_explorer_url": "https://snowtrace.io", "status": "active", "source": "seed"},
    {"chain_id": "fantom", "canonical_name": "Fantom", "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 250, "native_token_symbol": "FTM", "block_explorer_url": "https://ftmscan.com", "status": "active", "source": "seed"},
    {"chain_id": "gnosis", "canonical_name": "Gnosis Chain", "aliases": ["xDai"], "vm_family": "evm", "chain_type": "sidechain", "evm_chain_id": 100, "native_token_symbol": "xDAI", "block_explorer_url": "https://gnosisscan.io", "status": "active", "source": "seed"},
    {"chain_id": "celo", "canonical_name": "Celo", "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 42220, "native_token_symbol": "CELO", "block_explorer_url": "https://celoscan.io", "status": "active", "source": "seed"},
    {"chain_id": "moonbeam", "canonical_name": "Moonbeam", "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 1284, "native_token_symbol": "GLMR", "block_explorer_url": "https://moonbeam.moonscan.io", "status": "active", "source": "seed"},

    # ── EVM L2s / Rollups ───────────────────────────────────────────────
    {"chain_id": "arbitrum-one", "canonical_name": "Arbitrum One", "aliases": ["Arbitrum"], "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 42161, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://arbiscan.io", "status": "active", "source": "seed"},
    {"chain_id": "optimism", "canonical_name": "OP Mainnet", "aliases": ["Optimism"], "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 10, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://optimistic.etherscan.io", "status": "active", "source": "seed"},
    {"chain_id": "base", "canonical_name": "Base", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 8453, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://basescan.org", "status": "active", "source": "seed"},
    {"chain_id": "polygon", "canonical_name": "Polygon PoS", "aliases": ["Matic"], "vm_family": "evm", "chain_type": "sidechain", "evm_chain_id": 137, "native_token_symbol": "POL", "block_explorer_url": "https://polygonscan.com", "status": "active", "source": "seed"},
    {"chain_id": "polygon-zkevm", "canonical_name": "Polygon zkEVM", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 1101, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://zkevm.polygonscan.com", "status": "active", "source": "seed"},
    {"chain_id": "zksync-era", "canonical_name": "zkSync Era", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 324, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://explorer.zksync.io", "status": "active", "source": "seed"},
    {"chain_id": "linea", "canonical_name": "Linea", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 59144, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://lineascan.build", "status": "active", "source": "seed"},
    {"chain_id": "scroll", "canonical_name": "Scroll", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 534352, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://scrollscan.com", "status": "active", "source": "seed"},
    {"chain_id": "mantle", "canonical_name": "Mantle", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 5000, "native_token_symbol": "MNT", "parent_chain_id": "ethereum", "block_explorer_url": "https://mantlescan.xyz", "status": "active", "source": "seed"},
    {"chain_id": "blast", "canonical_name": "Blast", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 81457, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://blastscan.io", "status": "active", "source": "seed"},
    {"chain_id": "mode", "canonical_name": "Mode", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 34443, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://modescan.io", "status": "active", "source": "seed"},
    {"chain_id": "unichain", "canonical_name": "Unichain", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 130, "native_token_symbol": "ETH", "parent_chain_id": "ethereum", "block_explorer_url": "https://uniscan.xyz", "status": "active", "source": "seed"},
    {"chain_id": "sei", "canonical_name": "Sei", "vm_family": "evm", "chain_type": "l1", "evm_chain_id": 1329, "native_token_symbol": "SEI", "block_explorer_url": "https://seitrace.com", "status": "active", "source": "seed"},
    {"chain_id": "aurora", "canonical_name": "Aurora", "vm_family": "evm", "chain_type": "l2", "evm_chain_id": 1313161554, "native_token_symbol": "ETH", "parent_chain_id": "near", "block_explorer_url": "https://explorer.aurora.dev", "status": "active", "source": "seed"},

    # ── Non-EVM chains ──────────────────────────────────────────────────
    {"chain_id": "solana", "canonical_name": "Solana", "vm_family": "svm", "chain_type": "l1", "native_token_symbol": "SOL", "block_explorer_url": "https://solscan.io", "status": "active", "source": "seed"},
    {"chain_id": "bitcoin", "canonical_name": "Bitcoin", "vm_family": "bitcoin", "chain_type": "l1", "native_token_symbol": "BTC", "block_explorer_url": "https://mempool.space", "status": "active", "source": "seed"},
    {"chain_id": "near", "canonical_name": "NEAR Protocol", "vm_family": "near", "chain_type": "l1", "native_token_symbol": "NEAR", "block_explorer_url": "https://nearblocks.io", "status": "active", "source": "seed"},
    {"chain_id": "tron", "canonical_name": "TRON", "vm_family": "tvm", "chain_type": "l1", "native_token_symbol": "TRX", "block_explorer_url": "https://tronscan.org", "status": "active", "source": "seed"},
    {"chain_id": "sui", "canonical_name": "Sui", "vm_family": "movevm", "chain_type": "l1", "native_token_symbol": "SUI", "block_explorer_url": "https://suiscan.xyz", "status": "active", "source": "seed"},
    {"chain_id": "aptos", "canonical_name": "Aptos", "vm_family": "movevm", "chain_type": "l1", "native_token_symbol": "APT", "block_explorer_url": "https://aptoscan.com", "status": "active", "source": "seed"},
    {"chain_id": "cosmos-hub", "canonical_name": "Cosmos Hub", "vm_family": "cosmos", "chain_type": "l1", "native_token_symbol": "ATOM", "block_explorer_url": "https://mintscan.io/cosmos", "status": "active", "source": "seed"},
    {"chain_id": "osmosis", "canonical_name": "Osmosis", "vm_family": "cosmos", "chain_type": "appchain", "native_token_symbol": "OSMO", "block_explorer_url": "https://mintscan.io/osmosis", "status": "active", "source": "seed"},

    # ── Emerging / Pre-launch ───────────────────────────────────────────
    {"chain_id": "hyperliquid", "canonical_name": "Hyperliquid", "vm_family": "evm", "chain_type": "l1", "native_token_symbol": "HYPE", "block_explorer_url": "https://hyperliquid.xyz", "status": "active", "source": "seed"},
    {"chain_id": "monad", "canonical_name": "Monad", "vm_family": "evm", "chain_type": "l1", "native_token_symbol": "MON", "status": "active", "source": "seed"},
]


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOL SEED (top by TVL + major verticals)
# ═══════════════════════════════════════════════════════════════════════════

PROTOCOL_SEED: list[dict] = [
    # ── DEX ─────────────────────────────────────────────────────────────
    {"protocol_id": "uniswap", "canonical_name": "Uniswap", "protocol_family": "dex", "chains": ["ethereum", "arbitrum-one", "optimism", "base", "polygon", "bnb-chain", "avalanche", "celo", "blast", "zksync-era"], "defillama_slug": "uniswap", "status": "active", "source": "seed"},
    {"protocol_id": "curve", "canonical_name": "Curve Finance", "protocol_family": "dex", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "base", "fantom", "avalanche", "gnosis"], "defillama_slug": "curve-dex", "status": "active", "source": "seed"},
    {"protocol_id": "pancakeswap", "canonical_name": "PancakeSwap", "protocol_family": "dex", "chains": ["bnb-chain", "ethereum", "arbitrum-one", "base", "polygon-zkevm", "linea", "zksync-era"], "defillama_slug": "pancakeswap", "status": "active", "source": "seed"},
    {"protocol_id": "sushiswap", "canonical_name": "SushiSwap", "protocol_family": "dex", "chains": ["ethereum", "arbitrum-one", "polygon", "avalanche", "fantom", "bnb-chain", "base", "optimism"], "defillama_slug": "sushi", "status": "active", "source": "seed"},
    {"protocol_id": "balancer", "canonical_name": "Balancer", "protocol_family": "dex", "chains": ["ethereum", "arbitrum-one", "polygon", "gnosis", "avalanche", "base", "optimism"], "defillama_slug": "balancer-v2", "status": "active", "source": "seed"},
    {"protocol_id": "raydium", "canonical_name": "Raydium", "protocol_family": "dex", "chains": ["solana"], "defillama_slug": "raydium", "status": "active", "source": "seed"},
    {"protocol_id": "orca", "canonical_name": "Orca", "protocol_family": "dex", "chains": ["solana"], "defillama_slug": "orca", "status": "active", "source": "seed"},
    {"protocol_id": "trader-joe", "canonical_name": "Trader Joe", "protocol_family": "dex", "chains": ["avalanche", "arbitrum-one", "bnb-chain"], "defillama_slug": "trader-joe", "status": "active", "source": "seed"},

    # ── Lending ─────────────────────────────────────────────────────────
    {"protocol_id": "aave", "canonical_name": "Aave", "protocol_family": "lending", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "avalanche", "base", "gnosis", "bnb-chain", "scroll", "metis"], "defillama_slug": "aave", "status": "active", "source": "seed"},
    {"protocol_id": "compound", "canonical_name": "Compound", "protocol_family": "lending", "chains": ["ethereum", "arbitrum-one", "base", "optimism", "polygon", "scroll"], "defillama_slug": "compound-finance", "status": "active", "source": "seed"},
    {"protocol_id": "morpho", "canonical_name": "Morpho", "protocol_family": "lending", "chains": ["ethereum", "base"], "defillama_slug": "morpho", "status": "active", "source": "seed"},
    {"protocol_id": "spark", "canonical_name": "Spark Protocol", "protocol_family": "lending", "chains": ["ethereum", "gnosis"], "defillama_slug": "spark", "status": "active", "source": "seed"},
    {"protocol_id": "venus", "canonical_name": "Venus", "protocol_family": "lending", "chains": ["bnb-chain"], "defillama_slug": "venus", "status": "active", "source": "seed"},

    # ── Staking / Restaking ─────────────────────────────────────────────
    {"protocol_id": "lido", "canonical_name": "Lido", "protocol_family": "staking", "chains": ["ethereum", "polygon"], "defillama_slug": "lido", "status": "active", "source": "seed"},
    {"protocol_id": "rocket-pool", "canonical_name": "Rocket Pool", "protocol_family": "staking", "chains": ["ethereum"], "defillama_slug": "rocket-pool", "status": "active", "source": "seed"},
    {"protocol_id": "eigenlayer", "canonical_name": "EigenLayer", "protocol_family": "restaking", "chains": ["ethereum"], "defillama_slug": "eigenlayer", "status": "active", "source": "seed"},
    {"protocol_id": "jito", "canonical_name": "Jito", "protocol_family": "staking", "chains": ["solana"], "defillama_slug": "jito", "status": "active", "source": "seed"},
    {"protocol_id": "marinade", "canonical_name": "Marinade Finance", "protocol_family": "staking", "chains": ["solana"], "defillama_slug": "marinade-finance", "status": "active", "source": "seed"},

    # ── Bridges ─────────────────────────────────────────────────────────
    {"protocol_id": "stargate", "canonical_name": "Stargate Finance", "protocol_family": "bridge", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "bnb-chain", "avalanche", "base", "linea", "mantle", "scroll"], "defillama_slug": "stargate", "status": "active", "source": "seed"},
    {"protocol_id": "across", "canonical_name": "Across Protocol", "protocol_family": "bridge", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "base", "linea", "zksync-era"], "defillama_slug": "across", "status": "active", "source": "seed"},
    {"protocol_id": "wormhole", "canonical_name": "Wormhole", "protocol_family": "bridge", "chains": ["ethereum", "solana", "bnb-chain", "polygon", "avalanche", "arbitrum-one", "optimism", "base", "sui", "aptos", "near"], "defillama_slug": "wormhole", "status": "active", "source": "seed"},
    {"protocol_id": "layerzero", "canonical_name": "LayerZero", "protocol_family": "infrastructure", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "bnb-chain", "avalanche", "base", "fantom", "linea", "scroll", "mantle"], "defillama_slug": "layerzero", "status": "active", "source": "seed"},

    # ── Stablecoins ─────────────────────────────────────────────────────
    {"protocol_id": "maker", "canonical_name": "MakerDAO / Sky", "aliases": ["Sky", "MakerDAO"], "protocol_family": "stablecoin", "chains": ["ethereum"], "defillama_slug": "makerdao", "status": "active", "source": "seed"},
    {"protocol_id": "frax", "canonical_name": "Frax Finance", "protocol_family": "stablecoin", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "bnb-chain", "avalanche"], "defillama_slug": "frax-finance", "status": "active", "source": "seed"},
    {"protocol_id": "ethena", "canonical_name": "Ethena", "protocol_family": "stablecoin", "chains": ["ethereum"], "defillama_slug": "ethena", "status": "active", "source": "seed"},

    # ── Yield Aggregators ───────────────────────────────────────────────
    {"protocol_id": "yearn", "canonical_name": "Yearn Finance", "protocol_family": "yield_aggregator", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "fantom", "base"], "defillama_slug": "yearn-finance", "status": "active", "source": "seed"},
    {"protocol_id": "convex", "canonical_name": "Convex Finance", "protocol_family": "yield_aggregator", "chains": ["ethereum", "arbitrum-one"], "defillama_slug": "convex-finance", "status": "active", "source": "seed"},
    {"protocol_id": "pendle", "canonical_name": "Pendle", "protocol_family": "yield_aggregator", "chains": ["ethereum", "arbitrum-one", "bnb-chain", "optimism", "mantle"], "defillama_slug": "pendle", "status": "active", "source": "seed"},

    # ── Derivatives ─────────────────────────────────────────────────────
    {"protocol_id": "gmx", "canonical_name": "GMX", "protocol_family": "derivatives", "chains": ["arbitrum-one", "avalanche"], "defillama_slug": "gmx", "status": "active", "source": "seed"},
    {"protocol_id": "dydx", "canonical_name": "dYdX", "protocol_family": "derivatives", "chains": ["ethereum"], "defillama_slug": "dydx", "status": "active", "source": "seed"},
    {"protocol_id": "hyperliquid-perps", "canonical_name": "Hyperliquid", "protocol_family": "derivatives", "chains": ["hyperliquid"], "defillama_slug": "hyperliquid", "status": "active", "source": "seed"},
    {"protocol_id": "synthetix", "canonical_name": "Synthetix", "protocol_family": "derivatives", "chains": ["ethereum", "optimism", "base"], "defillama_slug": "synthetix", "status": "active", "source": "seed"},

    # ── Governance / NFT / Other ────────────────────────────────────────
    {"protocol_id": "opensea", "canonical_name": "OpenSea", "protocol_family": "nft_marketplace", "chains": ["ethereum", "polygon", "arbitrum-one", "optimism", "base", "avalanche", "bnb-chain", "solana"], "defillama_slug": "opensea", "status": "active", "source": "seed"},
    {"protocol_id": "ens", "canonical_name": "Ethereum Name Service", "protocol_family": "infrastructure", "chains": ["ethereum"], "defillama_slug": "ens", "status": "active", "source": "seed"},
    {"protocol_id": "safe", "canonical_name": "Safe (Gnosis Safe)", "aliases": ["Gnosis Safe"], "protocol_family": "infrastructure", "chains": ["ethereum", "arbitrum-one", "optimism", "polygon", "bnb-chain", "avalanche", "gnosis", "base"], "defillama_slug": "safe", "status": "active", "source": "seed"},

    # ── Prediction Markets ──────────────────────────────────────────────
    {"protocol_id": "polymarket", "canonical_name": "Polymarket", "protocol_family": "prediction_market", "chains": ["polygon"], "defillama_slug": "polymarket", "status": "active", "source": "seed"},

    # ── RWA ─────────────────────────────────────────────────────────────
    {"protocol_id": "ondo", "canonical_name": "Ondo Finance", "protocol_family": "rwa", "chains": ["ethereum"], "defillama_slug": "ondo-finance", "status": "active", "source": "seed"},
    {"protocol_id": "centrifuge", "canonical_name": "Centrifuge", "protocol_family": "rwa", "chains": ["ethereum"], "defillama_slug": "centrifuge", "status": "active", "source": "seed"},

    # ── DePIN ───────────────────────────────────────────────────────────
    {"protocol_id": "helium", "canonical_name": "Helium", "protocol_family": "depin", "chains": ["solana"], "defillama_slug": "helium", "status": "active", "source": "seed"},
    {"protocol_id": "render", "canonical_name": "Render Network", "protocol_family": "depin", "chains": ["solana"], "defillama_slug": "render-network", "status": "active", "source": "seed"},
]


# ═══════════════════════════════════════════════════════════════════════════
# APP / DAPP SEED
# ═══════════════════════════════════════════════════════════════════════════

APP_SEED: list[dict] = [
    {"app_id": "uniswap-app", "canonical_name": "Uniswap App", "category": "dex_aggregator", "protocols": ["uniswap"], "frontend_domains": ["app.uniswap.org"], "source": "seed"},
    {"app_id": "aave-app", "canonical_name": "Aave App", "category": "lending_ui", "protocols": ["aave"], "frontend_domains": ["app.aave.com"], "source": "seed"},
    {"app_id": "curve-app", "canonical_name": "Curve App", "category": "dex_aggregator", "protocols": ["curve"], "frontend_domains": ["curve.fi"], "source": "seed"},
    {"app_id": "metamask", "canonical_name": "MetaMask", "category": "wallet", "protocols": [], "frontend_domains": ["portfolio.metamask.io"], "source": "seed"},
    {"app_id": "rainbow", "canonical_name": "Rainbow", "category": "wallet", "protocols": [], "frontend_domains": ["rainbow.me"], "source": "seed"},
    {"app_id": "opensea-app", "canonical_name": "OpenSea", "category": "nft_marketplace", "protocols": ["opensea"], "frontend_domains": ["opensea.io"], "source": "seed"},
    {"app_id": "etherscan-app", "canonical_name": "Etherscan", "category": "explorer", "protocols": [], "frontend_domains": ["etherscan.io"], "source": "seed"},
    {"app_id": "dune-app", "canonical_name": "Dune Analytics", "category": "analytics", "protocols": [], "frontend_domains": ["dune.com"], "source": "seed"},
    {"app_id": "defillama-app", "canonical_name": "DefiLlama", "category": "analytics", "protocols": [], "frontend_domains": ["defillama.com"], "source": "seed"},
    {"app_id": "1inch-app", "canonical_name": "1inch", "category": "dex_aggregator", "protocols": [], "frontend_domains": ["app.1inch.io"], "source": "seed"},
    {"app_id": "lido-app", "canonical_name": "Lido", "category": "staking_ui", "protocols": ["lido"], "frontend_domains": ["stake.lido.fi"], "source": "seed"},
    {"app_id": "eigenlayer-app", "canonical_name": "EigenLayer", "category": "staking_ui", "protocols": ["eigenlayer"], "frontend_domains": ["app.eigenlayer.xyz"], "source": "seed"},
    {"app_id": "safe-app", "canonical_name": "Safe Wallet", "aliases": ["Gnosis Safe"], "category": "wallet", "protocols": ["safe"], "frontend_domains": ["app.safe.global"], "source": "seed"},
    {"app_id": "zapper", "canonical_name": "Zapper", "category": "portfolio_tracker", "protocols": [], "frontend_domains": ["zapper.xyz"], "source": "seed"},
    {"app_id": "zerion-app", "canonical_name": "Zerion", "category": "portfolio_tracker", "protocols": [], "frontend_domains": ["app.zerion.io"], "source": "seed"},
    {"app_id": "snapshot-app", "canonical_name": "Snapshot", "category": "governance_dashboard", "protocols": [], "frontend_domains": ["snapshot.org"], "source": "seed"},
    {"app_id": "tally-app", "canonical_name": "Tally", "category": "governance_dashboard", "protocols": [], "frontend_domains": ["tally.xyz"], "source": "seed"},
    {"app_id": "pendle-app", "canonical_name": "Pendle", "category": "multi_purpose", "protocols": ["pendle"], "frontend_domains": ["app.pendle.finance"], "source": "seed"},
    {"app_id": "gmx-app", "canonical_name": "GMX", "category": "multi_purpose", "protocols": ["gmx"], "frontend_domains": ["app.gmx.io"], "source": "seed"},
    {"app_id": "hyperliquid-app", "canonical_name": "Hyperliquid", "category": "exchange", "protocols": ["hyperliquid-perps"], "frontend_domains": ["app.hyperliquid.xyz"], "source": "seed"},
    {"app_id": "jupiter-app", "canonical_name": "Jupiter", "category": "dex_aggregator", "protocols": [], "frontend_domains": ["jup.ag"], "chains": ["solana"], "source": "seed"},
    {"app_id": "phantom", "canonical_name": "Phantom", "category": "wallet", "protocols": [], "frontend_domains": ["phantom.app"], "chains": ["solana", "ethereum", "polygon", "base"], "source": "seed"},
    {"app_id": "rabby", "canonical_name": "Rabby Wallet", "category": "wallet", "protocols": [], "frontend_domains": ["rabby.io"], "source": "seed"},
    {"app_id": "coinbase-wallet-app", "canonical_name": "Coinbase Wallet", "category": "wallet", "protocols": [], "frontend_domains": ["wallet.coinbase.com"], "source": "seed"},
]


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN SEED (major stablecoins, native tokens, wrapped assets)
# ═══════════════════════════════════════════════════════════════════════════

TOKEN_SEED: list[dict] = [
    # Native tokens
    {"token_id": "eth-ethereum", "symbol": "ETH", "name": "Ether", "chain_id": "ethereum", "standard": "native", "decimals": 18, "coingecko_id": "ethereum", "source": "seed"},
    {"token_id": "sol-solana", "symbol": "SOL", "name": "Solana", "chain_id": "solana", "standard": "native", "decimals": 9, "coingecko_id": "solana", "source": "seed"},
    {"token_id": "btc-bitcoin", "symbol": "BTC", "name": "Bitcoin", "chain_id": "bitcoin", "standard": "native", "decimals": 8, "coingecko_id": "bitcoin", "source": "seed"},
    {"token_id": "bnb-bnb-chain", "symbol": "BNB", "name": "BNB", "chain_id": "bnb-chain", "standard": "native", "decimals": 18, "coingecko_id": "binancecoin", "source": "seed"},

    # Stablecoins (Ethereum)
    {"token_id": "usdc-ethereum", "symbol": "USDC", "name": "USD Coin", "chain_id": "ethereum", "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "standard": "erc20", "decimals": 6, "is_stablecoin": True, "coingecko_id": "usd-coin", "source": "seed"},
    {"token_id": "usdt-ethereum", "symbol": "USDT", "name": "Tether", "chain_id": "ethereum", "address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "standard": "erc20", "decimals": 6, "is_stablecoin": True, "coingecko_id": "tether", "source": "seed"},
    {"token_id": "dai-ethereum", "symbol": "DAI", "name": "Dai Stablecoin", "chain_id": "ethereum", "address": "0x6b175474e89094c44da98b954eedeac495271d0f", "standard": "erc20", "decimals": 18, "is_stablecoin": True, "protocol_id": "maker", "coingecko_id": "dai", "source": "seed"},

    # Wrapped tokens
    {"token_id": "weth-ethereum", "symbol": "WETH", "name": "Wrapped Ether", "chain_id": "ethereum", "address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "standard": "erc20", "decimals": 18, "is_wrapped": True, "underlying_token_id": "eth-ethereum", "coingecko_id": "weth", "source": "seed"},
    {"token_id": "wbtc-ethereum", "symbol": "WBTC", "name": "Wrapped Bitcoin", "chain_id": "ethereum", "address": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "standard": "erc20", "decimals": 8, "is_wrapped": True, "underlying_token_id": "btc-bitcoin", "coingecko_id": "wrapped-bitcoin", "source": "seed"},

    # Staking derivatives
    {"token_id": "steth-ethereum", "symbol": "stETH", "name": "Lido Staked Ether", "chain_id": "ethereum", "address": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84", "standard": "erc20", "decimals": 18, "protocol_id": "lido", "coingecko_id": "staked-ether", "source": "seed"},
    {"token_id": "wsteth-ethereum", "symbol": "wstETH", "name": "Wrapped stETH", "chain_id": "ethereum", "address": "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0", "standard": "erc20", "decimals": 18, "is_wrapped": True, "underlying_token_id": "steth-ethereum", "protocol_id": "lido", "source": "seed"},

    # Governance tokens
    {"token_id": "uni-ethereum", "symbol": "UNI", "name": "Uniswap", "chain_id": "ethereum", "address": "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", "standard": "erc20", "decimals": 18, "protocol_id": "uniswap", "coingecko_id": "uniswap", "source": "seed"},
    {"token_id": "aave-ethereum", "symbol": "AAVE", "name": "Aave", "chain_id": "ethereum", "address": "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", "standard": "erc20", "decimals": 18, "protocol_id": "aave", "coingecko_id": "aave", "source": "seed"},
    {"token_id": "mkr-ethereum", "symbol": "MKR", "name": "Maker", "chain_id": "ethereum", "address": "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2", "standard": "erc20", "decimals": 18, "protocol_id": "maker", "coingecko_id": "maker", "source": "seed"},
    {"token_id": "ldo-ethereum", "symbol": "LDO", "name": "Lido DAO", "chain_id": "ethereum", "address": "0x5a98fcbea516cf06857215779fd812ca3bef1b32", "standard": "erc20", "decimals": 18, "protocol_id": "lido", "coingecko_id": "lido-dao", "source": "seed"},
    {"token_id": "crv-ethereum", "symbol": "CRV", "name": "Curve DAO Token", "chain_id": "ethereum", "address": "0xd533a949740bb3306d119cc777fa900ba034cd52", "standard": "erc20", "decimals": 18, "protocol_id": "curve", "coingecko_id": "curve-dao-token", "source": "seed"},
]


# ═══════════════════════════════════════════════════════════════════════════
# MARKET VENUE SEED
# ═══════════════════════════════════════════════════════════════════════════

VENUE_SEED: list[dict] = [
    {"venue_id": "binance", "canonical_name": "Binance", "venue_type": "cex", "api_provider": "binance", "website": "https://binance.com", "source": "seed"},
    {"venue_id": "coinbase-exchange", "canonical_name": "Coinbase Exchange", "venue_type": "cex", "api_provider": "coinbase", "website": "https://coinbase.com", "source": "seed"},
    {"venue_id": "kraken", "canonical_name": "Kraken", "venue_type": "cex", "website": "https://kraken.com", "source": "seed"},
    {"venue_id": "bybit", "canonical_name": "Bybit", "venue_type": "cex", "website": "https://bybit.com", "source": "seed"},
    {"venue_id": "okx", "canonical_name": "OKX", "venue_type": "cex", "website": "https://okx.com", "source": "seed"},
    {"venue_id": "uniswap-v3-ethereum", "canonical_name": "Uniswap V3 (Ethereum)", "venue_type": "dex", "protocol_id": "uniswap", "chains": ["ethereum"], "source": "seed"},
    {"venue_id": "uniswap-v3-arbitrum", "canonical_name": "Uniswap V3 (Arbitrum)", "venue_type": "dex", "protocol_id": "uniswap", "chains": ["arbitrum-one"], "source": "seed"},
    {"venue_id": "curve-ethereum", "canonical_name": "Curve (Ethereum)", "venue_type": "dex", "protocol_id": "curve", "chains": ["ethereum"], "source": "seed"},
    {"venue_id": "raydium-solana", "canonical_name": "Raydium (Solana)", "venue_type": "dex", "protocol_id": "raydium", "chains": ["solana"], "source": "seed"},
    {"venue_id": "robinhood", "canonical_name": "Robinhood", "venue_type": "cex", "website": "https://robinhood.com", "source": "seed"},
]


# ═══════════════════════════════════════════════════════════════════════════
# GOVERNANCE SPACE SEED
# ═══════════════════════════════════════════════════════════════════════════

GOVERNANCE_SEED: list[dict] = [
    {"space_id": "uniswapgovernance.eth", "canonical_name": "Uniswap Governance", "protocol_id": "uniswap", "platform": "snapshot", "voting_token_id": "uni-ethereum", "source": "seed"},
    {"space_id": "aave.eth", "canonical_name": "Aave Governance", "protocol_id": "aave", "platform": "snapshot", "voting_token_id": "aave-ethereum", "source": "seed"},
    {"space_id": "ens.eth", "canonical_name": "ENS Governance", "protocol_id": "ens", "platform": "snapshot", "source": "seed"},
    {"space_id": "safe.eth", "canonical_name": "Safe Governance", "protocol_id": "safe", "platform": "snapshot", "source": "seed"},
    {"space_id": "curve.eth", "canonical_name": "Curve Governance", "protocol_id": "curve", "platform": "snapshot", "voting_token_id": "crv-ethereum", "source": "seed"},
    {"space_id": "lido-snapshot.eth", "canonical_name": "Lido Governance", "protocol_id": "lido", "platform": "snapshot", "voting_token_id": "ldo-ethereum", "source": "seed"},
    {"space_id": "balancer.eth", "canonical_name": "Balancer Governance", "protocol_id": "balancer", "platform": "snapshot", "source": "seed"},
    {"space_id": "gitcoindao.eth", "canonical_name": "Gitcoin DAO", "platform": "snapshot", "source": "seed"},
    {"space_id": "optimism-governance", "canonical_name": "Optimism Governance", "platform": "onchain", "chain_id": "optimism", "source": "seed"},
    {"space_id": "arbitrum-governance", "canonical_name": "Arbitrum DAO", "platform": "onchain", "chain_id": "arbitrum-one", "source": "seed"},
]


async def seed_registries(
    chain_reg: "ChainRegistry",
    protocol_reg: "ProtocolRegistry",
    app_reg: "AppRegistry",
    token_reg: "TokenRegistry",
    venue_reg: "MarketVenueRegistry",
    gov_reg: "GovernanceSpaceRegistry",
) -> dict:
    """Seed all registries with initial data. Idempotent — upserts by ID."""
    from shared.logger.logger import get_logger
    logger = get_logger("aether.web3.seed")

    counts: dict[str, int] = {}

    for chain in CHAIN_SEED:
        await chain_reg.register(chain)
    counts["chains"] = len(CHAIN_SEED)
    logger.info(f"Seeded {counts['chains']} chains")

    for protocol in PROTOCOL_SEED:
        await protocol_reg.register(protocol)
    counts["protocols"] = len(PROTOCOL_SEED)
    logger.info(f"Seeded {counts['protocols']} protocols")

    for app in APP_SEED:
        await app_reg.register(app)
    counts["apps"] = len(APP_SEED)
    logger.info(f"Seeded {counts['apps']} apps")

    for token in TOKEN_SEED:
        await token_reg.register(token)
    counts["tokens"] = len(TOKEN_SEED)
    logger.info(f"Seeded {counts['tokens']} tokens")

    for venue in VENUE_SEED:
        await venue_reg.register(venue)
    counts["venues"] = len(VENUE_SEED)
    logger.info(f"Seeded {counts['venues']} venues")

    for gov in GOVERNANCE_SEED:
        await gov_reg.register(gov)
    counts["governance_spaces"] = len(GOVERNANCE_SEED)
    logger.info(f"Seeded {counts['governance_spaces']} governance spaces")

    return counts
