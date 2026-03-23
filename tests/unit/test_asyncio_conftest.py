from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


CONFTST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"
SPEC = importlib.util.spec_from_file_location("aether_tests_conftest", CONFTST_PATH)
assert SPEC and SPEC.loader
CONFTST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFTST)


def test_asyncio_harness_detects_pytest_asyncio(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "pytest_asyncio" else None)
    assert CONFTST._pytest_asyncio_available() is True


def test_asyncio_harness_defers_to_pytest_asyncio_plugin(monkeypatch):
    monkeypatch.setattr(CONFTST, "_pytest_asyncio_available", lambda: True)
    pyfuncitem = object()
    assert CONFTST.pytest_pyfunc_call(pyfuncitem) is None


def test_asyncio_harness_runs_coroutines_without_plugin(monkeypatch):
    monkeypatch.setattr(CONFTST, "_pytest_asyncio_available", lambda: False)

    called = {}

    async def sample_test(value: int) -> None:
        called["value"] = value

    class DummyFixtureInfo:
        argnames = ("value",)

    class DummyPyfuncItem:
        def __init__(self) -> None:
            self.obj = sample_test
            self.funcargs = {"value": 7}
            self._fixtureinfo = DummyFixtureInfo()

    assert CONFTST.pytest_pyfunc_call(DummyPyfuncItem()) is True
    assert called == {"value": 7}
