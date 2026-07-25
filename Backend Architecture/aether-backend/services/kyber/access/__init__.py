"""Kyber access plane — capabilities, disclosure, role templates, scopes.

Import order matters only in one direction: ``contracts`` → ``capabilities`` /
``disclosure`` / ``roles`` are leaf modules with no Kyber dependencies, and
``scopes`` / ``dependencies`` build on top of them. Nothing here imports the
identity, devices or sessions packages, so those three can be developed against
this module without circularity.
"""
from .capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_FLEET_DESTRUCTIVE,
    ACTION_CLASS_HIGH_IMPACT,
    ACTION_CLASS_READ,
    ACTION_CLASS_RECOMPUTE,
    ACTION_CLASS_RETRY,
    ALL_CAPABILITY_IDS,
    CAPABILITIES,
    COMMAND_CAPABILITY_IDS,
    SELF_CAPABILITY,
    TENANT_SCOPED_CAPABILITY_IDS,
    Capability,
    get_capability,
    require_capability,
)
from .disclosure import (
    DisclosureLevel,
    effective_disclosure,
    masks_tenant_identifiers,
    requires_step_up,
    requires_tenant_scope,
)
from .roles import (
    ALL_ROLE_TEMPLATE_IDS,
    DEVICE_APPROVER_TEMPLATE_IDS,
    ROLE_TEMPLATES,
    RoleTemplate,
    access_roles_for,
    capabilities_for,
    get_role_template,
    max_action_class_for,
    max_disclosure_for,
    require_role_template,
)

__all__ = [
    "ACTION_CLASS_ANNOTATE",
    "ACTION_CLASS_FLEET_DESTRUCTIVE",
    "ACTION_CLASS_HIGH_IMPACT",
    "ACTION_CLASS_READ",
    "ACTION_CLASS_RECOMPUTE",
    "ACTION_CLASS_RETRY",
    "ALL_CAPABILITY_IDS",
    "ALL_ROLE_TEMPLATE_IDS",
    "CAPABILITIES",
    "COMMAND_CAPABILITY_IDS",
    "DEVICE_APPROVER_TEMPLATE_IDS",
    "ROLE_TEMPLATES",
    "SELF_CAPABILITY",
    "TENANT_SCOPED_CAPABILITY_IDS",
    "Capability",
    "DisclosureLevel",
    "RoleTemplate",
    "access_roles_for",
    "capabilities_for",
    "effective_disclosure",
    "get_capability",
    "get_role_template",
    "masks_tenant_identifiers",
    "max_action_class_for",
    "max_disclosure_for",
    "require_capability",
    "require_role_template",
    "requires_step_up",
    "requires_tenant_scope",
]
