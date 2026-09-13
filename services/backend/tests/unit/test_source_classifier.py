"""Focused contracts for canonical AI and agent referral classification."""

from __future__ import annotations

import hashlib

import pytest

from services.traffic.classifier import SOURCE_CLASSIFIER_VERSION, SourceClassifier
from services.traffic.generated_registry import SOURCE_CLASSES, SOURCE_CLASS_DEFAULTS


@pytest.fixture
def classifier() -> SourceClassifier:
    return SourceClassifier()


def test_classifier_precedence_machine_before_verified_click_utm_and_domain(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        referrer="https://chatgpt.com/share/private?token=secret",
        utm_source="newsletter",
        utm_medium="email",
        click_ids={"gclid": "paid-click"},
        user_agent="Mozilla/5.0 GPTBot/1.2",
        verified_referral={
            "verified_referral_link_id": "link-1",
            "ai_provider": "anthropic",
            "ai_product": "claude",
        },
    )

    assert result.source == "openai"
    assert result.referral_mediation_type == "crawler_discovery"
    assert result.actor_type == "machine"
    assert result.journey_role == "excluded"
    assert result.attribution_eligible is False
    assert result.verified_referral_link_id is None


def test_classifier_precedence_verified_link_before_click_and_utm(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        referrer="https://example.com/path",
        utm_source="google",
        utm_medium="cpc",
        click_ids={"gclid": "paid-click"},
        verified_referral={
            "verified_referral_link_id": "3a37698f-3aee-41df-9255-33ee72e7922a",
            "referral_mediation_type": "owned_agent_referral",
            "ai_provider": "OpenAI",
            "ai_product": "ChatGPT",
            "actor_type": "agent",
        },
    )

    assert result.source == "openai"
    assert result.medium == "agent_referral"
    assert result.ai_provider == "openai"
    assert result.ai_product == "chatgpt"
    assert result.actor_type == "agent"
    assert result.verification_level == "verified_referral_link"
    assert result.evidence == ("verified_referral_link",)


def test_classifier_precedence_click_before_utm_and_ai_domain(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        referrer="https://claude.ai/chat/123",
        utm_source="perplexity",
        utm_medium="ai_referral",
        click_ids={"gclid": "paid-click"},
    )

    assert (result.source, result.medium, result.channel) == (
        "google",
        "cpc",
        "Paid Search",
    )
    assert result.ai_provider is None
    assert result.verification_level == "verified_click_id"


def test_classifier_precedence_utm_before_referrer_domain(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        referrer="https://chatgpt.com/share/123",
        utm_source="Claude",
        utm_medium="referral",
    )

    assert result.source == "anthropic"
    assert result.ai_provider == "anthropic"
    assert result.ai_product == "claude"
    assert result.referral_mediation_type == "ai_mediated_human_referral"
    assert result.verification_level == "declared_campaign_evidence"


@pytest.mark.parametrize(
    ("referrer", "provider", "product"),
    [
        ("https://chatgpt.com/", "openai", "chatgpt"),
        ("https://chat.openai.com/c/1", "openai", "chatgpt"),
        ("https://claude.ai/chat/1", "anthropic", "claude"),
        ("https://gemini.google.com/app/1", "google", "gemini"),
        ("https://copilot.microsoft.com/chats/1", "microsoft", "copilot"),
        ("https://www.perplexity.ai/search/1", "perplexity", "perplexity"),
    ],
)
def test_known_ai_domains_normalize_provider_and_product(
    classifier: SourceClassifier,
    referrer: str,
    provider: str,
    product: str,
) -> None:
    result = classifier.classify(referrer=referrer)

    assert result.source_class == "ai_referral"
    assert result.ai_provider == provider
    assert result.ai_product == product
    assert result.referral_mediation_type == "ai_mediated_human_referral"
    assert result.actor_type == "human"
    assert result.attribution_eligible is True


def test_ai_domain_matching_is_hostname_boundary_safe(classifier: SourceClassifier) -> None:
    result = classifier.classify(referrer="https://evilchatgpt.com/private")

    assert result.source_class == "external_referral"
    assert result.ai_provider is None
    assert result.source == "evilchatgpt.com"


@pytest.mark.parametrize(
    ("user_agent", "mediation", "channel"),
    [
        ("Proofpoint URL Defense", "scanner", "Machine Referral"),
        ("Slackbot-LinkExpanding 1.0", "link_preview", "Machine Referral"),
        ("PerplexityBot/1.0", "crawler_discovery", "AI Crawler"),
    ],
)
def test_machine_evidence_is_excluded_from_journeys_and_attribution(
    classifier: SourceClassifier,
    user_agent: str,
    mediation: str,
    channel: str,
) -> None:
    result = classifier.classify(
        referrer="https://example.com/path",
        user_agent=user_agent,
    )

    assert result.actor_type == "machine"
    assert result.referral_mediation_type == mediation
    assert result.channel == channel
    assert result.journey_role == "excluded"
    assert result.attribution_eligible is False


def test_agent_user_agent_remains_eligible_and_is_not_machine_noise(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(user_agent="ChatGPT-User/1.0")

    assert result.actor_type == "agent"
    assert result.ai_provider == "openai"
    assert result.ai_product == "chatgpt"
    assert result.journey_role == "handoff"
    assert result.attribution_eligible is True


def test_referrer_normalization_never_returns_path_query_fragment_credentials_or_port(
    classifier: SourceClassifier,
) -> None:
    raw_path = "/c/customer@example.com/private"
    referrer = (
        "https://user:password@ChatGPT.com:8443"
        f"{raw_path}?access_token=top-secret#private-fragment"
    )

    result = classifier.classify(referrer=referrer)

    assert result.normalized_referrer_domain == "chatgpt.com"
    assert result.normalized_referrer == "https://chatgpt.com/"
    assert result.referrer_path_hash == hashlib.sha256(raw_path.encode()).hexdigest()[:24]
    serialized = repr(result) + repr(result.evidence_payload())
    for sensitive_value in (
        "customer@example.com",
        "access_token",
        "top-secret",
        "password",
        "private-fragment",
        ":8443",
    ):
        assert sensitive_value not in serialized
    assert result.classifier_version == SOURCE_CLASSIFIER_VERSION


def test_no_source_evidence_is_direct_unknown_never_a_typed_url_claim(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify()

    # v3 intentionally replaces the v2 "Direct"/"direct" claim: absence of
    # evidence is reported as Direct / Unknown, never as typed-URL traffic.
    assert (result.source, result.medium, result.channel) == (
        "(direct)",
        "(none)",
        SOURCE_CLASS_DEFAULTS["direct_unknown"]["label"],
    )
    assert result.source_class == "direct_unknown"
    assert result.channel == "Direct / Unknown"
    assert result.referral_mediation_type == "direct_entry"
    assert result.journey_role == "entry"
    assert result.proof_level == "none"
    assert result.entry_method == "unknown"
    assert result.economic_class == "unknown"
    assert result.channel_family == "direct"
    assert result.evidence_conflicts == ()


# ── Canonical dimension matrix (v3 truth model) ──────────────────────────────


@pytest.mark.parametrize(
    ("referrer", "source_class", "economic_class", "channel_family"),
    [
        ("https://www.google.com/search?q=x", "organic_search", "unpaid", "search"),
        ("https://www.bing.com/search?q=x", "organic_search", "unpaid", "search"),
        ("https://twitter.com/somebody/status/1", "organic_social", "unpaid", "social"),
        ("https://www.linkedin.com/feed/", "organic_social", "unpaid", "social"),
    ],
)
def test_known_referrer_domains_carry_canonical_dimensions(
    classifier: SourceClassifier,
    referrer: str,
    source_class: str,
    economic_class: str,
    channel_family: str,
) -> None:
    result = classifier.classify(referrer=referrer)

    assert result.source_class == source_class
    assert result.economic_class == economic_class
    assert result.channel_family == channel_family
    assert result.entry_method == "web_referrer"
    assert result.proof_level == "domain_verified"
    assert result.traffic_origin == "external"
    assert result.evidence_conflicts == ()


def test_unknown_external_domain_is_external_referral(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(referrer="https://blog.smallpartner.example/post")

    assert result.source_class == "external_referral"
    assert result.economic_class == "unknown"
    assert result.channel_family == "referral"
    assert result.entry_method == "web_referrer"
    assert result.proof_level == "domain_verified"


@pytest.mark.parametrize(
    ("utm_source", "utm_medium", "source_class", "economic_class", "channel_family", "source"),
    [
        ("twitter", "social", "organic_social", "unpaid", "social", "twitter"),
        ("twitter", "organic", "organic_social", "unpaid", "social", "twitter"),
        ("x", "social", "organic_social", "unpaid", "social", "twitter"),
        ("google", "organic", "organic_search", "unpaid", "search", "google"),
        ("duckduckgo", "seo", "organic_search", "unpaid", "search", "duckduckgo"),
        ("google", "cpc", "paid_search", "paid", "search", "google"),
        ("facebook", "paid_social", "paid_social", "paid", "social", "facebook"),
        ("mailchimp", "email", "email", "unpaid", "email", "mailchimp"),
        ("impact", "affiliate", "affiliate", "paid", "affiliate", "impact"),
        ("acme", "partner", "partner", "unknown", "partner", "acme"),
        ("onesignal", "push", "push", "unpaid", "push", "onesignal"),
        ("twilio", "sms", "sms", "unpaid", "sms", "twilio"),
    ],
)
def test_utm_source_and_medium_are_co_evaluated(
    classifier: SourceClassifier,
    utm_source: str,
    utm_medium: str,
    source_class: str,
    economic_class: str,
    channel_family: str,
    source: str,
) -> None:
    result = classifier.classify(utm_source=utm_source, utm_medium=utm_medium)

    assert result.source_class == source_class
    assert result.economic_class == economic_class
    assert result.channel_family == channel_family
    assert result.source == source
    assert result.channel == SOURCE_CLASS_DEFAULTS[source_class]["label"]
    assert result.entry_method == "utm_declaration"
    assert result.proof_level == "declared"
    assert result.evidence_conflicts == ()


def test_unknown_utm_source_with_organic_medium_is_not_organic_search(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(utm_source="mysterysite", utm_medium="organic")

    assert result.source_class == "unknown"
    assert result.economic_class == "unpaid"
    assert result.channel_family == "unknown"
    assert result.source == "mysterysite"
    # The declaration itself is preserved as evidence.
    assert "utm_source" in result.evidence
    assert result.entry_method == "utm_declaration"
    assert result.proof_level == "declared"


def test_unmatched_declared_utm_keeps_declared_external_referral(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(utm_source="somevendor", utm_medium="banner")

    assert result.source_class == "external_referral"
    assert result.channel == "Display"
    assert result.source == "somevendor"
    assert result.verification_level == "declared_campaign_evidence"


@pytest.mark.parametrize(
    ("click_ids", "source_class", "source", "channel"),
    [
        ({"gclid": "abc"}, "paid_search", "google", "Paid Search"),
        ({"wbraid": "abc"}, "paid_search", "google", "Paid Search"),
        ({"fbclid": "abc"}, "paid_social", "facebook", "Paid Social"),
        ({"dclid": "abc"}, "display", "google", "Display"),
        ({"irclickid": "abc"}, "affiliate", "impact", "Affiliate"),
    ],
)
def test_click_ids_classify_to_canonical_paid_classes(
    classifier: SourceClassifier,
    click_ids: dict[str, str],
    source_class: str,
    source: str,
    channel: str,
) -> None:
    result = classifier.classify(click_ids=click_ids)

    assert result.source_class == source_class
    assert result.source == source
    assert result.channel == channel
    assert result.economic_class == "paid"
    assert result.entry_method == "paid_click_id"
    assert result.proof_level == "declared"
    assert result.verification_level == "verified_click_id"


def test_gclid_with_organic_utm_classifies_paid_and_records_conflict(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        utm_source="google",
        utm_medium="organic",
        click_ids={"gclid": "paid-click"},
    )

    assert result.source_class == "paid_search"
    assert result.economic_class == "paid"
    assert result.channel_family == "search"
    assert result.evidence_conflicts == (
        "paid_click_id_overrides_organic_utm:gclid",
    )


def test_verified_link_disagreeing_with_utm_records_conflict(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        utm_source="newsletter-tool",
        utm_medium="email",
        verified_referral={
            "verified_referral_link_id": "3a37698f-3aee-41df-9255-33ee72e7922a",
            "referral_mediation_type": "owned_agent_referral",
            "ai_provider": "openai",
            "ai_product": "chatgpt",
            "actor_type": "agent",
        },
    )

    assert result.source_class == "agent_referral"
    assert result.proof_level == "server_observed"
    assert result.entry_method == "verified_source_link"
    assert result.evidence_conflicts == (
        "verified_link_overrides_utm_declaration:newsletter-tool",
    )


def test_ai_domain_and_email_domain_dimension_defaults(
    classifier: SourceClassifier,
) -> None:
    ai = classifier.classify(referrer="https://claude.ai/chat/1")
    email = classifier.classify(referrer="https://mail.google.com/mail/u/0/")

    assert ai.source_class == "ai_referral"
    assert ai.economic_class == "unpaid"
    assert ai.channel_family == "ai"
    assert ai.proof_level == "domain_verified"
    assert email.source_class == "email"
    assert email.economic_class == "unpaid"
    assert email.channel_family == "email"
    assert email.entry_method == "web_referrer"


def test_machine_user_agent_is_nonhuman_machine_family(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(
        referrer="https://example.com/path",
        user_agent="Mozilla/5.0 GPTBot/1.2",
    )

    assert result.source_class == "machine_referral"
    assert result.attribution_eligible is False
    assert result.economic_class == "nonhuman"
    assert result.channel_family == "machine"
    assert result.traffic_origin == "external"
    assert result.proof_level == "server_observed"


def test_agent_user_agent_is_agent_referral_class(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(user_agent="ChatGPT-User/1.0")

    assert result.source_class == "agent_referral"
    assert result.channel_family == "agent"
    assert result.economic_class == "unpaid"
    assert result.attribution_eligible is True


def test_declared_entry_method_refines_direct_without_source_claim(
    classifier: SourceClassifier,
) -> None:
    result = classifier.classify(declared_entry_method="ios_universal_link")

    assert result.source_class == "direct_unknown"
    assert result.entry_method == "ios_universal_link"
    assert result.proof_level == "declared"
    assert "declared_entry_method:ios_universal_link" in result.evidence


def test_source_class_outputs_are_registry_canonical(
    classifier: SourceClassifier,
) -> None:
    samples = [
        classifier.classify(),
        classifier.classify(referrer="https://google.com/"),
        classifier.classify(utm_source="google", utm_medium="cpc"),
        classifier.classify(click_ids={"gclid": "x"}),
        classifier.classify(user_agent="Mozilla/5.0 GPTBot/1.2"),
    ]
    for result in samples:
        assert result.source_class in SOURCE_CLASSES
        assert result.economic_class in {"paid", "unpaid", "unknown", "nonhuman"}
        payload = result.evidence_payload()
        assert payload["economic_class"] == result.economic_class
        assert payload["channel_family"] == result.channel_family
        assert payload["entry_method"] == result.entry_method
        assert payload["proof_level"] == result.proof_level
        assert payload["conflicts"] == list(result.evidence_conflicts)
