"""A revocation cannot commit between a writer's grant check and its Bronze insert.

In-memory flavour (asyncio lock). The same scenarios run against real PostgreSQL
in tests/prod_equivalent/test_real_stack_rights_revocation_fence.py.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from connectors.integrations.data_rights.service import DataRightsService
from tests.provider_runtime import rights_fence_scenarios as scenarios


@pytest.fixture
def env():
    reset_in_memory_stores()
    yield scenarios.Env(service=DataRightsService(), tenant=scenarios.new_tenant())
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_revocation_waits_for_an_in_flight_write(env):
    await scenarios.revocation_waits_for_an_in_flight_write(env)


@pytest.mark.asyncio
async def test_a_write_after_a_committed_revocation_is_denied(env):
    await scenarios.a_write_after_a_committed_revocation_is_denied(env)


@pytest.mark.asyncio
async def test_no_record_is_retained_after_revocation_returns(env):
    await scenarios.no_record_is_retained_after_revocation_returns(env)
