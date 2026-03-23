from __future__ import annotations

import asyncio
import importlib.util
import inspect
from typing import Any

import pytest


def _pytest_asyncio_available() -> bool:
    return importlib.util.find_spec("pytest_asyncio") is not None


def pytest_configure(config: pytest.Config) -> None:
    if _pytest_asyncio_available():
        return
    config.addinivalue_line('markers', 'asyncio: run async test via the built-in asyncio runner')


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if _pytest_asyncio_available():
        return None

    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames  # type: ignore[attr-defined]
    }
    asyncio.run(testfunction(**kwargs))
    return True
