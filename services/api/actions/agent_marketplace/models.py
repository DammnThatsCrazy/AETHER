"""Provider-neutral contract for tenant-declared marketplace origins."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_REFERENCE_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")


class AgentMarketplaceOrigin(BaseModel):
    """Tenant declaration identifying a marketplace template source."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent.marketplace-origin.v1"] = (
        "agent.marketplace-origin.v1"
    )
    source_namespace: str = Field(min_length=1, max_length=64)
    listing_ref: str = Field(min_length=1, max_length=256)
    template_ref: str = Field(min_length=1, max_length=256)
    template_version: str = Field(min_length=1, max_length=128)
    listing_url: Optional[HttpUrl] = None
    category: Optional[str] = Field(default=None, max_length=128)
    catalog_capabilities: list[str] = Field(default_factory=list, max_length=64)
    # The registry, not the caller, owns the assertion class. This value makes
    # the provenance limitation explicit in stored records and graph evidence.
    assertion: Literal["tenant_declared"] = "tenant_declared"

    @field_validator("source_namespace")
    @classmethod
    def _validate_source_namespace(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _NAMESPACE_RE.fullmatch(normalized):
            raise ValueError("source_namespace must be a lowercase provider namespace")
        return normalized

    @field_validator("listing_ref", "template_ref", "template_version")
    @classmethod
    def _validate_references(cls, value: str) -> str:
        normalized = value.strip()
        if not _SAFE_REFERENCE_RE.fullmatch(normalized):
            raise ValueError(
                "source references must be non-empty and contain no control characters"
            )
        return normalized

    @field_validator("category")
    @classmethod
    def _normalize_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("category must not contain control characters")
        return normalized

    @field_validator("catalog_capabilities")
    @classmethod
    def _validate_catalog_capabilities(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if (
                not item
                or len(item) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in item)
            ):
                raise ValueError("catalog capability labels must be 1-128 safe characters")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def _reject_url_credentials_and_tracking(self) -> "AgentMarketplaceOrigin":
        url = self.listing_url
        if url is not None and (url.username or url.password or url.query or url.fragment):
            raise ValueError(
                "listing_url must not contain credentials, query parameters, or a fragment"
            )
        return self
