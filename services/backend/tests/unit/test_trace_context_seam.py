"""W3C trace-context seam: no-op unless AETHER_OTEL_ENABLED, real ids when on.

The seam exists so job/event hops share a trace id once real OTel lands
behind it. Two contracts matter: (1) disabled means *no* payload pollution
and None everywhere — production default; (2) enabled means valid W3C
traceparent values whose trace id survives the enqueue -> worker hop.
"""
from __future__ import annotations

import re

import pytest

from repositories.repos import reset_in_memory_stores
from shared.observability import child_traceparent, new_traceparent, parse_traceparent

pytestmark = pytest.mark.asyncio

_W3C = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


class TestSeamDisabled:
    def test_all_helpers_noop(self, monkeypatch):
        monkeypatch.delenv("AETHER_OTEL_ENABLED", raising=False)
        assert new_traceparent() is None
        assert child_traceparent(None) is None
        assert child_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-01") is None

    async def test_enqueue_does_not_stamp_payload(self, monkeypatch):
        monkeypatch.delenv("AETHER_OTEL_ENABLED", raising=False)
        from services.jobs.service import JobsService

        job = await JobsService().enqueue("t1", "measurement.source_classification_repair", {"k": 1})
        assert "_traceparent" not in (job.get("payload") or {})


class TestSeamEnabled:
    def test_new_traceparent_is_w3c(self, monkeypatch):
        monkeypatch.setenv("AETHER_OTEL_ENABLED", "1")
        value = new_traceparent()
        assert value is not None and _W3C.match(value)

    def test_child_keeps_trace_id_new_span(self, monkeypatch):
        monkeypatch.setenv("AETHER_OTEL_ENABLED", "1")
        parent = new_traceparent()
        child = child_traceparent(parent)
        p_trace, p_span = parse_traceparent(parent)
        c_trace, c_span = parse_traceparent(child)
        assert c_trace == p_trace
        assert c_span != p_span

    def test_child_of_invalid_parent_starts_fresh(self, monkeypatch):
        monkeypatch.setenv("AETHER_OTEL_ENABLED", "1")
        child = child_traceparent("garbage")
        assert child is not None and _W3C.match(child)

    def test_parse_rejects_malformed(self, monkeypatch):
        assert parse_traceparent(None) is None
        assert parse_traceparent("") is None
        assert parse_traceparent("00-short-short-01") is None

    async def test_enqueue_stamps_payload(self, monkeypatch):
        monkeypatch.setenv("AETHER_OTEL_ENABLED", "1")
        from services.jobs.service import JobsService

        job = await JobsService().enqueue("t1", "measurement.source_classification_repair", {"k": 1})
        stamped = (job.get("payload") or {}).get("_traceparent")
        assert stamped is not None and _W3C.match(stamped)

    async def test_caller_supplied_traceparent_wins(self, monkeypatch):
        monkeypatch.setenv("AETHER_OTEL_ENABLED", "1")
        from services.jobs.service import JobsService

        supplied = "00-" + "c" * 32 + "-" + "d" * 16 + "-01"
        job = await JobsService().enqueue(
            "t1", "measurement.source_classification_repair", {"_traceparent": supplied}
        )
        assert (job.get("payload") or {}).get("_traceparent") == supplied
