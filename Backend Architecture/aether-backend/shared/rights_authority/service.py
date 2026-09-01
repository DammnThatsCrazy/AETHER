"""AETHER's signed, effective-dated IRRL policy decision point."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from shared.logger.logger import get_logger, metrics
from shared.rights_authority.generated_registry import (
    RIGHTS_ACTION_DEFINITIONS,
    RIGHTS_PROFILE_DEFINITIONS,
    RIGHTS_TRANSFORM_DEFINITIONS,
)
from shared.rights_authority.contracts import (
    ArtifactRef,
    ArtifactRightsEnvelope,
    AttachRightsEnvelope,
    DerivationEdge,
    IssueRightsPolicySet,
    Obligation,
    RevokeRightsAuthority,
    RightsDecision,
    RightsImpactGraph,
    RightsImpactNode,
    RightsPolicySet,
    RightsUseRequest,
    TransformEvidence,
    UseGrant,
    lineage_hash,
)
from shared.rights_authority.repository import RightsLedgerRepository

logger = get_logger("aether.rights_authority")

_DISCLOSURE_RANK = {"none": 0, "masked": 1, "tenant_scoped": 2, "aggregate": 3, "raw": 4}
_SOURCE_GRANT_FIELDS = {
    "ingest": "tenant_lake_allowed",
    "store": "tenant_lake_allowed",
    "train": "model_training_allowed",
    "evaluate": "model_training_allowed",
    "aggregate": "cross_tenant_aggregate_allowed",
}


class RightsAuthorityUnavailable(RuntimeError):
    """Raised only for an unavailable authority dependency, never for denial."""


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_effective(start: Optional[str], end: Optional[str], at: datetime) -> bool:
    from_time = _parse_time(start)
    to_time = _parse_time(end)
    return (from_time is None or at >= from_time) and (to_time is None or at < to_time)


def _ref_tokens(ref: ArtifactRef) -> set[str]:
    return {ref.id, ref.ref, f"{ref.kind}:{ref.id}"}


class RightsAuthority:
    """Central PDP plus the append-only IRRL ledger.

    Expected policy denials are returned as signed ``RightsDecision`` records.
    Repository/key failures return ``unavailable`` so a dependency outage can
    never be rendered as an empty or successful product response.
    """

    def __init__(
        self,
        repository: Optional[RightsLedgerRepository] = None,
        *,
        signing_key: Optional[str | bytes] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.repository = repository or RightsLedgerRepository()
        self._signing_key_override = signing_key
        self._now = now or _now

    def _signing_key(self) -> bytes:
        value = self._signing_key_override
        if value is None:
            value = os.getenv("AETHER_RIGHTS_SIGNING_KEY")
        if value is None and os.getenv("AETHER_ENV", "local").lower() == "local":
            # Explicitly local-only test/development material. Production and
            # staging must provide a secret through the environment/secret vault.
            value = "local-development-rights-key"
        if not value:
            raise RightsAuthorityUnavailable("AETHER_RIGHTS_SIGNING_KEY is unavailable")
        return value.encode("utf-8") if isinstance(value, str) else value

    @staticmethod
    def _default_uses(profile: str) -> list[UseGrant]:
        definition = RIGHTS_PROFILE_DEFINITIONS.get(profile)
        if definition is None:
            raise ValueError(f"unknown rights profile: {profile}")
        return [UseGrant(action=action, purpose="*") for action in definition["allowedActions"]]

    async def issue_policy_set(self, command: IssueRightsPolicySet) -> RightsPolicySet:
        """Persist a policy set; an accepted agreement is the authority input."""
        allowed = command.allowed_uses or self._default_uses(command.rights_profile)
        policy = RightsPolicySet(
            tenant_id=command.tenant_id,
            agreement_ref=command.agreement_ref,
            rights_profile=command.rights_profile,
            effective_from=command.effective_from or self._now().isoformat(),
            effective_to=command.effective_to,
            deployment_constraints=command.deployment_constraints,
            allowed_uses=allowed,
            retention_rules=command.retention_rules,
            approval_refs=command.approval_refs,
            activation_state=command.activation_state,
        )
        await self.repository.append_policy(policy.model_dump(mode="json"))
        return policy

    async def attach_artifact(self, command: AttachRightsEnvelope) -> ArtifactRightsEnvelope:
        """Attach an immutable envelope to a material artifact."""
        policy = await self.repository.get_policy(command.policy_set_ref)
        if policy is None:
            raise RightsAuthorityUnavailable(f"policy set unavailable: {command.policy_set_ref}")
        roots = sorted(set(command.lineage_root_refs or [_ref_tokens(command.artifact_ref).pop()]))
        envelope = ArtifactRightsEnvelope(
            artifact_ref=command.artifact_ref,
            primary_rights_class=command.primary_rights_class,
            rights_holders=command.rights_holders,
            tenant_id=command.tenant_id or command.artifact_ref.tenant_id,
            source_grant_refs=command.source_grant_refs,
            consent_snapshot_refs=command.consent_snapshot_refs,
            source_license_refs=command.source_license_refs,
            classification_refs=command.classification_refs,
            lineage_root_refs=roots,
            retention_class=command.retention_class,
            retention_deadline=command.retention_deadline,
            effective_from=command.effective_from or self._now().isoformat(),
            effective_to=command.effective_to,
            legal_hold_ref=command.legal_hold_ref,
            policy_set_ref=command.policy_set_ref,
            lineage_set_hash=lineage_hash(roots),
            disclosure_ceiling=command.disclosure_ceiling,
        )
        await self.repository.append_envelope(envelope.model_dump(mode="json"))
        return envelope

    async def _find_envelopes(self, request: RightsUseRequest) -> list[dict[str, Any]]:
        wanted = set(request.envelope_refs)
        candidates = await self.repository.list_envelopes(request.tenant_id)
        result: list[dict[str, Any]] = []
        for envelope in candidates:
            artifact = envelope.get("artifact_ref") or {}
            tokens = {
                envelope.get("envelope_id"),
                artifact.get("id"),
                f"{artifact.get('kind')}:{artifact.get('id')}",
            }
            if wanted and not wanted.intersection(tokens):
                continue
            if not wanted and any(
                ref.kind == artifact.get("kind") and ref.id == artifact.get("id")
                for ref in request.artifacts
            ):
                pass
            elif not wanted:
                continue
            result.append(envelope)
        return result

    async def _policy(self, request: RightsUseRequest, envelopes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        policy_ref = request.policy_set_ref
        if not policy_ref and envelopes:
            policy_ref = envelopes[0].get("policy_set_ref")
        return await self.repository.get_policy(policy_ref) if policy_ref else None

    async def _source_grants(self, request: RightsUseRequest, envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs = set(request.source_grant_refs)
        for envelope in envelopes:
            refs.update(envelope.get("source_grant_refs") or [])
        grants: list[dict[str, Any]] = []
        for ref in sorted(refs):
            grant = await self.repository.get_latest_source_grant(ref)
            if grant is not None:
                grants.append(grant)
        return grants

    @staticmethod
    def _matches_use(policy: dict[str, Any], request: RightsUseRequest, envelopes: list[dict[str, Any]]) -> bool:
        classes = {e.get("primary_rights_class") for e in envelopes}
        for raw in policy.get("allowed_uses") or []:
            if raw.get("action") != request.action:
                continue
            if raw.get("purpose") not in ("*", request.purpose):
                continue
            allowed_classes = set(raw.get("rights_classes") or [])
            if allowed_classes and not classes.issubset(allowed_classes):
                continue
            destinations = set(raw.get("destinations") or [])
            if destinations and request.destination.kind not in destinations:
                continue
            expires = raw.get("expires_at")
            if expires and not _is_effective(None, expires, _parse_time(request.at) or _now()):
                continue
            return True
        return False

    async def _revoked_tokens(self, tenant_id: Optional[str]) -> set[str]:
        tokens: set[str] = set()
        for row in await self.repository.list_revocations(tenant_id):
            tokens.update(row.get("affected_refs") or row.get("root_refs") or [])
        return tokens

    def _signed(self, decision: RightsDecision) -> RightsDecision:
        payload = decision.model_dump(mode="json", exclude={"signature"})
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_key(), body, hashlib.sha256).hexdigest()
        return decision.model_copy(update={"signature": signature})

    def verify_signature(self, decision: RightsDecision) -> bool:
        try:
            expected = self._signed(decision.model_copy(update={"signature": ""})).signature
        except RightsAuthorityUnavailable:
            return False
        return hmac.compare_digest(expected, decision.signature)

    async def _finalize(self, decision: RightsDecision) -> RightsDecision:
        try:
            signed = self._signed(decision)
        except RightsAuthorityUnavailable as exc:
            signed = decision.model_copy(update={
                "outcome": "unavailable",
                "reasons": sorted(set(decision.reasons + ["signing_key_unavailable"])),
                "signature": "",
            })
        try:
            await self.repository.append_decision(signed.model_dump(mode="json"))
        except Exception as exc:
            logger.error("IRRL decision persistence unavailable: %s", exc)
            return signed.model_copy(update={
                "outcome": "unavailable",
                "reasons": sorted(set(signed.reasons + ["decision_persistence_unavailable"])),
            })
        try:
            from services.security.audit_ledger import audit_ledger

            actor_type = "olympus_operator" if signed.request_id and False else "system"
            await audit_ledger.record(
                actor_id="rights_authority",
                actor_type=actor_type,
                event_type="rights_authority.decision",
                resource_type="rights_decision",
                resource_id=signed.decision_id,
                action="evaluate",
                outcome="allowed" if signed.outcome in {"allow", "allow_with_obligations"} else "blocked",
                tenant_id=signed.tenant_id,
                policy_decision_id=signed.decision_id,
                metadata={"outcome": signed.outcome, "reasons": signed.reasons, "envelope_refs": signed.envelope_refs},
            )
        except Exception as exc:  # audit outage is visible, never a reason to allow
            logger.error("IRRL audit persistence unavailable: %s", exc)
            if signed.outcome in {"allow", "allow_with_obligations"}:
                return signed.model_copy(update={
                    "outcome": "unavailable",
                    "reasons": sorted(set(signed.reasons + ["audit_persistence_unavailable"])),
                })
        metrics.increment("rights_authority_decisions_total", labels={"outcome": signed.outcome})
        return signed

    async def evaluate(self, request: RightsUseRequest) -> RightsDecision:
        """Evaluate and persist one immutable decision before a material side effect."""
        at = _parse_time(request.at) or self._now()
        envelopes: list[dict[str, Any]] = []
        reasons: list[str] = []
        obligations: list[Obligation] = []
        try:
            if request.action not in RIGHTS_ACTION_DEFINITIONS:
                reasons.append("unknown_action")
            envelopes = await self._find_envelopes(request)
            action_def = RIGHTS_ACTION_DEFINITIONS.get(request.action, {})
            if action_def.get("requiresEnvelope") and not envelopes:
                reasons.append("rights_envelope_missing")
            policy = await self._policy(request, envelopes)
            if policy is None:
                reasons.append("policy_set_missing")
            else:
                if request.tenant_id and policy.get("tenant_id") != request.tenant_id:
                    reasons.append("policy_tenant_mismatch")
                if policy.get("activation_state") not in {"rights_active", "rights_restricted"}:
                    reasons.append("rights_activation_not_active")
                if not _is_effective(policy.get("effective_from"), policy.get("effective_to"), at):
                    reasons.append("policy_not_effective")
                if not self._matches_use(policy, request, envelopes):
                    reasons.append("use_not_allowed_by_policy")
                region = policy.get("deployment_constraints", {}).get("region")
                if region and request.destination.region and region != request.destination.region:
                    reasons.append("deployment_region_mismatch")

            grants = await self._source_grants(request, envelopes)
            if action_def.get("requiresSourceGrant"):
                if not grants:
                    reasons.append("source_grant_missing")
                else:
                    field = _SOURCE_GRANT_FIELDS.get(request.action)
                    for grant in grants:
                        if grant.get("tenant_id") != request.tenant_id:
                            reasons.append("source_grant_tenant_mismatch")
                        if grant.get("status") != "active" or grant.get("revoked_at"):
                            reasons.append("source_grant_inactive")
                        if not _is_effective(None, grant.get("expires_at"), at):
                            reasons.append("source_grant_expired")
                        if field and not grant.get(field, False):
                            reasons.append(f"{field}_not_granted")

            revoked = await self._revoked_tokens(request.tenant_id)
            for envelope in envelopes:
                artifact = envelope.get("artifact_ref") or {}
                tokens = {envelope.get("envelope_id"), artifact.get("id"), f"{artifact.get('kind')}:{artifact.get('id')}"}
                if revoked.intersection(tokens):
                    reasons.append("rights_revoked")
                if envelope.get("tenant_id") and request.tenant_id != envelope.get("tenant_id"):
                    reasons.append("artifact_tenant_mismatch")
                if not _is_effective(envelope.get("effective_from"), envelope.get("effective_to"), at):
                    reasons.append("artifact_rights_not_effective")
                if envelope.get("deletion_state") not in {None, "active"} and request.action not in {"delete", "retain"}:
                    reasons.append("artifact_not_active")
                if request.action == "delete" and envelope.get("legal_hold_ref"):
                    reasons.append("legal_hold_blocks_delete")
                ceiling = _DISCLOSURE_RANK.get(envelope.get("disclosure_ceiling", "none"), 0)
                if _DISCLOSURE_RANK.get(request.destination.disclosure_level, 0) > ceiling:
                    reasons.append("disclosure_exceeds_ceiling")

            if request.destination.kind == "olympus_plane":
                tenant_scoped = {
                    "tenant_contributed_data", "tenant_confidential_intelligence", "aether_computational_artifact",
                }
                if any(e.get("primary_rights_class") in tenant_scoped for e in envelopes):
                    if request.transform not in {"deidentification", "promote_to_olympus_generalized_graph"}:
                        reasons.append("tenant_artifact_cannot_enter_olympus_plane")

            if request.action == "derive":
                if not request.transform or request.transform not in RIGHTS_TRANSFORM_DEFINITIONS:
                    reasons.append("unregistered_transform")
                else:
                    definition = RIGHTS_TRANSFORM_DEFINITIONS[request.transform]
                    evidence = request.metadata.get("transform_evidence") or request.metadata.get("evidence") or {}
                    missing = [key for key in definition.get("requiresEvidence", []) if not evidence.get(key)]
                    if missing:
                        reasons.append(f"transform_evidence_missing:{','.join(sorted(missing))}")
                    if definition.get("requiresApproval") and not (request.metadata.get("approval_refs") or []):
                        reasons.append("transform_approval_missing")
                    if definition.get("outputClass") == "olympus_generalized_intelligence" and not evidence.get("release_proof"):
                        reasons.append("release_proof_missing")

            if request.action in {"ingest", "store", "derive", "graph_mutate"}:
                obligations.extend([Obligation(kind="stamp_lineage"), Obligation(kind="purpose_logging")])
            if request.action in {"read", "export", "disclose"}:
                obligations.append(Obligation(kind="provenance"))
            if request.action == "export":
                obligations.extend([Obligation(kind="recipient_binding", value=request.destination.id), Obligation(kind="export_restriction")])
            if request.action == "delete":
                obligations.append(Obligation(kind="recompute"))
            if envelopes:
                obligations.append(Obligation(kind="ttl", value=envelopes[0].get("retention_deadline") or envelopes[0].get("retention_class")))

            outcome = "allow_with_obligations" if not reasons and obligations else "allow" if not reasons else "deny"
            decision = RightsDecision(
                decision_id=(
                    "rdec_" + hashlib.sha256(
                        json.dumps({
                            "request_id": request.request_id,
                            "action": request.action,
                            "at": request.at,
                            "policy_set_ref": (policy or {}).get("policy_set_id"),
                            "envelope_refs": sorted(e.get("envelope_id") for e in envelopes),
                        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()[:32]
                ),
                outcome=outcome,
                evaluated_at=request.at,
                reasons=sorted(set(reasons)),
                obligations=obligations,
                envelope_refs=[e.get("envelope_id") for e in envelopes if e.get("envelope_id")],
                policy_set_ref=(policy or {}).get("policy_set_id"),
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                expires_at=(envelopes[0].get("effective_to") if envelopes else None),
            )
            return await self._finalize(decision)
        except Exception as exc:
            logger.error("IRRL evaluation unavailable: %s", exc)
            return await self._finalize(RightsDecision(
                outcome="unavailable",
                reasons=["rights_authority_unavailable", type(exc).__name__],
                envelope_refs=[e.get("envelope_id") for e in envelopes if e.get("envelope_id")],
                request_id=request.request_id,
                tenant_id=request.tenant_id,
            ))

    async def record_derivation(self, edge: DerivationEdge) -> None:
        if not edge.lineage_set_hash:
            edge = edge.model_copy(update={"lineage_set_hash": lineage_hash([p.ref for p in edge.parent_refs])})
        await self.repository.append_derivation(edge.model_dump(mode="json"))

    async def descendants(self, root_refs: list[str]) -> list[ArtifactRef]:
        edges = await self.repository.list_derivations()
        pending = set(root_refs)
        seen: set[str] = set()
        result: list[ArtifactRef] = []
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            for row in edges:
                parents = row.get("parent_refs") or []
                parent_tokens = {token for parent in parents for token in (parent.get("id"), f"{parent.get('kind')}:{parent.get('id')}" )}
                if current not in parent_tokens:
                    continue
                child = ArtifactRef(**row["child_ref"])
                if child.ref not in seen:
                    result.append(child)
                    pending.update(_ref_tokens(child))
        return result

    async def prove_transform(self, transform_ref: str, inputs: list[ArtifactRef], evidence: Optional[dict[str, Any]] = None) -> TransformEvidence:
        definition = RIGHTS_TRANSFORM_DEFINITIONS.get(transform_ref)
        if definition is None:
            raise ValueError(f"unregistered transform: {transform_ref}")
        evidence = evidence or {}
        missing = [key for key in definition.get("requiresEvidence", []) if not evidence.get(key)]
        approved = not missing and (not definition.get("requiresApproval") or bool(evidence.get("approval_refs")))
        return TransformEvidence(
            transform_ref=transform_ref,
            input_refs=[ref.ref for ref in inputs],
            evidence={**evidence, "missing": missing},
            output_class=definition["outputClass"],
            approved=approved,
            release_proof=evidence.get("release_proof"),
        )

    async def revoke(self, command: RevokeRightsAuthority) -> RightsImpactGraph:
        descendants = await self.descendants(command.root_refs)
        affected = set(command.root_refs)
        affected.update(token for ref in descendants for token in _ref_tokens(ref))
        for envelope in await self.repository.list_envelopes(command.tenant_id):
            artifact = envelope.get("artifact_ref") or {}
            if affected.intersection({envelope.get("envelope_id"), artifact.get("id"), f"{artifact.get('kind')}:{artifact.get('id')}"}):
                affected.add(envelope.get("envelope_id"))
        revocation_id = f"rrv_{hashlib.sha256(json.dumps(sorted(affected)).encode()).hexdigest()[:24]}"
        await self.repository.append_revocation({
            "revocation_id": revocation_id,
            "tenant_id": command.tenant_id,
            "root_refs": command.root_refs,
            "affected_refs": sorted(x for x in affected if x),
            "reason": command.reason,
            "actor": command.actor.model_dump(mode="json"),
            "created_at": self._now().isoformat(),
        })
        nodes: list[RightsImpactNode] = []
        for envelope in await self.repository.list_envelopes(command.tenant_id):
            artifact = envelope.get("artifact_ref") or {}
            if affected.intersection({envelope.get("envelope_id"), artifact.get("id"), f"{artifact.get('kind')}:{artifact.get('id')}"}):
                nodes.append(RightsImpactNode(
                    artifact_ref=ArtifactRef(**artifact),
                    remediation_action="quarantine_and_recompute",
                ))
        graph = RightsImpactGraph(
            tenant_id=command.tenant_id,
            root_refs=command.root_refs,
            nodes=nodes,
            reason=command.reason,
            status="open",
        )
        await self.repository.append_impact(graph.model_dump(mode="json"))
        metrics.increment("rights_authority_revocations_total")
        return graph

    async def impact(self, root_refs: list[str], tenant_id: Optional[str] = None) -> RightsImpactGraph:
        rows = await self.repository.list_impacts(tenant_id)
        for row in rows:
            if set(root_refs).intersection(row.get("root_refs") or []):
                clean = {
                    key: value for key, value in row.items()
                    if key not in {"id", "created_at", "updated_at"} and not key.startswith("_")
                }
                return RightsImpactGraph(**clean)
        return RightsImpactGraph(root_refs=root_refs, reason="impact_not_yet_open", status="blocked")


rights_authority = RightsAuthority()

__all__ = ["RightsAuthority", "RightsAuthorityUnavailable", "rights_authority"]
