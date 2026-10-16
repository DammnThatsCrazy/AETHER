"""Rights Authority admission for source-backed CSV import commits.

Imports can create Bronze, identity-evidence, and governed graph records. This
adapter asks the canonical Rights Authority for each use before the first such
write, then keeps the exact active source grant from being revoked until the
commit's writes finish. It owns no grant or rights policy of its own.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from shared.common.common import ConflictError
from shared.integration_contracts.source_relationship import UNCLASSIFIED

IMPORT_RIGHTS_PURPOSE = "tenant_import_commit"
IMPORT_RIGHTS_USES = (
    ("tenant_lake", "tenant_lake"),
    ("write_tenant_graph", "tenant_internal"),
    ("tenant_insights", "tenant_internal"),
)
IMPORT_SOURCE_RELATIONSHIPS = frozenset({"personal_account", "organization_system", UNCLASSIFIED})


@dataclass(frozen=True)
class ImportRightsEvidence:
    tenant_id: str
    import_id: str
    commit_id: str
    source_id: str
    actor: str
    source_grant_ref: Optional[str]
    decisions: dict[str, Any]
    graph_propagation: Any = None
    reason_codes: tuple[str, ...] = ()

    @property
    def decision_refs(self) -> dict[str, str]:
        return {
            use: str(decision.decision_id)
            for use, decision in self.decisions.items()
            if str(getattr(decision, "decision_id", "")).startswith("rdec_")
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "import_id": self.import_id,
            "commit_id": self.commit_id,
            "source_id": self.source_id or None,
            "source_grant_ref": self.source_grant_ref,
            "decision_refs": self.decision_refs,
            "status": "allowed" if not self.reason_codes else "denied",
            "reason_codes": list(self.reason_codes),
        }


class ImportRightsDenied(ConflictError):
    """Fail-closed import admission refusal with any durable decisions retained."""

    def __init__(self, evidence: ImportRightsEvidence, *reasons: str):
        reason_codes = tuple(dict.fromkeys(
            [*evidence.reason_codes, *(reason for reason in reasons if reason)]
        ))
        self.evidence = ImportRightsEvidence(
            tenant_id=evidence.tenant_id,
            import_id=evidence.import_id,
            commit_id=evidence.commit_id,
            source_id=evidence.source_id,
            actor=evidence.actor,
            source_grant_ref=evidence.source_grant_ref,
            decisions=evidence.decisions,
            graph_propagation=evidence.graph_propagation,
            reason_codes=reason_codes or ("rights_denied",),
        )
        super().__init__(
            "import_rights_denied:" + "|".join(self.evidence.reason_codes),
            details={"reason_codes": list(self.evidence.reason_codes)},
        )


class ImportRightsAdmission:
    """Resolve and hold an explicit active tenant/source import grant."""

    def __init__(self, *, resolver: Any = None, grant_service: Any = None) -> None:
        self._resolver = resolver
        self._grant_service = grant_service

    def _service(self) -> Any:
        if self._grant_service is not None:
            return self._grant_service
        from connectors.integrations.data_rights.service import data_rights_service

        return data_rights_service

    def _authority(self) -> Any:
        if self._resolver is not None:
            return self._resolver
        from tenancy.rights_authority.resolver import effective_rights_resolver

        return effective_rights_resolver

    @staticmethod
    def _evidence(
        tenant_id: str,
        import_id: str,
        commit_id: str,
        source_id: str,
        actor: str,
        decisions: dict[str, Any],
        *,
        source_grant_ref: Optional[str] = None,
        graph_propagation: Any = None,
        reasons: tuple[str, ...] = (),
    ) -> ImportRightsEvidence:
        return ImportRightsEvidence(
            tenant_id=tenant_id,
            import_id=import_id,
            commit_id=commit_id,
            source_id=source_id,
            actor=actor,
            source_grant_ref=source_grant_ref,
            decisions=dict(decisions),
            graph_propagation=graph_propagation,
            reason_codes=reasons,
        )

    async def admit(
        self,
        *,
        tenant_id: str,
        import_id: str,
        commit_id: str,
        source_id: Optional[str],
        actor: Optional[str],
    ) -> ImportRightsEvidence:
        from config.settings import Environment, settings
        from tenancy.rights_authority.contracts import RightsDecisionRequest
        from tenancy.rights_authority.propagation import RightsPropagation
        from tenancy.rights_authority.rollout import RolloutMode

        source = str(source_id or "").strip()
        principal = str(actor or "").strip()
        decisions: dict[str, Any] = {}
        graph_propagation = None
        evidence = self._evidence(
            tenant_id, import_id, commit_id, source, principal, decisions
        )
        if not principal:
            raise ImportRightsDenied(evidence, "approver_missing")

        try:
            service = self._service()
            if (
                settings.env in (Environment.STAGING, Environment.PRODUCTION)
                and not await service.is_durable()
            ):
                raise ImportRightsDenied(evidence, "grant_store_not_durable")
            resolver = self._authority()
        except ImportRightsDenied:
            raise
        except Exception as exc:
            raise ImportRightsDenied(evidence, "rights_authority_unavailable") from exc
        artifact_ref = f"{import_id}:{commit_id}"
        for requested_use, destination in IMPORT_RIGHTS_USES:
            try:
                decision = await resolver.resolve_request(
                    RightsDecisionRequest(
                        tenant_id=tenant_id,
                        source_id=source,
                        artifact_ref=artifact_ref,
                        artifact_class="tenant_import",
                        actor=principal,
                        actor_role="tenant_admin",
                        requested_use=requested_use,
                        purpose=IMPORT_RIGHTS_PURPOSE,
                        destination=destination,
                    )
                )
                if requested_use == "write_tenant_graph":
                    # CSV commits enforce this gate even if the general
                    # propagation rollout is off. The transient propagation
                    # value is only the existing stamp_intent carrier; the
                    # canonical resolver above made and persisted the decision.
                    graph_propagation = RightsPropagation(
                        decision=decision,
                        mode=RolloutMode.ENFORCE,
                        stamped=bool(getattr(decision, "allowed", False)),
                    )
                decisions[requested_use] = decision
            except ImportRightsDenied:
                raise
            except Exception as exc:
                current = self._evidence(
                    tenant_id, import_id, commit_id, source, principal,
                    decisions, graph_propagation=graph_propagation,
                )
                raise ImportRightsDenied(current, "rights_authority_unavailable") from exc

        grant_refs = {
            str(ref)
            for decision in decisions.values()
            for ref in (getattr(decision, "source_grant_refs", []) or [])
            if str(ref).strip()
        }
        reasons: list[str] = []
        for requested_use, _destination in IMPORT_RIGHTS_USES:
            decision = decisions.get(requested_use)
            if decision is None:
                reasons.append("rights_decision_missing")
                continue
            decision_ref = str(getattr(decision, "decision_id", "") or "")
            if not decision_ref.startswith("rdec_"):
                reasons.append("durable_decision_ref_missing")
            if (
                str(getattr(decision, "tenant_id", "") or "") != tenant_id
                or not str(getattr(decision, "policy_version", "") or "")
            ):
                reasons.append("rights_decision_scope_invalid")
            if not bool(getattr(decision, "allowed", False)):
                reasons.extend(getattr(decision, "reason_codes", []) or ["rights_denied"])
            refs = list(getattr(decision, "source_grant_refs", []) or [])
            if len(refs) != 1:
                reasons.append("source_grant_missing_or_ambiguous")

        if len(grant_refs) != 1 or not source:
            reasons.append("source_grant_missing_or_ambiguous")
        grant_ref = next(iter(grant_refs)) if len(grant_refs) == 1 else None
        if grant_ref is not None:
            try:
                grant = await service.get_grant(grant_ref, tenant_id=tenant_id)
            except Exception:
                grant = None
            relationship = str(getattr(grant, "source_relationship", "") or UNCLASSIFIED)
            if grant is None or relationship not in IMPORT_SOURCE_RELATIONSHIPS:
                reasons.append("source_relationship_mismatch")
        evidence = self._evidence(
            tenant_id, import_id, commit_id, source, principal, decisions,
            source_grant_ref=grant_ref,
            graph_propagation=graph_propagation,
            reasons=tuple(dict.fromkeys(reasons)),
        )
        if reasons:
            raise ImportRightsDenied(evidence)
        return evidence

    @asynccontextmanager
    async def hold_grant(self, evidence: ImportRightsEvidence) -> AsyncIterator[None]:
        """Close the revoke-between-decision-and-write race for this commit."""
        from config.settings import Environment, settings

        try:
            service = self._service()
        except Exception as exc:
            raise ImportRightsDenied(evidence, "grant_store_unavailable") from exc
        if not evidence.source_grant_ref or not evidence.source_id:
            raise ImportRightsDenied(evidence, "source_grant_missing_or_ambiguous")
        try:
            if (
                settings.env in (Environment.STAGING, Environment.PRODUCTION)
                and not await service.is_durable()
            ):
                raise ImportRightsDenied(evidence, "grant_store_not_durable")
        except ImportRightsDenied:
            raise
        except Exception as exc:
            raise ImportRightsDenied(evidence, "source_grant_unavailable") from exc

        hold_active = False
        try:
            async with service.hold_grant_unrevoked(
                evidence.source_grant_ref, tenant_id=evidence.tenant_id
            ):
                hold_active = True
                try:
                    grant = await service.get_effective_grant(
                        evidence.tenant_id, evidence.source_id
                    )
                except Exception as exc:
                    raise ImportRightsDenied(
                        evidence, "source_grant_unavailable"
                    ) from exc
                status = getattr(getattr(grant, "status", None), "value", None)
                if (
                    grant is None
                    or status != "active"
                    or str(getattr(grant, "data_rights_grant_id", "") or "")
                    != evidence.source_grant_ref
                    or str(getattr(grant, "tenant_id", "") or "") != evidence.tenant_id
                    or str(getattr(grant, "source_id", "") or "") != evidence.source_id
                ):
                    raise ImportRightsDenied(evidence, "source_grant_revoked_or_changed")
                yield
                hold_active = False
        except ImportRightsDenied:
            raise
        except Exception as exc:
            # Exceptions from the protected commit body must retain their real
            # failure cause. Only errors acquiring/checking the grant are rights
            # authority availability failures.
            if hold_active:
                raise
            raise ImportRightsDenied(evidence, "source_grant_unavailable") from exc


_import_rights_admission = ImportRightsAdmission()


def get_import_rights_admission() -> ImportRightsAdmission:
    return _import_rights_admission
