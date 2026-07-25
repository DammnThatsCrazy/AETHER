"""Kyber role templates.

A role template is the unit a founder assigns. It bundles three things that are
otherwise easy to drift apart:

  * the capability set the role may exercise,
  * the disclosure ceiling it may ever reach, and
  * its session, idle and step-up lifetimes.

Each template also binds to one or more existing
:data:`services.security.contracts.AccessRole` values, so the actual allow/deny
is still evaluated by ``AccessControlService`` against the governance grant
model rather than by a second RBAC implementation living here.

Lifetimes live on the backend on purpose. The frontend never decides how long a
session lasts; it reads what the backend granted. Every duration below is a
default that a deployment may override through configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from services.security.contracts import AccessRole

from .capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_FLEET_DESTRUCTIVE,
    ACTION_CLASS_HIGH_IMPACT,
    ACTION_CLASS_READ,
    ACTION_CLASS_RECOMPUTE,
    SELF_CAPABILITY,
)
from .disclosure import DisclosureLevel

RoleTemplateId = Literal[
    "founder_operator",
    "emergency_root",
    "cto_engineering_command",
    "operations_command",
    "founding_engineer",
    "head_of_product",
    "product_manager",
    "designer",
    "security_auditor",
    "observer",
]

_D = DisclosureLevel


@dataclass(frozen=True)
class RoleTemplate:
    """One assignable Kyber role."""

    template_id: RoleTemplateId
    display_name: str
    access_roles: tuple[AccessRole, ...]
    capabilities: frozenset[str]
    max_disclosure: DisclosureLevel
    max_action_class: int
    #: Trusted-device registration lifetime, in days. Not a session.
    device_registration_days: int
    #: Operator authority session: hard ceiling and inactivity window.
    session_absolute_minutes: int
    session_idle_minutes: int
    #: Step-up grant lifetime, in minutes.
    step_up_minutes: int
    #: Presence-session lifetime, in minutes. A presence session opens Kyber and
    #: shows low-risk aggregate health; it grants no tenant detail, evidence,
    #: command, export or workforce authority.
    presence_minutes: int = 7 * 24 * 60
    #: Environments this template may reach at all. An empty tuple means every
    #: configured environment.
    allowed_environments: tuple[str, ...] = ()
    #: True when the template may approve another operator's device.
    may_approve_devices: bool = False
    description: str = ""
    #: Capabilities every template holds implicitly (self-inspection only).
    implicit_capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset({SELF_CAPABILITY})
    )

    def grants(self, capability_id: str) -> bool:
        return (
            capability_id in self.capabilities
            or capability_id in self.implicit_capabilities
        )


_READ_PLATFORM = {
    "kyber.platform.health.read",
    "kyber.platform.release.read",
    "kyber.graph.platform.read",
}
_READ_FLEET = _READ_PLATFORM | {
    "kyber.graph.fleet.read",
    "kyber.graph.cohort.read",
    "kyber.incident.read",
    "kyber.policy.read",
}
_READ_TENANT = _READ_FLEET | {
    "kyber.tenant.mirror.read_masked",
    "kyber.tenant.mirror.read",
    "kyber.graph.tenant.read",
}
_READ_EVIDENCE = _READ_TENANT | {
    "kyber.graph.evidence.read",
    "kyber.audit.read",
}
_BOUNDED_COMMANDS = {
    "kyber.command.retry",
    "kyber.command.requeue",
    "kyber.command.replay",
    "kyber.command.recompute",
    "kyber.command.rebuild",
}
_HIGH_IMPACT_COMMANDS = {
    "kyber.command.pause",
    "kyber.command.rollback",
}
_ALL_COMMANDS = _BOUNDED_COMMANDS | _HIGH_IMPACT_COMMANDS | {"kyber.command.kill_switch"}
_INCIDENT_WRITE = {"kyber.incident.manage", "kyber.incident.close"}
_WORKFORCE_ADMIN = {
    "kyber.device.approve",
    "kyber.workforce.manage",
    "kyber.role.manage",
}


ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    t.template_id: t
    for t in (
        RoleTemplate(
            template_id="founder_operator",
            display_name="Founder Operator",
            access_roles=("olympus_founder", "olympus_admin"),
            capabilities=frozenset(
                _READ_EVIDENCE
                | _ALL_COMMANDS
                | _INCIDENT_WRITE
                | _WORKFORCE_ADMIN
                | {"kyber.platform.cost.read", "kyber.tenant.raw.read", "kyber.export.create"}
            ),
            max_disclosure=_D.D5_RAW_EVIDENCE,
            max_action_class=ACTION_CLASS_FLEET_DESTRUCTIVE,
            device_registration_days=90,
            session_absolute_minutes=24 * 60,
            session_idle_minutes=4 * 60,
            step_up_minutes=15,
            may_approve_devices=True,
            description="Full operating authority. The one role that may approve "
                        "devices and grant roles.",
        ),
        RoleTemplate(
            template_id="emergency_root",
            display_name="Emergency Root",
            access_roles=("olympus_admin",),
            capabilities=frozenset(
                _READ_EVIDENCE
                | _ALL_COMMANDS
                | _INCIDENT_WRITE
                | {"kyber.tenant.raw.read"}
            ),
            max_disclosure=_D.D5_RAW_EVIDENCE,
            max_action_class=ACTION_CLASS_FLEET_DESTRUCTIVE,
            device_registration_days=30,
            # Emergency access is never a working session: 15 minutes, no idle
            # grace beyond it, and it cannot be left logged in.
            session_absolute_minutes=15,
            session_idle_minutes=15,
            step_up_minutes=15,
            presence_minutes=0,
            may_approve_devices=False,
            description="Break-glass identity. Not for routine operation; every "
                        "use raises a critical alert and expires automatically.",
        ),
        RoleTemplate(
            template_id="cto_engineering_command",
            display_name="CTO / Engineering Command",
            access_roles=("olympus_engineering", "olympus_operator"),
            capabilities=frozenset(
                _READ_EVIDENCE
                | _BOUNDED_COMMANDS
                | _HIGH_IMPACT_COMMANDS
                | _INCIDENT_WRITE
                | {"kyber.platform.cost.read", "kyber.export.create"}
            ),
            max_disclosure=_D.D4_EVENT_EVIDENCE,
            max_action_class=ACTION_CLASS_HIGH_IMPACT,
            device_registration_days=60,
            session_absolute_minutes=16 * 60,
            session_idle_minutes=2 * 60,
            step_up_minutes=10,
            description="Engineering command authority short of fleet-destructive "
                        "actions.",
        ),
        RoleTemplate(
            template_id="operations_command",
            display_name="Operations Command",
            access_roles=("olympus_operator",),
            capabilities=frozenset(
                _READ_EVIDENCE
                | _BOUNDED_COMMANDS
                | _INCIDENT_WRITE
                | {"kyber.platform.cost.read", "kyber.export.create"}
            ),
            max_disclosure=_D.D4_EVENT_EVIDENCE,
            max_action_class=ACTION_CLASS_RECOMPUTE,
            device_registration_days=60,
            session_absolute_minutes=16 * 60,
            session_idle_minutes=2 * 60,
            step_up_minutes=10,
            description="Day-to-day operations: incidents, bounded remediation, "
                        "tenant support.",
        ),
        RoleTemplate(
            template_id="founding_engineer",
            display_name="Founding Engineer",
            access_roles=("olympus_engineering",),
            capabilities=frozenset(
                _READ_EVIDENCE | _BOUNDED_COMMANDS | _INCIDENT_WRITE
            ),
            max_disclosure=_D.D4_EVENT_EVIDENCE,
            # Bounded commands top out at recompute/replay: reversible work over
            # a bounded window. Pause, rollback and kill-switch stay out of reach.
            max_action_class=ACTION_CLASS_RECOMPUTE,
            device_registration_days=60,
            session_absolute_minutes=12 * 60,
            session_idle_minutes=2 * 60,
            step_up_minutes=10,
            description="Diagnose and remediate within bounded, reversible actions.",
        ),
        RoleTemplate(
            template_id="head_of_product",
            display_name="Head of Product",
            access_roles=("olympus_product",),
            capabilities=frozenset(
                _READ_TENANT | {"kyber.platform.cost.read", "kyber.incident.read"}
            ),
            max_disclosure=_D.D3_TENANT_VISIBLE,
            max_action_class=ACTION_CLASS_READ,
            device_registration_days=30,
            session_absolute_minutes=12 * 60,
            session_idle_minutes=60,
            step_up_minutes=10,
            description="Tenant-visible product state and fleet adoption. No "
                        "command authority.",
        ),
        RoleTemplate(
            template_id="product_manager",
            display_name="Product Manager",
            access_roles=("olympus_product",),
            capabilities=frozenset(_READ_TENANT),
            max_disclosure=_D.D3_TENANT_VISIBLE,
            max_action_class=ACTION_CLASS_READ,
            device_registration_days=30,
            session_absolute_minutes=12 * 60,
            session_idle_minutes=60,
            step_up_minutes=10,
            description="Tenant-visible product state. No command authority.",
        ),
        RoleTemplate(
            template_id="designer",
            display_name="Designer",
            access_roles=("olympus_observer",),
            capabilities=frozenset(_READ_FLEET),
            max_disclosure=_D.D1_FLEET_AGGREGATE,
            max_action_class=ACTION_CLASS_READ,
            device_registration_days=30,
            session_absolute_minutes=12 * 60,
            session_idle_minutes=60,
            step_up_minutes=10,
            # Designers build against staging and synthetic fixtures; production
            # raw tenant data is not part of the job.
            allowed_environments=("local", "staging"),
            description="Interface work against staging and synthetic data, plus "
                        "aggregate production health.",
        ),
        RoleTemplate(
            template_id="security_auditor",
            display_name="Security / Compliance Auditor",
            access_roles=("olympus_security", "auditor"),
            capabilities=frozenset(
                _READ_EVIDENCE | {"kyber.export.create", "kyber.policy.read"}
            ),
            max_disclosure=_D.D4_EVENT_EVIDENCE,
            # Export is class 1; the auditor role stops there and holds no
            # capability that changes platform state.
            max_action_class=ACTION_CLASS_ANNOTATE,
            device_registration_days=30,
            session_absolute_minutes=8 * 60,
            session_idle_minutes=60,
            step_up_minutes=10,
            description="Audit, policy and evidence review. Read and export only.",
        ),
        RoleTemplate(
            template_id="observer",
            display_name="Observer",
            access_roles=("olympus_observer",),
            capabilities=frozenset(_READ_FLEET),
            max_disclosure=_D.D1_FLEET_AGGREGATE,
            max_action_class=ACTION_CLASS_READ,
            device_registration_days=30,
            session_absolute_minutes=8 * 60,
            session_idle_minutes=60,
            step_up_minutes=10,
            description="Fleet aggregates only. No tenant detail, no commands.",
        ),
    )
}

ALL_ROLE_TEMPLATE_IDS: frozenset[str] = frozenset(ROLE_TEMPLATES)

#: Templates permitted to approve another operator's device registration.
DEVICE_APPROVER_TEMPLATE_IDS: frozenset[str] = frozenset(
    tid for tid, t in ROLE_TEMPLATES.items() if t.may_approve_devices
)


def get_role_template(template_id: str) -> Optional[RoleTemplate]:
    return ROLE_TEMPLATES.get(template_id)


def require_role_template(template_id: str) -> RoleTemplate:
    template = ROLE_TEMPLATES.get(template_id)
    if template is None:
        raise KeyError(f"unknown Kyber role template: {template_id}")
    return template


def access_roles_for(template_ids: "list[str] | tuple[str, ...]") -> list[AccessRole]:
    """Union of governance AccessRoles across the given templates."""
    roles: list[AccessRole] = []
    for tid in template_ids:
        template = ROLE_TEMPLATES.get(tid)
        if template is None:
            continue
        for role in template.access_roles:
            if role not in roles:
                roles.append(role)
    return roles


def capabilities_for(template_ids: "list[str] | tuple[str, ...]") -> frozenset[str]:
    """Union of capability ids across the given templates."""
    out: set[str] = set()
    for tid in template_ids:
        template = ROLE_TEMPLATES.get(tid)
        if template is None:
            continue
        out |= template.capabilities
        out |= template.implicit_capabilities
    return frozenset(out)


def max_disclosure_for(template_ids: "list[str] | tuple[str, ...]") -> DisclosureLevel:
    """Highest disclosure ceiling across the given templates.

    With no recognised template the answer is the least-revealing level, so an
    operator whose bindings all reference unknown templates sees topology only
    rather than everything.
    """
    levels = [
        ROLE_TEMPLATES[t].max_disclosure for t in template_ids if t in ROLE_TEMPLATES
    ]
    return max(levels) if levels else DisclosureLevel.D0_PLATFORM_TOPOLOGY


def max_action_class_for(template_ids: "list[str] | tuple[str, ...]") -> int:
    classes = [
        ROLE_TEMPLATES[t].max_action_class for t in template_ids if t in ROLE_TEMPLATES
    ]
    return max(classes) if classes else ACTION_CLASS_READ
