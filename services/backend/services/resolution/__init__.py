"""Retired legacy identity-resolution routes.

The engine, consumer, rules and signals were never registered in production and
their graph entry points already failed closed; they are deleted. Identity
resolution lives in ``services.identity``. Only fail-closed route tombstones
remain, until the Aether profile page stops requesting the cluster read.
"""
