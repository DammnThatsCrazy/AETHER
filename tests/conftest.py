from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line('markers', 'asyncio: run async test via the built-in asyncio runner')


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames  # type: ignore[attr-defined]
    }
    asyncio.run(testfunction(**kwargs))
    return True
