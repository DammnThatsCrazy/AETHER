"""Contracts for the tenant Command Center aggregator.

The Command Center is a **read-only** tenant surface: it composes a handful of
existing tenant-scoped reads into one envelope-per-section view. It owns no
state of its own — every section carries the underlying sub-service payload
verbatim, plus an honest :class:`SectionState` describing whether that read
produced live data, was empty, is not configured, timed out, or errored.

``SectionState`` mirrors the frontend/shared capability-state vocabulary so the
tenant UI can render each section without re-interpreting per-service shapes.
A section NEVER fabricates a forward value: a failed read degrades to
``unavailable``/``error`` with ``data=None`` rather than inventing a stand-in.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class SectionState(str, Enum):
    """Honest per-section state, aligned with the shared capability-state vocabulary.

    * ``live``            — the read returned real tenant data.
    * ``no_data``         — the read succeeded but the tenant has nothing yet.
    * ``not_configured``  — the source is off/unconfigured for this tenant.
    * ``unavailable``     — the read could not be completed (e.g. timed out).
    * ``error``           — the read raised unexpectedly.
    """

    live = "live"
    no_data = "no_data"
    not_configured = "not_configured"
    unavailable = "unavailable"
    error = "error"


class SectionEnvelope(BaseModel):
    """One composed Command Center section.

    ``data`` is the raw sub-service payload (a dict or list) exactly as the
    underlying tenant read returned it — nothing tenant-visible is added or
    redacted — or ``None`` when ``state`` is not ``live``/``no_data``.
    """

    key: str
    state: SectionState
    data: Optional[Union[dict[str, Any], list[Any]]] = None
    source: str
    generated_at: str


class CommandCenterView(BaseModel):
    """The full tenant Command Center view: nine composed sections."""

    tenant_id: str
    generated_at: str
    sections: dict[str, SectionEnvelope] = Field(default_factory=dict)
