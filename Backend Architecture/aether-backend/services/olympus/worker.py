"""Durable jobs-plane handler for Olympus generalized promotions."""

from __future__ import annotations

from services.jobs.handlers import HANDLER_REGISTRY, JobOutcome, register_handler
from services.olympus.gateway import olympus_generalized_gateway

JOB_TYPE = "rights.olympus_promotion"


async def process_olympus_promotion(payload: dict, ctx) -> JobOutcome:
    promotion_id = payload.get("promotion_id")
    if not promotion_id:
        return JobOutcome(status="failed", result={}, error="promotion_id is required")
    result = await olympus_generalized_gateway.process(promotion_id)
    status = "succeeded" if result.get("status") == "released" else "failed"
    return JobOutcome(
        status=status,
        result=result,
        error=None if status == "succeeded" else result.get("reason", "promotion blocked"),
    )


def register_olympus_promotion_handler() -> None:
    if JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(JOB_TYPE)(process_olympus_promotion)


__all__ = ["JOB_TYPE", "process_olympus_promotion", "register_olympus_promotion_handler"]
