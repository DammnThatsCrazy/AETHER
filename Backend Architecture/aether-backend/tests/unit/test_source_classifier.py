"""Focused contracts for canonical AI and agent referral classification."""

from __future__ import annotations

import hashlib

import pytest

from services.traffic.classifier import SOURCE_CLASSIFIER_VERSION, SourceClassifier


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


def test_no_source_evidence_is_direct_entry(classifier: SourceClassifier) -> None:
    result = classifier.classify()

    assert (result.source, result.medium, result.channel) == (
        "(direct)",
        "(none)",
        "Direct",
    )
    assert result.referral_mediation_type == "direct_entry"
    assert result.journey_role == "entry"
