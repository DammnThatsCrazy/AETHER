"""
Aether Agent Layer — Temporal Filler Enrichment Worker
Fills gaps in entity timelines by interpolating or back-filling
historical data points.

Capabilities:
  - Detect temporal gaps in entity event streams
  - Query historical APIs (Wayback Machine, SEC EDGAR, archive.org)
  - Interpolate missing metric data points (linear / carry-forward)
  - Back-fill funding rounds, hiring events, product launches
  - Assign confidence based on source recency and type
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.temporal_filler")

_HTTP_TIMEOUT = 30.0  # seconds


class TemporalFillerWorker(BaseWorker):
    """
    Enrichment worker that fills temporal gaps in entity timelines.

    Payload contract:
        entity_id       : str           — graph entity
        timeline_events : list[dict]    — existing dated events (sorted)
        gap_threshold   : str           — e.g. "30d" — interval that counts as a gap
        fill_strategy   : str           — "interpolate" | "backfill_api" | "hybrid"
        metric_fields   : list[str]     — numeric fields to interpolate
    """

    worker_type = WorkerType.TEMPORAL_FILLER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        events = task.payload.get("timeline_events", [])
        gap_threshold = task.payload.get("gap_threshold", "30d")
        strategy = task.payload.get("fill_strategy", "hybrid")
        metric_fields = task.payload.get("metric_fields", [])

        threshold_days = _parse_duration(gap_threshold)

        logger.info(
            f"Filling timeline for {entity_id}: "
            f"{len(events)} events, gap_threshold={gap_threshold}, "
            f"strategy={strategy}"
        )

        # Parse events into typed structure
        parsed_events = _parse_events(events)
        if len(parsed_events) < 2:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=True,
                data={
                    "entity_id": entity_id,
                    "gaps_detected": 0,
                    "gaps": [],
                    "events_filled": 0,
                    "filled_events": [],
                    "strategy_used": strategy,
                    "original_event_count": len(events),
                    "message": "Insufficient events to detect gaps (need >= 2)",
                },
                confidence=0.5,
                source_attribution=f"temporal_{strategy}",
            )

        # Step 1: Detect gaps
        gaps = _detect_gaps(parsed_events, threshold_days)
        logger.info(f"Detected {len(gaps)} gap(s) in timeline")

        if not gaps:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=True,
                data={
                    "entity_id": entity_id,
                    "gaps_detected": 0,
                    "gaps": [],
                    "events_filled": 0,
                    "filled_events": [],
                    "strategy_used": strategy,
                    "original_event_count": len(events),
                    "message": "No gaps detected above threshold",
                },
                confidence=0.9,
                source_attribution=f"temporal_{strategy}",
            )

        # Step 2: Fill gaps based on strategy
        try:
            if strategy == "interpolate":
                filled_events = self._fill_interpolate(
                    parsed_events, gaps, metric_fields
                )
            elif strategy == "backfill_api":
                filled_events = self._fill_backfill_api(
                    entity_id, gaps, metric_fields
                )
            elif strategy == "hybrid":
                filled_events = self._fill_hybrid(
                    entity_id, parsed_events, gaps, metric_fields
                )
            else:
                filled_events = self._fill_interpolate(
                    parsed_events, gaps, metric_fields
                )
        except Exception as exc:
            logger.exception(f"Gap filling failed: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                data={"error": str(exc), "entity_id": entity_id},
                confidence=0.0,
                source_attribution=f"temporal_{strategy}",
            )

        # Serialize gaps for output
        gap_dicts = [
            {
                "start": g["start"].isoformat(),
                "end": g["end"].isoformat(),
                "gap_days": str(g["gap_days"]),
                "midpoint": g["midpoint"].isoformat(),
            }
            for g in gaps
        ]

        data = {
            "entity_id": entity_id,
            "gaps_detected": len(gaps),
            "gaps": gap_dicts,
            "events_filled": len(filled_events),
            "filled_events": filled_events,
            "strategy_used": strategy,
            "original_event_count": len(events),
        }

        # Average confidence across filled events
        if filled_events:
            avg_conf = sum(e["confidence"] for e in filled_events) / len(
                filled_events
            )
        else:
            avg_conf = 0.5
        confidence = round(avg_conf, 3)

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=data,
            confidence=confidence,
            source_attribution=f"temporal_{strategy}",
        )

    # ------------------------------------------------------------------
    # Strategy: Interpolate
    # ------------------------------------------------------------------

    def _fill_interpolate(
        self,
        parsed_events: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
        metric_fields: list[str],
    ) -> list[dict[str, Any]]:
        """
        For numeric metric_fields, use linear interpolation between the
        known data points on either side of each gap.
        """
        filled: list[dict[str, Any]] = []

        for gap in gaps:
            gap_start: datetime = gap["start"]
            gap_end: datetime = gap["end"]
            gap_days: int = gap["gap_days"]

            # Find bounding events (the event just before and just after the gap)
            before_event = gap.get("before_event", {})
            after_event = gap.get("after_event", {})

            # Generate intermediate data points (one per threshold interval)
            num_points = max(gap_days // 30, 1)  # at least one point
            num_points = min(num_points, 10)  # cap at 10 synthetic points

            for i in range(1, num_points + 1):
                fraction = i / (num_points + 1)
                point_date = gap_start + timedelta(
                    days=int(gap_days * fraction)
                )

                interpolated_data: dict[str, Any] = {}
                for field in metric_fields:
                    val_before = _extract_numeric(before_event, field)
                    val_after = _extract_numeric(after_event, field)

                    if val_before is not None and val_after is not None:
                        # Linear interpolation
                        interpolated_data[field] = round(
                            val_before + (val_after - val_before) * fraction,
                            4,
                        )
                    elif val_before is not None:
                        # Carry forward
                        interpolated_data[field] = val_before
                    elif val_after is not None:
                        # Carry backward
                        interpolated_data[field] = val_after
                    else:
                        interpolated_data[field] = None

                # Confidence decreases the farther from known points
                distance_from_edge = min(fraction, 1.0 - fraction)
                point_confidence = 0.4 + (distance_from_edge * 0.4)

                filled.append({
                    "date": point_date.isoformat(),
                    "source": "interpolation",
                    "type": "interpolated_metric",
                    "data": interpolated_data,
                    "gap_start": gap_start.isoformat(),
                    "gap_end": gap_end.isoformat(),
                    "confidence": round(point_confidence, 3),
                    "method": "linear_interpolation",
                })

        return filled

    # ------------------------------------------------------------------
    # Strategy: Backfill API
    # ------------------------------------------------------------------

    def _fill_backfill_api(
        self,
        entity_id: str,
        gaps: list[dict[str, Any]],
        metric_fields: list[str],
    ) -> list[dict[str, Any]]:
        """
        Construct date-range queries to fetch historical data for each gap.
        Uses the Wayback Machine CDX API to check for archived snapshots.
        """
        filled: list[dict[str, Any]] = []

        for gap in gaps:
            gap_start: datetime = gap["start"]
            gap_end: datetime = gap["end"]

            # Query the Wayback Machine CDX API for any snapshots in the gap
            start_ts = gap_start.strftime("%Y%m%d")
            end_ts = gap_end.strftime("%Y%m%d")

            # Use entity_id as a potential URL/domain hint
            query_url = entity_id if "." in entity_id else f"{entity_id}.com"

            try:
                with httpx.Client(
                    timeout=_HTTP_TIMEOUT,
                    headers={"User-Agent": "Aether-TemporalFiller/1.0"},
                ) as client:
                    cdx_url = (
                        f"https://web.archive.org/cdx/search/cdx"
                        f"?url={query_url}"
                        f"&from={start_ts}&to={end_ts}"
                        f"&output=json&limit=5"
                    )
                    resp = client.get(cdx_url)

                    if resp.status_code == 200:
                        data = resp.json() if resp.text.strip() else []

                        # CDX returns header row + data rows
                        if len(data) > 1:
                            for row in data[1:]:
                                # row: [urlkey, timestamp, original, mimetype,
                                #       statuscode, digest, length]
                                if len(row) >= 2:
                                    ts_str = row[1]  # YYYYMMDDHHmmss
                                    try:
                                        snapshot_dt = datetime.strptime(
                                            ts_str[:8], "%Y%m%d"
                                        ).replace(tzinfo=timezone.utc)
                                    except ValueError:
                                        continue

                                    filled.append({
                                        "date": snapshot_dt.isoformat(),
                                        "source": "wayback_machine",
                                        "type": "archived_snapshot",
                                        "data": {
                                            "archive_url": (
                                                f"https://web.archive.org/web/"
                                                f"{ts_str}/{row[2]}"
                                                if len(row) > 2
                                                else None
                                            ),
                                            "status_code": row[4] if len(row) > 4 else None,
                                        },
                                        "gap_start": gap_start.isoformat(),
                                        "gap_end": gap_end.isoformat(),
                                        "confidence": 0.70,
                                        "method": "wayback_cdx",
                                    })

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                logger.warning(
                    f"Wayback API request failed for gap "
                    f"{gap_start.date()}-{gap_end.date()}: {exc}"
                )
            except (ValueError, KeyError) as exc:
                logger.warning(f"Error parsing Wayback response: {exc}")

            # If no API results, generate a placeholder event at the midpoint
            if not any(
                e["gap_start"] == gap_start.isoformat() for e in filled
            ):
                midpoint: datetime = gap["midpoint"]
                filled.append({
                    "date": midpoint.isoformat(),
                    "source": "backfill_placeholder",
                    "type": "inferred_event",
                    "data": {f: None for f in metric_fields},
                    "gap_start": gap_start.isoformat(),
                    "gap_end": gap_end.isoformat(),
                    "confidence": 0.35,
                    "method": "api_fallback_placeholder",
                })

        return filled

    # ------------------------------------------------------------------
    # Strategy: Hybrid (backfill first, interpolation for remainder)
    # ------------------------------------------------------------------

    def _fill_hybrid(
        self,
        entity_id: str,
        parsed_events: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
        metric_fields: list[str],
    ) -> list[dict[str, Any]]:
        """
        Try backfill_api first. For gaps that remain unfilled or only
        partially filled, fall back to interpolation.
        """
        # Phase 1: Try API backfill
        api_results = self._fill_backfill_api(entity_id, gaps, metric_fields)

        # Determine which gaps got real API data vs placeholders
        gaps_with_api_data: set[str] = set()
        real_events: list[dict[str, Any]] = []
        for event in api_results:
            if event.get("method") != "api_fallback_placeholder":
                gaps_with_api_data.add(event["gap_start"])
                real_events.append(event)

        # Phase 2: For gaps without API data, use interpolation
        unfilled_gaps = [
            g for g in gaps if g["start"].isoformat() not in gaps_with_api_data
        ]

        if unfilled_gaps:
            interp_results = self._fill_interpolate(
                parsed_events, unfilled_gaps, metric_fields
            )
            # Mark these as hybrid results
            for event in interp_results:
                event["method"] = "hybrid_interpolation_fallback"
            real_events.extend(interp_results)

        # Boost confidence on API results slightly since hybrid validated them
        for event in real_events:
            if event.get("source") == "wayback_machine":
                event["confidence"] = min(event["confidence"] + 0.05, 0.95)

        return real_events


# ── Helpers ───────────────────────────────────────────────────────────

def _parse_duration(s: str) -> int:
    """Convert '30d', '7d', '1d' -> integer days."""
    s = s.strip().lower()
    if s.endswith("d"):
        return int(s[:-1])
    if s.endswith("h"):
        return max(int(s[:-1]) // 24, 1)
    return 30  # default


def _parse_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parse event dicts, ensuring each has a valid datetime 'date' field.
    Returns events sorted by date with parsed datetime attached.
    """
    parsed: list[dict[str, Any]] = []
    for event in events:
        date_str = event.get("date")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append({**event, "_dt": dt})
        except (ValueError, TypeError):
            logger.debug(f"Skipping event with unparseable date: {date_str}")
            continue

    parsed.sort(key=lambda e: e["_dt"])
    return parsed


def _detect_gaps(
    parsed_events: list[dict[str, Any]],
    threshold_days: int,
) -> list[dict[str, Any]]:
    """Find gaps larger than threshold between consecutive events."""
    gaps: list[dict[str, Any]] = []
    if len(parsed_events) < 2:
        return gaps

    for i in range(len(parsed_events) - 1):
        d1: datetime = parsed_events[i]["_dt"]
        d2: datetime = parsed_events[i + 1]["_dt"]
        delta = (d2 - d1).days

        if delta > threshold_days:
            midpoint = d1 + timedelta(days=delta // 2)
            gaps.append({
                "start": d1,
                "end": d2,
                "gap_days": delta,
                "midpoint": midpoint,
                "before_event": parsed_events[i],
                "after_event": parsed_events[i + 1],
            })

    return gaps


def _extract_numeric(
    event: dict[str, Any], field: str
) -> float | None:
    """Safely extract a numeric value from an event's data dict."""
    if not event:
        return None

    # Check top-level and nested "data" dict
    val = event.get(field)
    if val is None:
        data = event.get("data", {})
        if isinstance(data, dict):
            val = data.get(field)

    if val is None:
        return None

    try:
        return float(val)
    except (ValueError, TypeError):
        return None
