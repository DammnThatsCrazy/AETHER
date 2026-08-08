"""Measurement privacy handler — propagates DSR erasure into the measurement pipeline."""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger
from services.measurement.reattribution import reattribute_affected
from services.measurement.repositories.touchpoint_repo import TouchpointRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository

logger = get_logger("aether.measurement.privacy")

_touchpoint_repo = TouchpointRepository()
_conversion_repo = ConversionRepository()
_attribution_run_repo = AttributionRunRepository()

# Bound on the pre-tombstone snapshot reads used to discover which
# touchpoints/conversions belong to the profile being erased. Mirrors
# JourneyCompiler's own per-profile bound (_MAX_JOURNEY_STEPS) so this
# doesn't read materially more than the journey rebuild already reads for
# the same profile in the same erasure.
#
# This bound is NEVER applied silently: handle_erasure fetches one row past
# it to detect an over-limit profile, and when that happens it reports
# reattribution_truncated=True (plus scanned counts) in its result and logs
# a warning, instead of quietly under-covering re-attribution the way a bare
# LIMIT would. See services/measurement/reattribution.py for the related
# amplification risk this same bound is deliberately kept for; the per-conversion
# deactivate/create-run core itself now lives in that shared service (Program 3
# M3), which this handler delegates to with reason="privacy_erasure".
_REATTRIBUTION_SCOPE_LIMIT = 2000


class MeasurementPrivacyHandler:
    """Propagates consent erasure into the measurement data pipeline.

    Executed by the durable ``consent.erasure`` job handler
    (services/consent/erasure_jobs.py) when a DSR with request_type ==
    'erasure' is submitted. Steps:
      1. Tombstone touchpoints (sets privacy_class='deleted', nulls identity fields)
      2. Mark conversions attribution-ineligible (nulls identity fields)
      3. Triggers journey rebuild for the profile (which will auto-recompute attribution)
      4. Re-attribution (Program 3 M1 — see
         docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §3): for every
         conversion whose ACTIVE attribution run was built from touchpoints
         that step 1 just tombstoned, deactivates that stale run and
         supersedes it with a fresh, zero-credit run recording that the
         conversion's attribution was voided by this erasure. The
         deactivate/create-run core is delegated to the generalized
         ``services.measurement.reattribution.reattribute_affected`` service
         (Program 3 M3) with ``reason="privacy_erasure"``; that service reuses
         the exact AttributionRunRepository primitives (create_run,
         deactivate_prior_runs) that attribution_engine.py and
         subscription_ltv.py already call in production — no attribution
         model logic is reimplemented. Scope is the erasure subject's
         OWN conversions only; a conversion in a *different* identity
         (e.g. another profile sharing a cluster) that happened to credit
         one of these touchpoints is a Program 3 M3 ("generalized
         invalidation") concern, not M1's.

    "Own conversions" is defined identically to what step 2's tombstone
    actually erases: ``ConversionRepository.list_by_erasure_identity``
    matches profile_id/cluster_id/account_id, the same three columns
    ``tombstone_for_profile`` matches on. Using ``list_by_profile`` (which
    only matches profile_id/cluster_id) here would silently miss any
    conversion reachable solely via account_id — it would still get
    tombstoned, but its stale attribution run would never be corrected.

    The pre-tombstone scope snapshot (touchpoints and conversions) is bounded
    by ``_REATTRIBUTION_SCOPE_LIMIT`` and that bound is surfaced, never
    silent: when either snapshot has more rows than the limit,
    ``result["reattribution_truncated"]`` is True, ``result["errors"]``
    records it (so ``partial_failure`` is also True), and it is logged —
    see the truncation-detection block below.
    """

    async def handle_erasure(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        touchpoint_count = 0
        conversion_count = 0
        journey_rebuild_triggered = False
        errors: list[str] = []
        reattribution_truncated = False
        reattribution_touchpoints_scanned = 0
        reattribution_conversions_scanned = 0

        # Snapshot which touchpoints/conversions belong to this profile BEFORE
        # tombstoning nulls their identity columns. tombstone_for_profile's own
        # WHERE clauses (touchpoints: profile_id/anonymous_id; conversions:
        # profile_id/cluster_id/account_id) become unmatchable afterwards, so
        # this is the only point re-attribution scope can still be discovered
        # from. A failure here is recorded as a partial failure but must not
        # block the tombstone steps that follow — privacy erasure proceeds
        # regardless of whether re-attribution scope could be determined.
        #
        # Conversions are read via list_by_erasure_identity (profile_id OR
        # cluster_id OR account_id) — the SAME identity dimensions
        # tombstone_for_profile matches on — not list_by_profile (profile_id
        # OR cluster_id only). Using list_by_profile here would silently miss
        # any conversion reachable solely through account_id: it would still
        # get tombstoned below, but its stale attribution run would never be
        # discovered or corrected — the exact stale-credit bug this
        # re-attribution step exists to close.
        #
        # Both reads over-fetch by one row (limit + 1) purely to detect
        # whether the profile has more rows than _REATTRIBUTION_SCOPE_LIMIT.
        # If so, the snapshot is trimmed back to the limit but the overage is
        # never silent: reattribution_truncated is set, a warning is logged,
        # and an entry is appended to errors so partial_failure reflects it.
        tombstoned_touchpoint_ids: set[str] = set()
        candidate_conversion_ids: list[str] = []
        try:
            affected_touchpoints = await _touchpoint_repo.list_by_profile(
                tenant_id, user_id, limit=_REATTRIBUTION_SCOPE_LIMIT + 1,
            )
            touchpoints_truncated = len(affected_touchpoints) > _REATTRIBUTION_SCOPE_LIMIT
            if touchpoints_truncated:
                affected_touchpoints = affected_touchpoints[:_REATTRIBUTION_SCOPE_LIMIT]
            reattribution_touchpoints_scanned = len(affected_touchpoints)
            tombstoned_touchpoint_ids = {
                str(tp["touchpoint_id"])
                for tp in affected_touchpoints
                if tp.get("touchpoint_id")
            }

            affected_conversions = await _conversion_repo.list_by_erasure_identity(
                tenant_id,
                user_id,
                attribution_eligible_only=False,
                limit=_REATTRIBUTION_SCOPE_LIMIT + 1,
            )
            conversions_truncated = len(affected_conversions) > _REATTRIBUTION_SCOPE_LIMIT
            if conversions_truncated:
                affected_conversions = affected_conversions[:_REATTRIBUTION_SCOPE_LIMIT]
            reattribution_conversions_scanned = len(affected_conversions)
            candidate_conversion_ids = [
                str(c["conversion_id"])
                for c in affected_conversions
                if c.get("conversion_id")
            ]

            reattribution_truncated = touchpoints_truncated or conversions_truncated
            if reattribution_truncated:
                truncation_msg = (
                    f"reattribution_scope_truncated: touchpoints_scanned="
                    f"{reattribution_touchpoints_scanned}, conversions_scanned="
                    f"{reattribution_conversions_scanned}, limit={_REATTRIBUTION_SCOPE_LIMIT} "
                    f"— profile has more rows than the re-attribution scope bound; "
                    f"some stale attribution runs may not be corrected by this erasure"
                )
                errors.append(truncation_msg)
                logger.warning(
                    "DSR erasure re-attribution scope truncated: %s", truncation_msg,
                    extra={"tenant_id": tenant_id, "user_id": user_id},
                )
        except Exception as exc:
            errors.append(f"reattribution_scope: {exc}")
            logger.error(
                "DSR erasure re-attribution scope lookup failed: %s", exc,
                extra={"tenant_id": tenant_id},
            )

        try:
            touchpoint_count = await _touchpoint_repo.tombstone_for_profile(tenant_id, user_id)
            logger.info(
                "DSR erasure: tombstoned %d touchpoints",
                touchpoint_count,
                extra={"tenant_id": tenant_id, "user_id": user_id},
            )
        except Exception as exc:
            errors.append(f"touchpoint_tombstone: {exc}")
            logger.error("DSR erasure touchpoint tombstone failed: %s", exc, extra={"tenant_id": tenant_id})

        try:
            conversion_count = await _conversion_repo.tombstone_for_profile(tenant_id, user_id)
            logger.info(
                "DSR erasure: tombstoned %d conversions",
                conversion_count,
                extra={"tenant_id": tenant_id, "user_id": user_id},
            )
        except Exception as exc:
            errors.append(f"conversion_tombstone: {exc}")
            logger.error("DSR erasure conversion tombstone failed: %s", exc, extra={"tenant_id": tenant_id})

        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
            compiler = JourneyCompiler()
            await compiler.rebuild_affected_by_consent_change(tenant_id, user_id)
            journey_rebuild_triggered = True
        except Exception as exc:
            errors.append(f"journey_rebuild: {exc}")
            logger.error("DSR erasure journey rebuild failed: %s", exc, extra={"tenant_id": tenant_id})

        # Delegate the per-conversion deactivate/create-run core to the shared
        # re-attribution invalidation service (Program 3 M3). Erasure passes the
        # snapshot it already read pre-tombstone (candidate_conversion_ids) plus
        # the touchpoints it just tombstoned (the voided set), so the service
        # does no re-resolution here — the scope-discovery + truncation surfacing
        # above stays this handler's own, keeping erasure's evidence dict
        # byte-for-byte unchanged. ``run_repo=_attribution_run_repo`` routes the
        # create/deactivate/update calls through THIS module's repo instance so
        # existing erasure tests that monkeypatch it still intercept them.
        #
        # Amplification risk (docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md
        # §3 "Risks"): that core does one create_run/deactivate_prior_runs/
        # update_run round trip PER affected conversion, synchronously, inside
        # the same erasure job — a bulk DSR request, or a profile with up to
        # _REATTRIBUTION_SCOPE_LIMIT affected conversions, can turn into a load
        # spike on attribution_runs. Throttling is intentionally NOT implemented
        # in this increment and is left to a later milestone; the risk stays
        # explicit (see reattribution.py) rather than silent.
        conversions_reattributed = 0
        # Full re-attribution summary (Program 3 M2) so the DSR erasure job can
        # record it as DSR propagation evidence on the attribution_records
        # component. None when no conversions were affected (no re-attribution
        # ran). Additive — every pre-existing key below is unchanged.
        reattribution_summary: dict[str, Any] | None = None
        if tombstoned_touchpoint_ids and candidate_conversion_ids:
            reattribution = await reattribute_affected(
                tenant_id,
                reason="privacy_erasure",
                conversions=candidate_conversion_ids,
                voided_touchpoint_ids=tombstoned_touchpoint_ids,
                scope_limit=_REATTRIBUTION_SCOPE_LIMIT,
                run_repo=_attribution_run_repo,
            )
            conversions_reattributed = reattribution.conversions_reattributed
            errors.extend(reattribution.errors)
            reattribution_summary = reattribution.to_dict()

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "touchpoints_tombstoned": touchpoint_count,
            "conversions_tombstoned": conversion_count,
            "journey_rebuild_triggered": journey_rebuild_triggered,
            "conversions_reattributed": conversions_reattributed,
            "reattribution_truncated": reattribution_truncated,
            "reattribution_scope_limit": _REATTRIBUTION_SCOPE_LIMIT,
            "reattribution_touchpoints_scanned": reattribution_touchpoints_scanned,
            "reattribution_conversions_scanned": reattribution_conversions_scanned,
            "reattribution": reattribution_summary,
            "errors": errors,
            "partial_failure": bool(errors),
        }


_handler = MeasurementPrivacyHandler()


async def handle_erasure_background(tenant_id: str, user_id: str) -> dict[str, Any]:
    """Durable-job entry point for measurement erasure.

    Returns the per-store evidence dict (tombstone counts, journey-rebuild
    flag, re-attribution count, per-store errors). Per-store failures are
    captured in ``result["errors"]``; a fatal error outside the per-store try
    blocks propagates so the jobs worker can retry/dead-letter the job
    instead of silently losing the erasure (the old fire-and-forget path
    swallowed it).
    """
    result = await _handler.handle_erasure(tenant_id, user_id)
    logger.info("DSR erasure complete: %s", result, extra={"tenant_id": tenant_id})
    return result
