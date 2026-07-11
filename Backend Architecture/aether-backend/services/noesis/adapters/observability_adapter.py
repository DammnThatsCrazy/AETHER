"""Noesis Observability Intelligence adapter — read-only imports / jobs / measurement.

Answers `import_status_lookup` (tenant import sessions + lifecycle status),
`job_status_lookup` (background jobs + status distribution), and
`measurement_integrity_lookup` (measurement results + value_state
distribution against the metric registry).

Observation-only. Every method touches ONLY read/list paths on its
repository — it never creates, commits, cancels, enqueues, retries, runs,
recomputes, restates, or supersedes anything. Measurement semantics are
reported verbatim: a ``None`` value is never coerced to ``0`` and a metric
is never relabelled (attributed credit is not causal; an index is not a
probability).

Each method returns the standard adapter envelope::

    {"answer": str, "results": list, "sources": list, "sufficient": bool}

A read that raises returns ``sufficient=False`` with an honest answer rather
than crashing the conversation surface.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.observability")


def _stringify(row: dict[str, Any]) -> dict[str, Any]:
    """Decimal-safe shallow copy — leaves ``None`` and other values untouched."""
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


class ObservabilityNoesisAdapter:
    """Deterministic, read-only lookups over the import, jobs, and
    measurement-integrity subsystems. ``target_id`` addresses a single
    import session / job / measurement result when supplied."""

    async def import_status(
        self,
        tenant_id: str,
        target_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from repositories.imports_repo import get_imports_repository
        from shared.common.common import NotFoundError

        repo = get_imports_repository()

        if target_id:
            try:
                session = await repo.get_session(tenant_id, target_id)
            except NotFoundError:
                return {
                    "answer": f"No import session found for '{target_id}' in this tenant.",
                    "results": [],
                    "sources": ["imports_repository"],
                    "sufficient": False,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("Noesis import_status read failed: %s", exc)
                return {
                    "answer": "Import status is temporarily unavailable.",
                    "results": [],
                    "sources": ["imports_repository"],
                    "sufficient": False,
                }
            return {
                "answer": (
                    f"Import session {target_id} is '{session.get('status')}' "
                    f"({session.get('file_count', 0)} file(s), "
                    f"{session.get('row_count')} row(s))."
                ),
                "results": [_stringify(session)],
                "sources": ["imports_repository"],
                "sufficient": True,
            }

        try:
            sessions = await repo.list_sessions(tenant_id, limit=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis import_status list failed: %s", exc)
            return {
                "answer": "Import status is temporarily unavailable.",
                "results": [],
                "sources": ["imports_repository"],
                "sufficient": False,
            }

        by_status = Counter(str(s.get("status")) for s in sessions)
        summary = ", ".join(f"{count} {status}" for status, count in by_status.most_common())
        return {
            "answer": (
                f"{len(sessions)} import session(s) observed"
                + (f" ({summary})" if summary else "")
                + "."
            ),
            "results": [_stringify(s) for s in sessions],
            "sources": ["imports_repository"],
            "sufficient": bool(sessions),
        }

    async def job_status(
        self,
        tenant_id: str,
        target_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from repositories.jobs_repo import get_jobs_repository

        repo = get_jobs_repository()

        if target_id:
            try:
                job = await repo.get_job(tenant_id, target_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Noesis job_status read failed: %s", exc)
                return {
                    "answer": "Job status is temporarily unavailable.",
                    "results": [],
                    "sources": ["jobs_repository"],
                    "sufficient": False,
                }
            if job is None:
                return {
                    "answer": f"No background job found for '{target_id}' in this tenant.",
                    "results": [],
                    "sources": ["jobs_repository"],
                    "sufficient": False,
                }
            return {
                "answer": (
                    f"Job {target_id} is '{job.get('status')}' "
                    f"(type {job.get('job_type')}, {job.get('attempts')} attempt(s))."
                ),
                "results": [_stringify(job)],
                "sources": ["jobs_repository"],
                "sufficient": True,
            }

        try:
            jobs = await repo.list_jobs(tenant_id, limit=20)
            counts = await repo.counts_by_status(tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis job_status list failed: %s", exc)
            return {
                "answer": "Job status is temporarily unavailable.",
                "results": [],
                "sources": ["jobs_repository"],
                "sufficient": False,
            }

        summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        return {
            "answer": (
                f"{len(jobs)} recent background job(s) observed"
                + (f"; status distribution: {summary}" if summary else "")
                + "."
            ),
            "results": [_stringify(j) for j in jobs],
            "sources": ["jobs_repository"],
            "sufficient": bool(jobs),
        }

    async def measurement_integrity(
        self,
        tenant_id: str,
        target_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from repositories.measurement_results_repo import (
            get_measurement_results_repository,
        )
        from shared.measurement import list_definitions

        repo = get_measurement_results_repository()
        # Metric registry is read verbatim — never mutated or relabelled.
        definitions = list_definitions()

        try:
            if target_id:
                result = await repo.get(tenant_id, target_id)
                if result is None:
                    return {
                        "answer": (
                            f"No measurement result found for '{target_id}' in this tenant."
                        ),
                        "results": [],
                        "sources": ["measurement_results_store", "metric_registry"],
                        "sufficient": False,
                    }
                results = [result]
            else:
                results = await repo.list_for_tenant(tenant_id, limit=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis measurement_integrity read failed: %s", exc)
            return {
                "answer": "Measurement integrity is temporarily unavailable.",
                "results": [],
                "sources": ["measurement_results_store", "metric_registry"],
                "sufficient": False,
            }

        # value_state distribution — reported exactly as stored. A missing
        # value stays absent (None); it is NEVER coerced to 0, and no state
        # is relabelled.
        by_state = Counter(str(r.get("value_state")) for r in results)
        with_value = sum(1 for r in results if r.get("value") is not None)
        absent = sum(1 for r in results if r.get("value") is None)
        state_summary = ", ".join(
            f"{count} {state}" for state, count in by_state.most_common()
        )

        parts = [f"{len(results)} measurement result(s) observed"]
        if state_summary:
            parts.append(f"value_state distribution: {state_summary}")
        parts.append(
            f"{with_value} carry a value, {absent} honestly absent (missing != zero)"
        )
        answer = (
            "Measurement integrity: "
            + "; ".join(parts)
            + f". {len(definitions)} metric definition(s) registered."
        )
        return {
            "answer": answer,
            "results": [_stringify(r) for r in results],
            "sources": ["measurement_results_store", "metric_registry"],
            "sufficient": bool(results),
        }
