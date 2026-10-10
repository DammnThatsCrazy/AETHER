"""Aether Service — Profile 360 (Entity Omniview)

Composes a holistic user/entity profile from existing subsystems:
- Identity service (profiles, merge history)
- Resolution service (identity clusters)
- Intelligence service (risk scores, features)
- Analytics (events, sessions)
- Graph (relationships, neighbors)
- Lake (Bronze/Silver/Gold across all domains)
- Consent (preferences, DSR history)
- Rewards (claim history)
- Fraud (risk signals)
- Agent (interactions, delegations)

Does NOT duplicate data or logic — aggregates from existing repositories and services.
"""
