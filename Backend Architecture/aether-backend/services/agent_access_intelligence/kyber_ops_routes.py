"""Agent Access Intelligence — Kyber operator ops surface (PR 4).

Three cross-tenant operator reads over the capability inventory, mirroring the Kyber
router already in ``routes.py`` (``/v1/kyber/capability-catalog``): the router carries
``Depends(require_kyber_operator)``, so a non-operator — including a role-admin Aether
tenant — is refused before any handler runs.

``GET /authority``       authorization posture across tenants (counts by derived state)
``GET /drift``           declared-vs-observed identity drift across tenants
``GET /blast-radius``    one bounded blast-radius review, ``?tenant_id=`` required

Nothing here re-derives inventory, authorization state, drift or exposure. Every number
comes from ``capability_catalog_service``, ``capability_authority_service.count_by_state``
and ``capability_risk_service`` — the services that were audited and corrected. A second
implementation of any of them would drift away from the fixed one, and the drift would be
invisible until an operator acted on the wrong number.

**Cross-tenant reads are always per-tenant reads.** Tenants are discovered from the
operator-only ``catalog_health()`` aggregate, and then every subsequent query names one
``tenant_id`` explicitly. There is no unscoped query in this module: fanning out over
named tenants keeps the tenant boundary in the query itself rather than in a filter
applied afterwards.

**The rule this module exists to protect — a partial sum is never a total.** A per-tenant
read that hit its bounded window, or a tenant discovery that hit its own, means the
cross-tenant total *could not be computed*. It is then ``null`` with the absent inputs
named in ``missing_inputs`` and ``totals_known: false`` — never the sum of the tenants
that happened to answer. Summing the readable tenants and labelling the result a total is
the single most damaging thing this surface could do: an operator reading "3 unauthorized"
when two tenants silently failed to read will close the investigation. The evidence we do
hold (per-tenant rows, drift findings) is still returned, labelled as evidence.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics

from services.security.request_context import require_kyber_operator
from services.agent_access_intelligence.authority import capability_authority_service
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.risk_service import (
    IDENTITY_DRIFT_CODE,
    capability_risk_service,
)

logger = get_logger("aether.service.agent_access_intelligence.kyber_ops_routes")

# Paths containing `/kyber` are auto-classified by `config/route_registry.yaml` as
# kyber_operator_required + audit_required + high risk, and `/v1/kyber` is already in
# `known_prefixes` — so this prefix needs no registry entry (asserted in the tests).
capability_kyber_ops_router = APIRouter(
    prefix="/v1/kyber/capability-ops",
    tags=["Kyber — Agent Access Intelligence"],
    dependencies=[Depends(require_kyber_operator)],
)

# The full derived-state vocabulary of `authority.authorization_state`. Always emitted,
# so "no revoked authorizations" and "we could not read the authorizations" are different
# shapes (`0` vs `null`) rather than the same absent key.
AUTHORIZATION_STATES: tuple[str, ...] = ("active", "pending", "expired", "revoked")

# Per-tenant drift counts. Reported together so a null block is unambiguous.
DRIFT_COUNT_KEYS: tuple[str, ...] = (
    "capabilities_examined",
    "declared",
    "drifted",
    "observed_only",
)

# Bounded page of drift findings read per tenant. Evidence, not a total — the counts
# above are what answers "how much drift is there".
_DRIFT_FINDINGS_PER_TENANT = 50


# ══════════════════════════════════════════════════════════════════════════════
# TENANT DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

async def _discover_tenants() -> tuple[list[str], list[str], dict[str, Any]]:
    """Tenants to fan out over, plus any reason the tenant list itself is incomplete.

    Reuses ``catalog_health()`` — the operator-only cross-tenant aggregate that already
    exists — rather than adding a second unscoped scan of the catalog. It reports both
    bounds that can hide a tenant from us:

    * ``sampled`` — its row window truncated, so a tenant whose rows all fell outside it
      is not in the list at all;
    * ``tenant_count`` above the length of its ranked ``top_tenants`` list — more distinct
      tenants were seen than were returned.

    Either one means the fan-out below covers *some* tenants, not *the* tenants, so every
    cross-tenant total derived from it is unknown. Returning the tenants anyway (with the
    reason named) keeps the evidence without letting it be read as complete.
    """
    health = await capability_catalog_service.catalog_health()
    ranked = list(health.get("top_tenants") or [])
    tenant_ids = sorted({str(entry[0]) for entry in ranked if entry and entry[0]})
    distinct_seen = int(health.get("tenant_count") or 0)

    missing: list[str] = []
    if health.get("sampled"):
        missing.append("capability_catalog:tenant_discovery_truncated")
    if distinct_seen > len(tenant_ids):
        # Ranked window, or a row we could not attribute to a tenant.
        missing.append("capability_catalog:tenant_discovery_ranked_window_only")

    discovery = {
        "tenants_examined": len(tenant_ids),
        "distinct_tenants_seen": distinct_seen,
        "complete": not missing,
    }
    return tenant_ids, missing, discovery


def _dedupe(entries: list[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        if entry not in out:
            out.append(entry)
    return out


def _unknown_summary(subject: str, missing: list[str]) -> str:
    return (
        f"Cross-tenant {subject} is UNKNOWN, not zero. Required input(s) absent: "
        f"{', '.join(missing)}. Every total is null because it could not be computed — "
        "the tenants that did answer are listed as evidence, and their sum is NOT a "
        "total. Do not read this as an absence of findings."
    )


# ══════════════════════════════════════════════════════════════════════════════
# AUTHORITY POSTURE (cross-tenant)
# ══════════════════════════════════════════════════════════════════════════════

async def authority_posture() -> dict[str, Any]:
    """Authorization state histogram across tenants.

    Each tenant is counted by ``capability_authority_service.count_by_state`` — the same
    bounded window ``GET /v1/capability-authorizations?state=`` pages, so the operator view
    and the tenant view can never disagree about a tenant's numbers. ``state`` is derived
    from ``revoked_at``/``ends_at``/``starts_at`` on read and is never stored, so there is
    nothing here to keep in sync.
    """
    tenant_ids, missing, discovery = await _discover_tenants()

    states: list[str] = list(AUTHORIZATION_STATES)
    tenants: list[dict[str, Any]] = []
    readable_totals: Counter = Counter()

    for tenant_id in tenant_ids:
        snapshot = await capability_authority_service.count_by_state(tenant_id=tenant_id)
        counts = dict(snapshot.get("counts") or {})
        for state in sorted(counts):
            if state not in states:
                states.append(state)

        tenant_missing: list[str] = []
        if snapshot.get("truncated"):
            # The window this tenant's authorizations were counted over was full, so an
            # authorization outside it is invisible. Its counts are a floor, not a count.
            tenant_missing.append(
                f"capability_authorizations:scan_truncated:tenant_id={tenant_id}"
            )

        if tenant_missing:
            missing.extend(tenant_missing)
            tenant_counts: dict[str, Optional[int]] = {s: None for s in states}
        else:
            tenant_counts = {s: int(counts.get(s, 0)) for s in states}
            readable_totals.update({s: int(counts.get(s, 0)) for s in states})

        tenants.append({
            "tenant_id": tenant_id,
            "known": not tenant_missing,
            "missing_inputs": tenant_missing,
            "counts_by_state": tenant_counts,
            "authorizations_scanned": int(snapshot.get("scanned") or 0),
            "scan_limit": int(snapshot.get("scan_limit") or 0),
        })

    # Backfill every tenant row with any state discovered on a later tenant, so all rows
    # carry the same keys and a missing key never has to be interpreted.
    for row in tenants:
        row_counts = row["counts_by_state"]
        for state in states:
            row_counts.setdefault(state, None if not row["known"] else 0)

    missing = _dedupe(missing)
    if missing:
        counts_by_state: dict[str, Optional[int]] = {s: None for s in states}
        summary = _unknown_summary("authorization posture", missing)
    else:
        counts_by_state = {s: int(readable_totals.get(s, 0)) for s in states}
        summary = (
            f"Across {discovery['tenants_examined']} tenant(s): "
            + ", ".join(f"{counts_by_state[s]} {s}" for s in states)
            + ". Every tenant's authorizations were counted within its scan window, and "
            "every window was complete. Authorization state is derived on read, never "
            "stored."
        )

    return {
        "scope": "cross_tenant",
        "totals_known": not missing,
        "missing_inputs": missing,
        "counts_by_state": counts_by_state,
        "tenants": tenants,
        "tenant_discovery": discovery,
        "summary": summary,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DRIFT (cross-tenant)
# ══════════════════════════════════════════════════════════════════════════════

async def drift_posture(
    *, findings_per_tenant: int = _DRIFT_FINDINGS_PER_TENANT
) -> dict[str, Any]:
    """Declared-vs-observed identity drift across tenants.

    Delegates entirely to ``capability_risk_service.findings(tenant_id, code=…)``, which
    owns the comparison (observed digest over the declared field subset) and already
    discloses both of its bounded reads. Undeclared capabilities are *not* drift — they
    are the normal state of a healthy tenant and are reported as ``observed_only``.
    """
    tenant_ids, missing, discovery = await _discover_tenants()

    tenants: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    readable_totals: Counter = Counter()

    for tenant_id in tenant_ids:
        result = await capability_risk_service.findings(
            tenant_id, code=IDENTITY_DRIFT_CODE, limit=findings_per_tenant, offset=0
        )
        identity = dict(result.get("identity") or {})
        coverage = dict(result.get("coverage") or {})

        tenant_missing: list[str] = []
        if coverage.get("catalog_truncated"):
            tenant_missing.append(f"capability_catalog:scan_truncated:tenant_id={tenant_id}")
        if identity.get("declarations_truncated"):
            # A declaration outside the window makes its capability look undeclared, and
            # undeclared is deliberately not a finding — so real drift disappears into a
            # clean-looking report. Never a computed zero.
            tenant_missing.append(
                f"capability_declarations:scan_truncated:tenant_id={tenant_id}"
            )

        findings.extend(
            {**item, "tenant_id": tenant_id} for item in (result.get("items") or [])
        )

        if tenant_missing:
            missing.extend(tenant_missing)
            tenant_counts: dict[str, Optional[int]] = {k: None for k in DRIFT_COUNT_KEYS}
        else:
            tenant_counts = {k: int(identity.get(k) or 0) for k in DRIFT_COUNT_KEYS}
            readable_totals.update({k: int(identity.get(k) or 0) for k in DRIFT_COUNT_KEYS})

        tenants.append({
            "tenant_id": tenant_id,
            "known": not tenant_missing,
            "missing_inputs": tenant_missing,
            "counts": tenant_counts,
        })

    missing = _dedupe(missing)
    if missing:
        counts: dict[str, Optional[int]] = {k: None for k in DRIFT_COUNT_KEYS}
        findings_scope = "evidence_only_incomplete_scan"
        summary = _unknown_summary("identity drift", missing)
    else:
        counts = {k: int(readable_totals.get(k, 0)) for k in DRIFT_COUNT_KEYS}
        findings_scope = "all_matching_findings"
        summary = (
            f"{counts['drifted']} capability(ies) across "
            f"{discovery['tenants_examined']} tenant(s) no longer match the identity their "
            f"tenant declared, out of {counts['capabilities_examined']} examined "
            f"({counts['declared']} declared, {counts['observed_only']} observed but never "
            "declared). Undeclared is the normal state of a healthy tenant, not a finding."
        )

    return {
        "scope": "cross_tenant",
        "totals_known": not missing,
        "missing_inputs": missing,
        "counts": counts,
        # Evidence. `findings_scope` states whether it is every matching finding or only
        # what an incomplete scan happened to surface.
        "findings": findings,
        "findings_scope": findings_scope,
        "findings_page_limit": findings_per_tenant,
        "tenants": tenants,
        "tenant_discovery": discovery,
        "summary": summary,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@capability_kyber_ops_router.get("/authority")
async def read_authority_posture(request: Request):
    """Cross-tenant authorization posture, counted by derived state (operator-only).

    ``counts_by_state`` is ``null`` for every state — with ``totals_known: false`` and the
    reasons in ``missing_inputs`` — whenever a tenant's authorization window truncated or
    the tenant list itself is incomplete. It is never the sum of the tenants that could be
    read."""
    data = await authority_posture()
    metrics.increment(
        "capability_kyber_authority_posture_reads",
        labels={"totals_known": "true" if data["totals_known"] else "false"},
    )
    return APIResponse(data=data).to_dict()


@capability_kyber_ops_router.get("/drift")
async def read_drift_posture(
    request: Request,
    findings_per_tenant: int = Query(
        _DRIFT_FINDINGS_PER_TENANT,
        ge=1,
        le=200,
        description="Bounded page of drift findings read per tenant (evidence, not a total).",
    ),
):
    """Cross-tenant declared-vs-observed identity drift (operator-only).

    Same rule as ``/authority``: an incomplete per-tenant read makes every cross-tenant
    count ``null``, not a partial sum. The findings that were read are still returned,
    labelled by ``findings_scope``."""
    data = await drift_posture(findings_per_tenant=findings_per_tenant)
    metrics.increment(
        "capability_kyber_drift_posture_reads",
        labels={"totals_known": "true" if data["totals_known"] else "false"},
    )
    return APIResponse(data=data).to_dict()


@capability_kyber_ops_router.get("/blast-radius")
async def read_kyber_blast_radius(
    request: Request,
    tenant_id: str = Query(
        ...,
        description="The tenant to review. Required — a blast radius is only meaningful "
        "within one tenant's observed inventory.",
    ),
    agent_id: Optional[str] = Query(
        default=None, description="What this agent has been observed reaching."
    ),
    capability_id: Optional[str] = Query(
        default=None,
        description="Which agents have been observed reaching this capability.",
    ),
):
    """One bounded blast-radius review inside one explicitly named tenant (operator-only).

    Deliberately **not** a cross-tenant aggregate. Blast radius is a per-subject exposure
    answer whose honesty depends on every input for that subject being present; summing it
    over tenants would produce a number no operator can act on and would hide exactly the
    tenants whose inputs were missing. The operator names the tenant, and the response is
    the same fail-honest shape the tenant surface returns — ``exposure_known: false`` with
    ``null`` counts and ``missing_inputs`` when an input was never observed."""
    scoped_tenant = (tenant_id or "").strip()
    if not scoped_tenant:
        raise BadRequestError(
            "tenant_id is required — a Kyber blast-radius review is always bounded to one "
            "explicitly named tenant"
        )
    data = await capability_risk_service.blast_radius(
        scoped_tenant, agent_id=agent_id, capability_id=capability_id
    )
    metrics.increment(
        "capability_kyber_blast_radius_reads",
        labels={
            "subject": str(data.get("subject", {}).get("kind")),
            "exposure_known": "true" if data.get("exposure_known") else "false",
        },
    )
    return APIResponse(data={"tenant_id": scoped_tenant, **data}).to_dict()
