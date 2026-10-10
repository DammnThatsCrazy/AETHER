"""Temporal preference contracts (viewer display + tenant business defaults)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from shared.temporal.zones import is_valid_iana_zone


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_zone(value: Optional[str]) -> Optional[str]:
    if value is not None and not is_valid_iana_zone(value):
        raise ValueError(f"not a canonical IANA timezone id: {value!r}")
    return value


class ViewerTemporalPreferences(_Model):
    """Per-principal display preferences. Resolution order at render time:
    manual preference → current device zone (automatic) → tenant display
    default → UTC. Display only — never a business authority."""

    mode: Literal["automatic", "manual"] = "automatic"
    manual_time_zone: Optional[str] = None
    locale: Optional[str] = None
    hour_cycle: Optional[Literal["h12", "h23"]] = None
    week_start: Optional[int] = None  # 0=Sunday … 6=Saturday
    date_format_preference: Optional[str] = None

    _zone = field_validator("manual_time_zone")(_require_zone)

    @field_validator("week_start")
    @classmethod
    def _week_start_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 6):
            raise ValueError("week_start must be 0..6")
        return v

    @field_validator("manual_time_zone")
    @classmethod
    def _manual_requires_zone(cls, v: Optional[str], info) -> Optional[str]:
        return v


class TenantTemporalDefaults(_Model):
    """Tenant business-calendar identity. Owns tenant-business calendar
    semantics; does not override an interactive viewer's display choice."""

    business_time_zone: Optional[str] = None
    default_display_time_zone: Optional[str] = None
    week_start: Optional[int] = None
    fiscal_year_start_month: Optional[int] = None
    billing_time_zone: Optional[str] = None
    retention_policy_time_zone: Optional[str] = None
    default_dst_gap_policy: Literal["shift_forward", "reject"] = "shift_forward"
    default_dst_overlap_policy: Literal[
        "earlier_offset", "later_offset", "reject"
    ] = "earlier_offset"
    version: int = 1

    _zones = field_validator(
        "business_time_zone",
        "default_display_time_zone",
        "billing_time_zone",
        "retention_policy_time_zone",
    )(_require_zone)

    @field_validator("fiscal_year_start_month")
    @classmethod
    def _month_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 12):
            raise ValueError("fiscal_year_start_month must be 1..12")
        return v

    @field_validator("week_start")
    @classmethod
    def _week_start_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 6):
            raise ValueError("week_start must be 0..6")
        return v


__all__ = ["ViewerTemporalPreferences", "TenantTemporalDefaults"]
