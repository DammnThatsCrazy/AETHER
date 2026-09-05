"""Per-projector honesty for the six Social Silver projectors (M3).

Each ``social_*`` projector turns a generic Bronze provider event into rows on a
single ``silver_social_*_facts`` table. These tests pin the honesty rules the
blueprint and the M1 ``social-silver-facts.schema.json`` encode:

- identity: provider-native ``account_type`` / ``verification_state`` tokens
  normalize to the canonical vocabulary; unknown -> ``unknown``; a missing
  ``provider_account_id`` cannot anchor a fact and is skipped; a resolved
  ``canonical_entity_ref`` is only ever recorded when upstream supplied it;
- connection: ``friend`` requires an explicit provider assertion — a
  ``mutual_follow`` token NEVER becomes ``friend``; ``friends`` -> ``friend``
  (undirected); follows/followed_by/blocks stay directed; bare identity refs are
  canonicalized to ``<provider>:<ref>``; unmapped relationship tokens are
  skipped, never guessed;
- interaction: ``tweet`` -> ``post``; a missing actor or an unmapped token is
  skipped; message body/content text is NEVER carried onto a silver row;
- content: ``tweet`` -> ``post``; an unmapped token is an honest ``other`` with
  the provider subtype preserved; no content-type token is skipped;
  ``content_hash`` is only ever the provider/upstream-supplied fingerprint and
  is never synthesized;
- community: ``mod``/``admin``/``owner``/``creator`` map to the canonical role
  vocabulary; unmapped roles default to ``unknown`` with the provider role
  preserved for explainability;
- metric: absent value -> value NULL + status ``unavailable`` (NEVER 0);
  explicit ``0`` is a measurement and is kept; ``not_authorized`` is preserved;
  string values are never parsed into numbers; a metric bundle fans out one row
  per metric with a stable per-metric idempotency key.
"""
from __future__ import annotations

# conftest.py has prepended the worktree backend path, so these imports resolve
# to THIS checkout, not the editable install that points at /Users/osazehunt/AETHER.
from shared.social360.canonical import SOURCE_SCOPES  # noqa: E402
from services.silver.projectors.social_identity_projector import (  # noqa: E402
    SOCIAL_IDENTITY_TABLE,
    SocialIdentityProjector,
)
from services.silver.projectors.social_connection_projector import (  # noqa: E402
    SOCIAL_CONNECTION_TABLE,
    SocialConnectionProjector,
)
from services.silver.projectors.social_interaction_projector import (  # noqa: E402
    SOCIAL_INTERACTION_TABLE,
    SocialInteractionProjector,
)
from services.silver.projectors.social_content_projector import (  # noqa: E402
    SOCIAL_CONTENT_TABLE,
    SocialContentProjector,
)
from services.silver.projectors.social_community_projector import (  # noqa: E402
    SOCIAL_COMMUNITY_TABLE,
    SocialCommunityMembershipProjector,
)
from services.silver.projectors.social_metric_projector import (  # noqa: E402
    SOCIAL_METRIC_TABLE,
    SocialMetricProjector,
)

TS = "2026-09-01T00:00:00+00:00"
IDENTITY = "social_identity_observed"
CONNECTION = "social_connection_observed"
INTERACTION = "social_interaction_observed"
CONTENT = "social_content_observed"
COMMUNITY = "social_community_membership_observed"
METRIC = "social_metric_observed"


def _skipped(result):
    return result is not None and result.skipped


# ── social identity ─────────────────────────────────────────────────────────


def test_identity_person_to_human_and_blue_verified_to_provider_verified(social_event):
    event = social_event(
        type_=IDENTITY,
        properties={
            "provider_account_id": "acct-1",
            "account_type": "person",
            "verification_state": "blue_verified",
        },
    )
    result = SocialIdentityProjector().project(event)
    assert result is not None and result.table == SOCIAL_IDENTITY_TABLE
    row = result.rows[0]
    assert row["account_type"] == "human"
    assert row["verification_state"] == "provider_verified"
    assert row["provider_identity"] == "x"
    assert row["provider_account_id"] == "acct-1"
    assert row["social_identity_id"] == "x:acct-1"
    # single-record event keeps the bare source_event_id as its idempotency key
    assert row["idempotency_key"] == "evt-1"


def test_identity_unknown_tokens_default_to_unknown(social_event):
    event = social_event(
        type_=IDENTITY,
        properties={
            "provider_account_id": "acct-1",
            "account_type": "mystery_kind",
            "verification_state": "vermillion_check",
        },
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["account_type"] == "unknown"
    assert row["verification_state"] == "unknown"


def test_identity_defaults_unresolved_and_no_synthesized_binding(social_event):
    # No upstream binding supplied -> canonical_entity_ref stays None, and the
    # projector does not claim "first seen now" on a stateless re-read.
    event = social_event(
        type_=IDENTITY,
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["resolution_state"] == "unresolved"
    assert row["resolution_confidence"] is None
    assert row["canonical_entity_ref"] is None
    assert row["first_observed_at"] is None


def test_identity_canonical_entity_ref_only_when_upstream_supplied(social_event):
    upstream = social_event(
        type_=IDENTITY,
        properties={
            "provider_account_id": "acct-1",
            "canonical_entity_ref": "entity:u-777",
        },
    )
    row = SocialIdentityProjector().project(upstream).rows[0]
    assert row["canonical_entity_ref"] == "entity:u-777"
    # from event.context.canonicalEntityRef as well
    ctx_event = social_event(
        type_=IDENTITY,
        context={"tenantId": "tenant-t1", "canonicalEntityRef": "entity:u-888"},
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(ctx_event).rows[0]
    assert row["canonical_entity_ref"] == "entity:u-888"


def test_identity_missing_provider_account_id_is_skipped(social_event):
    event = social_event(type_=IDENTITY, properties={"handle": "nobody"})
    result = SocialIdentityProjector().project(event)
    assert _skipped(result)
    assert result.rows == []
    assert result.skip_reason == "no_projectable_social_record"


def test_identity_account_type_alias_coverage(social_event):
    aliases = {
        "individual": "human", "user": "human", "bot": "agent",
        "org": "organization", "group": "community", "channel": "service",
    }
    for token, expected in aliases.items():
        event = social_event(
            type_=IDENTITY,
            properties={"provider_account_id": "acct-1", "account_type": token},
        )
        row = SocialIdentityProjector().project(event).rows[0]
        assert row["account_type"] == expected, token


def test_identity_verification_alias_coverage(social_event):
    aliases = {"verified": "provider_verified", "email_confirm": "email_verified"}
    for token, expected in aliases.items():
        event = social_event(
            type_=IDENTITY,
            properties={"provider_account_id": "acct-1", "verification_state": token},
        )
        row = SocialIdentityProjector().project(event).rows[0]
        assert row["verification_state"] == expected, token


# ── social connection ───────────────────────────────────────────────────────


def test_connection_mutual_follow_never_becomes_friend(social_event):
    # 'friend' is only ever a provider assertion. A mutual_follow token yields a
    # mutual_follow fact (reciprocal_pair), never a friend fact.
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "mutual_follow",
        },
    )
    result = SocialConnectionProjector().project(event)
    assert result.table == SOCIAL_CONNECTION_TABLE
    row = result.rows[0]
    assert row["connection_type"] == "mutual_follow"
    assert row["connection_type"] != "friend"
    assert row["directionality"] == "reciprocal_pair"


def test_connection_friends_alias_is_explicit_friend_undirected(social_event):
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "friends",
        },
    )
    row = SocialConnectionProjector().project(event).rows[0]
    assert row["connection_type"] == "friend"
    assert row["directionality"] == "undirected"


def test_connection_follows_is_directed(social_event):
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "follows",
        },
    )
    row = SocialConnectionProjector().project(event).rows[0]
    assert row["connection_type"] == "follows"
    assert row["directionality"] == "directed"


def test_connection_followed_by_and_blocks_are_directed(social_event):
    for token in ("followed_by", "blocks", "member_of", "moderates"):
        event = social_event(
            type_=CONNECTION,
            properties={
                "source_social_identity_ref": "alice",
                "target_social_identity_ref": "bob",
                "connection_type": token,
            },
        )
        row = SocialConnectionProjector().project(event).rows[0]
        assert row["connection_type"] == token
        assert row["directionality"] == "directed", token


def test_connection_bare_refs_are_canonicalized(social_event):
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "follows",
        },
    )
    row = SocialConnectionProjector().project(event).rows[0]
    assert row["source_social_identity_ref"] == "x:alice"
    assert row["target_social_identity_ref"] == "x:bob"
    # an already-canonical ref passes through untouched
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "x:alice",
            "target_social_identity_ref": "x:bob",
            "connection_type": "follows",
        },
    )
    row = SocialConnectionProjector().project(event).rows[0]
    assert row["source_social_identity_ref"] == "x:alice"


def test_connection_unmapped_token_is_skipped_not_guessed(social_event):
    event = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "colleague",
        },
    )
    result = SocialConnectionProjector().project(event)
    assert _skipped(result)
    assert result.skip_reason == "no_projectable_social_record"


def test_connection_missing_ref_is_skipped(social_event):
    event = social_event(
        type_=CONNECTION,
        properties={"source_social_identity_ref": "alice", "connection_type": "follows"},
    )
    result = SocialConnectionProjector().project(event)
    assert _skipped(result)


def test_connection_proof_and_claim_defaults_from_evidence_basis(social_event):
    # Default envelope acquisition_mode=poll -> evidence_basis provider_api ->
    # provider_observed / observed. derived_aggregate evidence yields inferred /
    # derived instead.
    observed = social_event(
        type_=CONNECTION,
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "follows",
        },
    )
    row = SocialConnectionProjector().project(observed).rows[0]
    assert row["proof_level"] == "provider_observed"
    assert row["claim_type"] == "observed"

    derived = social_event(
        type_=CONNECTION,
        envelope={"provider": "x", "acquisition_mode": "poll",
                  "evidence_basis": "derived_aggregate"},
        properties={
            "source_social_identity_ref": "alice",
            "target_social_identity_ref": "bob",
            "connection_type": "follows",
        },
    )
    row = SocialConnectionProjector().project(derived).rows[0]
    assert row["proof_level"] == "inferred_with_limitations"
    assert row["claim_type"] == "derived"


# ── social interaction ──────────────────────────────────────────────────────


def test_interaction_tweet_aliases_to_post(social_event):
    event = social_event(
        type_=INTERACTION,
        properties={"actor_social_identity_ref": "alice", "interaction_type": "tweet"},
    )
    result = SocialInteractionProjector().project(event)
    assert result.table == SOCIAL_INTERACTION_TABLE
    row = result.rows[0]
    assert row["interaction_type"] == "post"
    assert row["actor_social_identity_ref"] == "alice"
    assert row["interaction_id"] == f"x:alice:post:{TS}"


def test_interaction_missing_actor_is_skipped(social_event):
    event = social_event(
        type_=INTERACTION, properties={"interaction_type": "tweet"}
    )
    result = SocialInteractionProjector().project(event)
    assert _skipped(result)


def test_interaction_unmapped_token_is_skipped(social_event):
    event = social_event(
        type_=INTERACTION,
        properties={"actor_social_identity_ref": "alice", "interaction_type": "zorp"},
    )
    result = SocialInteractionProjector().project(event)
    assert _skipped(result)


def test_interaction_never_carries_message_body_onto_silver_row(social_event):
    # Communication360 governs private message content; Social360 carries
    # authorized metadata only. Provide a body explicitly and assert it never
    # reaches the silver row in any key or value.
    event = social_event(
        type_=INTERACTION,
        properties={
            "actor_social_identity_ref": "alice",
            "interaction_type": "message_metadata",
            "content_ref": "content-1",
            "body": "super-secret-message-text",
            "content": "super-secret-message-text",
        },
    )
    row = SocialInteractionProjector().project(event).rows[0]
    assert row["interaction_type"] == "message_metadata"
    assert "super-secret-message-text" not in row.values()
    for key in ("body", "content", "text", "message_body"):
        assert key not in row


def test_interaction_reply_and_retweet_aliases(social_event):
    reply = social_event(
        type_=INTERACTION,
        properties={"actor_social_identity_ref": "alice", "interaction_type": "answer"},
    )
    assert SocialInteractionProjector().project(reply).rows[0]["interaction_type"] == "reply"
    rt = social_event(
        type_=INTERACTION,
        properties={"actor_social_identity_ref": "alice", "interaction_type": "retweet"},
    )
    assert SocialInteractionProjector().project(rt).rows[0]["interaction_type"] == "repost"


# ── social content ──────────────────────────────────────────────────────────


def test_content_tweet_aliases_to_post_and_canonicalizes_refs(social_event):
    event = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "tweet",
        },
    )
    result = SocialContentProjector().project(event)
    assert result.table == SOCIAL_CONTENT_TABLE
    row = result.rows[0]
    assert row["content_type"] == "post"
    assert row["author_social_identity_ref"] == "x:alice"
    assert row["provider_content_id"] == "c1"
    assert row["content_id"] == "x:c1"


def test_content_hash_never_synthesized(social_event):
    # No hash supplied -> NULL, even though the projector can see a body it must
    # not fingerprint.
    event = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "post",
            "body": "some text the projector can see but must never hash",
        },
    )
    row = SocialContentProjector().project(event).rows[0]
    assert row["content_hash"] is None
    # provider/upstream-supplied fingerprint is honored verbatim (incl. media_hash)
    supplied = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "post",
            "content_hash": "provider-hash-abc",
        },
    )
    assert SocialContentProjector().project(supplied).rows[0]["content_hash"] == "provider-hash-abc"
    media = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "image",
            "media_hash": "media-hash-def",
        },
    )
    assert SocialContentProjector().project(media).rows[0]["content_hash"] == "media-hash-def"


def test_content_unmapped_token_is_honest_other_with_subtype(social_event):
    event = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "fleek_note",
        },
    )
    row = SocialContentProjector().project(event).rows[0]
    assert row["content_type"] == "other"
    assert row["provider_content_subtype"] == "fleek_note"


def test_content_without_type_token_is_skipped(social_event):
    event = social_event(
        type_=CONTENT,
        properties={"provider_content_id": "c1", "author_social_identity_ref": "alice"},
    )
    result = SocialContentProjector().project(event)
    assert _skipped(result)


def test_content_never_stores_body_text(social_event):
    event = social_event(
        type_=CONTENT,
        properties={
            "provider_content_id": "c1",
            "author_social_identity_ref": "alice",
            "content_type": "post",
            "body": "super-secret-post-text",
            "content": "super-secret-post-text",
            "media_url": "super-secret-post-text",
        },
    )
    row = SocialContentProjector().project(event).rows[0]
    assert "super-secret-post-text" not in row.values()
    for key in ("body", "content", "text", "media_url"):
        assert key not in row


# ── social community membership ─────────────────────────────────────────────


def test_community_mod_admin_owner_creator_mapping(social_event):
    cases = {
        "mod": "moderator",
        "moderating": "moderator",
        "admin": "administrator",
        "owner": "founder",
        "creator": "founder",
        "member": "member",
    }
    for token, expected in cases.items():
        event = social_event(
            type_=COMMUNITY,
            properties={
                "social_identity_ref": "alice",
                "community_ref": "comm-1",
                "membership_role": token,
            },
        )
        result = SocialCommunityMembershipProjector().project(event)
        assert result.table == SOCIAL_COMMUNITY_TABLE
        row = result.rows[0]
        assert row["membership_role"] == expected, token
        assert row["social_identity_ref"] == "x:alice"
        assert row["community_ref"] == "x:comm-1"


def test_community_unmapped_role_defaults_unknown_and_preserves_provider_role(social_event):
    event = social_event(
        type_=COMMUNITY,
        properties={
            "social_identity_ref": "alice",
            "community_ref": "comm-1",
            "membership_role": "super_admin",
        },
    )
    row = SocialCommunityMembershipProjector().project(event).rows[0]
    assert row["membership_role"] == "unknown"
    assert row["provider_membership_role"] == "super_admin"


def test_community_canonical_role_leaves_provider_role_null(social_event):
    event = social_event(
        type_=COMMUNITY,
        properties={
            "social_identity_ref": "alice",
            "community_ref": "comm-1",
            "membership_role": "member",
        },
    )
    row = SocialCommunityMembershipProjector().project(event).rows[0]
    assert row["membership_role"] == "member"
    assert row["provider_membership_role"] is None


def test_community_missing_member_or_community_is_skipped(social_event):
    no_member = social_event(
        type_=COMMUNITY, properties={"community_ref": "comm-1"}
    )
    assert _skipped(SocialCommunityMembershipProjector().project(no_member))
    no_community = social_event(
        type_=COMMUNITY, properties={"social_identity_ref": "alice"}
    )
    assert _skipped(SocialCommunityMembershipProjector().project(no_community))


# ── social metric observation ───────────────────────────────────────────────


def test_metric_absent_value_is_null_unavailable_never_zero(social_event):
    event = social_event(
        type_=METRIC,
        properties={"metric_name": "follower_count", "value": None, "unit": "count"},
    )
    result = SocialMetricProjector().project(event)
    assert result.table == SOCIAL_METRIC_TABLE
    row = result.rows[0]
    assert row["value"] is None
    assert row["status"] == "unavailable"
    assert row["value"] != 0
    # idempotency key reduces to the bare source_event_id for a single metric
    assert row["idempotency_key"] == "evt-1"


def test_metric_explicit_zero_is_a_measurement(social_event):
    event = social_event(
        type_=METRIC,
        properties={"metric_name": "follower_count", "value": 0, "unit": "count"},
    )
    row = SocialMetricProjector().project(event).rows[0]
    assert row["value"] == 0
    assert row["status"] == "observed"


def test_metric_not_authorized_status_is_preserved(social_event):
    event = social_event(
        type_=METRIC,
        properties={
            "metric_name": "follower_count",
            "value": None,
            "status": "not_authorized",
            "unit": "count",
        },
    )
    row = SocialMetricProjector().project(event).rows[0]
    assert row["value"] is None
    assert row["status"] == "not_authorized"


def test_metric_string_value_is_never_parsed_into_a_number(social_event):
    event = social_event(
        type_=METRIC,
        properties={"metric_name": "follower_count", "value": "123", "unit": "count"},
    )
    row = SocialMetricProjector().project(event).rows[0]
    assert row["value"] is None
    assert row["status"] == "unavailable"


def test_metric_name_is_recorded_verbatim(social_event):
    event = social_event(
        type_=METRIC,
        properties={
            "metric_name": "provider_reported_impressions",
            "value": 1200,
            "unit": "count",
        },
    )
    row = SocialMetricProjector().project(event).rows[0]
    assert row["metric_name"] == "provider_reported_impressions"
    assert row["value"] == 1200
    assert row["status"] == "observed"


def test_metric_bundle_fans_out_with_per_metric_idempotency_keys(social_event):
    event = social_event(
        type_=METRIC,
        properties={
            "records": [
                {"metric_name": "follower_count", "value": 100, "unit": "count",
                 "social_identity_ref": "alice"},
                {"metric_name": "following_count", "value": None, "unit": "count",
                 "social_identity_ref": "alice"},
            ]
        },
    )
    result = SocialMetricProjector().project(event)
    assert not result.skipped
    assert len(result.rows) == 2
    keys = sorted(row["idempotency_key"] for row in result.rows)
    assert keys == ["evt-1:follower_count", "evt-1:following_count"]
    by_name = {row["metric_name"]: row for row in result.rows}
    assert by_name["follower_count"]["value"] == 100
    assert by_name["follower_count"]["status"] == "observed"
    assert by_name["following_count"]["value"] is None
    assert by_name["following_count"]["status"] == "unavailable"


def test_metric_missing_name_is_skipped(social_event):
    event = social_event(
        type_=METRIC, properties={"value": 100, "unit": "count"}
    )
    assert _skipped(SocialMetricProjector().project(event))


# ── canonical provenance stamping (cross-cutting) ───────────────────────────


def test_provenance_acquisition_mode_derivation(social_event):
    # poll -> tenant_connected / provider_api
    event = social_event(
        type_=IDENTITY,
        envelope={"provider": "x", "acquisition_mode": "poll"},
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] == "tenant_connected"
    assert row["evidence_basis"] == "provider_api"

    # sdk -> tenant_first_party / first_party_sdk
    sdk = social_event(
        type_=IDENTITY,
        envelope={"provider": "x", "acquisition_mode": "sdk"},
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(sdk).rows[0]
    assert row["source_scope"] == "tenant_first_party"
    assert row["evidence_basis"] == "first_party_sdk"

    # import -> tenant_imported / imported_source
    imp = social_event(
        type_=IDENTITY,
        envelope={"provider": "x", "acquisition_mode": "import"},
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(imp).rows[0]
    assert row["source_scope"] == "tenant_imported"
    assert row["evidence_basis"] == "imported_source"


def test_provenance_explicit_record_stamp_wins_over_derivation(social_event):
    # record-level canonical stamp beats acquisition-mode derivation
    event = social_event(
        type_=IDENTITY,
        envelope={"provider": "x", "acquisition_mode": "poll"},
        properties={
            "provider_account_id": "acct-1",
            "source_scope": "tenant_imported",
            "evidence_basis": "imported_source",
        },
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] == "tenant_imported"
    assert row["evidence_basis"] == "imported_source"


def test_provenance_explicit_envelope_stamp_wins_over_derivation(social_event):
    event = social_event(
        type_=IDENTITY,
        envelope={
            "provider": "x",
            "acquisition_mode": "import",
            "source_scope": "tenant_connected",
            "evidence_basis": "provider_record",
        },
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] == "tenant_connected"
    assert row["evidence_basis"] == "provider_record"


def test_provenance_camel_case_record_stamp_accepted(social_event):
    event = social_event(
        type_=IDENTITY,
        envelope={"provider": "x", "acquisition_mode": "poll"},
        properties={
            "provider_account_id": "acct-1",
            "sourceScope": "tenant_imported",
            "evidenceBasis": "imported_source",
        },
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] == "tenant_imported"
    assert row["evidence_basis"] == "imported_source"


def test_provenance_no_envelope_leaves_source_scope_null_and_evidence_unknown(social_event):
    # A provider identity exists but no acquisition mode / stamp is present:
    # source_scope has no "unknown" member so it stays NULL, while evidence_basis
    # falls back to its honest "unknown" member.
    event = social_event(
        type_=IDENTITY,
        envelope={"provider": "x"},
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] is None
    assert row["evidence_basis"] == "unknown"


def test_provenance_invalid_explicit_scope_is_not_honored(social_event):
    # an out-of-vocabulary explicit stamp must NOT leak onto the row; derivation
    # (or unknown) applies instead.
    event = social_event(
        type_=IDENTITY,
        envelope={
            "provider": "x",
            "acquisition_mode": "poll",
            "source_scope": "olympus_corpus_sneaky",
            "evidence_basis": "server_observed",
        },
        properties={"provider_account_id": "acct-1"},
    )
    row = SocialIdentityProjector().project(event).rows[0]
    assert row["source_scope"] in SOURCE_SCOPES
    assert row["source_scope"] == "tenant_connected"
    assert row["evidence_basis"] == "provider_api"


def test_provenance_never_auto_derives_olympus_corpus(social_event):
    for mode in ("sdk", "webhook", "poll", "report", "stream", "import", "reconciliation"):
        event = social_event(
            type_=IDENTITY,
            envelope={"provider": "x", "acquisition_mode": mode},
            properties={"provider_account_id": "acct-1"},
        )
        row = SocialIdentityProjector().project(event).rows[0]
        assert row["source_scope"] != "olympus_corpus", mode
