"""The e2e flows must not depend on the process-global current event loop.

Earlier async tests in the same process (pytest-asyncio loop teardown,
``asyncio.run``) leave the global current loop unset; the flows' ``_run``
helpers then raised "There is no current event loop" and ~7 privacy-consent
steps failed only when ``tests/dsr`` / ``tests/measurement`` ran first.
"""

from __future__ import annotations

import asyncio
import importlib
import warnings

import pytest

FLOW_MODULES = (
    "test_privacy_consent_flow",
    "test_b2b_account_flow",
    "test_paid_media_ecommerce_flow",
    "test_agent_web3_attribution_flow",
)


async def _answer() -> int:
    await asyncio.sleep(0)
    return 42


@pytest.mark.parametrize("module_name", FLOW_MODULES)
def test_flow_run_helper_survives_an_unset_global_loop(module_name):
    module = importlib.import_module(f"{__package__}.{module_name}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # What an earlier async test leaves behind.
        asyncio.set_event_loop(None)
    assert module._run(_answer()) == 42


def test_flow_steps_share_one_loop_per_module():
    from ._event_loop import run

    async def _current():
        return asyncio.get_running_loop()

    assert run(_current()) is run(_current())
