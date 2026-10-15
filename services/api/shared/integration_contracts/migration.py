"""Migration projections from a legacy connector to a native provider identity.

The Unified Integration Control Plane migrates connectors toward native
provider identities. A :class:`MigrationProjection` is one fully-mapped legacy
connector: which native identity it maps to, how legacy config and secret keys
map onto native fields, the target credential reference
(``provider:{tenant}:{identity}`` shape), and a confidence verdict.
:class:`ProjectionCandidate` is the lighter pre-projection snapshot — a legacy
connector with an optional native counterpart; ``native_identity=None`` means no
native counterpart has been built yet, and ``requires_manual_mapping`` flags
fields that need a human decision.

Both models are strict (``extra="forbid"``) so a misspelled or unplanned field
fails fast instead of silently drifting from the migration plan. Each model
carries an explicit ``schema_version`` so a consumer can detect a contract
change without guessing (schema versions are always explicit).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, StrictBool

# Version of the migration-projection contract. Bump only on a breaking shape
# change; consumers must reject a projection whose schema_version differs.
MIGRATION_PROJECTION_SCHEMA_VERSION = "1"


class MigrationProjection(BaseModel):
    """One mapped migration from a legacy connector to a native identity."""

    model_config = ConfigDict(extra="forbid")

    connector_type: str  # legacy connector type, e.g. "shopify"
    native_identity: str  # target native identity, e.g. "shopify.admin.orders_read"
    config_field_map: dict[str, str]  # legacy config key -> native credential/config field
    secret_field_map: dict[str, str]  # legacy secret key -> native credential field
    credential_ref_target: str  # target credential ref (provider:{tenant}:{identity} shape)
    confidence: Literal["high", "medium", "low"]
    notes: str = ""
    schema_version: str = MIGRATION_PROJECTION_SCHEMA_VERSION


class ProjectionCandidate(BaseModel):
    """A legacy connector with an optional native counterpart."""

    model_config = ConfigDict(extra="forbid")

    connector_type: str
    native_identity: Optional[str] = None  # None => no native counterpart built yet
    confidence: str = ""
    requires_manual_mapping: StrictBool = False
    schema_version: str = MIGRATION_PROJECTION_SCHEMA_VERSION


__all__ = [
    "MIGRATION_PROJECTION_SCHEMA_VERSION",
    "MigrationProjection",
    "ProjectionCandidate",
]
