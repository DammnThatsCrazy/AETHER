"""A per-module event loop for the ordered, synchronous e2e flow classes.

The flow classes drive async repositories from plain ``def`` test methods.
They used ``asyncio.get_event_loop().run_until_complete(...)``, which reads the
process-global "current event loop". Any earlier async test (pytest-asyncio's
loop teardown, or ``asyncio.run``) leaves that global set to ``None``, after
which ``get_event_loop()`` raises "There is no current event loop" — so the
flows passed alone and failed whenever another suite ran first in the same
process. :func:`run` instead uses a loop the e2e ``conftest`` creates for each
module and closes afterwards, and never reads or writes the global.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Optional, TypeVar

T = TypeVar("T")

_loop: Optional[asyncio.AbstractEventLoop] = None


def open_module_loop() -> asyncio.AbstractEventLoop:
    global _loop
    close_module_loop()
    _loop = asyncio.new_event_loop()
    return _loop


def close_module_loop() -> None:
    global _loop
    loop, _loop = _loop, None
    if loop is None or loop.is_closed():
        return
    try:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on the current module's e2e loop."""
    if _loop is None or _loop.is_closed():
        coro.close()
        raise RuntimeError("the e2e module event loop fixture is not active")
    return _loop.run_until_complete(coro)
