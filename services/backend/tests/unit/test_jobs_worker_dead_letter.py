"""Dead-letter notification drops must be loud.

`_notify_dead_letter` is best-effort by design — it must never crash the
worker — but best-effort is not the same as silent: a dropped dead-letter
notification is an operator alert that never arrived. Every drop is logged at
error level with the job id and counted via the worker's metrics facility.
"""

from __future__ import annotations

import builtins
from unittest.mock import AsyncMock, patch

import pytest

from services.jobs import worker as jobs_worker

_JOB = {
    "id": "job-dl-1",
    "tenant_id": "t1",
    "job_type": "export",
    "attempts": 3,
    "error": "handler exploded",
    "correlation_id": "corr-1",
}


@pytest.mark.asyncio
async def test_delivery_failure_logs_error_with_job_id_and_counts_drop():
    with patch(
        "services.notification_intelligence.inbox.create_inbox_notification",
        AsyncMock(side_effect=RuntimeError("inbox down")),
    ), patch.object(jobs_worker, "logger") as mock_logger, patch.object(
        jobs_worker.metrics, "increment"
    ) as mock_increment:
        await jobs_worker._notify_dead_letter(_JOB)  # must not raise

    assert mock_logger.error.called, "a dropped notification must be logged at error level"
    logged = mock_logger.error.call_args.args[0]
    assert "job-dl-1" in logged
    assert mock_logger.error.call_args.kwargs.get("exc_info") is True
    mock_increment.assert_called_once_with(
        "jobs_dead_letter_notify_dropped", labels={"reason": "delivery_failed"}
    )


@pytest.mark.asyncio
async def test_missing_inbox_module_logs_error_with_job_id_and_counts_drop():
    real_import = builtins.__import__

    def _no_inbox(name, *args, **kwargs):
        if name.startswith("services.notification_intelligence"):
            raise ImportError("No module named 'services.notification_intelligence'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=_no_inbox), patch.object(
        jobs_worker, "logger"
    ) as mock_logger, patch.object(jobs_worker.metrics, "increment") as mock_increment:
        await jobs_worker._notify_dead_letter(_JOB)  # must not raise

    assert mock_logger.error.called
    assert "job-dl-1" in mock_logger.error.call_args.args[0]
    mock_increment.assert_called_once_with(
        "jobs_dead_letter_notify_dropped", labels={"reason": "inbox_unavailable"}
    )


@pytest.mark.asyncio
async def test_successful_delivery_does_not_count_a_drop():
    with patch(
        "services.notification_intelligence.inbox.create_inbox_notification",
        AsyncMock(return_value={"id": "n1"}),
    ) as mock_create, patch.object(jobs_worker.metrics, "increment") as mock_increment:
        await jobs_worker._notify_dead_letter(_JOB)

    assert mock_create.await_count == 1
    mock_increment.assert_not_called()
