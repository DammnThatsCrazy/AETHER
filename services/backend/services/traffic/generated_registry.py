# DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json
# Run: python scripts/generate_contracts.py
# Contract version: 1.0.0
"""Canonical traffic-source vocabulary shared by classifier, projections and APIs."""

TRAFFIC_SOURCE_CONTRACT_VERSION = "1.0.0"

TRAFFIC_ORIGINS: frozenset[str] = frozenset({
    "app_store",
    "external",
    "internal",
    "offline",
    "unknown",
})

ECONOMIC_CLASSES: frozenset[str] = frozenset({
    "nonhuman",
    "paid",
    "unknown",
    "unpaid",
})

CHANNEL_FAMILIES: frozenset[str] = frozenset({
    "affiliate",
    "agent",
    "ai",
    "app_store",
    "direct",
    "email",
    "internal",
    "machine",
    "partner",
    "push",
    "referral",
    "search",
    "sms",
    "social",
    "unknown",
})

SOURCE_CLASSES: frozenset[str] = frozenset({
    "affiliate",
    "agent_referral",
    "ai_referral",
    "app_store_referral",
    "direct_unknown",
    "display",
    "email",
    "external_referral",
    "internal_navigation",
    "machine_referral",
    "organic_search",
    "organic_social",
    "owned_referral",
    "paid_search",
    "paid_social",
    "partner",
    "push",
    "sms",
    "unknown",
})

ENTRY_METHODS: frozenset[str] = frozenset({
    "android_app_link",
    "android_install_referrer",
    "email_link",
    "internal_navigation",
    "ios_adattributionkit",
    "ios_custom_url",
    "ios_universal_link",
    "manual_sdk_evidence",
    "nfc",
    "paid_click_id",
    "push_notification",
    "qr_code",
    "server_redirect",
    "unknown",
    "utm_declaration",
    "vanity_url",
    "verified_source_link",
    "web_referrer",
})

PROOF_LEVELS: frozenset[str] = frozenset({
    "cryptographic",
    "declared",
    "domain_verified",
    "inferred",
    "none",
    "platform_verified",
    "server_observed",
})

# source_class -> {channelFamily, economicClass, label}. Labels are the
# customer-facing vocabulary: direct_unknown renders as 'Direct / Unknown',
# never as an unsupported typed-URL claim.
SOURCE_CLASS_DEFAULTS: dict[str, dict[str, str]] = {
    "affiliate": {"channelFamily": "affiliate", "economicClass": "paid", "label": "Affiliate"},
    "agent_referral": {"channelFamily": "agent", "economicClass": "unpaid", "label": "Agent Referral"},
    "ai_referral": {"channelFamily": "ai", "economicClass": "unpaid", "label": "AI Referral"},
    "app_store_referral": {"channelFamily": "app_store", "economicClass": "unknown", "label": "App Install"},
    "direct_unknown": {"channelFamily": "direct", "economicClass": "unknown", "label": "Direct / Unknown"},
    "display": {"channelFamily": "search", "economicClass": "paid", "label": "Display"},
    "email": {"channelFamily": "email", "economicClass": "unpaid", "label": "Email"},
    "external_referral": {"channelFamily": "referral", "economicClass": "unknown", "label": "Referral"},
    "internal_navigation": {"channelFamily": "internal", "economicClass": "unpaid", "label": "Internal Navigation"},
    "machine_referral": {"channelFamily": "machine", "economicClass": "nonhuman", "label": "Machine Referral"},
    "organic_search": {"channelFamily": "search", "economicClass": "unpaid", "label": "Organic Search"},
    "organic_social": {"channelFamily": "social", "economicClass": "unpaid", "label": "Organic Social"},
    "owned_referral": {"channelFamily": "referral", "economicClass": "unpaid", "label": "Verified Source"},
    "paid_search": {"channelFamily": "search", "economicClass": "paid", "label": "Paid Search"},
    "paid_social": {"channelFamily": "social", "economicClass": "paid", "label": "Paid Social"},
    "partner": {"channelFamily": "partner", "economicClass": "unknown", "label": "Partner"},
    "push": {"channelFamily": "push", "economicClass": "unpaid", "label": "Push"},
    "sms": {"channelFamily": "sms", "economicClass": "unpaid", "label": "SMS"},
    "unknown": {"channelFamily": "unknown", "economicClass": "unknown", "label": "Unknown"},
}

# Historical values normalized to the canonical vocabulary at API boundaries.
LEGACY_SOURCE_CLASS_ALIASES: dict[str, str] = {
    "direct": "direct_unknown",
}

# v2 display channel -> canonical source_class for legacy 'paid' rows.
LEGACY_PAID_CHANNEL_MAP: dict[str, str] = {
    "Display": "display",
    "Paid Search": "paid_search",
    "Paid Social": "paid_social",
}

# Lowercased utm_source tokens -> canonical search platform.
UTM_SEARCH_SOURCE_ALIASES: dict[str, str] = {
    "baidu": "baidu",
    "bing": "bing",
    "brave": "brave",
    "ddg": "duckduckgo",
    "duckduckgo": "duckduckgo",
    "ecosia": "ecosia",
    "google": "google",
    "msn": "bing",
    "naver": "naver",
    "qwant": "qwant",
    "seznam": "seznam",
    "startpage": "startpage",
    "yahoo": "yahoo",
    "yandex": "yandex",
}

# Lowercased utm_source tokens -> canonical social platform.
UTM_SOCIAL_SOURCE_ALIASES: dict[str, str] = {
    "bluesky": "bluesky",
    "bsky": "bluesky",
    "discord": "discord",
    "facebook": "facebook",
    "fb": "facebook",
    "hackernews": "hackernews",
    "ig": "instagram",
    "instagram": "instagram",
    "linkedin": "linkedin",
    "mastodon": "mastodon",
    "medium": "medium",
    "meta": "facebook",
    "pinterest": "pinterest",
    "quora": "quora",
    "reddit": "reddit",
    "snapchat": "snapchat",
    "t.co": "twitter",
    "telegram": "telegram",
    "threads": "threads",
    "tiktok": "tiktok",
    "tumblr": "tumblr",
    "twitter": "twitter",
    "whatsapp": "whatsapp",
    "x": "twitter",
    "youtube": "youtube",
}

# Lowercased utm_medium token sets, evaluated together with utm_source.
MEDIUM_TOKENS: dict[str, frozenset[str]] = {
    "affiliate": frozenset(['affiliate', 'affiliates']),
    "email": frozenset(['e-mail', 'email', 'newsletter']),
    "genericPaid": frozenset(['banner', 'cpa', 'cpm', 'cpv', 'display', 'paid', 'remarketing', 'retargeting']),
    "organic": frozenset(['organic', 'organic-search', 'organic_search', 'search', 'seo']),
    "organicSocial": frozenset(['organic-social', 'organic_social', 'profile_bio', 'social', 'social-media', 'social_media', 'social_organic']),
    "paidSearch": frozenset(['cpc', 'paid-search', 'paid_search', 'paidsearch', 'ppc', 'sem']),
    "paidSocial": frozenset(['paid-social', 'paid_social', 'paidsocial', 'social-paid', 'social_paid']),
    "partner": frozenset(['partner', 'partnership']),
    "push": frozenset(['push', 'push_notification']),
    "referral": frozenset(['link', 'referral', 'referrer']),
    "sms": frozenset(['mms', 'sms', 'text']),
}

# Advertising click identifiers -> {source, sourceClass}. Paid click evidence
# outranks conflicting self-declared organic UTM labels; conflicts are recorded.
CLICK_ID_CLASSES: dict[str, dict[str, str]] = {
    "aff_id": {"source": "unknown", "sourceClass": "affiliate"},
    "dclid": {"source": "google", "sourceClass": "display"},
    "epik": {"source": "pinterest", "sourceClass": "paid_social"},
    "fbclid": {"source": "facebook", "sourceClass": "paid_social"},
    "gbraid": {"source": "google", "sourceClass": "paid_search"},
    "gclid": {"source": "google", "sourceClass": "paid_search"},
    "irclickid": {"source": "impact", "sourceClass": "affiliate"},
    "li_fat_id": {"source": "linkedin", "sourceClass": "paid_social"},
    "msclkid": {"source": "bing", "sourceClass": "paid_search"},
    "rdt_cid": {"source": "reddit", "sourceClass": "paid_social"},
    "scid": {"source": "snapchat", "sourceClass": "paid_social"},
    "ttclid": {"source": "tiktok", "sourceClass": "paid_social"},
    "twclid": {"source": "twitter", "sourceClass": "paid_social"},
    "wbraid": {"source": "google", "sourceClass": "paid_search"},
}

# Maximum proof_level each entry_method can justify on its own.
ENTRY_METHOD_PROOF_CEILINGS: dict[str, str] = {
    "android_app_link": "platform_verified",
    "android_install_referrer": "platform_verified",
    "email_link": "server_observed",
    "internal_navigation": "server_observed",
    "ios_adattributionkit": "platform_verified",
    "ios_custom_url": "declared",
    "ios_universal_link": "platform_verified",
    "manual_sdk_evidence": "declared",
    "nfc": "server_observed",
    "paid_click_id": "declared",
    "push_notification": "server_observed",
    "qr_code": "server_observed",
    "server_redirect": "server_observed",
    "unknown": "none",
    "utm_declaration": "declared",
    "vanity_url": "server_observed",
    "verified_source_link": "cryptographic",
    "web_referrer": "domain_verified",
}


def canonical_source_class(value: str) -> str:
    """Normalize a possibly-legacy source_class to the canonical vocabulary."""
    return LEGACY_SOURCE_CLASS_ALIASES.get(value, value)
