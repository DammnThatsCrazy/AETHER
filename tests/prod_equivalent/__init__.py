"""Production-equivalent CI lane tests.

Tests under this package are meant to run against a REAL Postgres (+ Redis,
where relevant) service stack, not the AETHER_ENV=local in-memory fallback —
see ``.github/workflows/production-equivalent-ci.yml`` (Phase-2 Program 4,
M1: docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md).

Every test in this package must SKIP cleanly (``pytest.skip``, never fail)
when ``DATABASE_URL`` is not set, so this package never breaks the fast
AETHER_ENV=local lane or ``make ci-check``.
"""
