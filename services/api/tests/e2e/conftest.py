"""Fixtures for the e2e flow suites."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ._event_loop import close_module_loop, open_module_loop


@pytest.fixture(scope="module", autouse=True)
def _e2e_module_event_loop() -> Iterator[None]:
    """Give each e2e module its own event loop for ``_event_loop.run`` (the
    ordered flow methods share one loop, as their repositories expect), and
    close it after the module so no loop state outlives it."""
    open_module_loop()
    try:
        yield
    finally:
        close_module_loop()
