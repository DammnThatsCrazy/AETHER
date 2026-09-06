"""Phase-4 console vocabulary — reconciled-control surfacing on the Kyber plane.

Closes the Phase-0 close-out caveat ("no route-registry capability
declaration"): the reconciled-control operator surface now

- declares one capability in the Kyber workforce vocabulary
  (``kyber.reconciled_control.read``, domain ``reconciled_control``);
- grants it through the evidence-read role templates exactly like
  ``kyber.audit.read`` (change/access decision evidence rides together);
- declares every mounted GET in ``config/route_registry.yaml`` so the route
  policy boundary can enforce the capability at the authorization plane
  instead of relying on the blanket operator-required fallback alone.

Surfacing is inert by default: the routes stay unmounted until the
reconciled-control route flag flips, and capability-level denial only engages
under ``KYBER_BACKEND_AUTHZ_ENFORCED`` (default OFF in local/dev — the
explicit observe-mode lever for the whole capability plane).
"""

from __future__ import annotations

from config.settings import get_settings

_RCP_CAPABILITY = "kyber.reconciled_control.read"
_PREFIX = "/v1/admin/kyber/managed-integrations"


def _capability():
    from services.kyber.access.capabilities import require_capability

    return require_capability(_RCP_CAPABILITY)


def test_capability_is_declared_in_the_kyber_vocabulary() -> None:
    cap = _capability()
    # The governance domain the Phase-0 grants already locked down: operator
    # aggregate read, out of ALL_DOMAINS' tenant reach, no tenant scope.
    assert cap.domain == "reconciled_control"
    assert cap.action == "read"
    assert cap.scope == "all_tenants_aggregate"
    assert not cap.tenant_scoped

    from services.kyber.access.capabilities import (
        COMMAND_CAPABILITY_IDS,
        TENANT_SCOPED_CAPABILITY_IDS,
    )

    # A read surface can never authorize a dispatch/command, and the domain
    # carries no tenant grant — the boundary must not see a tenant scope here.
    assert _RCP_CAPABILITY not in COMMAND_CAPABILITY_IDS
    assert _RCP_CAPABILITY not in TENANT_SCOPED_CAPABILITY_IDS


def test_capability_rides_the_evidence_read_templates() -> None:
    # Workforce grant surfacing: the capability rides _READ_EVIDENCE exactly
    # like kyber.audit.read (operator change/access decision evidence). A role
    # that can read the audit ledger can read the reconciled-control review
    # surface; a role that cannot hold neither. This equivalence is asserted
    # as a set identity over every template so future role edits cannot drift
    # the two evidence surfaces apart.
    from services.kyber.access.roles import ROLE_TEMPLATES

    anchor = "kyber.audit.read"
    drifted = [
        tid
        for tid, template in ROLE_TEMPLATES.items()
        if template.grants(_RCP_CAPABILITY) != template.grants(anchor)
    ]
    assert not drifted, (
        f"templates drifted from the audit-read evidence set: {drifted}"
    )
    # The day-to-day operator role holds it (operations_command rides
    # olympus_operator); product/design read surfaces never do.
    assert ROLE_TEMPLATES["operations_command"].grants(_RCP_CAPABILITY)
    assert not ROLE_TEMPLATES["product_manager"].grants(_RCP_CAPABILITY)
    assert not ROLE_TEMPLATES["designer"].grants(_RCP_CAPABILITY)


def test_every_rcp_route_declares_the_capability() -> None:
    # kyber_routes registry declarations for the six mounted GETs (literal
    # routes plus the two id-capture templates, exercised through concrete
    # paths so the template regexes really match).
    from services.security.route_registry import classify

    paths = (
        f"{_PREFIX}",
        f"{_PREFIX}/mi-1",
        f"{_PREFIX}/change-sets",
        f"{_PREFIX}/change-sets/cs-1",
        f"{_PREFIX}/approvals",
        f"{_PREFIX}/action-required",
    )
    for path in paths:
        pol = classify(path, "GET")
        assert pol is not None, f"unclassified RCP route {path}"
        assert pol.kyber_operator_required, path
        assert pol.audit_required, path
        assert pol.required_capability == _RCP_CAPABILITY, path
        # Record-level operator evidence: the whole surface discloses D4 and
        # therefore demands the evidence disclosure ceiling when enforced.
        assert pol.minimum_disclosure == "D4", path


def test_surface_is_inert_by_default() -> None:
    # Flag-OFF parity for the console surfacing: nothing the surfacing added
    # is active under default settings. The RCP routes are not mounted until
    # the reconciled-control route flag flips, and capability-level denial
    # engages only when KYBER_BACKEND_AUTHZ_ENFORCED is on (default OFF in
    # local/dev — observe mode for the whole capability plane).
    settings = get_settings()
    assert settings.reconciled_control.kyber_route_enabled is False
    assert settings.kyber_workforce.backend_authz_enforced is False
