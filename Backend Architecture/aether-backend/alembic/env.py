"""Alembic environment — Aether backend.

Reads DATABASE_URL from the environment. asyncpg:// URLs are normalised to
postgresql:// so SQLAlchemy's psycopg2 driver can be used for synchronous
migration execution (Alembic's standard approach).

Usage:
    DATABASE_URL=postgresql://aether:pass@localhost/aether alembic upgrade head
    alembic -x db_url=postgresql://... upgrade head          # one-off override
    alembic upgrade head --sql                               # offline SQL dump
"""

from __future__ import annotations

import os
import re
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy metadata — we use raw SQL in each migration.
target_metadata = None


def _x_arguments() -> dict[str, str]:
    """Return the ``-x key=value`` overrides, across Alembic versions.

    Alembic removed ``Config.get_x_argument`` in 1.18; the parsed CLI namespace
    still carries the raw ``-x`` values. ``pyproject.toml`` allows
    ``alembic>=1.13``, so both shapes are live and the caller must not care —
    without this, ``alembic upgrade head`` raises ``AttributeError`` on a fresh
    install, which also breaks ``RUN_MIGRATIONS=1`` and the ``/v1/ready``
    migrations-head check.
    """
    getter = getattr(config, "get_x_argument", None)
    if getter is not None:
        return dict(getter(as_dictionary=True))
    raw = getattr(getattr(config, "cmd_opts", None), "x", None) or []
    parsed: dict[str, str] = {}
    for item in raw:
        key, _, value = str(item).partition("=")
        parsed[key] = value
    return parsed


def _get_url() -> str:
    """Resolve the database URL from env or -x db_url= CLI override."""
    url = _x_arguments().get("db_url") or os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required to run migrations. "
            "Example: DATABASE_URL=postgresql://aether:pass@localhost:5432/aether alembic upgrade head"
        )
    # Normalise asyncpg:// → postgresql:// for synchronous migration execution.
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)
    url = re.sub(r"^asyncpg://", "postgresql://", url)
    return url


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live DB connection (--sql mode)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and execute migrations."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Postgres-specific: use a lock so concurrent deploys don't race.
            # Alembic acquires pg_advisory_xact_lock during migration.
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
