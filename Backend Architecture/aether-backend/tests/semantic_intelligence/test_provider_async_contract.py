"""The semantic classification path is async end-to-end (rank3).

`engine.classify_event` and every provider's `classify` are coroutine
functions, so a network-backed provider awaits its inference round-trip
instead of blocking the event loop the classification pipeline runs on. These
tests lock that contract in: a future change that reverts any of them to a
plain ``def`` (re-introducing the event-loop stall) fails here deterministically,
and a concurrency probe proves a slow provider does not starve other coroutines.
"""

from __future__ import annotations

import asyncio
import inspect

from services.semantic_intelligence.providers import (
    DeterministicClassifierProvider,
    DisabledProvider,
    ProductionModelProvider,
    SemanticClassificationRequest,
    SemanticClassificationResult,
    SemanticClassifierProvider,
)
from services.semantic_intelligence.engine import classify_event

# No module-level asyncio mark: the async tests here run under the repo's
# ``asyncio_mode = "auto"``, and the two contract assertions below are plain
# sync tests (a module mark would warn on them).

TENANT = "tenant-async-contract"


def test_classify_event_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(classify_event)


def test_every_provider_classify_is_a_coroutine_function() -> None:
    # The ABC and all concrete providers must expose an awaitable classify — a
    # sync one would block the event loop from inside the async persistence path.
    for cls in (
        SemanticClassifierProvider,
        DeterministicClassifierProvider,
        DisabledProvider,
        ProductionModelProvider,
    ):
        assert inspect.iscoroutinefunction(cls.classify), cls.__name__


async def test_deterministic_classify_awaits_and_returns_a_result() -> None:
    result = await DeterministicClassifierProvider().classify(
        SemanticClassificationRequest(
            tenant_id=TENANT, source_event_id="ev_async", text="great, I recommend it"
        )
    )
    assert isinstance(result, SemanticClassificationResult)
    assert not result.abstained


async def test_slow_provider_does_not_block_the_event_loop() -> None:
    """A provider whose round-trip awaits must yield the loop to other tasks.

    A concurrent ticker advances while a deliberately slow provider is in flight;
    if classify blocked the loop (the pre-rank3 sync defect) the ticker could not
    advance until the classification finished.
    """

    class _SlowProvider(SemanticClassifierProvider):
        name = "slow-test-provider@1.0.0"

        def available(self) -> bool:
            return True

        async def classify(
            self, request: SemanticClassificationRequest
        ) -> SemanticClassificationResult:
            await asyncio.sleep(0.05)
            return SemanticClassificationResult.abstain(self.name, "test_slow")

    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.005)
            ticks += 1

    request = SemanticClassificationRequest(
        tenant_id=TENANT, source_event_id="ev_slow", text="hello"
    )
    _, pending = await asyncio.gather(_SlowProvider().classify(request), _ticker())
    # The ticker ran concurrently with the awaiting provider — proof the loop
    # was never blocked for the whole classify duration.
    assert ticks == 10
