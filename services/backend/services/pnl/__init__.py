"""Profile 360 — PNL Calculator service.

Computes realized + unrealized PNL and TVL delta per entity per time window.
Realized PNL uses FIFO cost basis from silver_web3_events tx history
combined with CoinGecko historical price data.
"""
