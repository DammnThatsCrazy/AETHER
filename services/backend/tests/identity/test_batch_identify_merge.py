"""Identity merge on realistic /v1/batch identify + track payloads.

Regression for the staging rehearsal finding "profiles never merge": every
event, including an SDK ``identify`` binding an anonymous_id to a user_id,
resolved to ``blocked`` / ``insufficient_evidence`` on a brand-new entity.

Root causes pinned here:

1. First sighting. The resolver lists only signal types that matched an
   existing alias, so a never-seen visitor has an empty match set. The policy
   scored that empty set (-> BLOCKED / insufficient_evidence) BEFORE its
   "no existing entity -> CREATE" rule, and a BLOCKED decision links no aliases
   -- so no alias was ever written and no later event could match anything.
2. Consent shape. The SDK stamps the flat ``ConsentState``
   (``{"analytics": true, ...}``) in ``context.consent``; only the nested
   ``{"purposes": {...}}`` shape was read, so every consent-gated signal
   (email/phone hash, install id) was dropped as unconsented.
3. Signal extraction. The web SDK's identify carries email in
   ``properties.traits``; only top-level ``properties.email`` was read.
4. Binding. anonymous_id -> user_id co-occurrence was only a PROBABLE
   anonymous-id match (CANDIDATE), never the deterministic evidence it is.

Payloads go through the real ingestion normalizer
(``services.ingestion.validation.build_normalized_payload``) and the exact
request the batch path hands the resolver (``_resolve_identity_safe``).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.confidence import has_stitching_consent  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.merge_policy import (  # noqa: E402
    REASON_AUTHENTICATED_BINDING,
    MergePolicyContext,
    evaluate,
)
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import (  # noqa: E402
    REASON_INSUFFICIENT_EVIDENCE,
    ConfidenceTier,
    IdentitySignalType,
    MergeDecision,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.identity.schemas import IdentityResolveRequest  # noqa: E402
from services.identity.signals import extract_signals  # noqa: E402
from services.ingestion.batch import BaseEvent  # noqa: E402
from services.ingestion.validation import build_normalized_payload  # noqa: E402

TENANT = "tenant_batch_identify"

# The flat ConsentState every SDK event carries (packages/shared/consent.ts).
SDK_CONSENT = {
    "analytics": True, "marketing": False, "personalization": False, "web3": False,
    "agent": False, "commerce": False, "updatedAt": "2026-09-20T09:00:00Z",
    "policyVersion": "2026-09",
}
NO_STITCHING_CONSENT = {**SDK_CONSENT, "analytics": False}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_in_memory_stores()
    monkeypatch.delenv("AETHER_IDENTITY_STRONG_AUTOLINK", raising=False)
    yield
    reset_in_memory_stores()


def _resolver() -> IdentityResolutionService:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )


def _batch_event(
    event_id: str,
    event_type: str,
    *,
    anonymous_id: str,
    session_id: str,
    user_id: Optional[str] = None,
    properties: Optional[dict[str, Any]] = None,
    consent: Optional[dict[str, Any]] = None,
    device: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One /v1/batch event -> the exact dict the batch path resolves."""
    sdk_event = BaseEvent(
        id=event_id,
        type=event_type,
        timestamp="2026-09-20T10:00:00Z",
        sessionId=session_id,
        anonymousId=anonymous_id,
        userId=user_id,
        properties=properties or {},
        context={
            "library": {"name": "@aether/web", "version": "9.1.0"},
            "consent": SDK_CONSENT if consent is None else consent,
            "device": device or {"type": "desktop"},
            "surface": "web",
        },
    )
    normalized = build_normalized_payload(
        sdk_event, TENANT, "batch_1", "2026-09-20T10:00:01Z"
    )
    # Mirrors services/ingestion/batch.py::_resolve_identity_safe.
    return IdentityResolveRequest(
        event_id=normalized["event_id"],
        tenant_id=TENANT,
        user_id=normalized.get("user_id"),
        anonymous_id=normalized.get("anonymous_id"),
        session_id=normalized.get("session_id"),
        properties=normalized.get("properties") or {},
        context=normalized.get("context") or {},
    ).model_dump()


def _identify(event_id, anonymous_id, session_id, user_id, email=None, **kw):
    traits = {"email": email, "name": "Jane Doe"} if email else {"name": "Jane Doe"}
    return _batch_event(
        event_id, "identify", anonymous_id=anonymous_id, session_id=session_id,
        user_id=user_id, properties={"userId": user_id, "traits": traits}, **kw,
    )


def _page(event_id, anonymous_id, session_id, user_id=None, **kw):
    return _batch_event(
        event_id, "page", anonymous_id=anonymous_id, session_id=session_id,
        user_id=user_id,
        properties={"url": "https://shop.example/", "path": "/", "title": "Home"}, **kw,
    )


async def _survivor(resolver, entity_id: str) -> str:
    return await resolver._repo.resolve_surviving_canonical_entity_id(TENANT, entity_id)


# -- First sighting ---------------------------------------------------------


@pytest.mark.asyncio
async def test_first_anonymous_page_creates_entity_not_insufficient_evidence():
    resolver = _resolver()
    d = await resolver.resolve_event(_page("e1", "anon_A", "sess_A"), TENANT)

    assert d.decision == MergeDecision.CREATE
    assert REASON_INSUFFICIENT_EVIDENCE not in d.reason_codes
    assert d.is_new_entity
    # Aliases are written, so the next event from this browser can match.
    assert d.linked_aliases
    aliases = await resolver._repo.get_aliases_for_entity(TENANT, d.canonical_entity_id)
    ids = await resolver._repo.find_subjects_by_alias(
        TENANT, IdentitySignalType.ANONYMOUS_ID,
        _alias_hash(aliases, IdentitySignalType.ANONYMOUS_ID),
    )
    assert ids == [d.canonical_entity_id]


def _alias_hash(aliases: list[dict], alias_type: IdentitySignalType) -> str:
    return next(a["alias_value_hash"] for a in aliases if a["alias_type"] == alias_type.value)


# -- Deterministic identify binding ------------------------------------------


@pytest.mark.asyncio
async def test_identify_after_anonymous_page_merges_deterministically():
    resolver = _resolver()
    anon = await resolver.resolve_event(_page("e1", "anon_A", "sess_A"), TENANT)
    ident = await resolver.resolve_event(
        _identify("e2", "anon_A", "sess_A", "user_42", email="Jane@Example.com"), TENANT
    )

    assert ident.decision == MergeDecision.MERGE
    assert ident.confidence_tier == ConfidenceTier.DETERMINISTIC
    assert REASON_AUTHENTICATED_BINDING in ident.reason_codes
    assert REASON_INSUFFICIENT_EVIDENCE not in ident.reason_codes
    assert ident.canonical_entity_id == anon.canonical_entity_id

    # Later traffic for the user (post-identify track, new device) lands on the
    # same profile deterministically.
    track = await resolver.resolve_event(
        _page("e3", "anon_A", "sess_A", user_id="user_42"), TENANT
    )
    other_device = await resolver.resolve_event(
        _page("e4", "anon_B", "sess_B", user_id="user_42"), TENANT
    )
    for d in (track, other_device):
        assert d.decision == MergeDecision.MERGE
        assert await _survivor(resolver, d.canonical_entity_id) == anon.canonical_entity_id


@pytest.mark.asyncio
async def test_identify_collapses_anonymous_and_known_profiles():
    resolver = _resolver()
    # The user is already known from device 1 ...
    known = await resolver.resolve_event(
        _identify("e1", "anon_phone", "sess_1", "user_42"), TENANT
    )
    # ... and browses anonymously on device 2 ...
    anon = await resolver.resolve_event(_page("e2", "anon_laptop", "sess_2"), TENANT)
    assert anon.canonical_entity_id != known.canonical_entity_id

    # ... then logs in on device 2: both fragments are the same person.
    d = await resolver.resolve_event(
        _identify("e3", "anon_laptop", "sess_2", "user_42"), TENANT
    )
    assert d.decision == MergeDecision.MERGE
    assert REASON_AUTHENTICATED_BINDING in d.reason_codes
    survivors = {
        await _survivor(resolver, known.canonical_entity_id),
        await _survivor(resolver, anon.canonical_entity_id),
    }
    assert survivors == {d.canonical_entity_id}

    # A later anonymous-id-only hit follows the tombstone to the survivor.
    again = await resolver.resolve_event(_page("e4", "anon_laptop", "sess_2"), TENANT)
    assert again.canonical_entity_id == d.canonical_entity_id


@pytest.mark.asyncio
async def test_shared_device_second_user_is_not_merged_into_first():
    resolver = _resolver()
    first = await resolver.resolve_event(
        _identify("e1", "anon_kiosk", "sess_1", "user_alice"), TENANT
    )
    second = await resolver.resolve_event(
        _identify("e2", "anon_kiosk", "sess_2", "user_bob"), TENANT
    )

    assert second.decision != MergeDecision.MERGE
    assert REASON_AUTHENTICATED_BINDING not in second.reason_codes
    assert second.canonical_entity_id != first.canonical_entity_id
    assert second.conflict_id, "a contradictory binding is routed to review"
    # Alice's profile did not absorb Bob's user_id.
    alice_aliases = await resolver._repo.get_aliases_for_entity(TENANT, first.canonical_entity_id)
    assert len([a for a in alice_aliases if a["alias_type"] == "user_id"]) == 1


# -- Weak / probabilistic evidence still needs corroboration -----------------


@pytest.mark.asyncio
async def test_returning_anonymous_visitor_is_not_a_deterministic_merge():
    resolver = _resolver()
    await resolver.resolve_event(_page("e1", "anon_A", "sess_A"), TENANT)
    d = await resolver.resolve_event(_page("e2", "anon_A", "sess_A2"), TENANT)
    assert d.decision == MergeDecision.CANDIDATE
    assert d.confidence_tier == ConfidenceTier.PROBABLE
    assert REASON_AUTHENTICATED_BINDING not in d.reason_codes


@pytest.mark.asyncio
async def test_email_hash_match_is_strong_and_needs_review_in_staging(monkeypatch):
    resolver = _resolver()
    await resolver.resolve_event(
        _identify("e1", "anon_A", "sess_A", "user_42", email="jane@example.com"), TENANT
    )
    # Staging/production default: strong (probabilistic) auto-link is OFF
    # (resolver._strong_autolink_enabled); pin it without leaving local mode.
    import services.identity.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "_strong_autolink_enabled", lambda: False)
    # Same email (+ a device id) from a different, never-identified browser.
    d = await resolver.resolve_event(_batch_event(
        "e2", "track", anonymous_id="anon_Z", session_id="sess_Z",
        properties={"event": "newsletter_signup", "email": "JANE@example.com"},
        device={"type": "mobile", "id": "device-123"},
    ), TENANT)
    assert d.confidence_tier == ConfidenceTier.STRONG
    assert "same_email_hash" in d.reason_codes
    assert "consent_allows_link" in d.reason_codes
    # Probabilistic: routed to review, not auto-merged, in staging/production.
    assert d.decision == MergeDecision.CANDIDATE


@pytest.mark.asyncio
async def test_email_without_stitching_consent_is_neither_matched_nor_stored():
    resolver = _resolver()
    first = await resolver.resolve_event(_identify(
        "e1", "anon_A", "sess_A", "user_42", email="jane@example.com",
        consent=NO_STITCHING_CONSENT,
    ), TENANT)
    aliases = await resolver._repo.get_aliases_for_entity(TENANT, first.canonical_entity_id)
    assert "email_hash" not in {a["alias_type"] for a in aliases}

    d = await resolver.resolve_event(_batch_event(
        "e2", "track", anonymous_id="anon_Z", session_id="sess_Z",
        properties={"email": "jane@example.com"},
    ), TENANT)
    assert d.decision == MergeDecision.CREATE
    assert d.canonical_entity_id != first.canonical_entity_id


# -- Units: consent shape, extraction, policy --------------------------------


def test_flat_sdk_consent_state_is_read():
    assert has_stitching_consent(SDK_CONSENT)
    assert not has_stitching_consent(NO_STITCHING_CONSENT)
    assert not has_stitching_consent({"policyVersion": "1", "updatedAt": "x"})
    assert not has_stitching_consent({**SDK_CONSENT, "denied": True})
    assert has_stitching_consent({"purposes": {"identity": True}})
    assert not has_stitching_consent({"purposes": {"analytics": False}})
    assert not has_stitching_consent(None)


def test_identify_traits_and_device_id_become_signals():
    event = _identify("e1", "anon_A", "sess_A", "user_42", email=" Jane@Example.com ")
    event["context"]["device"] = {"type": "mobile", "id": "device-123"}
    types = {s.type for s in extract_signals(event, TENANT)}
    assert {
        IdentitySignalType.USER_ID,
        IdentitySignalType.ANONYMOUS_ID,
        IdentitySignalType.SESSION_ID,
        IdentitySignalType.EMAIL_HASH,
        IdentitySignalType.INSTALLATION_ID,
    } <= types


def _ctx(**kw) -> MergePolicyContext:
    base = dict(
        tenant_id=TENANT, source_tenant_id=TENANT, matching_signal_types=[],
        consent_snapshot=SDK_CONSENT, existing_entity_ids=[],
    )
    base.update(kw)
    return MergePolicyContext(**base)


def test_policy_first_sighting_creates_from_observed_signals():
    r = evaluate(_ctx(observed_signal_types=[
        IdentitySignalType.ANONYMOUS_ID, IdentitySignalType.SESSION_ID,
    ]))
    assert r.decision == MergeDecision.CREATE
    assert not any(c.startswith("same_") for c in r.reason_codes)


def test_policy_first_sighting_fingerprint_only_stays_blocked():
    r = evaluate(_ctx(observed_signal_types=[IdentitySignalType.DEVICE_FINGERPRINT]))
    assert r.decision == MergeDecision.BLOCKED


def test_policy_binding_is_deterministic_but_plain_anonymous_match_is_not():
    bound = evaluate(_ctx(
        matching_signal_types=[IdentitySignalType.ANONYMOUS_ID],
        existing_entity_ids=["e1", "e2"],
        authenticated_binding=True,
    ))
    assert bound.decision == MergeDecision.MERGE
    assert bound.confidence_tier == ConfidenceTier.DETERMINISTIC
    assert bound.merge_all_candidates

    plain = evaluate(_ctx(
        matching_signal_types=[IdentitySignalType.ANONYMOUS_ID],
        existing_entity_ids=["e1"],
    ))
    assert plain.decision == MergeDecision.CANDIDATE

    weak = evaluate(_ctx(
        matching_signal_types=[IdentitySignalType.SESSION_ID],
        existing_entity_ids=["e1"],
    ))
    assert weak.decision == MergeDecision.REJECT
    assert REASON_INSUFFICIENT_EVIDENCE in weak.reason_codes
