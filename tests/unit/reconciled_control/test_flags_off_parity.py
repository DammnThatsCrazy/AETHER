"""Flag-OFF parity — Reconciled Control Plane must be inert by default.

All three toggles default OFF; with them OFF nothing about the plane is visible
or active: no route is mounted (the main.py conditional reads these flags) and
the flag reads fail safe. The operator router itself is read-only — GETs and no
mutation verb — regardless of flag state.
"""

from __future__ import annotations

import pytest

from services.managed_integrations import flags


def test_all_flags_default_off() -> None:
    assert flags.enabled() is False
    assert flags.reconciler_enabled() is False
    assert flags.kyber_route_enabled() is False


def test_settings_block_defaults_all_off() -> None:
    from config.settings import get_settings

    block = get_settings().reconciled_control
    assert block.enabled is False
    assert block.reconciler_enabled is False
    assert block.kyber_route_enabled is False


def test_unknown_flag_attribute_fails_safe_false() -> None:
    # A typo can never enable a mechanism.
    assert flags.reconciled_control_enabled("definitely_not_a_flag") is False


def test_flags_fail_safe_when_settings_import_is_broken(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "config.settings":
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert flags.enabled() is False
    assert flags.kyber_route_enabled() is False


def test_toggling_flags_on_is_reflected_in_flag_reads(rcp_flags) -> None:
    assert flags.enabled() is False
    rcp_flags(enabled=True, kyber_route_enabled=True)
    assert flags.enabled() is True
    assert flags.kyber_route_enabled() is True
    # reconciler_enabled was reset to False by the setter.
    assert flags.reconciler_enabled() is False
    rcp_flags(reconciler_enabled=True)
    assert flags.reconciler_enabled() is True
    assert flags.enabled() is False


def test_operator_router_is_read_only() -> None:
    # Phase-0 + Phase-1 scope discipline: no POST/PUT/PATCH/DELETE anywhere on
    # the managed-integrations operator surface. Four GETs only (managed
    # integrations list/detail + Phase-1 change-sets list/detail).
    from services.managed_integrations.routes import admin_router

    methods: set[str] = set()
    for route in admin_router.routes:
        route_methods = getattr(route, "methods", None) or set()
        methods |= {str(m).upper() for m in route_methods}
    assert methods == {"GET"}
    assert len(admin_router.routes) == 4


def test_operator_router_prefix_is_admin_kyber() -> None:
    from services.managed_integrations.routes import admin_router

    assert admin_router.prefix == "/v1/admin/kyber/managed-integrations"


def test_change_sets_routes_precede_the_id_capture_route() -> None:
    # ``/change-sets`` is a literal that must not be swallowed by the
    # ``/{managed_integration_id}`` capture route, so it must be declared first.
    from services.managed_integrations.routes import admin_router

    paths = [r.path for r in admin_router.routes]
    assert paths.index("/v1/admin/kyber/managed-integrations/change-sets") < paths.index(
        "/v1/admin/kyber/managed-integrations/{managed_integration_id}"
    )


def test_desired_state_and_reconcile_import_without_flags_on() -> None:
    # The reconcile skeleton and desired-state policy are importable and pure
    # while every flag is OFF (a caller may invoke reconcile explicitly — the
    # OFF state only means nothing *automatically* triggers it).
    from services.managed_integrations import build_desired_state, reconcile

    assert callable(build_desired_state)
    assert callable(reconcile)
