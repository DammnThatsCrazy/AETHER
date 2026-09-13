"""In-code metric definition registry.

A small, honest catalogue of the metrics the plane knows how to measure. Each
:class:`MetricDefinition` carries the unit, valid bounds, whether it represents
a probability, and the minimum sample size required before a real value may be
reported. Persistence, calculators, and validators all read from this single
source of metric truth.

This module is intentionally hand-authored. A separate generator owns
``generated_registry.py`` — do not merge the two.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

REGISTRY_VERSION: str = "1"


class MetricDefinition(BaseModel):
    """Definition of a single measurable metric."""

    name: str
    version: str = "1"
    unit: str
    description: str = ""
    lower: Optional[float] = None
    upper: Optional[float] = None
    allows_probability: bool = False
    min_sample: int = 1


_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        name="attributed_conversions",
        unit="count",
        description="Conversions credited under the active attribution model.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="campaign_cac",
        unit="usd",
        description="Customer acquisition cost for a campaign.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="campaign_ltv",
        unit="usd",
        description="Customer lifetime value attributed to a campaign.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="campaign_roas",
        unit="ratio",
        description="Return on ad spend for a campaign.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="campaign_spend",
        unit="usd",
        description="Media and allocated cost spent on a campaign.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="claim_retention_rate",
        unit="ratio",
        description="Share of source claims retained across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="citation_retention_rate",
        unit="ratio",
        description="Share of source citations retained across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="contradiction_rate",
        unit="ratio",
        description="Share of source claims contradicted across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="conversion_rate",
        unit="ratio",
        description="Share of journeys that reached a conversion.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=30,
    ),
    MetricDefinition(
        name="costs",
        unit="usd",
        description="Total costs incurred over the measurement window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="email_click_rate",
        unit="ratio",
        description="Share of delivered campaign messages with a qualified click.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=30,
    ),
    MetricDefinition(
        name="email_open_rate",
        unit="ratio",
        description="Share of delivered campaign messages with a qualified open.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=30,
    ),
    MetricDefinition(
        name="email_reply_rate",
        unit="ratio",
        description="Share of delivered campaign messages with a human reply.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=30,
    ),
    MetricDefinition(
        name="evidence_retention_rate",
        unit="ratio",
        description="Share of source evidence references retained across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="exposure",
        unit="usd",
        description="Observed economic exposure over the measurement window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="gross_value",
        unit="usd",
        description="Gross economic value observed over the window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="journey_completion_rate",
        unit="ratio",
        description="Share of started journeys that completed.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=20,
    ),
    MetricDefinition(
        name="ltv",
        unit="usd",
        description="Customer lifetime value over the measurement window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="machine_event_rate",
        unit="ratio",
        description="Share of campaign communication events classified as machine generated.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=30,
    ),
    MetricDefinition(
        name="margin",
        unit="ratio",
        description="Profit margin ratio over the measurement window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="net_value",
        unit="usd",
        description="Net economic value observed over the window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="omission_rate",
        unit="ratio",
        description="Share of source claims omitted across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="refunds",
        unit="usd",
        description="Refunds issued over the measurement window.",
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="revenue",
        unit="currency",
        description="Attributed revenue over the measurement window.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="semantic_drift",
        unit="ratio",
        description="Normalized semantic drift between source and derived information.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="touchpoints",
        unit="count",
        description="Distinct marketing touchpoints observed in the window.",
        lower=0.0,
        allows_probability=False,
        min_sample=1,
    ),
    MetricDefinition(
        name="unsupported_addition_rate",
        unit="ratio",
        description="Share of added claims lacking supporting citation across an information transformation chain.",
        lower=0.0,
        upper=1.0,
        allows_probability=False,
        min_sample=1,
    ),
)

# Keyed by metric name (all seeded definitions are version "1").
METRIC_REGISTRY: dict[str, MetricDefinition] = {d.name: d for d in _DEFINITIONS}


def get_definition(name: str, version: str = "1") -> Optional[MetricDefinition]:
    """Return the definition for ``name`` at ``version``, or ``None`` if unknown."""

    definition = METRIC_REGISTRY.get(name)
    if definition is None or definition.version != version:
        return None
    return definition


def list_definitions() -> list[dict]:
    """Return every registered definition as a plain dict."""

    return [d.model_dump() for d in METRIC_REGISTRY.values()]
