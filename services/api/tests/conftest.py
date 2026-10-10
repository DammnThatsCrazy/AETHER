"""Pytest support for backend test suites.

The root project declares ``pytest-asyncio`` as a development dependency, but
some CI/local environments run the backend tests with only the lightweight test
runtime installed.  These suites use plain ``async def`` tests marked with
``@pytest.mark.asyncio``; without an async plugin pytest reports them as
unsupported before executing the actual assertions.

This fallback intentionally handles only the backend's asyncio-marked coroutine
tests.  If pytest-asyncio is installed, that plugin remains the owner and this
hook does nothing.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from collections.abc import Mapping
from typing import Any

import pytest

# Credentials are stored via the provider-neutral credential platform. Under the
# test suite default to the non-durable in-memory backend so no DB/encryption
# key is required. An explicit env var still wins.
os.environ.setdefault("AETHER_CREDENTIAL_BACKEND", "in_memory")


# Make backend packages importable even when a sub-suite is executed directly.
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, "..", ".."))
for path in (BACKEND_ROOT, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


def _has_pytest_asyncio(pytestconfig: pytest.Config) -> bool:
    """Return true when pytest-asyncio is installed and registered."""

    return pytestconfig.pluginmanager.hasplugin("asyncio")


def _call_args_for_test(pyfuncitem: pytest.Function) -> Mapping[str, Any]:
    """Select only fixture arguments accepted by the test function."""

    argnames = pyfuncitem._fixtureinfo.argnames  # noqa: SLF001 - pytest hook API
    return {name: pyfuncitem.funcargs[name] for name in argnames}


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run asyncio-marked coroutine tests when pytest-asyncio is unavailable."""

    if _has_pytest_asyncio(pyfuncitem.config):
        return None

    test_fn = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_fn):
        return None

    if pyfuncitem.get_closest_marker("asyncio") is None:
        return None

    asyncio.run(test_fn(**_call_args_for_test(pyfuncitem)))
    return True
