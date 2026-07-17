"""Materiality scoring for comparison findings.

Composes the 14 registered materiality components
(``MATERIALITY_COMPONENTS``) into a 0..1 score and maps it onto the 5
registry severities. Hard severity overrides are floors: an override can
RAISE the severity of a finding but can never lower it (monotonicity is
structural — the final severity is the max over the banded severity and all
triggered floors).

Missing components are never silently defaulted: they carry zero weight and
are listed on the result so consumers can see what the score was NOT based on.
"""

from __future__ import annotations

from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.intelligence.comparison.generated_vocabulary import (
    COMPARISON_SEVERITIES,
    MATERIALITY_COMPONENTS,
)

# Severity ladder index — COMPARISON_SEVERITIES is ordered least → most severe.
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(COMPARISON_SEVERITIES)}

# Score → severity bands (upper bounds, last band catches the rest).
_SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (0.2, "info"),
    (0.4, "low"),
    (0.6, "medium"),
    (0.8, "high"),
    (1.0 + 1e-9, "critical"),
)

# Default component weights (uniform). Callers may pass their own weights for
# any subset of registered components.
DEFAULT_WEIGHTS: dict[str, float] = {name: 1.0 for name in MATERIALITY_COMPONENTS}


class HardSeverityOverride(BaseModel):
    """A raise-only severity floor triggered by one component."""

    model_config = ConfigDict(extra="forbid")

    component: str
    threshold: float = Field(ge=0.0, le=1.0)
    min_severity: str

    def model_post_init(self, __context) -> None:  # noqa: D105
        if self.component not in MATERIALITY_COMPONENTS:
            raise ValueError(f"Unknown materiality component: {self.component!r}")
        if self.min_severity not in COMPARISON_SEVERITIES:
            raise ValueError(f"Unknown severity: {self.min_severity!r}")


# Default hard floors: near-certain risk or policy impact can never sit below
# "high" regardless of how the blended score averages out.
DEFAULT_HARD_OVERRIDES: tuple[HardSeverityOverride, ...] = (
    HardSeverityOverride(component="risk_impact", threshold=0.9, min_severity="high"),
    HardSeverityOverride(component="policy_impact", threshold=0.9, min_severity="high"),
)


class MaterialityResult(BaseModel):
    """Score, severity, and full provenance of how they were produced."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    severity: str
    banded_severity: str  # severity implied by score alone, before overrides
    components: dict[str, float] = Field(default_factory=dict)
    missing_components: list[str] = Field(default_factory=list)
    overrides_applied: list[str] = Field(default_factory=list)


def severity_for_score(score: float) -> str:
    for upper, severity in _SEVERITY_BANDS:
        if score < upper:
            return severity
    return COMPARISON_SEVERITIES[-1]


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


def score_materiality(
    components: Mapping[str, float],
    *,
    weights: Optional[Mapping[str, float]] = None,
    hard_overrides: tuple[HardSeverityOverride, ...] = DEFAULT_HARD_OVERRIDES,
) -> MaterialityResult:
    """Blend provided component scores and apply raise-only severity floors.

    ``components`` maps registered component names to 0..1 scores. Unknown
    names raise; out-of-range values raise. Components NOT provided are
    reported in ``missing_components`` and contribute nothing.
    """
    clean: dict[str, float] = {}
    for name, value in components.items():
        if name not in MATERIALITY_COMPONENTS:
            raise ValueError(f"Unknown materiality component: {name!r}")
        v = float(value)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Component {name!r} out of range [0, 1]: {v}")
        clean[name] = v

    if not clean:
        raise ValueError("At least one materiality component is required")

    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for name, weight in weights.items():
            if name not in MATERIALITY_COMPONENTS:
                raise ValueError(f"Unknown materiality component in weights: {name!r}")
            if float(weight) < 0:
                raise ValueError(f"Negative weight for {name!r}")
            w[name] = float(weight)

    total_weight = sum(w[name] for name in clean)
    if total_weight <= 0:
        raise ValueError("All provided components have zero weight")
    score = sum(clean[name] * w[name] for name in clean) / total_weight
    score = min(max(score, 0.0), 1.0)

    banded = severity_for_score(score)
    severity = banded
    applied: list[str] = []
    for override in hard_overrides:
        value = clean.get(override.component)
        if value is None or value < override.threshold:
            continue
        raised = _max_severity(severity, override.min_severity)
        if raised != severity:
            applied.append(
                f"{override.component}>={override.threshold}->{override.min_severity}"
            )
        # max() is the invariant: a floor can raise, never lower.
        severity = raised

    return MaterialityResult(
        score=round(score, 6),
        severity=severity,
        banded_severity=banded,
        components=clean,
        missing_components=[n for n in MATERIALITY_COMPONENTS if n not in clean],
        overrides_applied=applied,
    )


__all__ = [
    "DEFAULT_HARD_OVERRIDES",
    "DEFAULT_WEIGHTS",
    "HardSeverityOverride",
    "MaterialityResult",
    "score_materiality",
    "severity_for_score",
]
