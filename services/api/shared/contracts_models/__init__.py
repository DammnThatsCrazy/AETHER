"""Shared, service-neutral contract models.

Home for wire-contract models that multiple planes compose (the boolean
filter language, exploration contracts). Services re-export from here for
backward compatibility; the canonical definitions live in this package so
``shared/`` never imports from ``services/``.
"""
