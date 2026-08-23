"""Grounded-synthesis D6 gate — retrieval-before-synthesis, fail-closed (ADR-008 D6).

The grounded-synthesis pipeline runs retrieval-before-synthesis: Aether
retrieves a tenant-scoped, freshness-bounded evidence set and the model
synthesizes ONLY from that evidence. This module owns the fail-closed gate a
synthesis engine must pass BEFORE a model may produce a response.

:class:`GroundingPolicy.check` enforces, in fixed order (all fail-closed):

1. **Tenant scope** — ``request.evidence.tenant_id`` must equal
   ``request.tenant_id``. The requested tenant is server-authoritative; a
   mismatch raises :class:`GroundingViolation` so cross-tenant evidence can
   never reach a model.
2. **Presence / count** — evidence must exist (``None`` is rejected), be
   non-empty, and carry at least ``min_evidence`` items. Missing or thin
   evidence raises :class:`InsufficientEvidence`.
3. **Freshness** — every item must be within ``max_age_seconds`` of the policy
   ``now``. ANY item older than the bound fails the whole gate
   (:class:`StaleEvidence`): synthesis must not ground on a mixed set that
   includes stale evidence.

Engines call :meth:`GroundingPolicy.ready` for a non-raising boolean gate; the
pipeline calls :meth:`GroundingPolicy.check` and lets failures propagate so
synthesis fails closed rather than inventing claims from nothing.

Boundaries (deliberate):

* The policy **never runs retrieval** and **never sees credentials** — it
  inspects only the assembled, secret-free :class:`EvidenceSet` already
  validated by the context layer.
* The policy is duck-typed: it reads only ``request.evidence`` and
  ``request.tenant_id``, so it works with any request-shaped object exposing
  that surface (currently the synthesis ``SynthesisRequest``).
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = [
    "InsufficientEvidence",
    "StaleEvidence",
    "GroundingViolation",
    "GroundingPolicy",
]


class InsufficientEvidence(Exception):
    """Raised when there is no evidence to ground synthesis on (fail-closed, D6).

    Either ``request.evidence`` is ``None``, the set is empty, or it holds
    fewer than ``min_evidence`` items. Without retrievable evidence the
    pipeline must NOT synthesize, so this gate refuses to proceed.
    """


class StaleEvidence(Exception):
    """Raised when any evidence item is older than ``max_age_seconds``.

    A synthesis engine must not ground claims on evidence that includes a stale
    item; the pipeline fails closed and requires a fresh retrieval before
    synthesis.
    """


class GroundingViolation(Exception):
    """Raised when evidence belongs to a tenant other than the request.

    The requested ``tenant_id`` is server-authoritative: a cross-tenant
    evidence set fails the whole gate (fail-closed) so out-of-tenant data can
    never reach a model.
    """


class GroundingPolicy:
    """Fail-closed D6 gate: retrieval-before-synthesis grounding check.

    ``now`` is injected at construction for deterministic tests; when it is
    left ``None`` the real UTC clock (``datetime.now(timezone.utc)``) is read
    fresh inside each :meth:`check` call, so a long-lived policy never grounds
    on evidence that goes stale after the policy was constructed.
    ``min_evidence`` and ``max_age_seconds`` are validated at init (must be
    positive).
    """

    def __init__(
        self,
        *,
        min_evidence: int = 1,
        max_age_seconds: int = 300,
        now: datetime | None = None,
    ) -> None:
        if min_evidence <= 0:
            raise ValueError(f"min_evidence must be positive; got {min_evidence!r}")
        if max_age_seconds <= 0:
            raise ValueError(f"max_age_seconds must be positive; got {max_age_seconds!r}")
        self._min_evidence = min_evidence
        self._max_age_seconds = max_age_seconds
        # ``None`` means "read the real UTC clock per check", NOT "capture it
        # once at construction": the policy is long-lived (SynthesisService
        # reuses its engine), so evidence that ages past max_age_seconds after
        # startup must become stale on the very next check. An injected fixed
        # clock (deterministic tests) is preserved verbatim.
        self._now = now

    def check(self, request) -> None:
        """Fail-closed D6 gate, enforced tenant scope -> presence/count -> freshness.

        Raises:
            GroundingViolation: ``request.evidence.tenant_id != request.tenant_id``.
            InsufficientEvidence: evidence is ``None``, empty, or below ``min_evidence``.
            StaleEvidence: any evidence item is older than ``max_age_seconds``.
        """
        evidence = request.evidence
        # 1. Tenant scope (server-authoritative; checked before anything else).
        if evidence is not None and evidence.tenant_id != request.tenant_id:
            raise GroundingViolation(
                f"evidence belongs to tenant {evidence.tenant_id!r}, "
                f"not requested tenant {request.tenant_id!r}"
            )
        # 2. Presence / count.
        if evidence is None or len(evidence.items) < self._min_evidence:
            present = 0 if evidence is None else len(evidence.items)
            raise InsufficientEvidence(
                f"grounding requires at least {self._min_evidence} evidence "
                f"item(s); got {present}"
            )
        # 3. Freshness — EVERY item must be within the bound. One stale item
        #    fails the whole set: synthesis must not ground on a mixed set.
        #    The clock is read per check (real UTC when ``now`` was not
        #    injected) so evidence collected after process startup is judged
        #    against the current time and goes stale once it exceeds the bound.
        now = self._now if self._now is not None else datetime.now(timezone.utc)
        stale_count = sum(
            1
            for item in evidence.items
            if (now - item.collected_at).total_seconds() > self._max_age_seconds
        )
        if stale_count:
            raise StaleEvidence(
                f"{stale_count} of {len(evidence.items)} evidence item(s) are "
                f"older than max_age_seconds={self._max_age_seconds}"
            )

    def ready(self, request) -> bool:
        """Non-raising gate used by synthesis engines.

        Returns ``True`` when :meth:`check` passes; ``False`` for any of the
        three fail-closed grounding failures. Programming errors (for example a
        request missing the required attributes) still propagate.
        """
        try:
            self.check(request)
            return True
        except (InsufficientEvidence, StaleEvidence, GroundingViolation):
            return False
