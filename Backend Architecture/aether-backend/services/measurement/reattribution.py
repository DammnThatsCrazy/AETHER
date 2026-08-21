"""Generalized re-attribution invalidation service.

Reliability Phase-2, Program 3 ("Deletion / replay / re-attribution") **M3**:
generalize the per-conversion "supersede the stale attribution run" core that
M1 inlined into ``services/measurement/privacy.py`` into a standalone, callable
service, so ANY trigger that must invalidate a conversion's now-wrong
attribution — privacy erasure (``reason="privacy_erasure"``) OR fraud-network
takedown (``reason="fraud_takedown"``) — voids that run the SAME honest way.

The correction is deliberately model-agnostic: for each affected conversion it
reuses ``AttributionRunRepository``'s existing run-creation primitives
(``create_run`` -> ``deactivate_prior_runs`` -> ``update_run(complete)``) — the
exact shape ``attribution_engine.py`` / ``subscription_ltv.py`` /
``privacy.py`` already run in production — to supersede the stale run with a
fresh, zero-credit run that records which touchpoints were voided and by what
trigger. No attribution/model logic is reimplemented here.

The M1 safety properties are preserved verbatim (see
``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md`` §3):

* **One round trip per conversion.** The loop does one
  ``create_run``/``deactivate_prior_runs``/``update_run`` per affected
  conversion, synchronously. A bulk trigger — a large DSR batch or a
  fraud-network takedown spanning many identities — can therefore turn into a
  load spike on ``attribution_runs``; that is the same amplification risk
  ``docs/BACKFILL-JOBS.md`` covers for backfills, and throttling it remains a
  later milestone. The risk is kept explicit here rather than silent.
* **Never a silent truncation.** When a caller passes ``identity_selectors`` /
  ``voided_touchpoint_selectors``, resolution over-fetches one row past
  ``scope_limit`` to detect an over-limit identity; if tripped it sets
  ``result.truncated``, appends a ``…_scope_truncated`` entry to
  ``result.errors`` (so ``partial_failure`` reflects it), and logs a warning —
  instead of quietly under-covering invalidation the way a bare ``LIMIT``
  would.
* **Never a blanket success.** A per-conversion failure is recorded in
  ``result.errors`` and every other conversion is still attempted, so one bad
  conversion can neither swallow the rest nor be reported as success.

Scope note: a conversion is only superseded when its ACTIVE run credits at
least one *voided* touchpoint (``input_touchpoint_ids`` intersects the voided
set) — the same "its touchpoint set actually changed" filter M1 uses. Callers
supply the voided set explicitly (``voided_touchpoint_ids``) or by identity
(``voided_touchpoint_selectors``); with no voided touchpoints nothing is
superseded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from shared.logger.logger import get_logger
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = get_logger("aether.measurement.reattribution")

# Default bound on identity -> conversion / identity -> touchpoint scope
# discovery when a caller passes selectors instead of pre-resolved ids. Kept in
# sync with privacy.py's ``_REATTRIBUTION_SCOPE_LIMIT`` (privacy passes its own
# already-resolved snapshot + limit through, so the two never disagree). NEVER
# applied silently — see the module docstring's truncation property.
DEFAULT_REATTRIBUTION_SCOPE_LIMIT = 2000

# Module-level repository singletons. Callers may inject their own instances
# (``run_repo`` / ``conversion_repo`` / ``touchpoint_repo``) — privacy.py passes
# ITS ``_attribution_run_repo`` so an erasure test that monkeypatches that
# instance still intercepts the create/deactivate/update calls this service
# makes on privacy's behalf.
_attribution_run_repo = AttributionRunRepository()
_conversion_repo = ConversionRepository()
_touchpoint_repo = TouchpointRepository()


@dataclass
class ReattributionResult:
    """Structured outcome of a generalized re-attribution invalidation.

    ``partial_failure`` mirrors the boolean privacy.py already surfaces: any
    non-empty ``errors`` (a per-conversion failure OR a surfaced scope
    truncation) means the invalidation did not fully complete and must not be
    reported as a clean success.
    """

    reason: str
    conversions_scanned: int = 0
    conversions_reattributed: int = 0
    runs_deactivated: int = 0
    runs_created: int = 0
    truncated: bool = False
    scope_limit: int = DEFAULT_REATTRIBUTION_SCOPE_LIMIT
    touchpoints_scanned: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def partial_failure(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "conversions_scanned": self.conversions_scanned,
            "conversions_reattributed": self.conversions_reattributed,
            "runs_deactivated": self.runs_deactivated,
            "runs_created": self.runs_created,
            "truncated": self.truncated,
            "scope_limit": self.scope_limit,
            "touchpoints_scanned": self.touchpoints_scanned,
            "errors": list(self.errors),
            "partial_failure": self.partial_failure,
        }


async def reattribute_affected(
    tenant_id: str,
    *,
    reason: str,
    conversions: Optional[Sequence[Any]] = None,
    identity_selectors: Optional[Sequence[str]] = None,
    voided_touchpoint_ids: Optional[Iterable[Any]] = None,
    voided_touchpoint_selectors: Optional[Sequence[str]] = None,
    scope_limit: int = DEFAULT_REATTRIBUTION_SCOPE_LIMIT,
    run_repo: Optional[AttributionRunRepository] = None,
    conversion_repo: Optional[ConversionRepository] = None,
    touchpoint_repo: Optional[TouchpointRepository] = None,
) -> ReattributionResult:
    """Supersede the stale attribution run of every affected conversion.

    Candidate conversions come from exactly one of:

    * ``conversions`` — already-resolved conversion ids (or dicts carrying a
      ``conversion_id``). privacy.py uses this, passing the snapshot it must
      read pre-tombstone anyway.
    * ``identity_selectors`` — identity ids (profile/cluster/account, or a
      fraud-network member entity id) resolved to conversions via
      ``ConversionRepository.list_by_erasure_identity`` — the SAME identity
      dimensions ``tombstone_for_profile`` matches on.

    The voided touchpoint set (the "what changed" filter) comes from
    ``voided_touchpoint_ids`` (explicit) or ``voided_touchpoint_selectors``
    (identity ids whose OWN touchpoints are the ones being voided, resolved via
    ``TouchpointRepository.list_by_profile``). A conversion is superseded only
    when its active run credits at least one voided touchpoint.

    ``reason`` is stamped as the new run's ``trigger_reason`` and as every
    ``exclusion_reasons`` value, giving the correction an honest audit trail
    (``"privacy_erasure"`` vs ``"fraud_takedown"``).
    """
    run_repo = run_repo or _attribution_run_repo
    conversion_repo = conversion_repo or _conversion_repo
    touchpoint_repo = touchpoint_repo or _touchpoint_repo

    result = ReattributionResult(reason=reason, scope_limit=scope_limit)

    # ── Resolve the voided touchpoint set ────────────────────────────────────
    voided_set: set[str] = set()
    if voided_touchpoint_ids is not None:
        voided_set = {str(t) for t in voided_touchpoint_ids if t is not None}
    elif voided_touchpoint_selectors:
        voided_set = await _resolve_touchpoint_ids(
            tenant_id, voided_touchpoint_selectors, scope_limit, touchpoint_repo, result,
        )
    result.touchpoints_scanned = len(voided_set)

    # ── Resolve the candidate conversion ids ─────────────────────────────────
    if conversions is not None:
        conversion_ids = _extract_conversion_ids(conversions)
    elif identity_selectors:
        conversion_ids = await _resolve_conversion_ids(
            tenant_id, identity_selectors, scope_limit, conversion_repo, result,
        )
    else:
        conversion_ids = []
    result.conversions_scanned = len(conversion_ids)

    # Nothing to correct if either side of the "run credits a voided touchpoint"
    # filter is empty — identical short-circuit to M1's
    # ``if tombstoned_touchpoint_ids and candidate_conversion_ids`` guard.
    if not conversion_ids or not voided_set:
        return result

    await _supersede_runs_for_conversions(
        tenant_id, conversion_ids, voided_set, reason, run_repo, result,
    )
    return result


async def _supersede_runs_for_conversions(
    tenant_id: str,
    conversion_ids: Sequence[str],
    voided_touchpoint_ids: set[str],
    reason: str,
    run_repo: AttributionRunRepository,
    result: ReattributionResult,
) -> None:
    """Per-conversion invalidation loop — the extracted M1 core.

    "Affected" means the conversion's current ACTIVE run was built from at
    least one voided touchpoint (its ``input_touchpoint_ids`` intersects
    ``voided_touchpoint_ids``). Conversions with no active run, or whose active
    run does not reference any voided touchpoint, are left untouched.

    The honest correction is to supersede the stale, now-wrong run with a
    zero-credit run recording that this conversion's attribution was voided by
    ``reason`` — reusing ``AttributionRunRepository``'s run-creation primitives
    rather than reimplementing any attribution/model logic, and never routing
    an (erasure-)ineligible conversion back through the attribution engine.

    Never raises: a per-conversion failure is appended to ``result.errors``
    (making ``result.partial_failure`` True) and every other conversion is
    still attempted, so one bad conversion cannot silently swallow the rest or
    turn into a blanket success.
    """
    for conversion_id in conversion_ids:
        try:
            prior_run = await run_repo.get_active_run(tenant_id, conversion_id)
            if prior_run is None:
                continue  # nothing active to correct

            input_ids = _json_id_set(prior_run.get("input_touchpoint_ids"))
            voided_ids = input_ids & voided_touchpoint_ids
            if not voided_ids:
                continue  # this run's credited touchpoints were not voided

            now = datetime.now(timezone.utc).isoformat()
            new_run = await run_repo.create_run({
                "tenant_id": tenant_id,
                "conversion_id": conversion_id,
                "model_type": prior_run.get("model_type", "last_touch"),
                "model_version": prior_run.get("model_version", "1.0"),
                "code_version": prior_run.get("code_version"),
                "status": "running",
                "currency": prior_run.get("currency", "USD"),
                "eligible_revenue": prior_run.get("eligible_revenue"),
                "trigger_reason": reason,
                "prior_attribution_run_id": prior_run.get("attribution_run_id"),
                "started_at": now,
            })
            # Switch the active run ATOMICALLY. complete_run_atomically
            # deactivates the prior active run(s) AND activates this fresh
            # zero-credit run inside ONE transaction, rolling the whole switch
            # back on failure — the repo documents it as the only success path
            # that should activate a run. The previous shape
            # (deactivate_prior_runs() then a separate update_run()) commits on
            # independent connections in production, so a transient failure of
            # update_run() after deactivate_prior_runs() succeeded would strand
            # the conversion with NO active run: the prior run left inactive and
            # the replacement stuck inactive/running.
            completed = await run_repo.complete_run_atomically(
                new_run["attribution_run_id"],
                tenant_id,
                conversion_id,
                [],  # zero-credit supersession — records the void, credits nothing
                {
                    "credit_total": "0",
                    "unattributed_credit": "1",
                    "input_touchpoint_ids": [],
                    "excluded_touchpoint_ids": sorted(voided_ids),
                    "exclusion_reasons": {tp_id: reason for tp_id in voided_ids},
                    "trigger_reason": reason,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if completed is None:
                raise RuntimeError(
                    f"attribution run {new_run['attribution_run_id']} disappeared before completion"
                )

            # The atomic switch superseded exactly the prior active run found
            # above (one active run per conversion); it returns no deactivation
            # count, so record that single superseded run here.
            result.runs_deactivated += 1
            result.runs_created += 1
            result.conversions_reattributed += 1
            logger.info(
                "re-attribution (%s): superseded stale attribution run %s -> %s "
                "for conversion %s (voided touchpoints=%s)",
                reason,
                prior_run.get("attribution_run_id"),
                new_run["attribution_run_id"],
                conversion_id,
                sorted(voided_ids),
                extra={"tenant_id": tenant_id},
            )
        except Exception as exc:
            result.errors.append(f"reattribution:{conversion_id}: {exc}")
            logger.error(
                "re-attribution (%s) failed for conversion %s: %s",
                reason, conversion_id, exc, extra={"tenant_id": tenant_id},
            )


async def _resolve_conversion_ids(
    tenant_id: str,
    identity_selectors: Sequence[str],
    scope_limit: int,
    conversion_repo: ConversionRepository,
    result: ReattributionResult,
) -> list[str]:
    """Resolve identity selectors to a deduped list of candidate conversion ids.

    Reads conversions via ``list_by_erasure_identity`` (profile_id OR cluster_id
    OR account_id) — the same identity dimensions ``tombstone_for_profile``
    matches — over-fetching one row past ``scope_limit`` per selector to detect,
    and surface, an over-limit identity rather than silently dropping the
    overage.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for selector in _dedupe_selectors(identity_selectors):
        try:
            rows = await conversion_repo.list_by_erasure_identity(
                tenant_id, selector,
                attribution_eligible_only=False,
                limit=scope_limit + 1,
            )
        except Exception as exc:
            result.errors.append(f"reattribution_scope:conversions:{selector}: {exc}")
            logger.error(
                "re-attribution conversion scope lookup failed for %s: %s",
                selector, exc, extra={"tenant_id": tenant_id},
            )
            continue
        if len(rows) > scope_limit:
            rows = rows[:scope_limit]
            _mark_truncated(result, tenant_id, "conversions", selector, scope_limit)
        for row in rows:
            cid = row.get("conversion_id")
            if cid is None:
                continue
            cid = str(cid)
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
    return ordered


async def _resolve_touchpoint_ids(
    tenant_id: str,
    selectors: Sequence[str],
    scope_limit: int,
    touchpoint_repo: TouchpointRepository,
    result: ReattributionResult,
) -> set[str]:
    """Resolve identity selectors to the set of their touchpoint ids (the voided
    set), over-fetching one row past ``scope_limit`` per selector to surface an
    over-limit identity instead of silently under-covering it."""
    voided: set[str] = set()
    for selector in _dedupe_selectors(selectors):
        # A fraud-network member id (and an erasure identity) is untyped: it may
        # name a profile/anonymous OR a cluster identity. The conversion side
        # (``list_by_erasure_identity``) already matches profile_id OR cluster_id
        # OR account_id, so the voided touchpoint set must cover the SAME
        # identity dimensions — otherwise a cluster-identified selector resolves
        # its conversions but an EMPTY voided set, and the "run credits a voided
        # touchpoint" filter leaves its fraudulent attribution silently active.
        # ``list_by_profile``'s default matches profile_id OR anonymous_id;
        # identity_type="cluster" adds the cluster_id dimension the touchpoint
        # table requires.
        for identity_type in (None, "cluster"):
            try:
                rows = await touchpoint_repo.list_by_profile(
                    tenant_id, selector,
                    identity_type=identity_type,
                    limit=scope_limit + 1,
                )
            except Exception as exc:
                result.errors.append(f"reattribution_scope:touchpoints:{selector}: {exc}")
                logger.error(
                    "re-attribution touchpoint scope lookup failed for %s: %s",
                    selector, exc, extra={"tenant_id": tenant_id},
                )
                continue
            if len(rows) > scope_limit:
                rows = rows[:scope_limit]
                _mark_truncated(result, tenant_id, "touchpoints", selector, scope_limit)
            for row in rows:
                tp_id = row.get("touchpoint_id")
                if tp_id is not None:
                    voided.add(str(tp_id))
    return voided


def _mark_truncated(
    result: ReattributionResult,
    tenant_id: str,
    kind: str,
    selector: str,
    scope_limit: int,
) -> None:
    result.truncated = True
    msg = (
        f"reattribution_scope_truncated: kind={kind}, selector={selector}, "
        f"limit={scope_limit} — identity has more {kind} than the re-attribution "
        f"scope bound; some stale attribution runs may not be corrected by this "
        f"invalidation"
    )
    result.errors.append(msg)
    logger.warning(
        "re-attribution scope truncated: %s", msg,
        extra={"tenant_id": tenant_id},
    )


def _extract_conversion_ids(conversions: Sequence[Any]) -> list[str]:
    """Normalize a caller-supplied conversion collection to a deduped id list.

    Accepts either bare conversion ids or conversion dicts carrying a
    ``conversion_id`` (the shape ``list_by_erasure_identity`` returns), so a
    caller can hand back either its ids or its full snapshot rows.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for item in conversions:
        if isinstance(item, dict):
            value = item.get("conversion_id")
        else:
            value = item
        if value is None:
            continue
        cid = str(value)
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def _dedupe_selectors(selectors: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for selector in selectors:
        if selector is None:
            continue
        key = str(selector)
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _json_id_set(value: Any) -> set[str]:
    """Normalize an ``input_touchpoint_ids``-shaped field to a set of str ids.

    Local/test mode stores whatever Python list was passed in; production reads
    a JSONB column back, which some asyncpg/codec configurations surface as a
    JSON string rather than a decoded list (the same defensive shape
    ``attribution_engine.py`` and the pre-M3 ``privacy.py`` already handle for
    this exact field).
    """
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value if v is not None}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return set()
        if isinstance(parsed, list):
            return {str(v) for v in parsed if v is not None}
    return set()
