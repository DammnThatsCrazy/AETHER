"""Reconciled Control Plane flag reads.

Function-local ``get_settings()`` reads mirror the WS-D pattern
(``shared/backend_interpretation/flags.py``): this package is imported by the
route module, the reconciliation skeleton and (in later phases) workers, so a
module-level settings import would drag the full settings graph into every one
of those surfaces. All three flags live on the frozen
:class:`config.settings.ReconciledControlPlaneConfig` (``Settings.reconciled_control``)
and default OFF:

* ``enabled``             ``AETHER_RECONCILED_CONTROL_PLANE_ENABLED``          plane master switch
* ``reconciler_enabled``  ``AETHER_RECONCILED_CONTROL_RECONCILER_ENABLED``     reconcile skeleton (tests-only in Phase 0)
* ``kyber_route_enabled`` ``AETHER_RECONCILED_CONTROL_KYBER_ROUTE_ENABLED``    read-only operator route mount
"""

from __future__ import annotations

# Attribute name on Settings.reconciled_control for each surface.
_FLAG_ATTRS: tuple[str, ...] = (
    "enabled",
    "reconciler_enabled",
    "kyber_route_enabled",
)


def reconciled_control_enabled(attr: str) -> bool:
    """Read one Reconciled Control Plane flag by attribute name.

    Unknown attribute names resolve to ``False`` (fail-safe): a typo can never
    enable a mechanism.
    """
    if attr not in _FLAG_ATTRS:
        return False
    try:
        from config.settings import get_settings

        return bool(getattr(get_settings().reconciled_control, attr, False))
    except Exception:  # noqa: BLE001 - import-defensive: never crash a caller
        return False


def enabled() -> bool:
    return reconciled_control_enabled("enabled")


def reconciler_enabled() -> bool:
    return reconciled_control_enabled("reconciler_enabled")


def kyber_route_enabled() -> bool:
    return reconciled_control_enabled("kyber_route_enabled")


__all__ = [
    "reconciled_control_enabled",
    "enabled",
    "reconciler_enabled",
    "kyber_route_enabled",
]
