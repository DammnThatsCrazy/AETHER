"""Alembic must name its synchronous PostgreSQL driver explicitly.

SQLAlchemy 2.1 made psycopg (v3) the default DBAPI for a bare ``postgresql://``
URL. Only ``psycopg2-binary`` is declared, so ``alembic upgrade head`` (CI and
the image's ``RUN_MIGRATIONS=1`` entrypoint) failed with
``ModuleNotFoundError: No module named 'psycopg'`` as soon as 2.1 resolved.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def _get_url(monkeypatch, database_url: str) -> str:
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_get_url")
    namespace = {"os": os, "re": re, "_x_arguments": lambda: {}}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(ENV_PY), "exec"), namespace)
    monkeypatch.setenv("DATABASE_URL", database_url)
    return namespace["_get_url"]()


@pytest.mark.parametrize("database_url", [
    "postgresql://aether:pw@db:5432/aether",
    "postgres://aether:pw@db:5432/aether",
    "postgresql+asyncpg://aether:pw@db:5432/aether",
    "asyncpg://aether:pw@db:5432/aether",
])
def test_migration_url_pins_the_declared_psycopg2_driver(monkeypatch, database_url):
    url = _get_url(monkeypatch, database_url)

    assert url == "postgresql+psycopg2://aether:pw@db:5432/aether"


def test_explicit_driver_is_left_alone(monkeypatch):
    url = "postgresql+psycopg2://aether:pw@db:5432/aether"

    assert _get_url(monkeypatch, url) == url
