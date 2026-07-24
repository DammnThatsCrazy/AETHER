"""Traffic-intelligence performance guardrails (spec §17.7).

These tests measure real, in-process latency/throughput of the hot paths and
assert thresholds derived from locally-measured baselines multiplied by a
generous safety factor, so they catch order-of-magnitude regressions without
being flaky on slower/noisy CI hardware.

Baselines measured on the repo's local runtime (Python 3, single core):

    classifier per-call        p95 ≈ 26–30 µs   (throughput ≈ 55–58k/s)
    token-hash (redirect verify) p95 ≈ 1–1.6 µs
    batch classification       mean ≈ 16–18 µs/event

Chosen thresholds keep ~7–8× headroom over those baselines.  Every case is
bounded to a few thousand iterations so the whole module runs in well under a
second.  Measured numbers are printed for each test.
"""

from __future__ import annotations

import hashlib
import secrets
import statistics
import time
from typing import Any, Optional

import pytest

from services.traffic.classifier import SourceClassifier
from services.traffic.referral_links import _token_hash
from services.traffic.repair import SourceClassificationRepairService

pytestmark = pytest.mark.performance


# ── Thresholds (measured baseline × safety factor) ───────────────────────────

# classifier per-call p95 baseline ≈ 30 µs → ceiling 250 µs (~8×).
CLASSIFIER_P95_US_CEILING = 250.0
# classifier throughput baseline ≈ 56k/s → floor 8,000/s (~7× headroom).
CLASSIFIER_THROUGHPUT_FLOOR = 8_000.0
# batch per-event mean baseline ≈ 18 µs → ceiling 200 µs (~11×).
BATCH_MEAN_US_CEILING = 200.0
# token-hash p95 baseline ≈ 1.6 µs → ceiling 50 µs (~30×; hashing is cheap but
# CI schedulers add jitter, so we stay well clear of flakiness).
TOKEN_VERIFY_P95_US_CEILING = 50.0

# Documented resource bounds enforced by SourceClassificationRepairService.run.
REPAIR_PAGE_SIZE_CEILING = 1_000
REPAIR_TOTAL_LIMIT_CEILING = 100_000


_CLASSIFY_CASES: list[dict[str, Any]] = [
    dict(
        referrer="https://www.google.com/search?q=x",
        referrer_domain="www.google.com",
        utm_source="google",
        utm_medium="cpc",
        click_ids={"gclid": "abc123"},
        landing_page="https://app.example.com/lp",
    ),
    dict(
        referrer="https://t.co/xyz",
        referrer_domain="t.co",
        utm_source="twitter",
        utm_medium="social",
        landing_page="https://app.example.com/",
    ),
    dict(referrer="", referrer_domain="", landing_page="https://app.example.com/"),
    dict(
        referrer="https://news.ycombinator.com/",
        referrer_domain="news.ycombinator.com",
        landing_page="https://app.example.com/blog",
    ),
    dict(
        user_agent=(
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        ),
        referrer="https://www.google.com/",
        referrer_domain="www.google.com",
    ),
]


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(q * len(sorted_values)))
    return sorted_values[idx]


def test_classifier_throughput_and_p95_latency():
    classifier = SourceClassifier()
    for case in _CLASSIFY_CASES:  # warm up import/branch caches
        classifier.classify(**case)

    n = 5_000
    per_call_us: list[float] = []
    start = time.perf_counter()
    for i in range(n):
        case = _CLASSIFY_CASES[i % len(_CLASSIFY_CASES)]
        t0 = time.perf_counter()
        classifier.classify(**case)
        per_call_us.append((time.perf_counter() - t0) * 1e6)
    elapsed = time.perf_counter() - start

    per_call_us.sort()
    p95 = _percentile(per_call_us, 0.95)
    throughput = n / elapsed
    print(
        f"\n[classifier] n={n} throughput={throughput:,.0f}/s "
        f"p50={_percentile(per_call_us, 0.50):.2f}µs p95={p95:.2f}µs "
        f"p99={_percentile(per_call_us, 0.99):.2f}µs"
    )

    assert p95 < CLASSIFIER_P95_US_CEILING, (
        f"classifier p95 {p95:.2f}µs exceeded ceiling {CLASSIFIER_P95_US_CEILING}µs"
    )
    assert throughput > CLASSIFIER_THROUGHPUT_FLOOR, (
        f"classifier throughput {throughput:,.0f}/s below floor "
        f"{CLASSIFIER_THROUGHPUT_FLOOR:,.0f}/s"
    )


def test_batch_ingestion_classification_impact():
    """Per-event classification cost stays bounded across a realistic batch."""

    classifier = SourceClassifier()
    batch_size = 500
    batch = [_CLASSIFY_CASES[i % len(_CLASSIFY_CASES)] for i in range(batch_size)]
    for case in batch[:10]:
        classifier.classify(**case)

    start = time.perf_counter()
    for case in batch:
        classifier.classify(**case)
    elapsed = time.perf_counter() - start
    mean_us = (elapsed / batch_size) * 1e6
    print(
        f"\n[batch] size={batch_size} total={elapsed * 1000:.2f}ms "
        f"mean={mean_us:.2f}µs/event"
    )

    assert mean_us < BATCH_MEAN_US_CEILING, (
        f"batch mean {mean_us:.2f}µs/event exceeded ceiling {BATCH_MEAN_US_CEILING}µs"
    )


def test_redirect_token_verify_latency():
    """The redirect endpoint verifies tokens by SHA-256 hash lookup; measure it."""

    tokens = [secrets.token_urlsafe(32) for _ in range(5_000)]
    for token in tokens[:50]:
        _token_hash(token)

    per_call_us: list[float] = []
    for token in tokens:
        t0 = time.perf_counter()
        digest = _token_hash(token)
        per_call_us.append((time.perf_counter() - t0) * 1e6)
        # Sanity: the verify path produces a full SHA-256 hex digest.
        assert len(digest) == 64

    per_call_us.sort()
    p95 = _percentile(per_call_us, 0.95)
    print(
        f"\n[token-verify] n={len(tokens)} "
        f"p50={_percentile(per_call_us, 0.50):.3f}µs p95={p95:.3f}µs "
        f"p99={_percentile(per_call_us, 0.99):.3f}µs"
    )

    assert p95 < TOKEN_VERIFY_P95_US_CEILING, (
        f"token-verify p95 {p95:.3f}µs exceeded ceiling {TOKEN_VERIFY_P95_US_CEILING}µs"
    )
    # Determinism guard: identical token → identical hash (constant-time lookup).
    assert _token_hash(tokens[0]) == hashlib.sha256(
        tokens[0].encode("utf-8")
    ).hexdigest()


class _RecordingTouchpointRepo:
    """Fake touchpoint source returning a fixed dataset, one bounded page at a time.

    Records the ``limit`` requested for every page so the test can assert the
    repair job honors its page-size and total-limit bounds.
    """

    def __init__(self, total_rows: int) -> None:
        self._rows = [
            {
                "touchpoint_id": f"tp-{i:06d}",
                "occurred_at": f"2026-01-01T00:00:{i % 60:02d}+00:00",
                "referrer": "",
                "normalized_referrer_domain": "",
            }
            for i in range(total_rows)
        ]
        self._served = 0
        self.requested_limits: list[int] = []

    async def list_for_source_reclassification(
        self,
        tenant_id: str,
        *,
        start_at: Any = None,
        end_at: Any = None,
        limit: int = 0,
        cursor_occurred_at: Any = None,
        cursor_touchpoint_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.requested_limits.append(limit)
        page = self._rows[self._served : self._served + limit]
        self._served += len(page)
        return page

    async def apply_source_classification(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - dry_run never calls this
        raise AssertionError("dry_run must not mutate touchpoints")


async def _run_dry_repair(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], dataset_rows: int
) -> tuple[dict[str, Any], _RecordingTouchpointRepo]:
    async def no_pool() -> None:
        return None

    # Repair uses the module-level get_pool for run-state persistence; the
    # no-pool local path keeps this test hermetic (no database).
    monkeypatch.setattr("services.traffic.repair.get_pool", no_pool)

    service = SourceClassificationRepairService()
    fake = _RecordingTouchpointRepo(dataset_rows)
    service._touchpoints = fake  # type: ignore[assignment]

    result = await service.run(
        tenant_id="tenant-perf",
        job_id=f"job-{secrets.token_hex(6)}",
        payload={**payload, "dry_run": True},
    )
    return result, fake


@pytest.mark.asyncio
async def test_repair_job_honors_page_size_bound(monkeypatch: pytest.MonkeyPatch):
    """An oversized page_size request is clamped to the documented ceiling."""

    dataset = 2_500
    result, fake = await _run_dry_repair(
        monkeypatch,
        {"limit": 10_000_000, "page_size": 999_999},
        dataset_rows=dataset,
    )

    assert result["counters"]["scanned"] == dataset
    assert fake.requested_limits, "repair must page through the touchpoint source"
    max_page = max(fake.requested_limits)
    print(
        f"\n[repair page-size] scanned={result['counters']['scanned']} "
        f"pages={len(fake.requested_limits)} max_page_request={max_page}"
    )
    assert max_page <= REPAIR_PAGE_SIZE_CEILING, (
        f"repair requested page of {max_page} rows, exceeding ceiling "
        f"{REPAIR_PAGE_SIZE_CEILING}"
    )


@pytest.mark.asyncio
async def test_repair_job_honors_total_limit_bound(monkeypatch: pytest.MonkeyPatch):
    """A small explicit limit caps total work even with a huge dataset."""

    limit = 50
    result, fake = await _run_dry_repair(
        monkeypatch,
        {"limit": limit, "page_size": 1_000},
        dataset_rows=5_000,
    )

    scanned = result["counters"]["scanned"]
    print(
        f"\n[repair total-limit] limit={limit} scanned={scanned} "
        f"page_requests={fake.requested_limits}"
    )
    assert scanned <= limit, f"repair scanned {scanned} rows, exceeding limit {limit}"
    # Never requests more than the remaining budget on any page.
    assert all(req <= limit for req in fake.requested_limits)
    assert limit <= REPAIR_TOTAL_LIMIT_CEILING
