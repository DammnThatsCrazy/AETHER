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
    ActorRef,
    AttachRightsEnvelope,
    DerivationEdge,
    IssueRightsPolicySet,
    Obligation,
    RevokeRightsAuthority,
    RightsDecision,
    RightsEvidenceManifest,
    RightsImpactGraph,
    RightsImpactNode,
    RightsPolicySet,
    RightsRemediationReceipt,
    RightsRemediationStep,
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
    return {ref.id, ref.ref, f"{ref.kind}:{ref.id}", f"{ref.kind}:{ref.id}:"}


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

    def _signing_key_id(self) -> str:
        return os.getenv("AETHER_RIGHTS_SIGNING_KEY_ID", "rights-v1")

    def _signing_key(self, key_id: Optional[str] = None) -> bytes:
        requested_key_id = key_id or self._signing_key_id()
        value = self._signing_key_override
        if value is None:
            keyring = os.getenv("AETHER_RIGHTS_SIGNING_KEYS")
            if keyring:
                try:
                    values = json.loads(keyring)
                    value = values.get(requested_key_id)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RightsAuthorityUnavailable(
                        "AETHER_RIGHTS_SIGNING_KEYS is invalid"
                    ) from exc
            if value is None:
                value = os.getenv("AETHER_RIGHTS_SIGNING_KEY")
        if value is None and os.getenv("AETHER_ENV", "local").lower() == "local":
            # Explicitly local-only test/development material. Production and
            # staging must provide a secret through the environment/secret vault.
            value = "local-development-rights-key"
        if not value:
            raise RightsAuthorityUnavailable("AETHER_RIGHTS_SIGNING_KEY is unavailable")
        raw = value.encode("utf-8") if isinstance(value, str) else value
        # Domain separation keeps a rights signature from being replayed as a
        # credential, webhook, or unrelated platform signature.
        return hmac.new(raw, b"aether/irrl/rights-decision/v1", hashlib.sha256).digest()

    @staticmethod
    def _default_uses(profile: str) -> list[UseGrant]:
        definition = RIGHTS_PROFILE_DEFINITIONS.get(profile)
        if definition is None:
            raise ValueError(f"unknown rights profile: {profile}")
        return [UseGrant(action=action, purpose="*") for action in definition["allowedActions"]]

    def _signed_evidence(self, manifest: RightsEvidenceManifest) -> RightsEvidenceManifest:
        key_id = self._signing_key_id()
        manifest = manifest.model_copy(update={"signature_key_id": key_id, "signature": ""})
        payload = manifest.model_dump(mode="json", exclude={"signature"})
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_key(key_id), body, hashlib.sha256).hexdigest()
        return manifest.model_copy(update={"signature": signature})

    def verify_evidence_manifest(self, manifest: RightsEvidenceManifest) -> bool:
        try:
            payload = manifest.model_copy(update={"signature": ""})
            body = json.dumps(
                payload.model_dump(mode="json", exclude={"signature"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected = hmac.new(
                self._signing_key(manifest.signature_key_id), body, hashlib.sha256
            ).hexdigest()
        except RightsAuthorityUnavailable:
            return False
        return hmac.compare_digest(expected, manifest.signature)

    async def issue_evidence_manifest(
        self,
        *,
        tenant_id: Optional[str],
        subject_refs: list[str],
        evidence: dict[str, list[str]],
        attested_by: Any,
        expires_at: Optional[str] = None,
    ) -> RightsEvidenceManifest:
        """Persist a signed manifest of evidence used by policy evaluation."""
        actor = attested_by if isinstance(attested_by, ActorRef) else ActorRef(**attested_by)
        if tenant_id and actor.tenant_id and actor.tenant_id != tenant_id:
            raise ValueError("evidence attestor tenant does not match manifest tenant")
        manifest = RightsEvidenceManifest(
            tenant_id=tenant_id,
            subject_refs=sorted(set(subject_refs)),
            evidence={key: sorted(set(values)) for key, values in evidence.items()},
            attested_by=actor,
            expires_at=expires_at,
        )
        signed = self._signed_evidence(manifest)
        await self.repository.append_evidence_manifest(signed.model_dump(mode="json"))
        return signed

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

    async def transition_policy_set(
        self,
        policy_set_ref: str,
        *,
        activation_state: str,
        actor: Any,
        evidence_ref: str,
    ) -> RightsPolicySet:
        """Append a reviewed policy-state transition; never rewrite history."""
        if activation_state not in {"rights_pending", "rights_review", "rights_active", "rights_restricted", "rights_revoked"}:
            raise ValueError(f"invalid rights activation state: {activation_state}")
        if not evidence_ref.strip():
            raise ValueError("policy state transition requires evidence_ref")
        current = await self.repository.get_policy(policy_set_ref)
        if current is None:
            raise RightsAuthorityUnavailable(f"policy set unavailable: {policy_set_ref}")
        policy_fields = set(RightsPolicySet.model_fields)
        updated = RightsPolicySet(**{
            key: value for key, value in current.items()
            if key in policy_fields
        }).model_copy(update={"activation_state": activation_state})
        revision = int(current.get("policy_revision", 1)) + 1
        payload = updated.model_dump(mode="json")
        payload.update({
            "policy_revision": revision,
            "transition_actor": actor.model_dump(mode="json") if hasattr(actor, "model_dump") else actor,
            "transition_evidence_ref": evidence_ref,
        })
        await self.repository.append_policy_revision(payload)
        return updated

    async def attach_artifact(self, command: AttachRightsEnvelope) -> ArtifactRightsEnvelope:
        """Attach an immutable envelope to a material artifact."""
        policy = await self.repository.get_policy(command.policy_set_ref)
        if policy is None:
            raise RightsAuthorityUnavailable(f"policy set unavailable: {command.policy_set_ref}")
        envelope_tenant = command.tenant_id or command.artifact_ref.tenant_id
        if envelope_tenant and policy.get("tenant_id") != envelope_tenant:
            raise ValueError("rights policy tenant does not match artifact tenant")
        for grant_ref in command.source_grant_refs:
            grant = await self.repository.get_latest_source_grant(grant_ref)
            if grant is None:
                raise RightsAuthorityUnavailable(f"source grant unavailable: {grant_ref}")
            if envelope_tenant and grant.get("tenant_id") != envelope_tenant:
                raise ValueError("source grant tenant does not match artifact tenant")
        for manifest_ref in command.evidence_manifest_refs:
            manifest = await self.repository.get_evidence_manifest(manifest_ref)
            if manifest is None:
                raise RightsAuthorityUnavailable(f"evidence manifest unavailable: {manifest_ref}")
            if envelope_tenant and manifest.get("tenant_id") not in {None, envelope_tenant}:
                raise ValueError("evidence manifest tenant does not match artifact tenant")
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
            evidence_manifest_refs=command.evidence_manifest_refs,
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
                f"{artifact.get('kind')}:{artifact.get('id')}:",
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

    async def _evidence_manifests(
        self, request: RightsUseRequest, envelopes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        refs = set(request.evidence_manifest_refs)
        for envelope in envelopes:
            refs.update(envelope.get("evidence_manifest_refs") or [])
        manifests: list[dict[str, Any]] = []
        for ref in sorted(refs):
            manifest = await self.repository.get_evidence_manifest(ref)
            if manifest is not None:
                manifests.append(manifest)
        return manifests

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

    def _context_reasons(
        self,
        policy: dict[str, Any],
        request: RightsUseRequest,
        envelopes: list[dict[str, Any]],
        grants: list[dict[str, Any]],
        manifests: list[dict[str, Any]],
    ) -> list[str]:
        """Resolve the reference-shaped parts of the effective rights set."""
        reasons: list[str] = []
        constraints = policy.get("deployment_constraints") or {}
        agreement = policy.get("agreement_ref") or {}
        if not agreement.get("contract_id") or not agreement.get("contract_version"):
            reasons.append("agreement_reference_incomplete")
        if not _parse_time(agreement.get("accepted_at")):
            reasons.append("agreement_acceptance_unverifiable")

        actor_kinds = set(constraints.get("allowed_actor_kinds") or [])
        if actor_kinds and request.actor.kind not in actor_kinds:
            reasons.append("actor_kind_not_allowed")
        if request.actor.tenant_id and request.tenant_id and request.actor.tenant_id != request.tenant_id:
            reasons.append("actor_tenant_mismatch")

        destinations = set(constraints.get("allowed_destinations") or [])
        if destinations and request.destination.kind not in destinations:
            reasons.append("destination_not_allowed")
        regions = set(
            constraints.get("allowed_regions")
            or constraints.get("sovereign_regions")
            or []
        )
        if regions and request.destination.region not in regions:
            reasons.append("sovereignty_region_not_allowed")

        requested_approvals = set(request.metadata.get("approval_refs") or [])
        policy_approvals = set(policy.get("approval_refs") or [])
        required_signatories = set(constraints.get("required_signatory_refs") or [])
        if required_signatories and not required_signatories.issubset(
            requested_approvals | policy_approvals
        ):
            reasons.append("required_signatory_missing")

        matching_grants = {
            str(grant.get("data_rights_grant_id") or grant.get("id"))
            for grant in grants
        }
        requested_grants = set(request.source_grant_refs)
        envelope_grants = {
            str(ref)
            for envelope in envelopes
            for ref in envelope.get("source_grant_refs") or []
        }
        missing_grants = (requested_grants | envelope_grants) - matching_grants
        if missing_grants:
            reasons.append("source_grant_reference_unresolved")

        requested_manifests = set(request.evidence_manifest_refs)
        envelope_manifests = {
            str(ref)
            for envelope in envelopes
            for ref in envelope.get("evidence_manifest_refs") or []
        }
        matching_manifests = {
            str(manifest.get("manifest_id") or manifest.get("id"))
            for manifest in manifests
        }
        if (requested_manifests | envelope_manifests) - matching_manifests:
            reasons.append("evidence_manifest_unresolved")
        at = _parse_time(request.at) or _now()
        for manifest in manifests:
            if manifest.get("tenant_id") not in {None, request.tenant_id}:
                reasons.append("evidence_manifest_tenant_mismatch")
            if manifest.get("status") != "active":
                reasons.append("evidence_manifest_inactive")
            if not self.verify_evidence_manifest(RightsEvidenceManifest(**{
                key: value for key, value in manifest.items()
                if key in RightsEvidenceManifest.model_fields
            })):
                reasons.append("evidence_manifest_signature_invalid")
            if not _is_effective(None, manifest.get("expires_at"), at):
                reasons.append("evidence_manifest_expired")

        required_evidence = set(constraints.get("required_evidence_kinds") or [])
        for evidence_kind in required_evidence:
            if not any((manifest.get("evidence") or {}).get(evidence_kind) for manifest in manifests):
                reasons.append(f"evidence_missing:{evidence_kind}")

        for envelope in envelopes:
            if envelope.get("policy_set_ref") != policy.get("policy_set_id"):
                reasons.append("envelope_policy_mismatch")
            roots = envelope.get("lineage_root_refs") or []
            if request.action in {"derive", "graph_mutate", "train", "evaluate", "export"} and not roots:
                reasons.append("lineage_root_missing")
            expected_hash = lineage_hash([str(ref) for ref in roots]) if roots else ""
            if roots and envelope.get("lineage_set_hash") != expected_hash:
                reasons.append("lineage_hash_mismatch")
            if constraints.get("require_consent_snapshot") and not envelope.get("consent_snapshot_refs"):
                reasons.append("consent_snapshot_missing")
            if constraints.get("require_source_license") and not envelope.get("source_license_refs"):
                reasons.append("source_license_missing")
            if constraints.get("require_classification") and not envelope.get("classification_refs"):
                reasons.append("classification_missing")
            if constraints.get("require_retention_rule") and not envelope.get("retention_class"):
                reasons.append("retention_rule_missing")
            retention_deadline = _parse_time(envelope.get("retention_deadline"))
            if retention_deadline and at >= retention_deadline and request.action not in {"delete", "retain"}:
                reasons.append("retention_deadline_expired")

        if constraints.get("require_consent_snapshot") and not any(
            envelope.get("consent_snapshot_refs") for envelope in envelopes
        ):
            reasons.append("consent_snapshot_missing")
        return reasons

    async def _revoked_tokens(self, tenant_id: Optional[str]) -> set[str]:
        tokens: set[str] = set()
        for row in await self.repository.list_revocations(tenant_id):
            tokens.update(row.get("affected_refs") or row.get("root_refs") or [])
        return tokens

    def _signed(self, decision: RightsDecision) -> RightsDecision:
        key_id = self._signing_key_id()
        decision = decision.model_copy(update={"signature_key_id": key_id, "signature": ""})
        payload = decision.model_dump(mode="json", exclude={"signature"})
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_key(key_id), body, hashlib.sha256).hexdigest()
        return decision.model_copy(update={"signature": signature})

    def verify_signature(self, decision: RightsDecision) -> bool:
        try:
            payload = decision.model_copy(update={"signature": ""})
            body = json.dumps(
                payload.model_dump(mode="json", exclude={"signature"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected = hmac.new(
                self._signing_key(decision.signature_key_id), body, hashlib.sha256
            ).hexdigest()
        except RightsAuthorityUnavailable:
            return False
        return hmac.compare_digest(expected, decision.signature)

    def _unavailable(self, decision: RightsDecision, reason: str) -> RightsDecision:
        """Return a self-consistent unavailable decision.

        A decision is immutable once written.  In particular, do not mutate an
        already-signed allow into an unavailable result: that would leave the
        signature and the durable ledger claiming different outcomes.
        """
        candidate = decision.model_copy(update={
            "outcome": "unavailable",
            "reasons": sorted(set(decision.reasons + [reason])),
            "signature": "",
        })
        try:
            return self._signed(candidate)
        except RightsAuthorityUnavailable:
            return candidate

    async def _finalize(self, decision: RightsDecision) -> RightsDecision:
        try:
            signed = self._signed(decision)
        except RightsAuthorityUnavailable:
            signed = self._unavailable(decision, "signing_key_unavailable")

        # A request id is an idempotency key. Return the original immutable
        # decision on retries before touching the audit ledger.
        if signed.request_id:
            try:
                existing = await self.repository.get_decision_by_request_id(signed.request_id)
            except Exception as exc:
                logger.error("IRRL decision replay lookup unavailable: %s", exc)
                return self._unavailable(signed, "decision_replay_lookup_unavailable")
            if existing is not None:
                return RightsDecision(**{
                    key: value for key, value in existing.items()
                    if key in RightsDecision.model_fields
                })

        audit_event = {
            "audit_event_id": f"raev_{signed.decision_id}",
            "actor_id": "rights_authority",
            "actor_type": "system",
            "event_type": "rights_authority.decision",
            "resource_type": "rights_decision",
            "resource_id": signed.decision_id,
            "action": "evaluate",
            "outcome": "allowed" if signed.outcome in {"allow", "allow_with_obligations"} else "blocked",
            "tenant_id": signed.tenant_id,
            "policy_decision_id": signed.decision_id,
            "metadata": {
                "outcome": signed.outcome,
                "reasons": signed.reasons,
                "envelope_refs": signed.envelope_refs,
            },
        }
        try:
            inserted = await self.repository.append_decision_with_audit_outbox(
                signed.model_dump(mode="json"), audit_event,
            )
        except Exception as exc:
            logger.error("IRRL decision/outbox persistence unavailable: %s", exc)
            return self._unavailable(signed, "decision_persistence_unavailable")
        if inserted:
            # The outbox is the atomic receipt. Mirror to the existing audit
            # ledger when available; a projection outage does not erase the
            # durable authorization receipt or turn a successful operation
            # into a misleading empty result.
            try:
                from services.security.audit_ledger import audit_ledger

                await audit_ledger.record(**{
                    key: value for key, value in audit_event.items()
                    if key in {
                        "audit_event_id", "actor_id", "actor_type", "event_type", "resource_type",
                        "resource_id", "action", "outcome", "tenant_id",
                        "policy_decision_id", "metadata",
                    }
                })
            except Exception as exc:
                logger.error("IRRL audit projection unavailable; outbox retained: %s", exc)
                metrics.increment("rights_authority_audit_projection_failures_total")
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
            manifests = await self._evidence_manifests(request, envelopes)
            if policy is not None:
                reasons.extend(self._context_reasons(policy, request, envelopes, grants, manifests))
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
                tokens = {
                    envelope.get("envelope_id"),
                    artifact.get("id"),
                    f"{artifact.get('kind')}:{artifact.get('id')}",
                    f"{artifact.get('kind')}:{artifact.get('id')}:",
                }
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
                # A generalized Olympus promotion discloses only the derived
                # output, never the source envelope itself.  The transform
                # evidence and the output envelope govern that boundary; the
                # source's tenant-scoped disclosure ceiling must not be
                # compared to the aggregate destination as if raw data were
                # being exported.
                source_is_transformed = (
                    request.destination.kind == "olympus_plane"
                    and request.transform in {
                        "deidentification",
                        "promote_to_olympus_generalized_graph",
                    }
                )
                if not source_is_transformed and _DISCLOSURE_RANK.get(request.destination.disclosure_level, 0) > ceiling:
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
                    envelope_classes = {
                        e.get("primary_rights_class") for e in envelopes
                    }
                    allowed_classes = set(definition.get("inputClasses") or [])
                    if envelope_classes and not envelope_classes.issubset(allowed_classes):
                        reasons.append("transform_input_class_not_allowed")
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
                evidence_manifest_refs=[
                    str(m.get("manifest_id")) for m in manifests if m.get("manifest_id")
                ],
                lineage_root_refs=sorted({
                    str(ref) for envelope in envelopes
                    for ref in envelope.get("lineage_root_refs") or []
                }),
                purpose=request.purpose,
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
                evidence_manifest_refs=[
                    str(m.get("manifest_id")) for m in manifests if m.get("manifest_id")
                ],
                lineage_root_refs=sorted({
                    str(ref) for envelope in envelopes
                    for ref in envelope.get("lineage_root_refs") or []
                }),
                purpose=request.purpose,
            ))

    async def record_derivation(self, edge: DerivationEdge) -> None:
        if not edge.lineage_set_hash:
            edge = edge.model_copy(update={"lineage_set_hash": lineage_hash([p.ref for p in edge.parent_refs])})
        await self.repository.append_derivation(edge.model_dump(mode="json"))

    async def record_remediation_step(self, step: RightsRemediationStep) -> RightsRemediationStep:
        """Append one immutable remediation state observation."""
        await self.repository.append_remediation_step(step.model_dump(mode="json"))
        return step

    async def record_remediation_receipt(
        self, receipt: RightsRemediationReceipt
    ) -> RightsRemediationReceipt:
        """Append the receipt for an attempted remediation side effect."""
        await self.repository.append_remediation_receipt(receipt.model_dump(mode="json"))
        return receipt

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
                parent_tokens = {
                    token
                    for parent in parents
                    for token in (
                        parent.get("id"),
                        f"{parent.get('kind')}:{parent.get('id')}",
                        f"{parent.get('kind')}:{parent.get('id')}:",
                    )
                }
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
        tenant_root = any(str(root).startswith("tenant:") for root in command.root_refs)
        for envelope in await self.repository.list_envelopes(command.tenant_id):
            artifact = envelope.get("artifact_ref") or {}
            if tenant_root or affected.intersection({
                envelope.get("envelope_id"),
                artifact.get("id"),
                f"{artifact.get('kind')}:{artifact.get('id')}",
                f"{artifact.get('kind')}:{artifact.get('id')}:",
            }):
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
        node_tokens: set[str] = set()
        for envelope in await self.repository.list_envelopes(command.tenant_id):
            artifact = envelope.get("artifact_ref") or {}
            if affected.intersection({
                envelope.get("envelope_id"),
                artifact.get("id"),
                f"{artifact.get('kind')}:{artifact.get('id')}",
                f"{artifact.get('kind')}:{artifact.get('id')}:",
            }):
                nodes.append(RightsImpactNode(
                    artifact_ref=ArtifactRef(**artifact),
                    remediation_action="quarantine_and_recompute",
                ))
                node_tokens.update(_ref_tokens(ArtifactRef(**artifact)))
        # Derivation edges are authoritative even when the derived artifact
        # has not yet received its own envelope (for example an old feature or
        # cache row). Keep it in the impact graph so remediation cannot silently
        # stop at the first envelope boundary.
        for descendant in descendants:
            if node_tokens.intersection(_ref_tokens(descendant)):
                continue
            nodes.append(RightsImpactNode(
                artifact_ref=descendant,
                remediation_action="quarantine_and_recompute",
            ))
            node_tokens.update(_ref_tokens(descendant))
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

    async def update_impact_status(
        self,
        impact_graph_id: str,
        status: str,
        *,
        receipt_refs: Optional[list[str]] = None,
    ) -> RightsImpactGraph:
        """Append a remediation status revision with execution receipts."""
        if status not in {"open", "in_progress", "completed", "blocked"}:
            raise ValueError(f"invalid impact status: {status}")
        current = await self.repository.get_impact(impact_graph_id)
        if current is None:
            raise RightsAuthorityUnavailable(f"impact graph unavailable: {impact_graph_id}")
        clean = {
            key: value for key, value in current.items()
            if key not in {"id", "created_at", "updated_at"}
            and not key.startswith("_")
            and key != "impact_revision"
        }
        graph = RightsImpactGraph(**clean).model_copy(update={"status": status})
        graph = graph.model_copy(update={
            "remediation_receipt_refs": sorted(set(
                graph.remediation_receipt_refs + (receipt_refs or [])
            )),
        })
        if status == "completed":
            graph = graph.model_copy(update={
                "nodes": [node.model_copy(update={"status": "remediated"}) for node in graph.nodes],
            })
        payload = graph.model_dump(mode="json")
        payload["impact_revision"] = int(current.get("impact_revision", 1)) + 1
        await self.repository.append_impact_revision(payload)
        return graph

    async def impact(self, root_refs: list[str], tenant_id: Optional[str] = None) -> RightsImpactGraph:
        rows = await self.repository.list_impacts(tenant_id)
        for row in rows:
            if set(root_refs).intersection(row.get("root_refs") or []):
                clean = {
                    key: value for key, value in row.items()
                    if key not in {"id", "created_at", "updated_at", "impact_revision"}
                    and not key.startswith("_")
                }
                return RightsImpactGraph(**clean)
        return RightsImpactGraph(root_refs=root_refs, reason="impact_not_yet_open", status="blocked")


rights_authority = RightsAuthority()

__all__ = ["RightsAuthority", "RightsAuthorityUnavailable", "rights_authority"]
