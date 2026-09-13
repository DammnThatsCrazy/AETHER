"""Profile 360 — Delegation engine.

Scoped, time-bound, revocable delegations between entities. Postgres is the
authoritative store; a DelegationProjector worker mirrors active rows to the
Neptune graph as DELEGATES edges for traversal.
"""
