"""
Aether Agent Layer — Atoms Runtime Integration
Bridges the Atoms identity registry with the controller hierarchy.
Pure work mode is the default; Atoms presentation is opt-in.
"""

from __future__ import annotations

from models.atoms import AtomClass, AtomIdentity, AtomRegistry


def create_controller_atom(
    registry: AtomRegistry,
    controller_name: str,
    designation: str = "",
    scope: str = "agent_layer",
    capabilities: list[str] | None = None,
) -> AtomIdentity:
    """Register a controller as an Atom."""
    atom = AtomIdentity(
        designation=designation or controller_name.upper(),
        name=controller_name,
        atom_class=AtomClass.CONTROLLER,
        atom_type="domain_controller",
        scope=scope,
        capabilities=capabilities or [],
        owner_controller=controller_name,
    )
    return registry.register(atom)


def create_team_atom(
    registry: AtomRegistry,
    team_name: str,
    owner_controller: str,
    designation: str = "",
    scope: str = "agent_layer",
    capabilities: list[str] | None = None,
) -> AtomIdentity:
    """Register a team as an Atom."""
    atom = AtomIdentity(
        designation=designation or team_name.upper(),
        name=team_name,
        atom_class=AtomClass.TEAM,
        atom_type="execution_team",
        scope=scope,
        capabilities=capabilities or [],
        owner_controller=owner_controller,
    )
    return registry.register(atom)


def create_worker_atom(
    registry: AtomRegistry,
    worker_name: str,
    owner_controller: str,
    designation: str = "",
    capabilities: list[str] | None = None,
) -> AtomIdentity:
    """Optionally register a worker as an Atom."""
    atom = AtomIdentity(
        designation=designation or worker_name.upper(),
        name=worker_name,
        atom_class=AtomClass.WORKER,
        atom_type="specialist_worker",
        scope="worker_pool",
        capabilities=capabilities or [],
        owner_controller=owner_controller,
    )
    return registry.register(atom)
