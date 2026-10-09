"""Identity Resolution Service — the canonical entry point.

Flow for each canonical event:
    1. Extract identity signals from event.
    2. Normalize signals.
    3. Hash sensitive values.
    4. Persist signal observations.
    5. Look up existing aliases/entities for this tenant.
    6. Score candidate matches.
    7. Apply merge policy.
    8. Create new canonical entity if needed.
    9. Link aliases if allowed.
    10. Merge entities if allowed.
    11. Create candidate/conflict if ambiguous.
    12. Write approved graph edges.
    13. Emit audit record.
    14. Emit metrics.
    15. Return decision response.

Idempotency: same event processed twice must not duplicate aliases,
graph edges, or merge records. The repository layer enforces this.
"""

from __future__ import annotations

import os
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

from .audit import IdentityAuditWriter
from .conflicts import IdentityConflictManager
from .decision_evidence import (
    IdentityDecisionEvidenceService,
    MERGE_POLICY_VERSION,
    decision_type_from_merge_decision,
)
from .exceptions import CrossTenantError, IdentityError
from .graph_writer import IdentityGraphWriter
from .hashing import (
    hash_email,
    hash_external_id,
    hash_fingerprint,
    hash_phone,
    hash_wallet,
    redact_display,
)
from .merge_policy import (
    MergePolicyContext,
    NON_MERGE_ELIGIBLE_SIGNAL_NAMES,
    evaluate,
    evaluate_operator_merge,
)
from .metrics import IdentityMetrics
from .models import (
    ConfidenceTier,
    DecisionType,
    EdgeType,
    EntityType,
    IdentityDecisionRecord,
    IdentityResolutionDecision,
    IdentitySignalType,
    IdentityVeto,
    MergeDecision,
    SubjectStatus,
    VetoType,
    REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED,
    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
    REASON_FRAGMENT_SPLIT,
    REASON_IDENTITY_CYCLE_BLOCKED,
    REASON_NEW_ENTITY,
)
from .repository import IdentityResolutionRepository
from .signals import extract_signals
from .confidence import CONSENT_REQUIRED_SIGNALS, has_stitching_consent, _has_consent
from .split_policy import SplitPolicyContext, evaluate_split
from .veto_engine import evaluate_vetoes, get_confidence_band
from .models import ConfidenceBand


def _event_entity_ids(
    tenant_id: str, event_id: str, policy_version: str
) -> tuple[str, str]:
    """Stable provisional entity/subject ids for at-least-once event delivery."""
    material = f"aether:identity-event:{tenant_id}:{event_id}:{policy_version}"
    return (
        str(uuid.uuid5(uuid.NAMESPACE_URL, material)),
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{material}:subject")),
    )

logger = get_logger("aether.identity.resolver")

_OPERATOR_MERGE_LOCKS: dict[str, "asyncio.Lock"] = {}
_OPERATOR_MERGE_LOCKS_GUARD: Optional["asyncio.Lock"] = None
_OPERATOR_MERGE_LOCKS_LOOP: Optional["asyncio.AbstractEventLoop"] = None


def _operator_merge_lock(key: str) -> "asyncio.Lock":
    import asyncio

    global _OPERATOR_MERGE_LOCKS_GUARD, _OPERATOR_MERGE_LOCKS_LOOP
    loop = asyncio.get_running_loop()
    if _OPERATOR_MERGE_LOCKS_LOOP is not loop:
        _OPERATOR_MERGE_LOCKS.clear()
        _OPERATOR_MERGE_LOCKS_GUARD = asyncio.Lock()
        _OPERATOR_MERGE_LOCKS_LOOP = loop
    assert _OPERATOR_MERGE_LOCKS_GUARD is not None
    # No await is needed while the dictionary is mutated: one event loop runs
    # this section atomically. Cross-process safety comes from deterministic
    # records and the route's durable review-claim CAS.
    return _OPERATOR_MERGE_LOCKS.setdefault(key, asyncio.Lock())

# Environments where strong (probabilistic) auto-linking is OFF by default.
_STRONG_AUTOLINK_DISABLED_ENVS = frozenset({"staging", "production", "prod"})


def _strong_autolink_enabled() -> bool:
    """Whether STRONG (probabilistic) auto-linking may merge automatically.

    Off by default in staging/production so probable-but-not-deterministic
    matches go to candidate/conflict review; deterministic auto-linking is
    unaffected. Explicit policy approval via a truthy
    ``AETHER_IDENTITY_STRONG_AUTOLINK`` re-enables it.
    """
    env = os.getenv("AETHER_ENV", "local").strip().lower()
    if env in _STRONG_AUTOLINK_DISABLED_ENVS:
        flag = os.getenv("AETHER_IDENTITY_STRONG_AUTOLINK", "")
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    return True


def _verified_email_merge_enabled() -> bool:
    """Verified-email deterministic merge. Deterministic evidence is safe by
    default; a kill switch can disable it operationally (blueprint §22/§66/§8)."""
    flag = os.getenv("AETHER_IDENTITY_VERIFIED_EMAIL_MERGE", "1")
    return flag.strip().lower() in {"1", "true", "yes", "on"}

# Signals that must be hashed before persistence
_HASH_ON_INGEST: dict[IdentitySignalType, str] = {
    IdentitySignalType.EMAIL_HASH: "email",
    IdentitySignalType.PHONE_HASH: "phone",
    IdentitySignalType.DEVICE_FINGERPRINT: "fingerprint",
}

# Signals that are attribution-only (never trigger identity merge)
_ATTRIBUTION_ONLY: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.CAMPAIGN_ID,
    IdentitySignalType.JOURNEY_ID,
})

# Signal *values* that never constitute identity sameness. A fragment made up
# solely of these carries no real identity evidence, so splitting it onto its
# own / another entity would assert sameness on campaign/attribution grounds
# alone — which is exactly what must be blocked. Combines the resolver's
# attribution-only set with merge_policy's non-merge-eligible telemetry denylist.
_NON_IDENTITY_SIGNAL_VALUES: frozenset[str] = frozenset(
    {t.value for t in _ATTRIBUTION_ONLY} | set(NON_MERGE_ELIGIBLE_SIGNAL_NAMES)
)


def _is_merge_eligible_signal(signal_value: str) -> bool:
    """True if a signal value can carry identity evidence (not campaign-only)."""
    return bool(signal_value) and signal_value not in _NON_IDENTITY_SIGNAL_VALUES


# Signals of the event through which an authenticated binding may reach a
# candidate: the event's own user_id, or the anonymous_id it binds to it.
_BINDING_SIGNAL_TYPES: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.USER_ID,
    IdentitySignalType.ANONYMOUS_ID,
})

# Identifiers that name exactly one real person/account: two different values
# across the candidates of a binding mean the binding would fuse two people.
_BINDING_DETERMINISTIC_TYPES: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.USER_ID,
    IdentitySignalType.EXTERNAL_ID,
    IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
})

# Signals that can be shared across people. When they are the only path to a
# candidate and the incoming tenant/app-scoped user ID contradicts it, retain
# a separate profile instead of reusing the shared-signal target.
_SHARED_IDENTITY_SIGNAL_TYPES: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.ANONYMOUS_ID,
    IdentitySignalType.SESSION_ID,
    IdentitySignalType.DEVICE_FINGERPRINT,
    IdentitySignalType.BROWSER_ID,
    IdentitySignalType.INSTALLATION_ID,
    IdentitySignalType.MOBILE_INSTALL_ID,
})


def _dedupe_types(items: list[IdentitySignalType]) -> list[IdentitySignalType]:
    return list(dict.fromkeys(items))


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


class _CandidateStateUnavailable(RuntimeError):
    """A candidate could not be proven safe from tenant-owned graph state."""


def _candidate_veto_entity_type(value: Any) -> str:
    """Map persisted subject entity types to the veto engine's vocabulary."""
    raw = str(getattr(value, "value", value) or "").strip().lower()
    aliases = {
        "human": "person",
        "person": "person",
        "anonymous_visitor": "person",
        "commerce_customer": "person",
        "payment_customer": "person",
        "organization": "account",
        "org": "account",
        "account": "account",
        "agent": "agent",
        "device": "device",
        "session": "session",
        "wallet": "wallet",
    }
    mapped = aliases.get(raw)
    if not mapped:
        raise _CandidateStateUnavailable("candidate_entity_type_unrecognized")
    return mapped


def _incoming_veto_entity_type(signal_types: list[IdentitySignalType]) -> str | None:
    """Infer a narrow incoming subject class from extracted canonical signals."""
    person_signals = {
        IdentitySignalType.USER_ID,
        IdentitySignalType.EMAIL_HASH,
        IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
        IdentitySignalType.PHONE_HASH,
        IdentitySignalType.COMMERCE_CUSTOMER_ID,
        IdentitySignalType.PAYMENT_CUSTOMER_ID,
    }
    account_signals = {
        IdentitySignalType.ACCOUNT_ID,
        IdentitySignalType.ORG_ID,
    }
    agent_signals = {IdentitySignalType.AGENT_ID}
    wallet_signals = {IdentitySignalType.WALLET_ADDRESS}
    has_person = any(signal in person_signals for signal in signal_types)
    has_account = any(signal in account_signals for signal in signal_types)
    has_agent = any(signal in agent_signals for signal in signal_types)
    has_wallet = any(signal in wallet_signals for signal in signal_types)
    classified = sum((has_person, has_account, has_agent, has_wallet))
    if classified > 1:
        raise _CandidateStateUnavailable("incoming_entity_type_ambiguous")
    if has_person:
        return "person"
    if has_account:
        return "account"
    if has_agent:
        return "agent"
    if has_wallet:
        return "wallet"
    return None


@dataclass
class _FragmentSplitPlan:
    """Result of analysing a fragment split (shared by preview + execute).

    A plan is either a rejection (``allowed=False`` + ``rejection_reason``) or
    an approved, fully-resolved plan describing exactly what execution will
    move/revoke. Analysis is strictly read-only, so the same plan powers the
    non-mutating preview and the mutating execute path.
    """
    allowed: bool
    entity_id: str
    mode: str
    reason: str
    actor_type: str
    actor_id: str
    source_merge_event_id: Optional[str]
    target_entity_id: Optional[str]        # resolved dest (None → mint new at execute)
    alias_rows: list[dict] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    edges_to_revoke: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    source_entity_type: Optional[str] = None
    rejection_reason: Optional[str] = None
    error: Optional[str] = None


class IdentityResolutionService:
    """
    Orchestrates the full identity resolution pipeline for a single event
    or a direct operator action.
    """

    def __init__(
        self,
        repo: IdentityResolutionRepository,
        graph_writer: IdentityGraphWriter,
        audit_writer: IdentityAuditWriter,
        conflict_manager: IdentityConflictManager,
        metrics: IdentityMetrics,
        decision_evidence: Optional[IdentityDecisionEvidenceService] = None,
        producer: Optional[EventProducer] = None,
        policy_evaluators: Optional[dict[str, Any]] = None,
    ) -> None:
        self._repo = repo
        self._graph = graph_writer
        self._audit = audit_writer
        self._conflicts = conflict_manager
        self._metrics = metrics
        # Additive decision-evidence trail (prompt §3.3). Optional + injectable
        # so a recording failure can never break resolution; defaults to the
        # real recorder when not supplied.
        self._decision_evidence = decision_evidence or IdentityDecisionEvidenceService()
        # Event producer used to publish IDENTITY_MERGED for automatic auto-merges
        # so downstream restatement fires (see _publish_identity_merged). Optional
        # and injectable (tests pass a fake); when not supplied it is resolved
        # lazily from the shared registry — the same producer the operator merge
        # route publishes through — because routes.py builds this service without
        # one. See _resolve_producer.
        self._producer = producer
        # Versions identify executable policy, not caller-provided labels. By
        # default this process supports only the policy implementation present
        # in this checkout. A rollout may register another evaluator explicitly.
        # Keep the active policy dynamically referenced so focused test/ops
        # overrides that replace the resolver module's evaluator remain
        # effective; explicit historical/future versions are bound directly.
        self._policy_evaluators = {MERGE_POLICY_VERSION: lambda ctx: evaluate(ctx)}
        if policy_evaluators:
            self._policy_evaluators.update(policy_evaluators)

    def supports_policy_version(self, policy_version: str) -> bool:
        """Return whether this resolver has an evaluator for the version."""
        return bool(policy_version) and policy_version in self._policy_evaluators

    # ── Main entry point ──────────────────────────────────────────────────

    async def resolve_event(
        self,
        event: dict[str, Any],
        tenant_id: str,
        *,
        policy_version: str = MERGE_POLICY_VERSION,
    ) -> IdentityResolutionDecision:
        """
        Resolve identity for a single canonical event payload.
        Returns the resolution decision (idempotent).
        """
        from config.settings import settings

        if not self.supports_policy_version(policy_version):
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.BLOCKED,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=["unsupported_policy_version"],
                blocked_reason="unsupported_policy_version",
                policy_version=policy_version,
            )

        if not settings.identity_continuity.resolution_enabled:
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.BLOCKED,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=["identity_resolution_disabled"],
                blocked_reason="identity_resolution_disabled",
                policy_version=policy_version,
            )
        try:
            return await self._resolve_event_inner(event, tenant_id, policy_version)
        except CrossTenantError:
            self._metrics.record_blocked("cross_tenant")
            raise
        except IdentityError as exc:
            logger.warning("Identity error during resolution: %s", exc)
            self._metrics.record_resolve(success=False, tenant_id=tenant_id)
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.BLOCKED,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=[str(exc)],
                blocked_reason=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected identity resolution error: %s", exc, exc_info=True)
            self._metrics.record_resolve(success=False, tenant_id=tenant_id)
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.NOOP,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=["internal_error"],
            )

    async def _resolve_event_inner(
        self,
        event: dict,
        tenant_id: str,
        policy_version: str = MERGE_POLICY_VERSION,
    ) -> IdentityResolutionDecision:
        event_id = event.get("event_id", "")
        consent_snapshot = _extract_consent(event)

        # Recompute path: caller provides pre-hashed signals to bypass
        # extract/normalize/hash/persist steps (observations already in DB).
        _pre_hashed = event.get("_pre_hashed_signals")
        if _pre_hashed is not None:
            raw_signals: list = []
            hashed_signals: list[tuple[IdentitySignalType, str, str]] = []
            for item in _pre_hashed:
                try:
                    sig_type = IdentitySignalType(item["type"])
                    hashed_signals.append((sig_type, item["hash"], item.get("display", "")))
                except (ValueError, KeyError):
                    continue
            if not hashed_signals:
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id="",
                    decision=MergeDecision.NOOP,
                    confidence=0.0,
                    confidence_tier=ConfidenceTier.WEAK,
                    reason_codes=["no_signals"],
                )
        else:
            # ── 1. Extract signals ────────────────────────────────────────────
            raw_signals = extract_signals(event, tenant_id)
            if not raw_signals:
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id="",
                    decision=MergeDecision.NOOP,
                    confidence=0.0,
                    confidence_tier=ConfidenceTier.WEAK,
                    reason_codes=["no_signals"],
                )

            # ── 2 & 3. Normalize + hash sensitive values ──────────────────────
            hashed_signals = []
            # (type, hash, display_redacted)
            for sig in raw_signals:
                h, display = _hash_signal(sig.type, sig.value, tenant_id)
                if h:
                    hashed_signals.append((sig.type, h, display))
                    self._metrics.record_signal_observation(sig.type.value)

            # ── 4. Persist signal observations ────────────────────────────────
            for sig in raw_signals:
                h, display = _hash_signal(sig.type, sig.value, tenant_id)
                if h:
                    await self._repo.create_signal_observation(
                        tenant_id=tenant_id,
                        source_event_id=event_id,
                        source_platform=sig.source_platform,
                        source_sdk=sig.source_sdk,
                        signal_type=sig.type,
                        signal_value_hash=h,
                        raw_value_redacted=display,
                        observed_at=sig.observed_at,
                        consent_snapshot=sig.consent_snapshot,
                        context={"source": sig.source},
                    )

        # ── 4b. Check suppression rules ───────────────────────────────────
        suppressed_types: list[IdentitySignalType] = []
        filtered_signals: list[tuple[IdentitySignalType, str, str]] = []
        for (sig_type, sig_hash, display) in hashed_signals:
            is_suppressed = await self._repo.check_suppression(
                tenant_id, sig_type.value, sig_hash
            )
            # A suppression on the observed email hash also suppresses the
            # verified-ownership signal for the SAME hash — the identifier is
            # forbidden from linking identities regardless of assurance level
            # (blueprint §41).
            if not is_suppressed and sig_type == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED:
                is_suppressed = await self._repo.check_suppression(
                    tenant_id, IdentitySignalType.EMAIL_HASH.value, sig_hash
                )
            if is_suppressed:
                suppressed_types.append(sig_type)
                self._metrics.record_blocked("suppression")
            else:
                filtered_signals.append((sig_type, sig_hash, display))
        if suppressed_types:
            logger.info(
                "Suppressed signals for tenant=%s: %s",
                tenant_id, [t.value for t in suppressed_types],
            )
        # Build exact (type, hash) pairs that were suppressed, then filter raw_signals
        # using those pairs only — not the entire type — so unsuppressed signals of the
        # same type (e.g., a second wallet address) are not incorrectly removed.
        filtered_hash_set = {(t, h) for (t, h, _) in filtered_signals}
        suppressed_pairs: set[tuple[IdentitySignalType, str]] = {
            (t, h) for (t, h, _) in hashed_signals if (t, h) not in filtered_hash_set
        }
        hashed_signals = filtered_signals
        if suppressed_pairs:
            raw_signals = [
                sig for sig in raw_signals
                if (sig.type, _hash_signal(sig.type, sig.value, tenant_id)[0])
                not in suppressed_pairs
            ]

        # ── 5. Find existing aliases/entities for this tenant ─────────────
        existing_entity_ids: list[str] = []
        matching_types: list[IdentitySignalType] = []
        revoked_types: list[IdentitySignalType] = []
        # candidate entity id -> the signal types of THIS event that reached it
        found_via: dict[str, set[IdentitySignalType]] = {}

        for (sig_type, sig_hash, _) in hashed_signals:
            if sig_type in _ATTRIBUTION_ONLY:
                continue
            lookup_types = [sig_type]
            if sig_type == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED:
                # Verified-email and observed-email hashes share the same
                # tenant-scoped digest; include both persisted aliases when
                # checking for a revoked identifier veto.
                lookup_types.append(IdentitySignalType.EMAIL_HASH)
            for lookup_type in lookup_types:
                historical_aliases = await self._repo.find_aliases_by_signal(
                    tenant_id, lookup_type, sig_hash, include_revoked=True
                )
                if any(alias.get("revoked_at") for alias in historical_aliases):
                    if sig_type not in revoked_types:
                        revoked_types.append(sig_type)
            entity_ids = await self._repo.find_subjects_by_alias(
                tenant_id, sig_type, sig_hash
            )
            # Aliases stay on a merged fragment (fragment-aware repair needs
            # them there); follow the merge tombstone so a match lands on the
            # surviving entity instead of resurrecting a merged one.
            entity_ids = await self._surviving_entity_ids(tenant_id, entity_ids)
            if sig_type == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED:
                # hash_email() yields the SAME hash for the observed EMAIL_HASH
                # alias and the verified evidence identifier, so verified email
                # must also discover entities that carry only the observed alias.
                observed_ids = await self._repo.find_subjects_by_alias(
                    tenant_id, IdentitySignalType.EMAIL_HASH, sig_hash
                )
                entity_ids = list(dict.fromkeys([*entity_ids, *observed_ids]))
            if entity_ids:
                matching_types.append(sig_type)
                for eid in entity_ids:
                    found_via.setdefault(eid, set()).add(sig_type)
                    if eid not in existing_entity_ids:
                        existing_entity_ids.append(eid)

        # Aliases intentionally remain attached to merged fragments for
        # provenance and reversible identity history. They must not make a
        # later replay treat the tombstoned entity as another live candidate,
        # which would write duplicate merge/audit/projection effects under a
        # new policy version. Resolve every match to its tenant-local survivor
        # before conflict detection and policy evaluation.
        if existing_entity_ids:
            canonical_ids = [
                await self._repo.resolve_surviving_canonical_entity_id(tenant_id, eid)
                for eid in existing_entity_ids
            ]
            existing_entity_ids = list(dict.fromkeys(canonical_ids))

        # The durable SDK worker supplies the current owner of this
        # source-scoped identity. It is internal evidence loaded from the
        # tenant's SourceIdentity record, never a caller-selected canonical ID.
        source_entity_id = event.get("_source_canonical_entity_id")
        if isinstance(source_entity_id, str) and source_entity_id.strip():
            source_entity_id = source_entity_id.strip()
            source_subject = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, source_entity_id
            )
            if source_subject and source_subject.get("tenant_id") == tenant_id:
                source_entity_id = await self._repo.resolve_surviving_canonical_entity_id(
                    tenant_id, source_entity_id
                )
                if source_entity_id not in existing_entity_ids:
                    existing_entity_ids.append(source_entity_id)
                    source_signal_types = {
                        signal_type
                        for signal_type, _, _ in hashed_signals
                        if signal_type not in _ATTRIBUTION_ONLY
                    }
                    found_via.setdefault(source_entity_id, set()).update(
                        source_signal_types
                    )
                    matching_types.extend(
                        signal_type
                        for signal_type in source_signal_types
                        if signal_type not in matching_types
                    )
            else:
                source_entity_id = None
        else:
            source_entity_id = None

        # ── 6. Check for conflicting strong aliases ───────────────────────
        has_conflict = len(existing_entity_ids) > 1 and _has_strong_signal(matching_types)
        verified_present = any(
            t in {
                IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
                IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
            }
            for t in matching_types
        )
        if verified_present and len(existing_entity_ids) > 1:
            # Verified ownership can merge fragments; but only if they carry no
            # CONTRADICTORY deterministic identifier. Re-derive the conflict flag
            # from the candidate entities' deterministic aliases.
            has_conflict = await self._has_deterministic_conflict(
                tenant_id, existing_entity_ids
            )

        # ── 6b. Authenticated binding (anonymous_id -> user_id) ─────────────
        # An event that carries a user_id together with its anonymous_id (an
        # SDK identify, or any event after identify) is the SDK asserting that
        # this anonymous visitor IS that user: deterministic evidence, not a
        # probabilistic anonymous-id match. It authorizes collapsing the
        # candidates only when every candidate was reached through this
        # event's user_id / anonymous_id and no candidate (including anything
        # already merged into it) holds a DIFFERENT user_id, external_id or
        # verified wallet -- a shared device must never fuse two people.
        authenticated_binding = False
        binding_contradicted = False
        event_user_hashes = {
            h for (t, h, _) in hashed_signals if t == IdentitySignalType.USER_ID
        }
        conflicting_user_identity = False
        if existing_entity_ids and len(event_user_hashes) == 1:
            conflicting_user_identity = await self._has_conflicting_user_id(
                tenant_id, existing_entity_ids, next(iter(event_user_hashes))
            )
        identity_signal_types = {
            t for (t, _, _) in hashed_signals if t not in _ATTRIBUTION_ONLY
        }
        separate_user_profile = bool(
            conflicting_user_identity
            and IdentitySignalType.USER_ID in identity_signal_types
            and identity_signal_types <= (
                _SHARED_IDENTITY_SIGNAL_TYPES | {IdentitySignalType.USER_ID}
            )
            and _has_consent(consent_snapshot)
        )
        event_has_anonymous = any(
            t == IdentitySignalType.ANONYMOUS_ID for (t, _, _) in hashed_signals
        )
        if (
            existing_entity_ids
            and len(event_user_hashes) == 1
            and event_has_anonymous
            and IdentitySignalType.ANONYMOUS_ID in matching_types
            and all(
                found_via.get(eid, set()) & _BINDING_SIGNAL_TYPES
                for eid in existing_entity_ids
            )
        ):
            binding_contradicted = await self._binding_contradicted(
                tenant_id, existing_entity_ids, next(iter(event_user_hashes))
            )
            if binding_contradicted:
                has_conflict = True
            else:
                authenticated_binding = True
                has_conflict = False

        # Anonymous-to-user contradictions keep the existing review workflow:
        # the new profile is created, while the conflicting candidate remains
        # attached to a durable conflict record. The separate-profile path is
        # reserved for a person reached only through non-binding shared-device
        # or session evidence.
        if binding_contradicted:
            separate_user_profile = False

        # ── 7. Apply merge policy ─────────────────────────────────────────
        # Strong (probabilistic) auto-linking is OFF by default in staging/
        # production — those signals go to candidate/conflict review instead of
        # silently merging. Deterministic auto-linking (verified user_id/
        # external_id/wallet) stays enabled. Explicit policy approval via
        # AETHER_IDENTITY_STRONG_AUTOLINK re-enables strong auto-link.
        policy_ctx = MergePolicyContext(
            tenant_id=tenant_id,
            source_tenant_id=tenant_id,
            matching_signal_types=list(dict.fromkeys([*matching_types, *revoked_types])),
            consent_snapshot=consent_snapshot,
            revoked_signal_types=revoked_types,
            has_conflict=has_conflict,
            existing_entity_ids=existing_entity_ids,
            auto_link_strong=_strong_autolink_enabled(),
            verified_present=verified_present,
            auto_merge_verified=_verified_email_merge_enabled(),
            observed_signal_types=_dedupe_types([
                t for (t, _, _) in hashed_signals if t not in _ATTRIBUTION_ONLY
            ]),
            authenticated_binding=authenticated_binding,
        )
        policy_result = self._policy_evaluators[policy_version](policy_ctx)

        # A consented deterministic app user ID on a first-seen profile is an
        # anchor, not a match. Materialize that profile as CREATE and retain
        # its keyed alias so subsequent platform SDKs for the same tenant app
        # can resolve to it. Consent is required here because there is no
        # existing alias yet for the policy scorer to evaluate.
        identity_consent_valid = _has_consent(consent_snapshot)
        initial_user_id_anchor = False

        if (
            not existing_entity_ids
            and policy_result.decision == MergeDecision.BLOCKED
            and "insufficient_evidence" in policy_result.reason_codes
            and not revoked_types
            and any(sig_type == IdentitySignalType.USER_ID for sig_type, _, _ in hashed_signals)
            and identity_consent_valid
        ):
            initial_user_id_anchor = True
            policy_result.decision = MergeDecision.CREATE
            policy_result.reason_codes = [REASON_NEW_ENTITY, "consented_sdk_user_id_anchor"]

        from config.settings import settings

        continuity = settings.identity_continuity
        if (
            policy_result.decision == MergeDecision.MERGE
            and not continuity.auto_merge_enabled
        ):
            policy_result.decision = (
                MergeDecision.CANDIDATE
                if continuity.manual_review_enabled
                else MergeDecision.BLOCKED
            )
            policy_result.reason_codes = list(policy_result.reason_codes) + [
                "auto_merge_disabled"
            ]

        # Verified evidence may collapse ALL compatible candidates — when the
        # policy authorized a multi-candidate merge but could not pick a target,
        # choose the deterministic survivor here (blueprint §25).
        if (
            getattr(policy_result, "merge_all_candidates", False)
            and not policy_result.merge_target_entity_id
            and existing_entity_ids
        ):
            policy_result.merge_target_entity_id = await self._pick_survivor(
                tenant_id, existing_entity_ids
            )

        # ── 7b. Hard veto evaluation — any veto forces BLOCKED band regardless of score (blueprint §8.2/§8.3)
        # Veto engine is wired here so a high confidence score can never override a hard veto.
        _vetoes = []
        try:
            # Candidate state comes only from tenant-scoped canonical subject
            # rows and aliases. Do not infer candidate status/type from the
            # incoming SDK payload. A lookup or integrity failure becomes a
            # hard veto below so the policy score cannot bypass it.
            candidate_entity_types: list[str] = []
            candidate_statuses: list[str] = []
            candidate_device_ids: set[str] = set()
            candidate_verified_emails: list[tuple[str, str]] = []
            candidate_authenticated_user_ids: list[tuple[str, str]] = []
            candidate_has_revoked_consent = bool(revoked_types)
            current_device_ids = {
                signal_hash
                for signal_type, signal_hash, _ in hashed_signals
                if signal_type in {
                    IdentitySignalType.DEVICE_FINGERPRINT,
                    IdentitySignalType.BROWSER_ID,
                    IdentitySignalType.INSTALLATION_ID,
                    IdentitySignalType.MOBILE_INSTALL_ID,
                }
            }
            current_verified_emails = [
                signal_hash
                for signal_type, signal_hash, _ in hashed_signals
                if signal_type == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED
            ]
            current_authenticated_user_ids = [
                signal_hash
                for signal_type, signal_hash, _ in hashed_signals
                if signal_type == IdentitySignalType.USER_ID
            ]
            incoming_entity_type = _incoming_veto_entity_type(matching_types)
            veto_device_signal_types = {
                IdentitySignalType.DEVICE_FINGERPRINT.value,
                IdentitySignalType.BROWSER_ID.value,
                IdentitySignalType.INSTALLATION_ID.value,
                IdentitySignalType.MOBILE_INSTALL_ID.value,
            }
            signal_pairs = {(sig_type.value, sig_hash) for sig_type, sig_hash, _ in hashed_signals}
            for candidate_entity_id in existing_entity_ids:
                subject = await self._repo.get_subject_by_canonical_entity_id(
                    tenant_id, candidate_entity_id
                )
                if (
                    not subject
                    or subject.get("tenant_id") != tenant_id
                    or subject.get("canonical_entity_id") != candidate_entity_id
                ):
                    raise _CandidateStateUnavailable("candidate_subject_unavailable")
                status = str(subject.get("status") or "").strip().lower()
                if status not in {
                    SubjectStatus.ACTIVE.value,
                    "deleted",
                    "suppressed",
                }:
                    raise _CandidateStateUnavailable("candidate_subject_status_unrecognized")
                candidate_statuses.append(status)
                candidate_entity_types.append(
                    _candidate_veto_entity_type(subject.get("entity_type"))
                )
                aliases = await self._repo.get_aliases_for_entity(
                    tenant_id, candidate_entity_id, include_revoked=True
                )
                for alias in aliases:
                    if (
                        alias.get("tenant_id") != tenant_id
                        or alias.get("canonical_entity_id") != candidate_entity_id
                    ):
                        raise _CandidateStateUnavailable("candidate_alias_scope_mismatch")
                    alias_type = str(alias.get("alias_type") or "")
                    alias_hash = str(alias.get("alias_value_hash") or "")
                    if alias_type in veto_device_signal_types and alias_hash:
                        candidate_device_ids.add(alias_hash)
                    if alias_type == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED.value and alias_hash:
                        candidate_verified_emails.append((alias_hash, candidate_entity_id))
                    if alias_type == IdentitySignalType.USER_ID.value and alias_hash:
                        candidate_authenticated_user_ids.append((alias_hash, candidate_entity_id))
                    if alias.get("revoked_at") and (alias_type, alias_hash) in signal_pairs:
                        candidate_has_revoked_consent = True

            # Gather veto inputs from repository-owned candidate state plus
            # the resolver's canonicalized incoming signal types. Caller
            # fields such as `entity_type` are deliberately ignored.
            _vetoes = await evaluate_vetoes(
                tenant_id=tenant_id,
                candidate_tenant_id=tenant_id,  # same-tenant path; cross-tenant already blocked above
                candidate_entity_types=candidate_entity_types,
                candidate_statuses=candidate_statuses,
                candidate_verified_emails=candidate_verified_emails,
                candidate_authenticated_user_ids=candidate_authenticated_user_ids,
                candidate_device_ids=sorted(candidate_device_ids),
                candidate_has_revoked_consent=candidate_has_revoked_consent,
                candidate_is_deleted="deleted" in candidate_statuses,
                candidate_is_suppressed="suppressed" in candidate_statuses,
                candidate_source_namespaces=[],
                current_entity_type=incoming_entity_type,
                current_device_ids=sorted(current_device_ids),
                current_verified_emails=current_verified_emails,
                current_authenticated_user_ids=current_authenticated_user_ids,
            )
            if separate_user_profile or binding_contradicted:
                # The contradictory authenticated user proves this is a
                # different person. Shared-device and conflicting-user vetoes
                # still prevent merging, but should not force the new person
                # onto the existing profile.
                _vetoes = [
                    veto for veto in _vetoes
                    if veto.veto_type not in {
                        VetoType.SHARED_DEVICE,
                        VetoType.CONFLICTING_AUTHENTICATED_USER,
                    }
                ]
            if _vetoes:
                # Blocked band on veto — confidence tier forced to BLOCKED
                blocked_band = get_confidence_band(
                    score=policy_result.confidence,
                    tier=policy_result.confidence_tier,
                    vetoes=_vetoes,
                )
                # get_confidence_band returns BLOCKED when vetoes non-empty; enforce it
                assert blocked_band == ConfidenceBand.BLOCKED
                policy_result.confidence_tier = ConfidenceTier.BLOCKED
                policy_result.confidence = 0.0
                policy_result.decision = MergeDecision.BLOCKED
                if "veto_blocked" not in policy_result.reason_codes:
                    policy_result.reason_codes = list(policy_result.reason_codes) + ["veto_blocked"]
                self._metrics.record_blocked("veto")
                logger.info(
                    "identity.veto.blocked",
                    extra={"tenant_id": tenant_id, "veto_count": len(_vetoes), "band": blocked_band.value},
                )
                # Observability: veto evaluation trace
                try:
                    from services.identity.observability import IdentityTrace

                    _trace = IdentityTrace(
                        tenant_id=tenant_id,
                        source_system_id="identity.resolver",
                        correlation_id=str(
                            event.get("trace_correlation_id") or event.get("event_id") or ""
                        ) or None,
                    )
                    _trace.veto_evaluate(len(_vetoes))
                except Exception:
                    pass
        except Exception as e:
            # Any uncertainty while reading candidate state blocks resolution.
            # Keep diagnostics free of candidate identifiers and SDK claims.
            _vetoes = [IdentityVeto(
                veto_type=VetoType.CANDIDATE_STATE_UNAVAILABLE,
                reason="Candidate state could not be verified for this tenant",
                severity="blocked",
                details={"error_type": type(e).__name__},
            )]
            policy_result.confidence_tier = ConfidenceTier.BLOCKED
            policy_result.confidence = 0.0
            policy_result.decision = MergeDecision.BLOCKED
            policy_result.reason_codes = list(policy_result.reason_codes) + [
                "candidate_state_unavailable"
            ]
            logger.warning("identity candidate state unavailable: %s", type(e).__name__)

        if separate_user_profile and not _vetoes:
            policy_result.decision = MergeDecision.CREATE
            policy_result.reason_codes = list(dict.fromkeys([
                *policy_result.reason_codes,
                "distinct_scoped_user_on_shared_signal",
            ]))

        # ── 8. Create or fetch canonical entity ───────────────────────────
        canonical_entity_id: str
        is_new = False

        _signal_types_for_type_infer = (
            [sig.type for sig in raw_signals]
            if raw_signals
            else [t for (t, _, _) in hashed_signals]
        )
        event_entity_id, event_subject_id = (
            _event_entity_ids(tenant_id, str(event_id), policy_version)
            if event_id
            else (str(uuid.uuid4()), str(uuid.uuid4()))
        )
        if (
            source_entity_id
            and policy_result.decision
            in (MergeDecision.CANDIDATE, MergeDecision.REJECT, MergeDecision.BLOCKED)
            and not binding_contradicted
            and not separate_user_profile
        ):
            # Keep unresolved evidence on its established source profile while
            # the competing canonical identity remains in the review record.
            canonical_entity_id = source_entity_id
        elif (
            policy_result.decision == MergeDecision.CREATE
            or not existing_entity_ids
            or (binding_contradicted and policy_result.decision != MergeDecision.BLOCKED)
            or separate_user_profile
        ):
            # A contradicted binding (this user_id on a device whose anonymous
            # id already belongs to a DIFFERENT scoped user) resolves to the event's
            # own entity; the candidates go to a conflict record for review
            # instead of absorbing another person's aliases.
            canonical_entity_id = event_entity_id
            entity_type = _infer_entity_type_from_types(_signal_types_for_type_infer)
            await self._repo.create_subject(
                tenant_id=tenant_id,
                canonical_entity_id=canonical_entity_id,
                entity_type=entity_type,
                subject_id=event_subject_id,
            )
            is_new = True
        elif policy_result.decision in (MergeDecision.MERGE, MergeDecision.LINK):
            canonical_entity_id = (
                policy_result.merge_target_entity_id or existing_entity_ids[0]
            )
        else:
            # CANDIDATE, REJECT, BLOCKED → use first existing or create anonymous
            canonical_entity_id = existing_entity_ids[0] if existing_entity_ids else event_entity_id
            if not existing_entity_ids:
                is_new = True
                entity_type = _infer_entity_type_from_types(_signal_types_for_type_infer)
                await self._repo.create_subject(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical_entity_id,
                    entity_type=entity_type,
                    subject_id=event_subject_id,
                )

        # ── 8b. Link this event's observations to the resolved entity ─────
        # Observations are persisted at step 4 before the canonical entity is
        # known; link them now so get_observations_for_entity (and entity-scoped
        # recompute) can actually find them.
        if canonical_entity_id and event_id:
            await self._repo.set_observations_canonical_entity(
                tenant_id, event_id, canonical_entity_id
            )

        # ── 9. Link aliases ───────────────────────────────────────────────
        linked_aliases: list[str] = []
        # First-seen deterministic identifiers can anchor a new profile even
        # when policy has no existing candidate to match. Keep that narrow
        # exception while preserving the consent gate for every alias write:
        # an identifier ignored during scoring must not become a future match.
        stitching_consent = has_stitching_consent(consent_snapshot)
        allowed_initial_anchor = initial_user_id_anchor and is_new and not existing_entity_ids
        can_link_aliases = (
            policy_result.decision not in (MergeDecision.BLOCKED, MergeDecision.REJECT)
            or allowed_initial_anchor
        )
        if can_link_aliases:
            for (sig_type, sig_hash, display) in hashed_signals:
                if sig_type in _ATTRIBUTION_ONLY:
                    continue
                if separate_user_profile and sig_type != IdentitySignalType.USER_ID:
                    # Keep shared device/session/anonymous aliases off either
                    # profile; only the tenant/app-scoped user ID belongs here.
                    continue
                if sig_type == IdentitySignalType.DEVICE_FINGERPRINT and (
                    IdentitySignalType.USER_ID in identity_signal_types
                ):
                    # A device fingerprint is a weak, potentially shared
                    # observation. It cannot serve as a durable alias of a
                    # user profile merely because a user ID was supplied.
                    continue
                if sig_type in CONSENT_REQUIRED_SIGNALS and not stitching_consent:
                    continue
                if allowed_initial_anchor and sig_type not in {
                    IdentitySignalType.USER_ID,
                    IdentitySignalType.EXTERNAL_ID,
                    IdentitySignalType.ANONYMOUS_ID,
                }:
                    continue
                signal = next(
                    (item for item in raw_signals if item.type == sig_type), None
                )
                alias = await self._repo.upsert_alias(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical_entity_id,
                    alias_type=sig_type,
                    alias_value_hash=sig_hash,
                    alias_display_value_redacted=display,
                    source=signal.source if signal else "recompute",
                    source_event_id=event_id,
                    source_platform=signal.source_platform if signal else None,
                    confidence=policy_result.confidence,
                    confidence_tier=policy_result.confidence_tier,
                    consent_snapshot=consent_snapshot,
                )
                linked_aliases.append(alias["id"])

        # ── 10. Merge entities if approved ───────────────────────────────
        merge_event_id: Optional[str] = None
        auto_merged_from_ids: list[str] = []
        resolution_revision_before: Optional[int] = None
        resolution_revision_after: Optional[int] = None
        if policy_result.decision == MergeDecision.MERGE and policy_result.merge_target_entity_id:
            for from_id in existing_entity_ids:
                if from_id == canonical_entity_id:
                    continue
                merge_event_id = await self._audit.record_merge(
                    tenant_id=tenant_id,
                    from_entity_id=from_id,
                    into_entity_id=canonical_entity_id,
                    resulting_entity_id=canonical_entity_id,
                    confidence=policy_result.confidence,
                    confidence_tier=policy_result.confidence_tier,
                    reason_codes=policy_result.reason_codes,
                    source_event_ids=[event_id] if event_id else [],
                )
                await self._repo.mark_subject_merged_by_canonical_id(
                    tenant_id, from_id, canonical_entity_id
                )
                self._metrics.record_merge(tenant_id=tenant_id)
                auto_merged_from_ids.append(from_id)

            # Bump the survivor's resolution revision once per auto-merge. The
            # event is emitted only after the audit decision and durable job
            # enqueue below, so it can carry the committed decision/version and
            # serve as an idempotent enqueue-recovery signal.
            if auto_merged_from_ids:
                (
                    resolution_revision_before,
                    resolution_revision_after,
                ) = await self._advance_resolution_revision(tenant_id, canonical_entity_id)

        # ── 11. Create conflict if ambiguous ──────────────────────────────
        conflict_id: Optional[str] = None
        if (
            policy_result.decision == MergeDecision.CANDIDATE
            and has_conflict
            and continuity.conflict_detection_enabled
        ):
            if binding_contradicted and not policy_result.conflict_type:
                policy_result.conflict_type = "conflicting_user_binding"
            conflict_id = await self._conflicts.open_conflict(
                tenant_id=tenant_id,
                candidate_entity_ids=existing_entity_ids,
                candidate_aliases=[
                    {"type": st.value, "hash": h, "display": d}
                    for (st, h, d) in hashed_signals
                ],
                conflict_type=policy_result.conflict_type or "ambiguous_match",
                confidence=policy_result.confidence,
                reason_codes=policy_result.reason_codes,
            )
            self._metrics.record_conflict()
        elif policy_result.decision == MergeDecision.CANDIDATE and has_conflict:
            policy_result.reason_codes = list(policy_result.reason_codes) + [
                "conflict_detection_disabled"
            ]

        # ── 12. Write graph edges ─────────────────────────────────────────
        decision_obj = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=canonical_entity_id,
            decision=policy_result.decision,
            confidence=policy_result.confidence,
            confidence_tier=policy_result.confidence_tier,
            reason_codes=policy_result.reason_codes,
            linked_aliases=linked_aliases,
            candidate_entity_ids=[
                e for e in existing_entity_ids if e != canonical_entity_id
            ],
            conflict_id=conflict_id,
            source_event_ids=[event_id] if event_id else [],
            blocked_reason=(
                policy_result.reason_codes[0]
                if policy_result.decision == MergeDecision.BLOCKED
                else None
            ),
            is_new_entity=is_new,
            policy_version=policy_version,
        )

        graph_edges = await self._graph.write_decision(
            decision_obj, [event_id] if event_id else [], consent_snapshot
        )
        decision_obj.graph_edges_written = graph_edges

        # Write attribution / relationship edges
        await self._write_relationship_edges(
            raw_signals, canonical_entity_id, tenant_id,
            policy_result.confidence, policy_result.confidence_tier,
            policy_result.reason_codes, [event_id] if event_id else [],
            consent_snapshot,
        )

        # Resolver links can change the Profile 360 identity view too. Persist
        # a monotonic subject revision at the same decision boundary so a later
        # restatement job refers to a real committed version, not a fabricated
        # graph-version placeholder.
        if policy_result.decision == MergeDecision.LINK:
            (
                resolution_revision_before,
                resolution_revision_after,
            ) = await self._advance_resolution_revision(tenant_id, canonical_entity_id)

        # ── 13. Emit audit record ─────────────────────────────────────────
        audit_id = await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=policy_result.decision,
            canonical_entity_id=canonical_entity_id,
            candidate_entity_ids=existing_entity_ids,
            confidence=policy_result.confidence,
            confidence_tier=policy_result.confidence_tier,
            reason_codes=policy_result.reason_codes,
            source_event_ids=[event_id] if event_id else [],
            policy_result=policy_result.decision.value,
            consent_snapshot=consent_snapshot,
            resolution_revision_before=resolution_revision_before,
            resolution_revision_after=resolution_revision_after,
        )
        decision_obj.audit_id = audit_id
        decision_obj.resolution_revision_before = resolution_revision_before
        decision_obj.resolution_revision_after = resolution_revision_after

        # ── 13b. Record identity decision evidence (additive, fail-safe) ──
        # Captures the decision's provenance (§3.3): matching signal types as
        # signals_used, suppressed/revoked types as signals_excluded, the
        # source event, confidence tier, and the audit record as the policy
        # decision reference. Wrapped so a recorder failure never breaks
        # resolution — evidence is strictly observational.
        try:
            await self._record_decision_evidence(
                tenant_id=tenant_id,
                canonical_entity_id=canonical_entity_id,
                policy_result=policy_result,
                has_conflict=has_conflict,
                matching_types=matching_types,
                excluded_types=[*suppressed_types, *revoked_types],
                raw_signals=raw_signals,
                event_id=event_id,
                consent_snapshot=consent_snapshot,
                policy_decision_id=audit_id,
                policy_version=policy_version,
            )
        except Exception as exc:  # noqa: BLE001 - evidence must never break resolution
            logger.warning("decision evidence recording failed: %s", exc)

        if auto_merged_from_ids or policy_result.decision == MergeDecision.LINK:
            await self._queue_resolver_restatement(
                decision=decision_obj,
                decision_id=audit_id,
                confidence_band=get_confidence_band(
                    policy_result.confidence,
                    policy_result.confidence_tier,
                    _vetoes,
                ),
                affected_entity_ids=[canonical_entity_id, *auto_merged_from_ids],
                is_merge=bool(auto_merged_from_ids),
            )
        if auto_merged_from_ids:
            await self._publish_identity_merged(
                tenant_id=tenant_id,
                canonical_entity_id=canonical_entity_id,
                merged_from_ids=auto_merged_from_ids,
                confidence=policy_result.confidence,
                confidence_tier=policy_result.confidence_tier,
                reason_codes=policy_result.reason_codes,
                event_id=event_id,
                decision_id=audit_id,
                resolution_revision_before=resolution_revision_before,
                resolution_revision_after=resolution_revision_after,
                restatement_job_id=decision_obj.restatement_job_id,
            )

        # ── 14. Emit metrics ──────────────────────────────────────────────
        if policy_result.decision == MergeDecision.BLOCKED:
            blocked_reason = _blocked_reason_category(policy_result.reason_codes)
            self._metrics.record_blocked(blocked_reason)
        elif policy_result.decision == MergeDecision.CANDIDATE:
            self._metrics.record_candidate()
        elif policy_result.decision == MergeDecision.LINK:
            self._metrics.record_link(tenant_id)

        self._metrics.record_resolve(
            success=policy_result.decision != MergeDecision.BLOCKED,
            tenant_id=tenant_id,
        )

        return decision_obj

    def _resolve_producer(self) -> Optional[EventProducer]:
        """Return the event producer, falling back to the shared registry.

        routes.py constructs this service without a producer, so when one was
        not injected obtain the process-wide producer the operator merge route
        publishes through (``dependencies.providers.get_producer`` → the
        ``ResourceRegistry`` singleton). The import is deferred to keep the
        resolver import-light and free of any provider import cycle. A lookup
        failure degrades to no-publish rather than raising — restatement
        triggering must never break resolution.
        """
        if self._producer is not None:
            return self._producer
        try:
            from dependencies.providers import get_producer

            self._producer = get_producer()
        except Exception as exc:  # noqa: BLE001 - never break resolution
            logger.warning(
                "identity resolver could not obtain an event producer: %s", exc
            )
            return None
        return self._producer

    async def _publish_identity_merged(
        self,
        *,
        tenant_id: str,
        canonical_entity_id: str,
        merged_from_ids: list[str],
        confidence: float,
        confidence_tier: Any,
        reason_codes: list[str],
        event_id: str,
        decision_id: str,
        resolution_revision_before: Optional[int],
        resolution_revision_after: Optional[int],
        restatement_job_id: Optional[str],
    ) -> None:
        """Publish one IDENTITY_MERGED event per entity folded into the survivor.

        Mirrors the payload the operator merge route
        (services/identity/routes.py::merge_identities) publishes — survivor as
        ``primary_entity_id`` and consumed entity as ``secondary_entity_id`` —
        so the downstream measurement + semantic restatement consumers that
        subscribe to ``Topic.IDENTITY_MERGED`` recompute journeys/attribution
        and Gold semantic state for auto-merges exactly as they do for operator
        merges.

        Best-effort and fail-safe: the merge is already durably recorded by the
        time this runs, so a producer/bus error is logged and swallowed rather
        than propagated into resolution (where ``resolve_event``'s guard would
        otherwise discard the whole decision as an internal error).
        """
        producer = self._resolve_producer()
        if producer is None:
            return
        reason = reason_codes[0] if reason_codes else "auto_merge"
        tier_value = getattr(confidence_tier, "value", confidence_tier)
        for from_id in merged_from_ids:
            try:
                await producer.publish(Event(
                    topic=Topic.IDENTITY_MERGED,
                    tenant_id=tenant_id,
                    source_service="identity",
                    payload={
                        "primary_entity_id": canonical_entity_id,
                        "secondary_entity_id": from_id,
                        "canonical_entity_id": canonical_entity_id,
                        "reason": reason,
                        "reason_codes": list(reason_codes),
                        "confidence": confidence,
                        "confidence_tier": tier_value,
                        "auto_merge": True,
                        "is_merge": True,
                        "decision_id": decision_id,
                        "resolution_revision_before": resolution_revision_before,
                        "resolution_revision_after": resolution_revision_after,
                        "restatement_job_id": restatement_job_id,
                        "affected_canonical_entity_ids": [
                            canonical_entity_id, *merged_from_ids
                        ],
                        "source_event_ids": [event_id] if event_id else [],
                    },
                ))
            except Exception as exc:  # noqa: BLE001 - restatement must never break ingestion
                logger.warning(
                    "failed to publish IDENTITY_MERGED for auto-merge %s -> %s: %s",
                    from_id, canonical_entity_id, exc,
                )

    async def _record_decision_evidence(
        self,
        *,
        tenant_id: str,
        canonical_entity_id: str,
        policy_result: Any,
        has_conflict: bool,
        matching_types: list,
        excluded_types: list,
        raw_signals: list,
        event_id: str,
        consent_snapshot: Optional[dict],
        policy_decision_id: Optional[str],
        policy_version: str,
    ) -> None:
        """Record an IdentityDecisionEvidence row for this resolution (§3.3).

        Purely observational: maps the policy MergeDecision to a decision_type,
        captures matching signal types as evidence and suppressed/revoked types
        as exclusions, and links the audit record as the policy decision id.
        """
        decision_type = decision_type_from_merge_decision(
            policy_result.decision, has_conflict=has_conflict
        )
        # Derive connector provenance from the signals observed on this event.
        source_connectors: list[str] = []
        for sig in raw_signals or []:
            for attr in ("source", "source_platform", "source_sdk"):
                val = getattr(sig, attr, "") or ""
                if val:
                    source_connectors.append(val)
        await self._decision_evidence.record_decision(
            tenant_id=tenant_id,
            entity_id=canonical_entity_id,
            subject_entity_id=canonical_entity_id,
            decision_type=decision_type,
            signals_used=[getattr(t, "value", t) for t in matching_types],
            signals_excluded=[getattr(t, "value", t) for t in excluded_types],
            source_events=[event_id] if event_id else [],
            source_connectors=source_connectors,
            consent_snapshot=consent_snapshot,
            policy_decision_id=policy_decision_id,
            confidence_score=policy_result.confidence,
            confidence_tier=policy_result.confidence_tier,
            merge_policy_version=policy_version,
        )

    # ── Verified-ownership merge helpers ──────────────────────────────────

    async def _surviving_entity_ids(
        self, tenant_id: str, entity_ids: list[str]
    ) -> list[str]:
        """Map candidate ids through merge tombstones to their survivors (deduped).

        Fail-safe: a lookup failure keeps the original id.
        """
        out: list[str] = []
        for eid in entity_ids:
            try:
                survivor = await self._repo.resolve_surviving_canonical_entity_id(
                    tenant_id, eid
                )
            except Exception as exc:  # noqa: BLE001 - keep the original id
                logger.warning("survivor lookup failed for %s: %s", eid, exc)
                survivor = eid
            survivor = survivor or eid
            if survivor not in out:
                out.append(survivor)
        return out

    async def _entity_family(self, tenant_id: str, survivor: str) -> set[str]:
        """The survivor plus every fragment currently merged into it."""
        family = {survivor}
        frontier = [survivor]
        while frontier and len(family) < 200:
            node = frontier.pop()
            for merge in await self._repo.get_merge_history(tenant_id, node):
                src = merge.get("from_entity_id")
                if merge.get("into_entity_id") != node or not src or src in family:
                    continue
                current = await self._repo.resolve_surviving_canonical_entity_id(
                    tenant_id, src
                )
                if current != survivor:
                    continue  # split back out since
                family.add(src)
                frontier.append(src)
        return family

    async def _has_conflicting_user_id(
        self, tenant_id: str, entity_ids: list[str], event_user_hash: str
    ) -> bool:
        """Whether a candidate (or merged fragment) is owned by another user.

        This is used only to keep a distinct tenant/app-scoped user ID from
        being assigned to a profile reached through a shared device/session
        alias. A lookup failure never authorizes profile creation on this basis.
        """
        try:
            for survivor in entity_ids:
                for entity_id in await self._entity_family(tenant_id, survivor):
                    for alias in await self._repo.get_aliases_for_entity(
                        tenant_id, entity_id
                    ):
                        if (
                            not alias.get("revoked_at")
                            and alias.get("alias_type") == IdentitySignalType.USER_ID.value
                            and alias.get("alias_value_hash")
                            and alias["alias_value_hash"] != event_user_hash
                        ):
                            return True
            return False
        except Exception as exc:  # noqa: BLE001 - do not infer conflict on read failure
            logger.warning("identity user contradiction check failed: %s", exc)
            return False

    async def _binding_contradicted(
        self, tenant_id: str, entity_ids: list[str], event_user_hash: str
    ) -> bool:
        """True when collapsing ``entity_ids`` under ``event_user_hash`` would
        fuse different people: some candidate (or a fragment merged into it)
        holds a different user_id, or the candidates disagree on external_id /
        verified wallet. Fail-CLOSED: an error reports a contradiction, because
        this check is what authorizes an automatic merge.
        """
        try:
            by_type: dict[IdentitySignalType, set[str]] = {
                IdentitySignalType.USER_ID: {event_user_hash},
            }
            for survivor in entity_ids:
                for eid in await self._entity_family(tenant_id, survivor):
                    for alias in await self._repo.get_aliases_for_entity(tenant_id, eid):
                        if alias.get("revoked_at"):
                            continue
                        try:
                            at = IdentitySignalType(alias.get("alias_type"))
                        except (ValueError, TypeError):
                            continue
                        if at not in _BINDING_DETERMINISTIC_TYPES:
                            continue
                        by_type.setdefault(at, set()).add(
                            alias.get("alias_value_hash") or ""
                        )
            return any(len(hashes) >= 2 for hashes in by_type.values())
        except Exception as exc:  # noqa: BLE001 - fail closed: no auto-merge
            logger.warning("identity binding contradiction check failed: %s", exc)
            return True

    async def _has_deterministic_conflict(
        self, tenant_id: str, entity_ids: list[str]
    ) -> bool:
        """True iff candidate entities carry CONTRADICTORY deterministic ids.

        Verified ownership only authorizes a merge when the fragments are
        compatible. If two candidates carry different user_id / external_id /
        verified-wallet hashes, merging would fuse distinct real identities —
        that is a conflict, routed to review instead (blueprint §41). Revoked
        aliases are ignored. Fail-safe: any error returns False so a lookup
        failure never fabricates a conflict.
        """
        deterministic_types = {
            IdentitySignalType.USER_ID,
            IdentitySignalType.EXTERNAL_ID,
            IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
        }
        try:
            by_type: dict[IdentitySignalType, set[str]] = {}
            for eid in entity_ids:
                aliases = await self._repo.get_aliases_for_entity(tenant_id, eid)
                for a in aliases:
                    if a.get("revoked_at"):
                        continue
                    try:
                        at = IdentitySignalType(a.get("alias_type"))
                    except (ValueError, TypeError):
                        continue
                    if at not in deterministic_types:
                        continue
                    by_type.setdefault(at, set()).add(a.get("alias_value_hash") or "")
            return any(len(hashes) >= 2 for hashes in by_type.values())
        except Exception as exc:  # noqa: BLE001 - never fabricate a conflict
            logger.warning("deterministic conflict check failed: %s", exc)
            return False

    async def _pick_survivor(
        self, tenant_id: str, entity_ids: list[str]
    ) -> str:
        """Choose the survivor for a verified multi-candidate merge.

        Deterministic and identity-fair (blueprint §25): the OLDEST entity wins
        by (first_seen_at, created_at) ascending, tie-broken by entity_id — never
        by size, revenue, or recency. Fail-safe to the lexicographically smallest
        id if subject lookups fail.
        """
        try:
            scored: list[tuple[str, str, str]] = []
            for eid in entity_ids:
                row = await self._repo.get_subject_by_canonical_entity_id(tenant_id, eid)
                first_seen = (row or {}).get("first_seen_at") or "~"
                created = (row or {}).get("created_at") or "~"
                scored.append((first_seen, created, eid))
            scored.sort(key=lambda t: (t[0], t[1], t[2]))
            return scored[0][2] if scored else sorted(entity_ids)[0]
        except Exception as exc:  # noqa: BLE001 - deterministic fallback
            logger.warning("survivor selection failed: %s", exc)
            return sorted(entity_ids)[0]

    async def _bump_resolution_revision(
        self, tenant_id: str, canonical_entity_id: str
    ) -> int:
        """Increment the survivor subject's monotonic resolution revision.

        Bumped once per successful merge/split so downstream consumers can
        detect an entity's identity was restated. Best-effort and fail-safe:
        a read/write failure is logged and swallowed (never breaks resolution).
        """
        _before, after = await self._advance_resolution_revision(
            tenant_id, canonical_entity_id
        )
        return after or 0

    async def _advance_resolution_revision(
        self, tenant_id: str, canonical_entity_id: str
    ) -> tuple[Optional[int], Optional[int]]:
        """Persist and return the exact subject revision transition.

        ``None`` before means the subject had no explicit revision field yet;
        ``None`` after means the write could not be confirmed and is not safe as
        a restatement version.
        """
        try:
            row = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, canonical_entity_id
            )
            if row is None:
                return None, None
            raw_before = row.get("resolution_revision")
            before = int(raw_before) if raw_before is not None else None
            after = (before or 0) + 1
            row["resolution_revision"] = after
            stored = await self._repo._subjects.update(row["id"], row)
            if not stored or int(stored.get("resolution_revision", -1)) != after:
                return before, None
            return before, after
        except Exception as exc:  # noqa: BLE001 - revision failure must not break resolution
            logger.warning(
                "resolution_revision bump failed for %s: %s", canonical_entity_id, exc
            )
            return None, None

    async def _current_resolution_revision(
        self, tenant_id: str, canonical_entity_id: str
    ) -> int:
        """Read the current resolution revision for a canonical entity (0 default)."""
        try:
            row = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, canonical_entity_id
            )
            return int((row or {}).get("resolution_revision") or 0)
        except Exception:  # noqa: BLE001
            return 0

    async def _queue_resolver_restatement(
        self,
        *,
        decision: IdentityResolutionDecision,
        decision_id: str,
        confidence_band: ConfidenceBand,
        affected_entity_ids: list[str],
        is_merge: bool,
        decision_type_override: Optional[DecisionType] = None,
    ) -> None:
        """Enqueue a resolver decision only when its committed revision is known."""
        from config.settings import settings

        if not settings.identity_continuity.projection_restatement_enabled:
            decision.restatement_status = "disabled"
            decision.restatement_error = "projection_restatement_disabled"
            return
        if not decision_id:
            decision.restatement_status = "non_queueable"
            decision.restatement_error = "persisted decision id is missing"
            return
        if decision.resolution_revision_after is None:
            decision.restatement_status = "non_queueable"
            decision.restatement_error = "persisted resolution revision is unavailable"
            logger.error(
                "identity.restatement.non_queueable",
                extra={
                    "tenant_id": decision.tenant_id,
                    "decision_id": decision_id,
                    "reason": "resolution_revision_unavailable",
                },
            )
            return
        try:
            from services.projections.projection_restatement_orchestrator import (
                ProjectionRestatementOrchestrator,
            )

            restatement = IdentityDecisionRecord(
                id=decision_id,
                tenant_id=decision.tenant_id,
                decision_type=decision_type_override or (
                    DecisionType.AUTO_MERGE if is_merge else DecisionType.AUTO_RESOLVE
                ),
                candidate_source_identity_ids=[],
                candidate_canonical_entity_ids=list(affected_entity_ids),
                selected_canonical_entity_id=decision.canonical_entity_id,
                confidence=decision.confidence,
                confidence_band=confidence_band,
                positive_evidence=[{"reason_codes": list(decision.reason_codes)}],
                negative_evidence=[],
                vetoes=[],
                policy_version=decision.policy_version,
                graph_version_before=None,
                graph_version_after=None,
                explanation="persisted resolver decision",
                decided_by="identity_resolver",
                decided_at=utc_now().isoformat(),
                resolution_revision_before=decision.resolution_revision_before,
                resolution_revision_after=decision.resolution_revision_after,
            )
            job = await ProjectionRestatementOrchestrator().queue_restatement(restatement)
            decision.restatement_status = "queued"
            decision.restatement_job_id = job.id
        except Exception as exc:  # noqa: BLE001 - decision mutation is already committed
            decision.restatement_status = "enqueue_failed"
            decision.restatement_error = type(exc).__name__
            logger.error(
                "identity.restatement.enqueue_failed",
                extra={
                    "tenant_id": decision.tenant_id,
                    "decision_id": decision_id,
                    "error_type": type(exc).__name__,
                },
            )

    # ── Operator actions ──────────────────────────────────────────────────

    async def operator_merge(
        self,
        tenant_id: str,
        primary_entity_id: str,
        secondary_entity_id: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "manual_merge",
        idempotency_key: Optional[str] = None,
    ) -> IdentityResolutionDecision:
        if not idempotency_key:
            return await self._operator_merge_impl(
                tenant_id, primary_entity_id, secondary_entity_id, actor_id,
                actor_type, reason, None,
            )
        lock_key = f"{tenant_id}:{idempotency_key}"
        async with _operator_merge_lock(lock_key):
            return await self._operator_merge_impl(
                tenant_id, primary_entity_id, secondary_entity_id, actor_id,
                actor_type, reason, idempotency_key,
            )

    async def _operator_merge_impl(
        self,
        tenant_id: str,
        primary_entity_id: str,
        secondary_entity_id: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "manual_merge",
        idempotency_key: Optional[str] = None,
    ) -> IdentityResolutionDecision:
        """Operator merge with optional durable idempotency for review actions.

        When ``idempotency_key`` is supplied, the merge event, revision
        transition, resolution audit, and restatement are all keyed from the
        tenant-scoped operation. Retrying after any intermediate write resumes
        the same merge and returns the same decision identifiers.
        """
        from config.settings import settings
        deterministic_merge_id = None
        deterministic_audit_id = None
        prior_merge = None
        if idempotency_key:
            deterministic_merge_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aether:operator-merge:{tenant_id}:{idempotency_key}",
            ))
            deterministic_audit_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aether:operator-merge-audit:{tenant_id}:{idempotency_key}",
            ))
            prior_merge = await self._repo.get_merge_event_by_id(
                tenant_id, deterministic_merge_id
            )
            if prior_merge and (
                prior_merge.get("from_entity_id") != secondary_entity_id
                or prior_merge.get("into_entity_id") != primary_entity_id
            ):
                raise ValueError("operator merge idempotency key is bound to another merge")
            saved_result = (prior_merge or {}).get("operator_decision_result")
            if saved_result and (
                saved_result.get("restatement_status") == "queued"
                and saved_result.get("restatement_job_id")
            ):
                try:
                    saved_decision = MergeDecision(str(saved_result["decision"]))
                    saved_tier = ConfidenceTier(str(saved_result["confidence_tier"]))
                except (KeyError, ValueError) as exc:
                    raise ValueError("persisted operator merge result is invalid") from exc
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id=str(saved_result["canonical_entity_id"]),
                    decision=saved_decision,
                    confidence=float(saved_result.get("confidence") or 0.0),
                    confidence_tier=saved_tier,
                    reason_codes=list(saved_result.get("reason_codes") or []),
                    candidate_entity_ids=list(saved_result.get("candidate_entity_ids") or []),
                    audit_id=saved_result.get("audit_id"),
                    resolution_revision_before=saved_result.get("resolution_revision_before"),
                    resolution_revision_after=saved_result.get("resolution_revision_after"),
                    graph_edges_written=list(saved_result.get("graph_edges_written") or []),
                    restatement_status=str(saved_result.get("restatement_status") or "not_required"),
                    restatement_job_id=saved_result.get("restatement_job_id"),
                    restatement_error=saved_result.get("restatement_error"),
                )

        if prior_merge:
            try:
                confidence_tier = ConfidenceTier(str(prior_merge["confidence_tier"]))
            except (KeyError, ValueError):
                confidence_tier = ConfidenceTier.DETERMINISTIC
            confidence = float(prior_merge.get("confidence") or 1.0)
            reason_codes = list(prior_merge.get("reason_codes") or ["manual_operator_merge"])
        else:
            if not settings.identity_continuity.manual_review_enabled:
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id=primary_entity_id,
                    decision=MergeDecision.BLOCKED,
                    confidence=0.0,
                    confidence_tier=ConfidenceTier.BLOCKED,
                    reason_codes=["manual_merge_disabled"],
                    blocked_reason="manual_merge_disabled",
                )
            policy = evaluate_operator_merge(
                tenant_id=tenant_id,
                primary_entity_id=primary_entity_id,
                secondary_entity_id=secondary_entity_id,
                actor_id=actor_id,
                actor_type=actor_type,
                reason=reason,
            )
            if policy.decision != MergeDecision.MERGE:
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id=primary_entity_id,
                    decision=policy.decision,
                    confidence=policy.confidence,
                    confidence_tier=policy.confidence_tier,
                    reason_codes=policy.reason_codes,
                )
            confidence = policy.confidence
            confidence_tier = policy.confidence_tier
            reason_codes = policy.reason_codes

        merge_event_id = await self._audit.record_merge(
            tenant_id=tenant_id,
            from_entity_id=secondary_entity_id,
            into_entity_id=primary_entity_id,
            resulting_entity_id=primary_entity_id,
            confidence=confidence,
            confidence_tier=confidence_tier,
            reason_codes=reason_codes,
            source_event_ids=[],
            actor_type=actor_type,
            actor_id=actor_id,
            merge_event_id=deterministic_merge_id,
        )
        await self._repo.mark_subject_merged_by_canonical_id(
            tenant_id, secondary_entity_id, primary_entity_id
        )
        self._metrics.record_merge(tenant_id=tenant_id)
        if deterministic_merge_id:
            revision_before, revision_after = await self._repo.advance_resolution_revision_for_merge_once(
                tenant_id=tenant_id,
                canonical_entity_id=primary_entity_id,
                merge_event_id=deterministic_merge_id,
            )
        else:
            revision_before, revision_after = await self._advance_resolution_revision(
                tenant_id, primary_entity_id
            )

        decision_obj = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=primary_entity_id,
            decision=MergeDecision.MERGE,
            confidence=confidence,
            confidence_tier=confidence_tier,
            reason_codes=reason_codes,
            candidate_entity_ids=[secondary_entity_id],
            resolution_revision_before=revision_before,
            resolution_revision_after=revision_after,
        )

        audit_id = await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=MergeDecision.MERGE,
            canonical_entity_id=primary_entity_id,
            candidate_entity_ids=[secondary_entity_id],
            confidence=confidence,
            confidence_tier=confidence_tier,
            reason_codes=reason_codes,
            source_event_ids=[],
            policy_result="operator_merge",
            resolution_revision_before=revision_before,
            resolution_revision_after=revision_after,
            audit_id=deterministic_audit_id,
        )
        decision_obj.audit_id = audit_id

        graph_edges = await self._graph.write_decision(decision_obj, [], None)
        decision_obj.graph_edges_written = graph_edges

        await self._queue_resolver_restatement(
            decision=decision_obj,
            decision_id=audit_id,
            confidence_band=ConfidenceBand.VERY_HIGH,
            affected_entity_ids=[primary_entity_id, secondary_entity_id],
            is_merge=True,
            decision_type_override=DecisionType.MANUAL_MERGE,
        )

        if deterministic_merge_id:
            await self._repo.persist_operator_merge_result(
                tenant_id=tenant_id,
                merge_event_id=deterministic_merge_id,
                decision={
                    "canonical_entity_id": decision_obj.canonical_entity_id,
                    "decision": decision_obj.decision.value,
                    "confidence": decision_obj.confidence,
                    "confidence_tier": decision_obj.confidence_tier.value,
                    "reason_codes": decision_obj.reason_codes,
                    "candidate_entity_ids": decision_obj.candidate_entity_ids,
                    "audit_id": decision_obj.audit_id,
                    "resolution_revision_before": decision_obj.resolution_revision_before,
                    "resolution_revision_after": decision_obj.resolution_revision_after,
                    "graph_edges_written": decision_obj.graph_edges_written,
                    "restatement_status": decision_obj.restatement_status,
                    "restatement_job_id": decision_obj.restatement_job_id,
                    "restatement_error": decision_obj.restatement_error,
                },
            )

        return decision_obj

    async def operator_split(
        self,
        tenant_id: str,
        original_entity_id: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "incorrect_merge",
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """Operator-initiated split of an incorrectly merged entity."""
        from config.settings import settings

        continuity = settings.identity_continuity
        if not continuity.split_enabled or not continuity.manual_split_enabled:
            return {
                "allowed": False,
                "error": "manual_split_disabled",
                "reason_codes": ["manual_split_disabled"],
            }
        split_ctx = SplitPolicyContext(
            tenant_id=tenant_id,
            original_entity_id=original_entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            source_merge_event_id=source_merge_event_id,
        )
        split_policy = evaluate_split(split_ctx)
        if not split_policy.allowed:
            return {
                "allowed": False,
                "error": split_policy.error,
                "reason_codes": split_policy.reason_codes,
            }

        new_entity_id = str(uuid.uuid4())

        split_event_id = await self._audit.record_split(
            tenant_id=tenant_id,
            original_entity_id=original_entity_id,
            resulting_entity_ids=[original_entity_id, new_entity_id],
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
        )

        # Revoke same_as edges
        revoked_edges = await self._graph.revoke_edges_after_split(
            tenant_id, original_entity_id
        )
        self._metrics.record_split(tenant_id=tenant_id)
        revision_before, revision_after = await self._advance_resolution_revision(
            tenant_id, original_entity_id
        )
        _new_revision_before, new_revision_after = await self._advance_resolution_revision(
            tenant_id, new_entity_id
        )
        decision_obj = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=original_entity_id,
            decision=MergeDecision.LINK,
            confidence=0.0,
            confidence_tier=ConfidenceTier.BLOCKED,
            reason_codes=split_policy.reason_codes,
            candidate_entity_ids=[new_entity_id],
            resolution_revision_before=revision_before,
            resolution_revision_after=revision_after,
        )
        decision_obj.audit_id = split_event_id
        await self._queue_resolver_restatement(
            decision=decision_obj,
            decision_id=split_event_id,
            confidence_band=ConfidenceBand.BLOCKED,
            affected_entity_ids=[original_entity_id, new_entity_id],
            is_merge=False,
            decision_type_override=DecisionType.MANUAL_SPLIT,
        )

        return {
            "allowed": True,
            "split_event_id": split_event_id,
            "original_entity_id": original_entity_id,
            "new_entity_id": new_entity_id,
            "revoked_edge_ids": revoked_edges,
            "reason_codes": split_policy.reason_codes,
            "decision_id": split_event_id,
            "resolution_revision_before": revision_before,
            "resolution_revision_after": revision_after,
            "resulting_resolution_revision_after": new_revision_after,
            "restatement_status": decision_obj.restatement_status,
            "restatement_job_id": decision_obj.restatement_job_id,
            "restatement_error": decision_obj.restatement_error,
        }

    # ── Fragment-aware identity repair (PR5 slice) ────────────────────────

    async def _same_as_edges_between(
        self, tenant_id: str, entity_a: str, entity_b: str
    ) -> list[str]:
        """Active SAME_AS edge ids incident to entity_a whose other end is entity_b."""
        edges = await self._repo.get_entity_graph(tenant_id, entity_a)
        result: list[str] = []
        for e in edges:
            if e.get("edge_type") != EdgeType.SAME_AS.value or e.get("revoked_at"):
                continue
            endpoints = {e.get("source_entity_id"), e.get("target_entity_id")}
            if entity_b in endpoints:
                result.append(e["id"])
        return result

    async def _analyze_fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        alias_ids: list[str],
        observation_ids: list[str],
        mode: str,
        actor_id: str,
        actor_type: str,
        reason: str,
        target_entity_id: Optional[str],
        source_merge_event_id: Optional[str],
    ) -> _FragmentSplitPlan:
        """Read-only validation + impact analysis for a fragment split.

        Enforces: operator/admin split policy, per-fragment tenant match (no
        cross-tenant), fragment ownership by the source entity, campaign-only
        sameness blocking, and identity-cycle prevention. Performs NO writes —
        it is safe to call from the non-mutating preview endpoint.
        """
        risk_notes: list[str] = []
        base_codes: list[str] = []

        def reject(
            rejection_reason: str, error: str, codes: Optional[list[str]] = None
        ) -> _FragmentSplitPlan:
            return _FragmentSplitPlan(
                allowed=False,
                entity_id=entity_id,
                mode=mode,
                reason=reason,
                actor_type=actor_type,
                actor_id=actor_id,
                source_merge_event_id=source_merge_event_id,
                target_entity_id=None,
                risk_notes=risk_notes,
                reason_codes=_dedupe_preserve(base_codes + (codes or [])),
                rejection_reason=rejection_reason,
                error=error,
            )

        # 1. Operator/admin split policy gate (actor, entity, reason).
        policy = evaluate_split(SplitPolicyContext(
            tenant_id=tenant_id,
            original_entity_id=entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            source_merge_event_id=source_merge_event_id,
            proposed_entity_ids=[target_entity_id] if target_entity_id else [],
        ))
        if not policy.allowed:
            return reject("split_policy_denied", policy.error or "split not permitted", policy.reason_codes)
        base_codes = list(policy.reason_codes)  # includes REASON_MANUAL_OPERATOR_SPLIT

        # 2. A fragment must name at least one member.
        if not alias_ids and not observation_ids:
            return reject(
                "empty_fragment",
                "fragment must include at least one alias_id or observation_id",
            )

        # 3. Source entity (subject may be absent if it only owns aliases).
        source_subject = await self._repo.get_subject_by_canonical_entity_id(
            tenant_id, entity_id
        )
        source_entity_type = (
            source_subject.get("entity_type") if source_subject else None
        )

        # 4. Validate alias fragments: tenant + ownership; collect signal values.
        alias_rows: list[dict] = []
        fragment_signal_values: list[str] = []
        for alias_id in alias_ids:
            row = await self._repo.get_alias_by_id(alias_id)
            if row is None:
                return reject("fragment_alias_not_found", f"alias {alias_id!r} not found")
            if row.get("tenant_id") != tenant_id:
                return reject(
                    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
                    f"alias {alias_id!r} belongs to another tenant",
                    [REASON_CROSS_TENANT_FRAGMENT_BLOCKED],
                )
            if row.get("canonical_entity_id") != entity_id:
                return reject(
                    "fragment_not_owned_by_entity",
                    f"alias {alias_id!r} is not owned by entity {entity_id!r}",
                )
            fragment_signal_values.append(str(row.get("alias_type", "")))
            if row.get("revoked_at"):
                risk_notes.append(
                    f"alias {alias_id} already revoked — skipped (idempotent)"
                )
                continue
            alias_rows.append(row)

        # 5. Validate observation fragments: tenant + ownership.
        valid_observation_ids: list[str] = []
        for obs_id in observation_ids:
            row = await self._repo.get_observation_by_id(obs_id)
            if row is None:
                return reject(
                    "fragment_observation_not_found", f"observation {obs_id!r} not found"
                )
            if row.get("tenant_id") != tenant_id:
                return reject(
                    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
                    f"observation {obs_id!r} belongs to another tenant",
                    [REASON_CROSS_TENANT_FRAGMENT_BLOCKED],
                )
            obs_entity = row.get("canonical_entity_id")
            if obs_entity not in (None, "", entity_id):
                return reject(
                    "fragment_not_owned_by_entity",
                    f"observation {obs_id!r} is not owned by entity {entity_id!r}",
                )
            fragment_signal_values.append(str(row.get("signal_type", "")))
            valid_observation_ids.append(obs_id)

        # 6. Campaign-only sameness guard (merge_policy signal classes).
        if fragment_signal_values and not any(
            _is_merge_eligible_signal(v) for v in fragment_signal_values
        ):
            return reject(
                REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED,
                "fragment carries only campaign/attribution signals — campaign "
                "attribution never establishes identity sameness",
                [REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED],
            )

        # 7. Resolve the destination entity per mode + identity-cycle guards.
        resolved_target: Optional[str] = None
        if mode == "create_new_entity":
            resolved_target = None  # brand-new id minted at execution time
            risk_notes.append(
                "create_new_entity: a brand-new canonical entity will be minted"
            )
        elif mode == "restore_pre_merge_entity":
            if not source_merge_event_id:
                return reject(
                    "source_merge_event_required",
                    "restore_pre_merge_entity requires source_merge_event_id",
                )
            merge_event = await self._repo.get_merge_event_by_id(
                tenant_id, source_merge_event_id
            )
            if merge_event is None:
                return reject(
                    "merge_event_not_found",
                    f"merge event {source_merge_event_id!r} not found for tenant",
                )
            pre_merge_id = merge_event.get("from_entity_id") or ""
            if not pre_merge_id:
                return reject(
                    "merge_event_missing_from_entity",
                    "merge event has no from_entity_id to restore",
                )
            survivors = {
                merge_event.get("into_entity_id"),
                merge_event.get("resulting_entity_id"),
            }
            if entity_id not in survivors:
                risk_notes.append(
                    f"entity {entity_id} is not the recorded survivor of merge "
                    f"{source_merge_event_id}"
                )
            if pre_merge_id == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "pre-merge entity equals the entity being split",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            resolved_target = pre_merge_id
        elif mode == "move_to_existing_entity":
            if not target_entity_id:
                return reject(
                    "target_entity_required",
                    "move_to_existing_entity requires target_entity_id",
                )
            if target_entity_id == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "cannot move a fragment onto the same entity",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            target_subject = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, target_entity_id
            )
            if target_subject is None:
                return reject(
                    "target_entity_not_found",
                    f"target entity {target_entity_id!r} not found for tenant",
                )
            if target_subject.get("status") != SubjectStatus.ACTIVE.value:
                return reject(
                    "target_entity_not_active",
                    f"target entity {target_entity_id!r} is not active",
                )
            # Cycle guard: target must not redirect back to the source entity.
            target_survivor = await self._repo.resolve_surviving_canonical_entity_id(
                tenant_id, target_entity_id
            )
            if target_survivor == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "target entity's survivor chain resolves back to the source entity",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            resolved_target = target_entity_id
        else:
            return reject("unknown_split_mode", f"unknown split mode {mode!r}")

        # 8. SAME_AS edges to revoke between source and the resolved target.
        edges_to_revoke: list[str] = []
        if resolved_target:
            edges_to_revoke = await self._same_as_edges_between(
                tenant_id, entity_id, resolved_target
            )
            if not edges_to_revoke:
                risk_notes.append(
                    "no active SAME_AS edges between source and target to revoke"
                )
        else:
            risk_notes.append("create_new_entity: no pre-existing SAME_AS edges to revoke")

        if not alias_rows and not valid_observation_ids:
            risk_notes.append(
                "all fragment members already moved/revoked — split will be a no-op"
            )

        return _FragmentSplitPlan(
            allowed=True,
            entity_id=entity_id,
            mode=mode,
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
            target_entity_id=resolved_target,
            alias_rows=alias_rows,
            observation_ids=valid_observation_ids,
            edges_to_revoke=edges_to_revoke,
            risk_notes=risk_notes,
            reason_codes=_dedupe_preserve(base_codes + [REASON_FRAGMENT_SPLIT]),
            source_entity_type=source_entity_type,
        )

    async def preview_fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        fragments: dict,
        mode: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "fragment_repair",
        target_entity_id: Optional[str] = None,
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """NON-MUTATING impact analysis for splitting a fragment off an entity.

        Reports what execution WOULD move/revoke plus risk notes. When the
        split is not permitted, returns ``allowed=False`` with a typed
        ``rejection_reason`` (e.g. ``campaign_only_sameness_blocked``) rather
        than raising — the operator still gets the full analysis.
        """
        plan = await self._analyze_fragment_split(
            tenant_id=tenant_id,
            entity_id=entity_id,
            alias_ids=list((fragments or {}).get("alias_ids") or []),
            observation_ids=list((fragments or {}).get("observation_ids") or []),
            mode=mode,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            target_entity_id=target_entity_id,
            source_merge_event_id=source_merge_event_id,
        )
        return {
            "allowed": plan.allowed,
            "entity_id": entity_id,
            "mode": mode,
            "target_entity_id": plan.target_entity_id,
            "aliases_to_reassign": [r["id"] for r in plan.alias_rows],
            "observations_to_relink": list(plan.observation_ids),
            "edges_to_revoke": list(plan.edges_to_revoke),
            "risk_notes": plan.risk_notes,
            "reason_codes": plan.reason_codes,
            "rejection_reason": plan.rejection_reason,
            "error": plan.error,
        }

    async def fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        fragments: dict,
        mode: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "fragment_repair",
        target_entity_id: Optional[str] = None,
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """Execute a fragment-aware identity split.

        Modes:
          * ``create_new_entity`` — mint a new canonical entity for the fragment.
          * ``restore_pre_merge_entity`` — restore the pre-merge id recovered
            from ``source_merge_event_id`` (a merge event's ``from_entity_id``).
          * ``move_to_existing_entity`` — move the fragment onto an existing,
            active, same-tenant entity.

        Reassigns the named aliases (lineage-preserving: recreate on target,
        revoke on source — never leaving duplicate active aliases), relinks the
        named observations, appends an immutable split event carrying the exact
        fragment payload, and selectively revokes SAME_AS edges between the
        fragment and the original. Returns a structured result; failures surface
        as ``allowed=False`` with a typed ``rejection_reason``.
        """
        from config.settings import settings

        continuity = settings.identity_continuity
        if not continuity.split_enabled or not continuity.manual_split_enabled:
            return {
                "allowed": False,
                "error": "manual_split_disabled",
                "reason_codes": ["manual_split_disabled"],
                "rejection_reason": "manual_split_disabled",
            }
        alias_ids = list((fragments or {}).get("alias_ids") or [])
        observation_ids = list((fragments or {}).get("observation_ids") or [])

        plan = await self._analyze_fragment_split(
            tenant_id=tenant_id,
            entity_id=entity_id,
            alias_ids=alias_ids,
            observation_ids=observation_ids,
            mode=mode,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            target_entity_id=target_entity_id,
            source_merge_event_id=source_merge_event_id,
        )
        if not plan.allowed:
            return {
                "allowed": False,
                "entity_id": entity_id,
                "mode": mode,
                "split_event_id": None,
                "resulting_entity_id": None,
                "moved_alias_ids": [],
                "moved_observation_ids": [],
                "revoked_edge_ids": [],
                "reason_codes": plan.reason_codes,
                "rejection_reason": plan.rejection_reason,
                "error": plan.error,
            }

        entity_type = plan.source_entity_type or EntityType.HUMAN.value

        # ── Resolve / create the destination entity ───────────────────────
        if mode == "create_new_entity":
            resulting_entity_id = str(uuid.uuid4())
            await self._repo.create_subject(tenant_id, resulting_entity_id, entity_type)
        elif mode == "restore_pre_merge_entity":
            resulting_entity_id = plan.target_entity_id or str(uuid.uuid4())
            # Reactivate (or recreate) the pre-merge subject as a live identity.
            await self._repo.restore_subject(tenant_id, resulting_entity_id, entity_type)
        else:  # move_to_existing_entity — target already validated active
            resulting_entity_id = plan.target_entity_id  # type: ignore[assignment]

        # ── Reassign aliases (lineage-preserving) ─────────────────────────
        moved_alias_ids: list[str] = []
        moved_alias_map: list[dict[str, str]] = []
        for alias in plan.alias_rows:
            new_alias = await self._repo.upsert_alias(
                tenant_id=tenant_id,
                canonical_entity_id=resulting_entity_id,
                alias_type=alias.get("alias_type"),
                alias_value_hash=alias.get("alias_value_hash", ""),
                alias_display_value_redacted=alias.get("alias_display_value_redacted", ""),
                source="fragment_split",
                source_event_id=alias.get("source_event_id", ""),
                source_platform=alias.get("source_platform", ""),
                confidence=alias.get("confidence", 1.0),
                confidence_tier=alias.get("confidence_tier", ConfidenceTier.DETERMINISTIC),
                consent_snapshot=alias.get("consent_snapshot"),
            )
            # Revoke the original on the source so no duplicate active alias exists.
            await self._repo.revoke_alias(alias["id"])
            moved_alias_ids.append(new_alias["id"])
            moved_alias_map.append({
                "source_alias_id": str(alias["id"]),
                "resulting_alias_id": str(new_alias["id"]),
            })

        # ── Relink the named observations ─────────────────────────────────
        moved_observation_ids = await self._repo.relink_observations_to_entity(
            tenant_id, plan.observation_ids, resulting_entity_id
        )

        # ── Selectively revoke SAME_AS edges between fragment and original ─
        # These are the repo-backed (source-of-truth) identity edges. The
        # Neptune-side SAME_AS revoke is wired separately in shared/graph
        # (GraphClient.revoke_edge is intentionally out of scope for this slice).
        revoked_edge_ids: list[str] = []
        for edge_id in plan.edges_to_revoke:
            revoked = await self._repo.revoke_identity_edge(edge_id)
            if revoked and revoked.get("revoked_at"):
                revoked_edge_ids.append(edge_id)

        # ── Append the immutable split event with the fragment payload ────
        split_event = await self._repo.create_split_event(
            tenant_id=tenant_id,
            original_entity_id=entity_id,
            resulting_entity_ids=[entity_id, resulting_entity_id],
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
            fragment={
                "alias_ids": alias_ids,
                "observation_ids": observation_ids,
                "moved_alias_ids": moved_alias_ids,
                "moved_alias_map": moved_alias_map,
                "moved_observation_ids": moved_observation_ids,
            },
            mode=mode,
        )
        self._metrics.record_split(tenant_id=tenant_id)
        revision_before, revision_after = await self._advance_resolution_revision(
            tenant_id, entity_id
        )
        _result_revision_before, result_revision_after = await self._advance_resolution_revision(
            tenant_id, resulting_entity_id
        )
        split_decision = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=entity_id,
            decision=MergeDecision.LINK,
            confidence=0.0,
            confidence_tier=ConfidenceTier.BLOCKED,
            reason_codes=plan.reason_codes,
            candidate_entity_ids=[resulting_entity_id],
            resolution_revision_before=revision_before,
            resolution_revision_after=revision_after,
        )
        split_decision.audit_id = split_event["id"]
        await self._queue_resolver_restatement(
            decision=split_decision,
            decision_id=split_event["id"],
            confidence_band=ConfidenceBand.BLOCKED,
            affected_entity_ids=[entity_id, resulting_entity_id],
            is_merge=False,
            decision_type_override=DecisionType.MANUAL_SPLIT,
        )

        return {
            "allowed": True,
            "entity_id": entity_id,
            "mode": mode,
            "split_event_id": split_event["id"],
            "resulting_entity_id": resulting_entity_id,
            "moved_alias_ids": moved_alias_ids,
            "moved_observation_ids": moved_observation_ids,
            "revoked_edge_ids": revoked_edge_ids,
            "reason_codes": plan.reason_codes,
            "rejection_reason": None,
            "error": None,
            "decision_id": split_event["id"],
            "resolution_revision_before": revision_before,
            "resolution_revision_after": revision_after,
            "resulting_resolution_revision_after": result_revision_after,
            "restatement_status": split_decision.restatement_status,
            "restatement_job_id": split_decision.restatement_job_id,
            "restatement_error": split_decision.restatement_error,
        }

    async def suppress_identifier(
        self,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        reason: str,
        actor_id: str,
        subject_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> dict:
        """Suppress a specific identifier hash — it can no longer link identities."""
        rule = await self._repo.create_suppression_rule(
            tenant_id=tenant_id,
            identifier_hash=identifier_hash,
            identifier_type=identifier_type,
            reason=reason,
            created_by=actor_id,
            subject_id=subject_id,
            expires_at=expires_at,
        )
        # Revoke any active aliases using this identifier
        aliases = await self._repo.find_aliases_by_signal(
            tenant_id, identifier_type, identifier_hash
        )
        revoked_alias_ids: list[str] = []
        for alias in aliases:
            if not alias.get("revoked_at"):
                await self._repo.revoke_alias(alias["id"])
                revoked_alias_ids.append(alias["id"])

        await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=MergeDecision.BLOCKED,
            canonical_entity_id=subject_id or "",
            candidate_entity_ids=[],
            confidence=1.0,
            confidence_tier=ConfidenceTier.DETERMINISTIC,
            reason_codes=["suppression_applied", reason],
            source_event_ids=[],
            policy_result="suppressed",
            consent_snapshot=None,
        )
        self._metrics.record_blocked("suppression")
        return {
            "suppression_id": rule["id"],
            "tenant_id": tenant_id,
            "identifier_type": identifier_type,
            "reason": reason,
            "revoked_alias_ids": revoked_alias_ids,
            "created_at": rule.get("created_at", ""),
            "expires_at": expires_at,
        }

    async def unsuppress_identifier(
        self,
        tenant_id: str,
        suppression_id: str,
        actor_id: str,
    ) -> dict:
        """Revoke a suppression rule."""
        result = await self._repo.revoke_suppression_rule(tenant_id, suppression_id)
        if result is None:
            return {"error": "not_found", "suppression_id": suppression_id}
        return {"revoked": True, "suppression_id": suppression_id, "revoked_by": actor_id}

    async def recompute(
        self,
        tenant_id: str,
        entity_id: Optional[str] = None,
        event_ids: Optional[list[str]] = None,
        reason: str = "recompute",
    ) -> dict:
        """
        Recompute identity resolution by replaying signal observations.
        Idempotent — will not create duplicate aliases or edges.
        """
        if entity_id:
            observations = await self._repo.get_observations_for_entity(
                tenant_id, entity_id, limit=500
            )
        elif event_ids:
            observations = await self._repo.get_observations_for_events(
                tenant_id, event_ids, limit=500
            )
        else:
            return {
                "status": "error",
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_ids": event_ids or [],
                "reason": reason,
                "note": "Either entity_id or event_ids is required",
                "events_replayed": 0,
                "decisions": [],
                "errors": 0,
            }

        if not observations:
            return {
                "status": "complete",
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_ids": event_ids or [],
                "reason": reason,
                "events_replayed": 0,
                "decisions": [],
                "errors": 0,
            }

        # Group all observations by source_event_id so all signals from one event
        # are replayed together. Using _pre_hashed_signals bypasses re-hashing of
        # already-stored hashes.
        events_map: dict[str, list] = {}
        for obs in observations:
            src_evt_id = obs.get("source_event_id", "")
            if src_evt_id:
                events_map.setdefault(src_evt_id, []).append(obs)

        decisions: list[dict] = []
        errors = 0

        for src_evt_id, event_obs in events_map.items():
            pre_hashed: list[dict] = []
            consent_snapshot_val = event_obs[0].get("consent_snapshot") if event_obs else None
            for obs in event_obs:
                sig_type_str = obs.get("signal_type", "")
                sig_hash = obs.get("signal_value_hash", "")
                if sig_type_str and sig_hash:
                    pre_hashed.append({
                        "type": sig_type_str,
                        "hash": sig_hash,
                        "display": obs.get("raw_value_redacted", ""),
                    })
            if not pre_hashed:
                continue

            synthetic_event: dict = {
                "event_id": src_evt_id,
                "tenant_id": tenant_id,
                "context": {"consent": consent_snapshot_val},
                "_pre_hashed_signals": pre_hashed,
                "source": "recompute",
            }

            try:
                decision = await self._resolve_event_inner(synthetic_event, tenant_id)
                decisions.append({
                    "event_id": src_evt_id,
                    "decision": decision.decision.value,
                    "canonical_entity_id": decision.canonical_entity_id,
                })
            except Exception as exc:
                logger.warning("Recompute replay failed for event %s: %s", src_evt_id, exc)
                errors += 1

        return {
            "status": "complete",
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "event_ids": event_ids or [],
            "reason": reason,
            "events_replayed": len(events_map),
            "decisions": decisions,
            "errors": errors,
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _write_relationship_edges(
        self,
        raw_signals: list,
        canonical_entity_id: str,
        tenant_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        consent_snapshot: Optional[dict],
    ) -> None:
        for sig in raw_signals:
            if sig.type == IdentitySignalType.AGENT_ID:
                await self._graph.write_agent_delegation_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.ORG_ID:
                await self._graph.write_org_membership_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.CAMPAIGN_ID:
                await self._graph.write_campaign_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.JOURNEY_ID:
                await self._graph.write_journey_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type in (
                IdentitySignalType.WALLET_ADDRESS,
                IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
            ):
                is_verified = sig.type == IdentitySignalType.WALLET_SIGNATURE_VERIFIED
                h, _ = _hash_signal(sig.type, sig.value, tenant_id)
                if h:
                    await self._graph.write_wallet_edge(
                        tenant_id, canonical_entity_id, h,
                        is_verified, confidence, confidence_tier,
                        reason_codes, source_event_ids, consent_snapshot,
                    )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _hash_signal(
    sig_type: IdentitySignalType, value: str, tenant_id: str
) -> tuple[str, str]:
    """
    Hash a signal value and return (hash, display_redacted).
    Non-sensitive types return (value_as_is, value_or_display).
    """
    if not value:
        return "", ""

    if sig_type == IdentitySignalType.EMAIL_HASH:
        from .hashing import hash_email
        h = hash_email(value, tenant_id)
        return h, redact_display(value, "email_hash")

    if sig_type == IdentitySignalType.PHONE_HASH:
        from .hashing import hash_phone
        h = hash_phone(value, tenant_id)
        return h, redact_display(value, "phone_hash")

    if sig_type == IdentitySignalType.DEVICE_FINGERPRINT:
        h = hash_fingerprint(value)
        return h, redact_display(value, "device_fingerprint")

    if sig_type in (
        IdentitySignalType.WALLET_ADDRESS,
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
    ):
        h = hash_wallet(value)
        return h, redact_display(value, "wallet_address")

    if sig_type == IdentitySignalType.EXTERNAL_ID:
        h = hash_external_id(value, tenant_id)
        return h, redact_display(value, "external_id")

    if sig_type == IdentitySignalType.USER_ID:
        from .hashing import hash_value
        return hash_value(value, scope=f"user:{tenant_id}"), "[REDACTED:user_id]"

    # Non-sensitive: return as-is
    return value, value[:16] if len(value) > 16 else value


def _has_strong_signal(types: list[IdentitySignalType]) -> bool:
    strong = {
        IdentitySignalType.USER_ID,
        IdentitySignalType.EXTERNAL_ID,
        IdentitySignalType.EMAIL_HASH,
        IdentitySignalType.PHONE_HASH,
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
    }
    return any(t in strong for t in types)


def _infer_entity_type(signals: list) -> EntityType:
    return _infer_entity_type_from_types([sig.type for sig in signals])


def _infer_entity_type_from_types(signal_types: list[IdentitySignalType]) -> EntityType:
    for st in signal_types:
        if st == IdentitySignalType.USER_ID:
            return EntityType.HUMAN
        if st == IdentitySignalType.AGENT_ID:
            return EntityType.AGENT
        if st == IdentitySignalType.ORG_ID:
            return EntityType.ORGANIZATION
        if st == IdentitySignalType.WALLET_ADDRESS:
            return EntityType.WALLET
    return EntityType.ANONYMOUS_VISITOR


def _blocked_reason_category(reason_codes: list[str]) -> str:
    from .models import (
        REASON_CROSS_TENANT_BLOCKED,
        REASON_FINGERPRINT_ONLY_BLOCKED,
        REASON_CONSENT_BLOCKS_LINK,
    )
    if REASON_CROSS_TENANT_BLOCKED in reason_codes:
        return "cross_tenant"
    if REASON_FINGERPRINT_ONLY_BLOCKED in reason_codes:
        return "fingerprint_only"
    if REASON_CONSENT_BLOCKS_LINK in reason_codes:
        return "consent"
    return "other"


def _extract_consent(event: dict) -> Optional[dict]:
    ctx = event.get("context") or {}
    return ctx.get("consent") or None
