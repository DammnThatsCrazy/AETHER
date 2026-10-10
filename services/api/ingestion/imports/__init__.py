"""Aether Tenant Import Engine.

A tenant uploads a file, Aether analyzes its schema, the tenant maps source
columns onto Aether's canonical primitives, a dry-run validates, and a commit
stages the rows into Bronze → Silver → the graph with full lineage. Every step
is durable, tenant-scoped, and auditable — nothing is reported imported until
there is evidence it was.
"""
