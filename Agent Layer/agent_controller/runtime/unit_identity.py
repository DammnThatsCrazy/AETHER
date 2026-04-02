"""
Aether Agent Layer — UNITS Runtime Integration
Bridges the UNITS identity registry with the controller hierarchy.
Pure work mode is the default; UNITS presentation is opt-in.
"""

from __future__ import annotations

from models.units import UnitClass, UnitIdentity, UnitRegistry, UnitStatus


def create_controller_unit(
    registry: UnitRegistry,
    controller_name: str,
    designation: str = "",
    scope: str = "agent_layer",
    capabilities: list[str] | None = None,
) -> UnitIdentity:
    """Register a controller as a UNIT."""
    unit = UnitIdentity(
        designation=designation or controller_name.upper(),
        name=controller_name,
        unit_class=UnitClass.CONTROLLER,
        unit_type="domain_controller",
        scope=scope,
        capabilities=capabilities or [],
        owner_controller=controller_name,
    )
    return registry.register(unit)


def create_team_unit(
    registry: UnitRegistry,
    team_name: str,
    owner_controller: str,
    designation: str = "",
    scope: str = "agent_layer",
    capabilities: list[str] | None = None,
) -> UnitIdentity:
    """Register a team as a UNIT."""
    unit = UnitIdentity(
        designation=designation or team_name.upper(),
        name=team_name,
        unit_class=UnitClass.TEAM,
        unit_type="execution_team",
        scope=scope,
        capabilities=capabilities or [],
        owner_controller=owner_controller,
    )
    return registry.register(unit)


def create_worker_unit(
    registry: UnitRegistry,
    worker_name: str,
    owner_controller: str,
    designation: str = "",
    capabilities: list[str] | None = None,
) -> UnitIdentity:
    """Optionally register a worker as a UNIT."""
    unit = UnitIdentity(
        designation=designation or worker_name.upper(),
        name=worker_name,
        unit_class=UnitClass.WORKER,
        unit_type="specialist_worker",
        scope="worker_pool",
        capabilities=capabilities or [],
        owner_controller=owner_controller,
    )
    return registry.register(unit)
