"""Typed dependency-read outcomes for Profile360 degradation handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Optional, TypeVar

T = TypeVar("T")
ReadStatus = Literal["available", "unavailable"]


@dataclass(frozen=True)
class DimensionReadResult(Generic[T]):
    """Separates a legitimate empty value from dependency unavailability."""

    label: str
    status: ReadStatus
    value: Optional[T] = None
    error_code: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.status == "available"

    @classmethod
    def success(cls, label: str, value: T) -> "DimensionReadResult[T]":
        return cls(label=label, status="available", value=value)

    @classmethod
    def unavailable(
        cls, label: str, error_code: str
    ) -> "DimensionReadResult[T]":
        return cls(
            label=label,
            status="unavailable",
            value=None,
            error_code=error_code,
        )

    def value_or(self, default: T) -> T:
        """Return the real value when available, otherwise an explicit default."""
        return self.value if self.available else default


__all__ = ["DimensionReadResult", "ReadStatus"]
