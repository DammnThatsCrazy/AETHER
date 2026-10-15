"""Typed error hierarchy for the intelligence projection plane (P0.4).

Every plane failure raises a :class:`ProjectionError` subclass so a caller can
classify and translate failures without string-matching. Subclasses carry an
optional ``projection_id``, an optional ``version`` (the offending contract
version, e.g. for :class:`ContractVersionIncompatible`) and a diagnostic-only
``context`` dict (never surfaced as a safe message) alongside the human
``message``.
"""

from __future__ import annotations

from typing import Any, Optional


class ProjectionError(Exception):
    """Base error for the intelligence projection plane."""

    def __init__(
        self,
        message: str,
        *,
        projection_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        version: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.projection_id = projection_id
        self.context = dict(context) if context else {}
        self.version = version


class ProjectionNotFound(ProjectionError):
    """No provider/definition is registered for the requested projection id."""


class DuplicateProjection(ProjectionError):
    """A provider for an already-registered projection id was registered twice."""


class ContractVersionIncompatible(ProjectionError):
    """A provider's contract version is incompatible with the registry contract."""


class DependencyUnavailable(ProjectionError):
    """A hard dependency of the projection is unavailable at build time."""


class ProjectionNotImplemented(ProjectionError):
    """The projection is registered but no provider implements it yet."""


__all__ = [
    "ContractVersionIncompatible",
    "DependencyUnavailable",
    "DuplicateProjection",
    "ProjectionError",
    "ProjectionNotFound",
    "ProjectionNotImplemented",
]
