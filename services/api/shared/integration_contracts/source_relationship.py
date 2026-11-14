"""SourceRelationship: what kind of source produced evidence.

Descriptive provenance, never a permission. Use is decided by the governing
DataRightsGrant, consent, and the Effective Rights Resolver. The only runtime
effect of a relationship is ``relationship_consistent`` returning False, which
callers turn into a denial.
"""

from __future__ import annotations

from typing import Literal, Optional

SOURCE_RELATIONSHIPS: tuple[str, ...] = (
    "personal_account",
    "organization_system",
    "first_party_application",
    "partner_feed",
    "olympus_source",
    "public_reference",
    "internal_system",
    "unclassified",
)

SourceRelationship = Literal[
    "personal_account",
    "organization_system",
    "first_party_application",
    "partner_feed",
    "olympus_source",
    "public_reference",
    "internal_system",
    "unclassified",
]

UNCLASSIFIED = "unclassified"

TENANT_SELF_SERVICE_RELATIONSHIPS: frozenset[str] = frozenset(
    {"personal_account", "organization_system"}
)
OPERATOR_RELATIONSHIPS: frozenset[str] = frozenset(
    {"partner_feed", "olympus_source", "public_reference", "internal_system"}
)

RAW_DATA_OWNERS: tuple[str, ...] = ("subject", "tenant", "partner", "olympus_labs", "public")
RawDataOwner = Literal["subject", "tenant", "partner", "olympus_labs", "public"]

# Grant/connection scope for Olympus-owned and Olympus-licensed sources. Never a
# customer tenant; evidence under it never enters the tenant pipeline.
OLYMPUS_SOURCE_TENANT_ID = "olympus"

REQUIRED_RAW_DATA_OWNER: dict[str, str] = {
    "personal_account": "subject",
    "organization_system": "tenant",
    "first_party_application": "tenant",
    "partner_feed": "partner",
    "olympus_source": "olympus_labs",
    "public_reference": "public",
    "internal_system": "olympus_labs",
}

# ``tenant_import`` is the class live CSV import grants carry.
_TENANT_DATA_CLASSES = frozenset(
    {"tenant_byod_data", "tenant_import", "byok_gateway", "action_notifier", "dual_role"}
)

COMPATIBLE_RIGHTS_CLASSES: dict[str, frozenset[str]] = {
    "personal_account": _TENANT_DATA_CLASSES,
    "organization_system": _TENANT_DATA_CLASSES,
    "first_party_application": frozenset({"tenant_byod_data"}),
    "partner_feed": frozenset({"partner_feed"}),
    "olympus_source": frozenset({"olympus_provider"}),
    "public_reference": frozenset({"olympus_provider", "tenant_byod_data"}),
    "internal_system": frozenset({"olympus_provider"}),
}


def relationship_consistent(
    relationship: Optional[str], connector_class: Optional[str],
) -> bool:
    """Consistency guard between a grant's relationship and its rights-source class.

    False means deny. True has no effect: the grant and RightsDecision still decide.
    An unclassified (legacy) grant stays consistent only with ``tenant_byod_data``,
    the single class provider raw admission accepted before classification existed.
    """
    rel = relationship or UNCLASSIFIED
    cls = connector_class or ""
    if rel == UNCLASSIFIED:
        return cls == "tenant_byod_data"
    return cls in COMPATIBLE_RIGHTS_CLASSES.get(rel, frozenset())


__all__ = [
    "COMPATIBLE_RIGHTS_CLASSES",
    "OLYMPUS_SOURCE_TENANT_ID",
    "OPERATOR_RELATIONSHIPS",
    "RAW_DATA_OWNERS",
    "REQUIRED_RAW_DATA_OWNER",
    "RawDataOwner",
    "SOURCE_RELATIONSHIPS",
    "SourceRelationship",
    "TENANT_SELF_SERVICE_RELATIONSHIPS",
    "UNCLASSIFIED",
    "relationship_consistent",
]
