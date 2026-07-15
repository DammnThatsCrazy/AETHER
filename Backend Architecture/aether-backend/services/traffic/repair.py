"""Durable source-classification repair on the existing jobs platform.

The repair deliberately walks the canonical measurement path in order:
touchpoint classification revision -> canonical activity refresh -> journey
rebuild -> conversion attribution rerun -> Gold/measurement restatement.  It is
restartable by ``job_id`` and never overwrites classification history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from repositories.repos import get_pool
from services.jobs.handlers import (
    HANDLER_REGISTRY,
    JobContext,
    JobOutcome,
    register_handler,
)
from services.measurement.engine.attribution_engine import AttributionEngine
from services.measurement.engine.gold_materializer import backfill_tenant
from services.measurement.engine.journey_compiler import JourneyCompiler
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository
from services.traffic.classifier import SOURCE_CLASSIFIER_VERSION, ClassifiedSource, SourceClassifier
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.traffic.source_classification_repair")

JOB_TYPE = "measurement.source_classification_repair"
_local_runs: dict[str, dict[str, Any]] = {}


class SourceClassificationRepairService:
    """Checkpointed, tenant-scoped historical classification repair."""

    def __init__(self) -> None:
        self._touchpoints = TouchpointRepository()
        self._conversions = ConversionRepository()
        self._compiler = JourneyCompiler()
        self._attribution = AttributionEngine()
        self._classifier = SourceClassifier()

    async def run(
        self,
        tenant_id: str,
        job_id: str,
        payload: dict[str, Any],
        *,
        heartbeat: Optional[Any] = None,
        emit_event: Optional[Any] = None,
    ) -> dict[str, Any]:
        start_at = _parse_datetime(payload.get("start_date") or payload.get("start_at"), end=False)
        end_at = _parse_datetime(payload.get("end_date") or payload.get("end_at"), end=True)
        dry_run = bool(payload.get("dry_run", False))
        total_limit = max(1, min(int(payload.get("limit") or 10000), 100000))
        page_size = max(1, min(int(payload.get("page_size") or 250), 1000, total_limit))
        filters = {
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
            "dry_run": dry_run,
            "limit": total_limit,
        }
        state = await self._start_or_resume(tenant_id, job_id, filters)
        counters = dict(state.get("counters") or {})
        counters.setdefault("scanned", 0)
        counters.setdefault("reclassified", 0)
        counters.setdefault("unchanged", 0)
        counters.setdefault("journeys_rebuilt", 0)
        counters.setdefault("conversions_recomputed", 0)
        counters.setdefault("gold_rows", 0)
        counters.setdefault("errors", 0)
        counters.setdefault("affected_profiles", [])
        counters.setdefault("affected_identities", [])
        counters.setdefault("affected_conversion_ids", [])
        counters.setdefault("rebuilt_profile_ids", [])
        counters.setdefault("rebuilt_identity_keys", [])
        counters.setdefault("recomputed_conversion_ids", [])
        counters.setdefault("min_occurred_at", None)
        counters.setdefault("max_occurred_at", None)
        counters.setdefault("min_conversion_occurred_at", None)
        counters.setdefault("max_conversion_occurred_at", None)
        errors = list(state.get("errors") or [])
        run_id = state["run_id"]
        phase = state.get("phase") or "classify_touchpoints"

        if state.get("status") != "running":
            # A durable jobs retry resumes the same repair row. Reflect that it
            # is active again and clear the prior terminal timestamp before
            # doing any work; successful phases below remove their resolved
            # transient errors from the outstanding error set.
            await self._checkpoint(
                run_id,
                status="running",
                phase=phase,
                counters=counters,
                errors=errors,
            )

        try:
            if phase == "classify_touchpoints":
                cursor_at = _parse_datetime(state.get("cursor_occurred_at"), end=False)
                cursor_id = state.get("cursor_touchpoint_id")
                while counters["scanned"] < total_limit:
                    if heartbeat:
                        await heartbeat()
                    remaining = total_limit - counters["scanned"]
                    page = await self._touchpoints.list_for_source_reclassification(
                        tenant_id,
                        start_at=start_at,
                        end_at=end_at,
                        limit=min(page_size, remaining),
                        cursor_occurred_at=cursor_at,
                        cursor_touchpoint_id=cursor_id,
                    )
                    if not page:
                        break
                    for row in page:
                        counters["scanned"] += 1
                        occurred = _parse_datetime(row.get("occurred_at"), end=False)
                        if occurred:
                            iso_occurred = occurred.isoformat()
                            if not counters["min_occurred_at"] or iso_occurred < counters["min_occurred_at"]:
                                counters["min_occurred_at"] = iso_occurred
                            if not counters["max_occurred_at"] or iso_occurred > counters["max_occurred_at"]:
                                counters["max_occurred_at"] = iso_occurred
                        classified = self._classify_row(row)
                        fields = _classification_fields(classified)
                        # Historical touchpoints retain only an origin-safe
                        # referrer plus this one-way path fingerprint.  A
                        # reclassification cannot recreate the path from the
                        # sanitized origin, so preserve the existing hash
                        # rather than silently erasing privacy-safe evidence.
                        if not fields.get("referrer_path_hash") and row.get("referrer_path_hash"):
                            fields["referrer_path_hash"] = row["referrer_path_hash"]
                        input_hash = _input_hash(row)
                        if _same_current_classification(row, fields):
                            counters["unchanged"] += 1
                        else:
                            counters["reclassified"] += 1
                        identity = _identity_ref(row)
                        if identity:
                            if identity not in counters["affected_identities"]:
                                counters["affected_identities"].append(identity)
                            # Retained as a response-compatibility summary; the
                            # rebuild itself always uses the typed identity.
                            if identity["id"] not in counters["affected_profiles"]:
                                counters["affected_profiles"].append(identity["id"])
                        if not dry_run:
                            await self._touchpoints.apply_source_classification(
                                tenant_id,
                                str(row["touchpoint_id"]),
                                fields,
                                input_hash=input_hash,
                                reason=f"historical_reclassification:{SOURCE_CLASSIFIER_VERSION}",
                                job_id=job_id,
                            )
                    last = page[-1]
                    cursor_at = _parse_datetime(last.get("occurred_at"), end=False)
                    cursor_id = str(last.get("touchpoint_id"))
                    await self._checkpoint(
                        run_id,
                        status="running",
                        phase="classify_touchpoints",
                        counters=counters,
                        errors=errors,
                        cursor_occurred_at=cursor_at,
                        cursor_touchpoint_id=cursor_id,
                    )
                    if emit_event:
                        await emit_event(
                            "source_classification.progress",
                            {
                                "phase": "classify_touchpoints",
                                "scanned": counters["scanned"],
                                "reclassified": counters["reclassified"],
                            },
                        )
                    if len(page) < min(page_size, remaining):
                        break

                next_phase = "complete" if dry_run else "rebuild_journeys"
                errors = _without_phase_errors(errors, "classify_touchpoints")
                counters["errors"] = len(errors)
                await self._checkpoint(
                    run_id, status="running", phase=next_phase,
                    counters=counters, errors=errors,
                    cursor_occurred_at=cursor_at,
                    cursor_touchpoint_id=cursor_id,
                )
                phase = next_phase

            if phase == "rebuild_journeys":
                affected_identities = counters["affected_identities"] or [
                    {"type": "profile", "id": profile_id}
                    for profile_id in counters["affected_profiles"]
                ]
                for identity in affected_identities:
                    identity_type = str(identity["type"])
                    identity_id = str(identity["id"])
                    identity_key = f"{identity_type}:{identity_id}"
                    if identity_key in counters["rebuilt_identity_keys"]:
                        continue
                    if heartbeat:
                        await heartbeat()
                    try:
                        await self._compiler.compile_for_profile(
                            tenant_id,
                            identity_id,
                            identity_type=identity_type,
                            trigger_reason=f"source_classifier:{SOURCE_CLASSIFIER_VERSION}",
                        )
                        counters["journeys_rebuilt"] += 1
                        conversions = await self._conversions.list_by_profile(
                            tenant_id,
                            identity_id,
                            identity_type=identity_type,
                            attribution_eligible_only=True,
                            limit=10000,
                        )
                        for conversion in conversions:
                            conversion_id = str(conversion.get("conversion_id"))
                            if conversion_id not in counters["affected_conversion_ids"]:
                                counters["affected_conversion_ids"].append(conversion_id)
                            conversion_occurred = _parse_datetime(
                                conversion.get("occurred_at"), end=False
                            )
                            if conversion_occurred:
                                conversion_iso = conversion_occurred.isoformat()
                                if (
                                    not counters["min_conversion_occurred_at"]
                                    or conversion_iso
                                    < counters["min_conversion_occurred_at"]
                                ):
                                    counters["min_conversion_occurred_at"] = conversion_iso
                                if (
                                    not counters["max_conversion_occurred_at"]
                                    or conversion_iso
                                    > counters["max_conversion_occurred_at"]
                                ):
                                    counters["max_conversion_occurred_at"] = conversion_iso
                    except Exception as exc:  # continue other identities; surface partial status
                        counters["errors"] += 1
                        errors.append(
                            {
                                "phase": "rebuild_journeys",
                                "identity_type": identity_type,
                                "identity_id": identity_id,
                                "error": str(exc),
                            }
                        )
                    else:
                        # A checkpoint key means the complete identity rebuild
                        # and conversion discovery succeeded. Failed identities
                        # remain absent so the durable job retry can resume them.
                        counters["rebuilt_identity_keys"].append(identity_key)
                        if identity_id not in counters["rebuilt_profile_ids"]:
                            counters["rebuilt_profile_ids"].append(identity_id)
                    await self._checkpoint(
                        run_id, status="running", phase="rebuild_journeys",
                        counters=counters, errors=errors,
                    )

                pending_identity_keys = [
                    f"{identity['type']}:{identity['id']}"
                    for identity in affected_identities
                    if f"{identity['type']}:{identity['id']}"
                    not in counters["rebuilt_identity_keys"]
                ]
                if pending_identity_keys:
                    # Returning a partial outcome would be terminal on the jobs
                    # platform. Raise instead so max_attempts/backoff can retry
                    # exactly the identities that lack success checkpoints.
                    raise RuntimeError(
                        "journey rebuild work remains for "
                        f"{len(pending_identity_keys)} identity(s)"
                    )
                errors = _without_phase_errors(errors, "rebuild_journeys")
                counters["errors"] = len(errors)
                await self._checkpoint(
                    run_id, status="running", phase="recompute_attribution",
                    counters=counters, errors=errors,
                )
                phase = "recompute_attribution"

            if phase == "recompute_attribution":
                for conversion_id in counters["affected_conversion_ids"]:
                    if conversion_id in counters["recomputed_conversion_ids"]:
                        continue
                    if heartbeat:
                        await heartbeat()
                    try:
                        # run_for_conversion always creates a new run; the
                        # repository atomically makes it active on completion.
                        await self._attribution.run_for_conversion(
                            tenant_id,
                            conversion_id,
                            trigger_reason=f"source_classifier:{SOURCE_CLASSIFIER_VERSION}",
                            source_classifier_version=SOURCE_CLASSIFIER_VERSION,
                        )
                        counters["conversions_recomputed"] += 1
                    except Exception as exc:
                        counters["errors"] += 1
                        errors.append({"phase": "recompute_attribution", "conversion_id": conversion_id, "error": str(exc)})
                    else:
                        # As above, the durable checkpoint records success only;
                        # failed conversions must remain retryable.
                        counters["recomputed_conversion_ids"].append(conversion_id)
                    await self._checkpoint(
                        run_id, status="running", phase="recompute_attribution",
                        counters=counters, errors=errors,
                    )

                pending_conversion_ids = [
                    conversion_id
                    for conversion_id in counters["affected_conversion_ids"]
                    if conversion_id not in counters["recomputed_conversion_ids"]
                ]
                if pending_conversion_ids:
                    raise RuntimeError(
                        "attribution recomputation work remains for "
                        f"{len(pending_conversion_ids)} conversion(s)"
                    )
                errors = _without_phase_errors(errors, "recompute_attribution")
                counters["errors"] = len(errors)
                await self._checkpoint(
                    run_id, status="running", phase="restate_measurement",
                    counters=counters, errors=errors,
                )
                phase = "restate_measurement"

            if phase == "restate_measurement":
                from datetime import timedelta
                observed_start = _parse_datetime(counters.get("min_occurred_at"), end=False)
                observed_end = _parse_datetime(counters.get("max_occurred_at"), end=False)
                conversion_start = _parse_datetime(
                    counters.get("min_conversion_occurred_at"), end=False
                )
                conversion_end = _parse_datetime(
                    counters.get("max_conversion_occurred_at"), end=False
                )
                range_starts = [value for value in (start_at, observed_start, conversion_start) if value]
                materialize_start = (
                    min(range_starts) if range_starts else datetime.now(timezone.utc)
                ).date()
                materialize_end = (
                    max(
                        value
                        for value in (
                            (end_at - timedelta(microseconds=1)) if end_at else None,
                            observed_end,
                            conversion_end,
                            datetime.now(timezone.utc) if not any((end_at, observed_end, conversion_end)) else None,
                        )
                        if value is not None
                    ).date()
                )
                if materialize_end < materialize_start:
                    materialize_end = materialize_start
                try:
                    result = await backfill_tenant(
                        tenant_id,
                        materialize_start,
                        materialize_end,
                        restatement_reason=(
                            f"source classification repair {run_id} "
                            f"to {SOURCE_CLASSIFIER_VERSION}"
                        ),
                    )
                    counters["gold_rows"] = (
                        result.campaign_perf_rows + result.journey_econ_rows
                        + result.attribution_credit_rows
                    )
                    for error in result.errors:
                        counters["errors"] += 1
                        errors.append({"phase": "restate_measurement", "error": error})
                except Exception as exc:
                    counters["errors"] += 1
                    errors.append({"phase": "restate_measurement", "error": str(exc)})
                    # Gold restatement is the last required phase, not optional
                    # telemetry. Preserve this phase and let the jobs platform
                    # retry rather than publishing a terminal partial outcome.
                    raise
                if result.errors:
                    raise RuntimeError(
                        "measurement restatement work remains after "
                        f"{len(result.errors)} error(s)"
                    )
                errors = _without_phase_errors(errors, "restate_measurement")
                counters["errors"] = len(errors)
                phase = "complete"

            final_status = "partially_succeeded" if errors else "succeeded"
            await self._checkpoint(
                run_id,
                status=final_status,
                phase="complete",
                counters=counters,
                errors=errors,
                completed=True,
            )
            metrics.increment(
                "source_classification_repair_completed",
                labels={"status": final_status, "dry_run": str(dry_run).lower()},
            )
            return {
                "run_id": run_id,
                "status": final_status,
                "target_classifier_version": SOURCE_CLASSIFIER_VERSION,
                "dry_run": dry_run,
                "counters": counters,
                "errors": errors[:100],
            }
        except Exception as exc:
            errors.append({"phase": phase, "error": str(exc)})
            counters["errors"] += 1
            await self._checkpoint(
                run_id, status="failed", phase=phase,
                counters=counters, errors=errors, completed=True,
            )
            raise

    def _classify_row(self, row: dict[str, Any]) -> ClassifiedSource:
        evidence = row.get("source_classification_evidence") or {}
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except (ValueError, TypeError):
                evidence = {}
        verified: Optional[dict[str, Any]] = None
        if row.get("verified_referral_link_id"):
            verified = {
                "verified_referral_link_id": str(row["verified_referral_link_id"]),
                "referral_mediation_type": row.get("referral_mediation_type"),
                "ai_provider": row.get("ai_provider"),
                "ai_product": row.get("ai_product"),
                "actor_type": row.get("actor_type"),
                "source": row.get("source"),
                "journey_role": row.get("journey_role"),
            }
        return self._classifier.classify(
            referrer=row.get("referrer") or "",
            referrer_domain=row.get("normalized_referrer_domain") or "",
            utm_source=row.get("utm_source"),
            utm_medium=row.get("utm_medium"),
            utm_campaign=row.get("utm_campaign"),
            click_ids=_historical_click_ids(row, evidence),
            landing_page=row.get("landing_url") or "",
            user_agent=_historical_user_agent(evidence),
            verified_referral=verified,
            explicit_actor_type=row.get("actor_type"),
        )

    async def _start_or_resume(
        self, tenant_id: str, job_id: str, filters: dict[str, Any]
    ) -> dict[str, Any]:
        pool = await get_pool()
        if pool is None:
            existing = _local_runs.get(job_id)
            if existing:
                if existing["tenant_id"] != tenant_id:
                    raise ValueError("repair job tenant mismatch")
                return dict(existing)
            row = {
                "run_id": str(uuid4()), "tenant_id": tenant_id, "job_id": job_id,
                "target_classifier_version": SOURCE_CLASSIFIER_VERSION,
                "status": "running", "phase": "classify_touchpoints",
                "filters": filters, "cursor_occurred_at": None,
                "cursor_touchpoint_id": None, "counters": {}, "errors": [],
                "started_at": datetime.now(timezone.utc), "completed_at": None,
            }
            _local_runs[job_id] = row
            return dict(row)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM source_classification_repair_runs WHERE job_id=$1",
                job_id,
            )
            if row:
                if row["tenant_id"] != tenant_id:
                    raise ValueError("repair job tenant mismatch")
                return _decode_checkpoint(dict(row))
            row = await conn.fetchrow(
                """
                INSERT INTO source_classification_repair_runs (
                    tenant_id, job_id, target_classifier_version, status,
                    phase, filters, counters, errors, started_at
                ) VALUES ($1,$2,$3,'running','classify_touchpoints',$4::jsonb,'{}'::jsonb,'[]'::jsonb,now())
                RETURNING *
                """,
                tenant_id, job_id, SOURCE_CLASSIFIER_VERSION,
                json.dumps(filters, default=str),
            )
            return _decode_checkpoint(dict(row))

    async def _checkpoint(
        self,
        run_id: str,
        *,
        status: str,
        phase: str,
        counters: dict[str, Any],
        errors: list[Any],
        cursor_occurred_at: Optional[datetime] = None,
        cursor_touchpoint_id: Optional[str] = None,
        completed: bool = False,
    ) -> None:
        pool = await get_pool()
        if pool is None:
            for row in _local_runs.values():
                if str(row["run_id"]) == str(run_id):
                    row.update({
                        "status": status, "phase": phase,
                        "counters": dict(counters), "errors": list(errors),
                        "cursor_occurred_at": cursor_occurred_at or row.get("cursor_occurred_at"),
                        "cursor_touchpoint_id": cursor_touchpoint_id or row.get("cursor_touchpoint_id"),
                        "completed_at": datetime.now(timezone.utc) if completed else None,
                    })
                    return
            raise KeyError(f"repair run not found: {run_id}")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE source_classification_repair_runs
                SET status=$2, phase=$3, counters=$4::jsonb, errors=$5::jsonb,
                    cursor_occurred_at=COALESCE($6, cursor_occurred_at),
                    cursor_touchpoint_id=COALESCE($7, cursor_touchpoint_id),
                    completed_at=CASE WHEN $8 THEN now() ELSE NULL END,
                    updated_at=now()
                WHERE run_id=$1
                """,
                _uuid(run_id), status, phase,
                json.dumps(counters, default=str), json.dumps(errors[-100:], default=str),
                cursor_occurred_at, _uuid(cursor_touchpoint_id), completed,
            )


def register_source_classification_repair_handler() -> None:
    """Register the internal-only job handler exactly once at startup."""
    if JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx: JobContext) -> JobOutcome:
        service = SourceClassificationRepairService()
        try:
            result = await service.run(
                ctx.tenant_id,
                ctx.job_id,
                payload,
                heartbeat=ctx.heartbeat,
                emit_event=ctx.emit_event,
            )
            return JobOutcome(
                status=result["status"],
                result=result,
                error=("one or more repair phases failed" if result["errors"] else None),
            )
        except Exception as exc:
            logger.exception("source classification repair failed: %s", exc)
            return JobOutcome(status="failed", result={}, error=str(exc))


def _without_phase_errors(
    errors: list[Any], phase: str
) -> list[Any]:
    """Drop transient errors for a phase that has now completed successfully."""

    return [
        error
        for error in errors
        if not isinstance(error, dict) or error.get("phase") != phase
    ]


def _classification_fields(classified: ClassifiedSource) -> dict[str, Any]:
    return {
        "channel": _silver_channel(classified.channel),
        "source": classified.source,
        "medium": classified.medium,
        "source_class": classified.source_class,
        "referral_mediation_type": classified.referral_mediation_type,
        "ai_provider": classified.ai_provider,
        "ai_product": classified.ai_product,
        "actor_type": classified.actor_type,
        "journey_role": classified.journey_role,
        "evidence_confidence": classified.confidence,
        "verification_level": classified.verification_level,
        "source_classifier_version": classified.classifier_version,
        "source_classified_at": datetime.now(timezone.utc),
        "normalized_referrer_domain": classified.normalized_referrer_domain or None,
        "referrer_path_hash": classified.referrer_path_hash,
        "source_classification_evidence": classified.evidence_payload(),
        "attribution_eligible": classified.attribution_eligible,
        "verified_referral_link_id": classified.verified_referral_link_id,
        "referrer": classified.normalized_referrer or None,
    }


def _identity_ref(row: dict[str, Any]) -> Optional[dict[str, str]]:
    for identity_type, field in (
        ("profile", "profile_id"),
        ("cluster", "cluster_id"),
        ("anonymous", "anonymous_id"),
    ):
        value = row.get(field)
        if value:
            return {"type": identity_type, "id": str(value)}
    return None


def _input_hash(row: dict[str, Any]) -> str:
    evidence = row.get("source_classification_evidence") or {}
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except (ValueError, TypeError):
            evidence = {}
    payload = {
        "referrer_domain": row.get("normalized_referrer_domain") or row.get("referrer"),
        "referrer_path_hash": row.get("referrer_path_hash"),
        "utm_source": row.get("utm_source"),
        "utm_medium": row.get("utm_medium"),
        "utm_campaign": row.get("utm_campaign"),
        "click_id_hash": (
            hashlib.sha256(str(row["click_id"]).encode()).hexdigest()
            if row.get("click_id") else None
        ),
        "verified_referral_link_id": str(row.get("verified_referral_link_id") or "") or None,
        "actor_type": row.get("actor_type"),
        "classification_signals": sorted(evidence.get("signals") or []),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _historical_click_ids(row: dict[str, Any], evidence: dict[str, Any]) -> dict[str, str]:
    value = row.get("click_id")
    if not value:
        return {}
    for signal in evidence.get("signals") or []:
        if isinstance(signal, str) and signal.startswith("click_id:"):
            return {signal.split(":", 1)[1]: str(value)}
    # The old ledger stored only the click-id value, not its provider key.
    # Do not guess a provider and corrupt historical source classification.
    return {}


def _historical_user_agent(evidence: dict[str, Any]) -> str:
    """Recover only a classifier-owned UA signature, never a raw user agent."""

    for signal in evidence.get("signals") or []:
        if isinstance(signal, str) and signal.startswith("user_agent:"):
            return signal.split(":", 1)[1]
    # Backward compatibility for an early internal evidence shape. New
    # revisions intentionally persist signatures in ``signals`` instead.
    return str(evidence.get("user_agent_signature") or "")


def _same_current_classification(row: dict[str, Any], fields: dict[str, Any]) -> bool:
    comparable = (
        "channel", "source", "medium", "source_class", "referral_mediation_type",
        "ai_provider", "ai_product", "actor_type", "journey_role",
        "verification_level", "normalized_referrer_domain", "referrer_path_hash",
        "attribution_eligible", "verified_referral_link_id",
    )
    return row.get("source_classifier_version") == SOURCE_CLASSIFIER_VERSION and all(
        str(row.get(key) or "") == str(fields.get(key) or "") for key in comparable
    )


def _silver_channel(channel: str) -> str:
    mapping = {
        "Paid Search": "paid", "Paid Social": "paid", "Display": "paid",
        "Organic Search": "organic_search", "Organic Social": "social",
        "Email": "email", "Affiliate": "affiliate", "Partner": "partner",
        "Referral": "referral", "AI Referral": "ai_referral",
        "Agent Referral": "agent_referral", "AI Crawler": "ai_crawler",
        "Machine Referral": "machine_referral", "Direct": "direct",
    }
    return mapping.get(channel, channel.lower().replace(" ", "_") if channel else "other")


def _parse_datetime(value: Any, *, end: bool) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        raw = str(value)
        if len(raw) == 10:
            parsed = date.fromisoformat(raw)
            dt = datetime(parsed.year, parsed.month, parsed.day)
            if end:
                from datetime import timedelta
                dt += timedelta(days=1)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _uuid(value: Any) -> Optional[UUID]:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _decode_checkpoint(row: dict[str, Any]) -> dict[str, Any]:
    for field, default in (("filters", {}), ("counters", {}), ("errors", [])):
        value = row.get(field)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = default
        row[field] = value if value is not None else default
    row["run_id"] = str(row["run_id"])
    if row.get("cursor_touchpoint_id"):
        row["cursor_touchpoint_id"] = str(row["cursor_touchpoint_id"])
    return row


def _reset_local_repair_runs() -> None:
    _local_runs.clear()


__all__ = [
    "JOB_TYPE", "SourceClassificationRepairService",
    "register_source_classification_repair_handler",
]
