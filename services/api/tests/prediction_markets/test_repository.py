"""Observation occurrences: returning quotes are kept, retries are not (Codex on #867)."""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from value.prediction_markets import repository
from value.prediction_markets.models import MarketObservation, MarketStatus, MarketVenue, OutcomeQuote
from value.prediction_markets.repository import PredictionMarketObservationRepository


def _obs(price: str) -> MarketObservation:
    return MarketObservation(
        venue=MarketVenue.KALSHI, market_ref="KX-1", title="KX-1", status=MarketStatus.OPEN,
        outcomes=(OutcomeQuote(label="yes", price=Decimal(price)),),
    )


class _FakeConn:
    """The statements ``record`` / ``latest`` issue, over an in-memory table
    with the migration's primary key (tenant, venue, market, observation_sha256).
    ``pg_advisory_xact_lock`` is modelled by a per-key asyncio lock held until
    the transaction ends."""

    def __init__(self, rows: dict, locks: dict, pause=None) -> None:
        self.rows = rows
        self.locks = locks
        self.pause = pause
        self.held: list = []

    @contextlib.asynccontextmanager
    async def transaction(self):
        try:
            yield
        finally:
            for lock in self.held:
                lock.release()
            self.held.clear()

    async def execute(self, query, *args):
        assert "pg_advisory_xact_lock" in query
        lock = self.locks.setdefault(args[0], __import__("asyncio").Lock())
        await lock.acquire()
        self.held.append(lock)

    def _market(self, tenant, venue, market):
        return [r for r in self.rows.values() if r["tenant_id"] == tenant
                and r["venue"] == venue and r["market_ref"] == market]

    async def fetchrow(self, query, *args):
        if query.lstrip().startswith("INSERT"):
            tenant, venue, market, key, status, received_at, data = args
            pk = (tenant, venue, market, key)
            if pk in self.rows:
                return None
            self.rows[pk] = {"tenant_id": tenant, "venue": venue, "market_ref": market,
                             "observation_sha256": key, "received_at": received_at,
                             "data": json.loads(data)}
            return {"observation_sha256": key}
        rows = self._market(*args[:3])
        if len(args) > 3:
            rows = [r for r in rows if r["received_at"] <= args[3]]
        found = max(rows, key=lambda r: (r["received_at"], r["observation_sha256"]), default=None)
        if self.pause is not None:
            await self.pause()
        return found


class _FakePool:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.locks: dict = {}
        self.pauses: list = []

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield _FakeConn(self.rows, self.locks, self.pauses.pop(0) if self.pauses else None)


@pytest.fixture(params=["local", "sql"])
def repo(request, monkeypatch):
    repository._LOCAL_STORE.clear()
    r = PredictionMarketObservationRepository()
    if request.param == "sql":
        pool = _FakePool()

        async def _pool(self):
            return pool

        monkeypatch.setattr(PredictionMarketObservationRepository, "_pool", _pool)
    yield r
    repository._LOCAL_STORE.clear()


async def _price(repo, **kw):
    found = await repo.latest("t1", MarketVenue.KALSHI, "KX-1", **kw)
    return None if found is None else str(found[0].outcomes[0].price)


@pytest.mark.asyncio
async def test_quote_returning_to_an_earlier_value_is_a_new_occurrence(repo):
    created, marks = [], []
    for price in ("0.40", "0.60", "0.40"):
        created.append((await repo.record("t1", _obs(price)))[1])
        marks.append((await repo.latest("t1", MarketVenue.KALSHI, "KX-1"))[1])
    assert created == [True, True, True]
    assert await _price(repo) == "0.40"
    assert await _price(repo, as_of=marks[1]) == "0.60"
    assert await _price(repo, as_of=marks[0]) == "0.40"


@pytest.mark.asyncio
async def test_retry_of_the_latest_observation_is_idempotent(repo):
    assert (await repo.record("t1", _obs("0.40")))[1] is True
    assert (await repo.record("t1", _obs("0.40")))[1] is False
    assert (await repo.record("t1", _obs("0.60")))[1] is True
    assert (await repo.record("t1", _obs("0.60")))[1] is False
    assert await _price(repo) == "0.60"


@pytest.mark.asyncio
async def test_receipt_time_stays_ordered_when_the_clock_steps_back(repo, monkeypatch):
    fixed = datetime(2030, 1, 1, tzinfo=timezone.utc)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(repository, "datetime", _Clock)
    for price in ("0.40", "0.60", "0.40"):
        await repo.record("t1", _obs(price))
    assert await _price(repo) == "0.40"


@pytest.mark.asyncio
async def test_concurrent_writers_are_serialized_per_market(monkeypatch):
    """Codex review on #872: without a per-market lock a writer that read the
    predecessor, then paused while others committed, derived its occurrence key
    from a stale row and stored the same quote twice in a row
    (0.40, 0.80, 0.60, 0.60, both 0.60 submissions reporting created)."""
    import asyncio

    repository._LOCAL_STORE.clear()
    pool = _FakePool()

    async def _pool(self):
        return pool

    monkeypatch.setattr(PredictionMarketObservationRepository, "_pool", _pool)
    repo = PredictionMarketObservationRepository()
    await repo.record("t1", _obs("0.40"))

    resume = asyncio.Event()

    async def paused():
        await resume.wait()

    pool.pauses = [paused]  # the next writer pauses right after its predecessor read
    slow = asyncio.create_task(repo.record("t1", _obs("0.60")))
    await asyncio.sleep(0)
    others = asyncio.gather(repo.record("t1", _obs("0.80")), repo.record("t1", _obs("0.60")))
    for _ in range(5):
        await asyncio.sleep(0)
    resume.set()
    await slow
    await others
    sequence = [str(json.loads(json.dumps(r["data"]))["outcomes"][0]["price"])
                for r in sorted(pool.rows.values(), key=lambda r: (r["received_at"], r["observation_sha256"]))]
    assert all(a != b for a, b in zip(sequence, sequence[1:])), sequence
