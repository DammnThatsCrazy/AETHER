"""Deterministic canary routing and promotion tracking for the model-runtime.

Canary routing sends a small, controlled fraction of traffic to a candidate
model/provider and compares outcomes — latency, error rate, and verification
pass rate — before promoting the candidate to full traffic (ADR-008 D8).

Selection is fully deterministic: it is driven by a salted SHA-256 hash of the
tenant and trace ids, so no ``random`` module (and no equivalent of
Math.random) appears anywhere in the production path. Tenant and trace ids are
hashed and never stored, so the tracker holds no secrets and no
request-identifying data.

This module is self-contained (stdlib + pydantic only) so it imports cleanly
while the rest of the ``observability`` package lands concurrently.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple

from pydantic import BaseModel, field_validator

__all__ = ["CanaryMetrics", "CanaryPolicy", "CanarySelector", "CanaryTracker"]


class CanaryPolicy(BaseModel, frozen=True):
    """Thresholds and traffic controls for a single canary candidate.

    ``traffic_fraction`` is validated to fall in ``(0, 1]`` — exclusive of
    zero — so a misconfigured policy can never silently disable a canary or
    accidentally become an all-traffic canary.

    ``min_samples`` is the minimum evidence floor an operator should collect
    before even *evaluating* a candidate; promotion itself is governed by
    ``promote_after_samples`` plus the ``max_error_rate`` / ``max_latency_ms``
    thresholds (see ``CanaryTracker.metrics``).
    """

    candidate_model: str
    candidate_provider: str
    traffic_fraction: float = 0.05
    min_samples: int = 20
    max_latency_ms: float | None = None
    max_error_rate: float = 0.05
    promote_after_samples: int = 100

    @field_validator("traffic_fraction")
    @classmethod
    def _validate_traffic_fraction(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError("traffic_fraction must be in (0, 1]")
        return value

    @field_validator("min_samples", "promote_after_samples")
    @classmethod
    def _validate_sample_counts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("sample counts must be non-negative")
        return value

    @field_validator("max_error_rate")
    @classmethod
    def _validate_error_rate(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("max_error_rate must be in [0, 1]")
        return value


class CanaryMetrics(BaseModel, frozen=True):
    """Snapshot of a single candidate's canary outcome accumulation."""

    candidate: str
    samples: int
    ok_count: int
    error_rate: float
    avg_latency_ms: float
    verify_pass_rate: float
    promote: bool


class CanarySelector:
    """Deterministic traffic-fraction selector for canary candidates.

    Given the same policy, seed, tenant, and trace ids, ``select`` returns the
    same answer every time (and across processes), so canary eligibility can be
    reproduced for audits and rollouts without any shared randomness.
    """

    def __init__(self, policy: CanaryPolicy, *, seed: str = "aether-canary") -> None:
        self._policy = policy
        self._seed = seed

    def select(self, tenant_id: str, trace_id: str) -> bool:
        """Return True when this request is part of the canary traffic.

        The first 16 hex chars of ``sha256(seed:tenant:trace)`` are treated as
        a 64-bit integer bucket; the request is canaried when that bucket falls
        strictly below ``traffic_fraction``. A non-positive fraction is always
        False (defensive: ``CanaryPolicy`` already rejects such values).
        """
        fraction = self._policy.traffic_fraction
        if fraction <= 0.0:
            return False
        digest = hashlib.sha256(
            f"{self._seed}:{tenant_id}:{trace_id}".encode("utf-8")
        ).hexdigest()
        bucket = int(digest[:16], 16) / 2**64
        return bucket < fraction


class _Sample(NamedTuple):
    """A single recorded canary outcome."""

    latency_ms: float
    ok: bool
    verified: bool


class CanaryTracker:
    """In-memory, per-candidate accumulation of canary outcomes.

    A single tracker may follow several candidate labels; ``record`` appends
    each outcome to the bucket for the given candidate string. ``metrics()``
    reports the bucket for the policy's candidate by default — the canonical
    label ``f"{candidate_model}@{candidate_provider}"`` — and an explicit
    ``candidate`` argument can inspect any other tracked bucket.

    The tracker stores only outcome counts and summed latencies — never
    tenant/trace ids — so it holds no secrets and no request-identifying data.
    """

    def __init__(self, policy: CanaryPolicy) -> None:
        self._policy = policy
        self._buckets: dict[str, list[_Sample]] = {}

    @property
    def candidate(self) -> str:
        """Canonical candidate label derived from the policy."""

        return f"{self._policy.candidate_model}@{self._policy.candidate_provider}"

    def record(
        self, candidate: str, *, latency_ms: float, ok: bool, verified: bool
    ) -> None:
        """Record one outcome for a candidate."""

        self._buckets.setdefault(candidate, []).append(
            _Sample(latency_ms=latency_ms, ok=ok, verified=verified)
        )

    def metrics(self, candidate: str | None = None) -> CanaryMetrics:
        """Compute a metrics snapshot for a candidate's accumulation.

        Promotion requires all of: at least ``promote_after_samples`` samples,
        ``error_rate <= max_error_rate``, latency at or below ``max_latency_ms``
        when a limit is configured, and ``verify_pass_rate >= 0.9``.
        """

        key = candidate if candidate is not None else self.candidate
        samples = self._buckets.get(key, [])
        sample_count = len(samples)
        ok_count = sum(1 for s in samples if s.ok)
        verify_count = sum(1 for s in samples if s.verified)
        latency_sum = sum(s.latency_ms for s in samples)

        if sample_count:
            error_rate = (sample_count - ok_count) / sample_count
            avg_latency_ms = latency_sum / sample_count
            verify_pass_rate = verify_count / sample_count
        else:
            error_rate = 0.0
            avg_latency_ms = 0.0
            verify_pass_rate = 0.0

        policy = self._policy
        promote = (
            sample_count >= policy.promote_after_samples
            and error_rate <= policy.max_error_rate
            and (policy.max_latency_ms is None or avg_latency_ms <= policy.max_latency_ms)
            and verify_pass_rate >= 0.9
        )

        return CanaryMetrics(
            candidate=key,
            samples=sample_count,
            ok_count=ok_count,
            error_rate=error_rate,
            avg_latency_ms=avg_latency_ms,
            verify_pass_rate=verify_pass_rate,
            promote=promote,
        )
