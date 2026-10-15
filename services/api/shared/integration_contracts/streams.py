"""Versioned declarations for streams within one provider capability.

A stream descriptor states what a plugin claims it can acquire and normalize.
It is manifest metadata, not proof that a provider API, webhook, or downstream
projection has been certified. The provider runtime validates each claim
against the manifest and the plugin's installed adapters at registration.

Existing v1 plugins have no declared streams. They retain their current
capability-level behavior until migrated; an empty stream list is not an
implicit claim that any particular source object is supported.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.privacy.classification import DataClassification


StreamAcquisitionMode = Literal["pull", "webhook", "report", "stream"]
STREAM_DESCRIPTOR_SCHEMA_VERSION = "1"

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class StreamDescriptor(BaseModel):
    """One independently addressable source-object stream.

    ``stream_id`` is stable within ``ProviderIdentity``. ``output_contract``
    names a declared manifest output; it is not a promise of graph projection.
    ``cursor_scheme`` describes a stream's durable cursor format, while the
    actual checkpoint and acquisition behavior belong to the runtime worker.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = STREAM_DESCRIPTOR_SCHEMA_VERSION
    stream_id: str
    object_kind: str
    domain_pack: str
    acquisition_modes: tuple[StreamAcquisitionMode, ...] = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    source_authority_class: str = Field(min_length=1)
    data_classification: DataClassification
    required_scopes: tuple[str, ...] = ()
    cursor_scheme: Optional[str] = None
    # Pull streams are opt-in unless explicitly enabled or activated by a
    # declared, non-secret connection config value.
    enabled_by_default: bool = False
    activation_config_field: Optional[str] = None
    activation_config_value: Optional[str] = None
    webhook_topics: tuple[str, ...] = ()
    initial_backfill: bool = False
    incremental: bool = False

    @field_validator("stream_id", "object_kind", "domain_pack")
    @classmethod
    def _stable_token(cls, value: str) -> str:
        if not _TOKEN_RE.fullmatch(value):
            raise ValueError("expected a stable lowercase token")
        return value

    @field_validator("output_contract", "source_authority_class")
    @classmethod
    def _nonblank_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("expected a non-empty reference")
        return value

    @model_validator(mode="after")
    def _complete_activation_condition(self) -> "StreamDescriptor":
        if (self.activation_config_field is None) != (self.activation_config_value is None):
            raise ValueError(
                "activation_config_field and activation_config_value must be declared together"
            )
        if self.activation_config_field is not None and not self.activation_config_field.strip():
            raise ValueError("activation_config_field must be non-empty")
        if self.activation_config_value is not None and not self.activation_config_value.strip():
            raise ValueError("activation_config_value must be non-empty")
        return self


__all__ = [
    "STREAM_DESCRIPTOR_SCHEMA_VERSION",
    "StreamAcquisitionMode",
    "StreamDescriptor",
]
