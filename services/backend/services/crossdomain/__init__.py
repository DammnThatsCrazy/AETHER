"""
Aether Cross-Domain Business, TradFi, and Web Intelligence Graph

Unifies four major layers into one identity-resolved graph:
  1. Identity Layer — person, business, account, household, wallet, app identity
  2. Business/Application Layer — companies, institutions, apps, domains, service providers
  3. TradFi/Market/Account Layer — accounts, portfolios, instruments, trades, positions, balances
  4. Cross-Domain Fusion Layer — links Web2, TradFi, and Web3 with confidence scoring

Reuses existing patterns:
  - BaseRepository (asyncpg) for all registries
  - CompletenessStatus/Provenance from Web3 coverage
  - Graph vertex/edge types from shared/graph/graph.py
  - Identity resolution from services/resolution/
  - Profile 360 composition from services/profile/
"""
