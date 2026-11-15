"""Detector output container."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import RawPattern


@dataclass
class DetectorOutput:
    detector: str
    patterns: list[RawPattern] = field(default_factory=list)
    #: Contributions to the tenant baseline (merged by the engine).
    baseline: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
