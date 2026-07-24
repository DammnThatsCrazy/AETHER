"""Provider-attested access evidence (PR 3, Phase A, §9.6).

An **evidence** row records what a *provider* reported about an agent's access to a
capability, attributed to that provider. It is **provider-attested, never
platform-verified**: nothing in this backend authenticates a third-party publisher, and
nothing here may be read as having done so (the same hard rule ``identity.py`` and
``declarations.py`` are built around). ``verification_status`` is the provider's own claim,
carried verbatim from ``services.agentic_observability.provider_framework
.ProviderVerificationStatus`` — this module deliberately defines no status vocabulary of
its own, so a ``verified``-meaning-"we-checked-the-publisher" value cannot be introduced
here by accident.

What this module is *for* is making the agentic provider framework reachable. The
framework already knows how to turn grants + observed actions into permission findings
(``compute_permission_findings``); it had no stored input and no route. ``permission_findings``
is that wiring: stored evidence becomes ``AuthorizationGrantRecord``s, the observed
capability catalog becomes ``ProviderActionRecord``s, active capability authorizations
become the approved scope baselines, and the framework computes the findings.

Storage invariants:

1. ``evidence_id`` is deterministic over ``(tenant, provider_id, capability_id,
   external_account_id)``, so re-capturing the same evidence **upserts** one row. Two rows
   for one provider claim would each carry their own status and an operator reading a
   "confirmed / revoked" pair would have no way to tell which is current.
2. URL-shaped free text (``external_account_id``, ``verification_method``) is passed
   through ``catalog_service._sanitize_server_url`` **before** it is stored *and before it
   is hashed*, so a pasted ``user:pass@`` / ``?token=`` value reaches neither the durable
   row nor the deterministic id nor the digest.
3. ``verified_at`` is parsed by ``shared.temporal.instant.parse_instant_strict`` and
   normalized to a single canonical UTC form. This is not decoration:
   ``compute_permission_findings`` compares instants **lexicographically**
   (``expires_at < now_str``, ``observed_at > revoked_at``), which is only correct when
   both sides are in identical canonical form — a ``…Z`` string sorts *after* the same
   moment written ``…+00:00``, which is how this package once produced a grant that never
   expired. Every instant handed to the framework goes through the same normalizer.
4. ``evidence_digest`` covers the attested tuple (status/method/verified_at/agent), not
   just the identity keys, so a *change* in what the provider attests about an unchanged
   identity is detectable across upserts.
5. Reads compare ``tenant_id`` and raise ``NotFoundError`` on mismatch, identically to
   absent, so an evidence id cannot be used as a cross-tenant existence oracle.
6. No derived state is stored. ``is_active`` / "expired" / "unauthorized" are computed at
   read time from the row and the framework; a stored verdict that disagreed with its own
   row would be invisible.

Records are flat (no nesting) because ``BaseRepository`` stores the dict as JSONB and
filters **top-level** ``data->>'key'`` only — and because DSR erasure by ``tenant_id`` goes
through ``delete_by_entity`` on that same top-level field.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict
from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger
from shared.temporal.instant import TemporalError, parse_instant_strict
from services.security.repositories import _ScopedRepo

from services.agentic_observability.provider_framework import (
    AuthorizationGrantRecord,
    ProviderActionRecord,
    ProviderVerificationStatus,
    compute_permission_findings,
)

from . import identity
from .authority import capability_authority_service
from .catalog_service import _clean, _sanitize_server_url, capability_catalog_service

logger = get_logger("aether.service.agent_access_intelligence.provider_evidence")

PROVIDER_EVIDENCE_TABLE = "provider_evidence"

# Where the assertion comes from. Constant, not caller-supplied: a caller must not be able
# to label its own row "platform_verified".
EVIDENCE_SOURCE = "provider_attested"

ATTESTATION_DISCLOSURE = (
    "Provider-attested. Each record states what the named provider reported about an "
    "agent's access, attributed to that provider. AETHER does not authenticate "
    "third-party publishers and no field here asserts that it did."
)

# The provider's claim about this access. Enumerated so the digest covers exactly what the
# provider attests — an unrelated bookkeeping field (`updated_at`) must never change it.
_ATTESTED_FIELDS: tuple[str, ...] = (
    "provider_id",
    "capability_id",
    "external_account_id",
    "agent_id",
    "verification_status",
    "verification_method",
    "verified_at",
)

# Statuses that mean the provider is no longer attesting live access. Used only to build
# the framework's grant record at read time; never stored (invariant 6).
_INACTIVE_STATUSES = frozenset({
    ProviderVerificationStatus.REVOKED.value,
    ProviderVerificationStatus.EXPIRED.value,
})

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Hard cap on the action records handed to the framework, independent of the read `limit`.
# `compute_permission_findings` walks `actions` twice per grant, so the work is
# O(grants x actions); one installation may carry up to `models._MAX_CAPABILITY_IDS` (100)
# capabilities, which would let a 500-row installation window alone produce 50k actions and
# turn a compliance read into tens of seconds. Capped and DISCLOSED rather than left
# unbounded — an endpoint that times out answers nothing at all.
_MAX_ACTIONS = 2000

# `expired_grant` is the one finding `compute_permission_findings` can produce that this
# input set cannot support: a provider attestation carries no grant expiry. Named in the
# response rather than silently absent — "we did not evaluate expiry" and "no grant has
# expired" are different answers and only one of them is true.
_NOT_EVALUATED = {
    "expired_grant": (
        "provider-attested evidence carries no grant expiry, so grant expiry was not "
        "evaluated. This is not a statement that no grant has expired."
    )
}


# ── identity / digest helpers ─────────────────────────────────────────────────

def evidence_id_for(
    tenant_id: str,
    provider_id: Optional[str],
    capability_id: Optional[str],
    external_account_id: Optional[str],
) -> str:
    """Deterministic evidence identity — re-capture upserts rather than accumulating rows.

    Tenant-scoped like every other id in this package, so the same provider claim in two
    tenants is two rows and an id never collides across tenants."""
    raw = f"{tenant_id}|{provider_id or ''}|{capability_id or ''}|{external_account_id or ''}"
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def evidence_digest_for(record: dict[str, Any]) -> str:
    """Digest over what the provider attests.

    Not provenance — a digest of an unverified claim is still unverified. Its job is to
    make *change* detectable: the same provider later attesting a different status,
    method, moment or agent digests differently, even though the row's identity keys (and
    therefore its ``evidence_id``) are unchanged."""
    raw = "|".join(
        f"{name}={str(record.get(name) or '').strip().lower()}" for name in _ATTESTED_FIELDS
    )
    return "evd_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _coerce_status(value: Any) -> ProviderVerificationStatus:
    """Resolve a caller-supplied status to a framework enum member.

    An **absent** status resolves to ``INSUFFICIENT_DATA``, not ``UNVERIFIED``: omitting a
    status is the absence of an assertion, while ``unverified`` is a substantive claim the
    provider did not make. Recording the stronger one would be inventing evidence."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ProviderVerificationStatus.INSUFFICIENT_DATA
    raw = getattr(value, "value", value)
    try:
        return ProviderVerificationStatus(str(raw).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(s.value for s in ProviderVerificationStatus)
        raise BadRequestError(
            f"verification_status must be one of: {allowed}"
        ) from exc


def _canonical_instant(value: Any, *, field_name: str) -> Optional[str]:
    """Strict parse → single canonical UTC form, or ``BadRequestError``.

    The canonical form is ``datetime.isoformat()`` on a UTC-normalized aware datetime
    (``…+00:00``) — deliberately the same rendering ``shared.common.common.utc_now()
    .isoformat()`` produces, because ``compute_permission_findings`` compares stored
    instants against exactly that string with ``<``. Storing ``…Z`` here would sort every
    already-expired grant *after* "now" and the finding would never fire."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_instant_strict(text).isoformat()
    except TemporalError as exc:
        raise BadRequestError(
            f"{field_name} must be an ISO-8601 instant with an explicit UTC offset or 'Z' "
            f"({exc.reason_code})"
        ) from exc


def _comparable_instant(value: Any) -> Optional[str]:
    """Canonicalize an instant this module did **not** write, or ``None`` if it cannot.

    Applied to catalog/installation timestamps. ``None`` (rather than the raw string) is
    returned on failure so an uncomparable value never reaches the framework's lexicographic
    ``>`` — a mixed-format comparison is worse than no comparison, because it silently
    produces or suppresses a finding. Every ``None`` is counted and disclosed."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_instant_strict(text).isoformat()
    except TemporalError:
        return None


def _scope_for(
    capability_id: Optional[str],
    capability_row: Optional[dict[str, Any]],
    provider_id: Optional[str],
) -> str:
    """The scope string both sides of the comparison use.

    Grants (from evidence), actions (from observed installations) and baselines (from
    authorizations) all derive their scope through this one function, so "the same scope"
    means the same string on every side. Prefers the catalog's ``tool_name`` — the only
    name that carries an operator-legible verb, which is what the framework's
    write-scope heuristic reads — and degrades to opaque, still-comparable keys."""
    tool_name = _clean((capability_row or {}).get("tool_name"))
    if tool_name:
        return tool_name.lower()
    if capability_id:
        return f"capability:{capability_id}"
    return f"provider:{provider_id or 'unknown'}"


# ── repository ────────────────────────────────────────────────────────────────

class ProviderEvidenceRepository(_ScopedRepo):
    """``provider_evidence`` rows (JSONB-backed; in-memory for local/dev/tests).

    Store name matches the alembic table (``20260808_provider_evidence``) and its
    ``storage_policies.yaml`` ``resource_type`` entry exactly — the storage-policy gate
    derives its inventory from those table names."""

    def __init__(self) -> None:
        super().__init__(PROVIDER_EVIDENCE_TABLE)

    async def list_evidence(
        self,
        tenant_id: str,
        *,
        provider_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        extra: dict[str, Any] = {}
        if provider_id:
            extra["provider_id"] = provider_id
        if capability_id:
            extra["capability_id"] = capability_id
        return await self.list_for_tenant(tenant_id, limit=limit, offset=offset, extra=extra or None)


# ── service ───────────────────────────────────────────────────────────────────

class ProviderEvidenceService:
    """Capture / read provider-attested access evidence, and run the framework over it.

    Holds no finding logic of its own: ``compute_permission_findings`` is the single
    implementation and this service is the adapter that gives it stored inputs. A second
    finding implementation here would eventually disagree with the first."""

    def __init__(self, repo: Optional[ProviderEvidenceRepository] = None) -> None:
        self._repo = repo or ProviderEvidenceRepository()

    # ── writes ────────────────────────────────────────────────────────────────

    async def capture(
        self,
        *,
        tenant_id: str,
        recorded_by_entity_id: str,
        provider_id: str,
        capability_id: Optional[str] = None,
        external_account_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        verification_status: Optional[Any] = None,
        verification_method: Optional[str] = None,
        verified_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Upsert one provider attestation about an agent's access to a capability.

        Records what the provider reported. It does not verify the provider, and re-capture
        of the same ``(provider, capability, account)`` updates the row rather than adding
        a competing one — see invariant 1."""
        if not tenant_id or not str(tenant_id).strip():
            raise BadRequestError("tenant_id is required")
        provider = _clean(provider_id)
        if not provider:
            raise BadRequestError(
                "provider_id is required: evidence is attributed to the provider that "
                "reported it, and an unattributed attestation attributes nothing"
            )

        # Sanitized BEFORE the id and digest are derived, so a credential pasted into a
        # URL-shaped value reaches neither the row nor either hash.
        account = _sanitize_server_url(_clean(external_account_id))
        method = _sanitize_server_url(_clean(verification_method))
        status = _coerce_status(verification_status)
        attested_at = _canonical_instant(verified_at, field_name="verified_at")

        capability = _clean(capability_id)
        evidence_id = evidence_id_for(tenant_id, provider, capability, account)

        existing = await self._repo.find_by_id(evidence_id)
        if existing is not None and str(existing.get("tenant_id")) != str(tenant_id):
            # Unreachable: `evidence_id_for` hashes tenant_id, so ids never collide across
            # tenants. Fail closed rather than overwrite a foreign row if it ever becomes
            # reachable.
            raise BadRequestError("provider evidence id collision")  # pragma: no cover

        now = utc_now().isoformat()
        record: dict[str, Any] = {
            "evidence_id": evidence_id,
            "tenant_id": str(tenant_id),
            "provider_id": provider,
            "capability_id": capability,
            "external_account_id": account,
            "agent_id": _clean(agent_id),
            "verification_status": status.value,
            "verification_method": method,
            "verified_at": attested_at,
            # Same origin key the catalog and declarations use — one origin key for the
            # package, not a second one invented here. Evidence carries no server URL, so
            # the provider is the observed origin.
            "publisher_ref": identity.publisher_ref_for(None, provider),
            "source": EVIDENCE_SOURCE,
            "recorded_by_entity_id": _clean(recorded_by_entity_id),
            # First capture wins `recorded_at`; `updated_at` moves on re-capture, so "when
            # did this provider first attest this" survives an edit.
            "recorded_at": (existing or {}).get("recorded_at") or now,
            "updated_at": now,
            "notes": _clean(notes),
        }
        record["evidence_digest"] = evidence_digest_for(record)

        if existing is not None:
            stored = await self._repo.update(evidence_id, record)
        else:
            stored = await self._repo.insert(evidence_id, record)
        return self._public(stored)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, *, tenant_id: str, evidence_id: str) -> dict:
        record = await self._repo.find_by_id(evidence_id)
        if not record or str(record.get("tenant_id")) != str(tenant_id):
            # Identical failure for "absent" and "other tenant" so the id cannot be used as
            # an existence oracle.
            raise NotFoundError("provider_evidence")
        return self._public(record)

    async def list(
        self,
        *,
        tenant_id: str,
        provider_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._repo.list_evidence(
            tenant_id,
            provider_id=provider_id,
            capability_id=capability_id,
            limit=limit,
            offset=offset,
        )
        return [self._public(r) for r in rows]

    async def permission_findings(
        self, *, tenant_id: str, limit: int = 500, max_actions: Optional[int] = None
    ) -> dict:
        """Run ``provider_framework.compute_permission_findings`` over stored inputs.

        Four bounded reads feed it, and each one's truncation is reported:

        * **grants** — one per evidence row that names an ``agent_id``. A permission
          finding is agent-scoped, so an attestation with no agent cannot support one.
        * **actions** — one per (installation, capability) pair the catalog observed, for
          installations that name an ``agent_id``. Agentless rows are excluded on *both*
          sides deliberately: the framework matches ``action.agent_id == grant.agent_id``,
          so two unrelated agentless rows would compare equal and fabricate a
          ``revoked_grant_used`` finding about an agent nobody identified.
        * **baselines** — the scopes of the tenant's *active* capability authorizations,
          per agent. That is this package's meaning of "approved", so
          ``unexpected_new_scope`` reads as "the provider attests a scope the tenant never
          authorized" rather than comparing against an empty dict nobody supplied.

        The action list additionally carries the ``_MAX_ACTIONS`` cap, because the
        framework's work is O(grants x actions) and one installation may name up to 100
        capabilities. Hitting it is disclosed like any other bounded read.

        With no usable grant the response is **unknown, not empty**: every count is
        ``None`` and ``missing_inputs`` names what was absent. "0 findings" about a tenant
        whose evidence we never had would read as "no permission problems", which is the
        one thing this surface must never say.
        """
        evidence = await self._repo.list_for_tenant(tenant_id, limit=limit)
        evidence_truncated = len(evidence) >= limit
        catalog = await capability_catalog_service.list_capabilities(tenant_id, limit=limit)
        catalog_truncated = len(catalog) >= limit
        installations = await capability_catalog_service.list_installations(
            tenant_id, limit=limit
        )
        installations_truncated = len(installations) >= limit
        authorizations = await capability_authority_service.list(
            tenant_id=tenant_id, limit=limit
        )
        authorizations_truncated = len(authorizations) >= limit

        by_capability = {
            str(row.get("capability_id")): row for row in catalog if row.get("capability_id")
        }
        missing: list[str] = []
        if evidence_truncated:
            missing.append("provider_evidence:scan_truncated")
        if catalog_truncated:
            missing.append("capability_catalog:scan_truncated")
        if installations_truncated:
            missing.append("capability_installations:scan_truncated")
        if authorizations_truncated:
            missing.append("capability_authorizations:scan_truncated")

        grants, grant_missing = self._grants_from_evidence(
            str(tenant_id), evidence, by_capability
        )
        missing.extend(grant_missing)
        # The effective cap, reported below. Disclosing the module default while a
        # different bound was applied would understate how much was cut.
        effective_max_actions = max_actions if max_actions is not None else _MAX_ACTIONS
        actions, action_missing, action_window_truncated = self._actions_from_installations(
            installations,
            by_capability,
            max_actions=effective_max_actions,
        )
        missing.extend(action_missing)

        complete = not (
            evidence_truncated
            or catalog_truncated
            or installations_truncated
            or authorizations_truncated
            or action_window_truncated
        )

        if not grants:
            return self._unknown(
                missing=missing or ["provider_evidence:no_agent_scoped_record"],
                evidence_examined=len(evidence),
                installations_examined=len(installations),
                capabilities_examined=len(catalog),
                authorizations_examined=len(authorizations),
                limit=limit,
                complete=complete,
            )

        baselines = self._baselines(authorizations, by_capability, grants)

        # THE call this lane exists for: the framework, not a reimplementation of it.
        findings = compute_permission_findings(str(tenant_id), grants, actions, baselines)
        items = [asdict(finding) for finding in findings]
        items.sort(
            key=lambda i: (
                _SEVERITY_RANK.get(str(i.get("severity") or ""), 99),
                str(i.get("finding_type") or ""),
                str(i.get("grant_id") or ""),
                str(i.get("description") or ""),
            )
        )

        deduped: list[str] = []
        for entry in missing:
            if entry not in deduped:
                deduped.append(entry)

        return {
            "items": items,
            "count": len(items),
            "findings_known": True,
            "basis": EVIDENCE_SOURCE,
            "counts": {
                "total": len(items),
                # `total` covers the scanned window, and says so when any of the four reads
                # was truncated. Claiming "all findings" off a partial window under-reports
                # exactly the tenant with the most of them.
                "scope": "all_matching_findings" if complete else "scanned_window_only",
                "by_finding_type": dict(
                    Counter(str(i.get("finding_type") or "unknown") for i in items)
                ),
                "by_severity": dict(
                    Counter(str(i.get("severity") or "unknown") for i in items)
                ),
            },
            "coverage": {
                "evidence_examined": len(evidence),
                "grants_evaluated": len(grants),
                "actions_evaluated": len(actions),
                "installations_examined": len(installations),
                "capabilities_examined": len(catalog),
                "authorizations_examined": len(authorizations),
                "scan_limit": limit,
                "evidence_truncated": evidence_truncated,
                "catalog_truncated": catalog_truncated,
                "installations_truncated": installations_truncated,
                "authorizations_truncated": authorizations_truncated,
                "action_window_truncated": action_window_truncated,
                "action_window_limit": effective_max_actions,
                "complete": complete,
                "missing_inputs": deduped,
            },
            "finding_types_not_evaluated": dict(_NOT_EVALUATED),
            "attestation": ATTESTATION_DISCLOSURE,
        }

    # ── permission-finding inputs ─────────────────────────────────────────────

    def _grants_from_evidence(
        self,
        tenant_id: str,
        evidence: list[dict[str, Any]],
        by_capability: dict[str, dict[str, Any]],
    ) -> tuple[list[AuthorizationGrantRecord], list[str]]:
        grants: list[AuthorizationGrantRecord] = []
        missing: list[str] = []
        agentless = 0
        revoked_without_moment = 0

        for row in evidence:
            agent_id = _clean(row.get("agent_id"))
            if not agent_id:
                agentless += 1
                continue
            capability_id = _clean(row.get("capability_id"))
            if capability_id and capability_id not in by_capability:
                # Attested against something the catalog window does not describe; the
                # scope degrades to an opaque key, so say the name was unavailable.
                missing.append(f"capability_catalog:capability_id={capability_id}")
            status = str(row.get("verification_status") or "").strip().lower()
            attested_at = _clean(row.get("verified_at"))
            revoked_at = (
                attested_at
                if status == ProviderVerificationStatus.REVOKED.value
                else None
            )
            if status == ProviderVerificationStatus.REVOKED.value and not revoked_at:
                # A revocation with no moment cannot be compared against an observation:
                # "used after revocation" is unanswerable, not answerable as "no".
                revoked_without_moment += 1
            grants.append(AuthorizationGrantRecord(
                grant_id=str(row.get("evidence_id") or ""),
                tenant_id=tenant_id,
                provider_id=_clean(row.get("provider_id")) or "",
                agent_id=agent_id,
                scopes=[
                    _scope_for(
                        capability_id,
                        by_capability.get(capability_id or ""),
                        _clean(row.get("provider_id")),
                    )
                ],
                granted_at=attested_at,
                # Provider evidence carries no expiry — see `finding_types_not_evaluated`.
                # Left `None` rather than filled with a guess that would make every grant
                # look permanent or every grant look expired.
                expires_at=None,
                revoked_at=revoked_at,
                is_active=status not in _INACTIVE_STATUSES,
            ))

        if agentless:
            missing.append(f"provider_evidence:agent_id_absent={agentless}")
        if revoked_without_moment:
            missing.append(
                f"provider_evidence:revoked_without_verified_at={revoked_without_moment}"
            )
        return grants, missing

    @staticmethod
    def _actions_from_installations(
        installations: list[dict[str, Any]],
        by_capability: dict[str, dict[str, Any]],
        *,
        max_actions: int = _MAX_ACTIONS,
    ) -> tuple[list[ProviderActionRecord], list[str], bool]:
        actions: list[ProviderActionRecord] = []
        missing: list[str] = []
        agentless = 0
        uncomparable = 0
        action_window_truncated = False

        for installation in installations:
            if len(actions) >= max_actions:
                action_window_truncated = True
                break
            agent_id = _clean(installation.get("agent_id"))
            if not agent_id:
                agentless += 1
                continue
            observed_at = _comparable_instant(installation.get("last_seen_at"))
            if observed_at is None and installation.get("last_seen_at"):
                uncomparable += 1
            provider = _clean(installation.get("provider"))
            for capability_id in installation.get("capability_ids") or []:
                # The cap is enforced HERE as well as between installations. One
                # installation may name up to `models._MAX_CAPABILITY_IDS` (100)
                # capabilities, so checking only at the top of the outer loop let a single
                # installation overshoot the cap entirely — and, when the tenant had just
                # one installation, the loop never came back around, so the overshoot was
                # never disclosed and a truncated action set was reported as complete.
                if len(actions) >= max_actions:
                    action_window_truncated = True
                    break
                actions.append(ProviderActionRecord(
                    action_id=f"{installation.get('installation_id')}:{capability_id}",
                    provider_id=provider or "",
                    agent_id=agent_id,
                    action_type="capability_observed",
                    scopes_used=[
                        _scope_for(
                            str(capability_id),
                            by_capability.get(str(capability_id)),
                            provider,
                        )
                    ],
                    observed_at=observed_at,
                    outcome=None,
                ))

        if agentless:
            missing.append(f"capability_installations:agent_id_absent={agentless}")
        if uncomparable:
            missing.append(
                f"capability_installations:last_seen_at_uncomparable={uncomparable}"
            )
        if action_window_truncated:
            # Directly weakens `write_scope_unused` ("we never saw it used" may only mean
            # "we stopped looking") and `revoked_grant_used`. Never silent.
            missing.append(f"capability_installations:action_window_truncated={max_actions}")
        return actions, missing, action_window_truncated

    @staticmethod
    def _baselines(
        authorizations: list[dict[str, Any]],
        by_capability: dict[str, dict[str, Any]],
        grants: list[AuthorizationGrantRecord],
    ) -> dict[str, list[str]]:
        """Approved scopes per grant, from the tenant's *active* authorizations.

        A revoked or expired authorization is not an approval, so it must not suppress an
        ``unexpected_new_scope`` finding. ``state`` is derived by the authority service
        (never stored), which is why it is filtered here rather than in the query."""
        by_agent: dict[str, set[str]] = {}
        for authorization in authorizations:
            if str(authorization.get("state") or "") != "active":
                continue
            agent_id = _clean(authorization.get("agent_id"))
            capability_id = _clean(authorization.get("capability_id"))
            if not agent_id or not capability_id:
                continue
            by_agent.setdefault(agent_id, set()).add(
                _scope_for(capability_id, by_capability.get(capability_id), None)
            )
        return {
            grant.grant_id: sorted(by_agent.get(grant.agent_id or "", set()))
            for grant in grants
        }

    @staticmethod
    def _unknown(
        *,
        missing: list[str],
        evidence_examined: int,
        installations_examined: int,
        capabilities_examined: int,
        authorizations_examined: int,
        limit: int,
        complete: bool,
    ) -> dict[str, Any]:
        """Every count ``None``; the reads we did make kept as labelled evidence.

        Emitting ``0`` here would be an assertion about the world that no input supports —
        and the specific false assertion "this tenant has no permission problems"."""
        deduped: list[str] = []
        for entry in missing:
            if entry not in deduped:
                deduped.append(entry)
        return {
            "items": [],
            "count": 0,
            "findings_known": False,
            "basis": EVIDENCE_SOURCE,
            "counts": {
                "total": None,
                "scope": None,
                "by_finding_type": None,
                "by_severity": None,
            },
            "coverage": {
                "evidence_examined": evidence_examined,
                "grants_evaluated": 0,
                "actions_evaluated": None,
                "installations_examined": installations_examined,
                "capabilities_examined": capabilities_examined,
                "authorizations_examined": authorizations_examined,
                "scan_limit": limit,
                "complete": complete,
                "missing_inputs": deduped,
            },
            "finding_types_not_evaluated": dict(_NOT_EVALUATED),
            "attestation": ATTESTATION_DISCLOSURE,
            "summary": (
                "Permission findings are UNKNOWN, not zero. No agent-scoped provider "
                f"evidence was available; input(s) absent: {', '.join(deduped)}. Every "
                "count is null because it could not be computed — do not read the empty "
                "list as an absence of permission problems."
            ),
        }

    # ── serialization ─────────────────────────────────────────────────────────

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        """API-facing view: private (``_``-prefixed) fields stripped."""
        out = {k: v for k, v in record.items() if not k.startswith("_")}
        out["evidence_id"] = record.get("evidence_id") or record.get("id")
        # Restated on every row, not only in the collection envelope, so a record lifted
        # out of a list into a ticket or an export still carries what it is.
        out["attestation"] = ATTESTATION_DISCLOSURE
        return out


provider_evidence_service = ProviderEvidenceService()
