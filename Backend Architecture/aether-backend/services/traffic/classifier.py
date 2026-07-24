"""Canonical acquisition-source classification for Aether touchpoints.

The classifier is deliberately a pure function.  SDKs capture evidence, this
module describes what that evidence represents, the campaign resolver remains
the sole owner of campaign identity, and the attribution engine remains the
sole owner of conversion credit.

Classifier precedence (highest first):

1. machine/scanner user-agent evidence (never attribution eligible)
2. a server-verified Aether referral link
3. paid click identifiers
4. declared UTM evidence
5. a normalized referrer domain
6. direct / unknown entry

v3 truth model: the classifier reports the strongest evidence it actually
observed.  The no-evidence fallback is ``direct_unknown`` ("Direct / Unknown"),
never a typed-URL claim.  Every classification carries the canonical dimension
set (source_class, traffic_origin, economic_class, channel_family,
entry_method, proof_level) from the shared traffic-source registry, and every
suppressed-but-conflicting signal is preserved in ``evidence_conflicts``.

Raw referrer URLs are never returned.  Only a normalized hostname, an origin-
only URL, and (when present) a one-way path hash are emitted for persistence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from services.traffic.generated_registry import (
    CLICK_ID_CLASSES,
    ENTRY_METHODS,
    ENTRY_METHOD_PROOF_CEILINGS,
    MEDIUM_TOKENS,
    PROOF_LEVELS,
    SOURCE_CLASS_DEFAULTS,
    UTM_SEARCH_SOURCE_ALIASES,
    UTM_SOCIAL_SOURCE_ALIASES,
    canonical_source_class,
)


SOURCE_CLASSIFIER_VERSION = "3.0"

# Shadow-mode ONLY: canonical source_class -> the coarser bucket the legacy
# (pre-v3) vocabulary used, derived by reverse-mapping the registry LEGACY
# aliases. Used solely by the observational shadow-compare seam
# (services/traffic/shadow.py) to measure legacy-vs-canonical drift. This map
# is never consulted by v3 classification — it does not change any customer
# result. Classes absent here were already legacy-representable 1:1.
_LEGACY_SHADOW_MAP: dict[str, str] = {
    "direct_unknown": "direct",
    "paid_search": "paid",
    "paid_social": "paid",
    "display": "paid",
}


def legacy_shadow_source_class(source_class: str) -> str:
    """Shadow-only entrypoint: legacy bucket for a canonical source_class.

    Pure projection with no side effects; provided so the shadow-compare path
    has a single canonical mapping to reverse a v3 classification without
    touching classifier logic.
    """
    return _LEGACY_SHADOW_MAP.get(source_class, source_class)

# Weakest -> strongest.  Used to cap claim-provided proof levels.
_PROOF_RANK: dict[str, int] = {
    "none": 0,
    "inferred": 1,
    "declared": 2,
    "domain_verified": 3,
    "server_observed": 4,
    "platform_verified": 5,
    "cryptographic": 6,
}

# channel_family -> default traffic origin when a branch does not override it.
_FAMILY_TRAFFIC_ORIGIN: dict[str, str] = {
    "direct": "unknown",
    "internal": "internal",
    "app_store": "app_store",
    "unknown": "unknown",
}

_ORGANIC_MEDIUM_TOKENS: frozenset[str] = frozenset(
    MEDIUM_TOKENS["organic"] | MEDIUM_TOKENS["organicSocial"]
)


@dataclass(frozen=True)
class ClassifiedSource:
    """Immutable, campaign-agnostic description of acquisition evidence.

    The first four fields are the original public contract and intentionally
    remain positional/backward compatible.  All extension fields have safe
    defaults so existing callers that only read source/medium/channel continue
    to work.
    """

    source: str
    medium: str
    channel: str
    confidence: float
    source_class: str = "unknown"
    referral_mediation_type: str = "unknown_external_referral"
    ai_provider: Optional[str] = None
    ai_product: Optional[str] = None
    actor_type: str = "unknown"
    journey_role: str = "discovery"
    verification_level: str = "inferred"
    normalized_referrer_domain: str = ""
    normalized_referrer: str = ""
    referrer_path_hash: Optional[str] = None
    classifier_version: str = SOURCE_CLASSIFIER_VERSION
    attribution_eligible: bool = True
    verified_referral_link_id: Optional[str] = None
    evidence: tuple[str, ...] = ()
    traffic_origin: str = "unknown"
    economic_class: str = "unknown"
    channel_family: str = "unknown"
    entry_method: str = "unknown"
    proof_level: str = "none"
    evidence_conflicts: tuple[str, ...] = ()

    def evidence_payload(self) -> dict[str, Any]:
        """JSON-safe evidence summary suitable for the Silver fact ledger."""
        return {
            "signals": list(self.evidence),
            "classifier_version": self.classifier_version,
            "verification_level": self.verification_level,
            "normalized_referrer_domain": self.normalized_referrer_domain or None,
            "referrer_path_hash": self.referrer_path_hash,
            "traffic_origin": self.traffic_origin,
            "economic_class": self.economic_class,
            "channel_family": self.channel_family,
            "entry_method": self.entry_method,
            "proof_level": self.proof_level,
            "conflicts": list(self.evidence_conflicts),
        }


class SourceClassifier:
    """Classify raw landing evidence without resolving campaign identity."""

    # click_id key -> (source, medium, display channel).  Classification-grade
    # source_class comes from the registry's CLICK_ID_CLASSES; this table only
    # supplies the display medium/channel and legacy camelCase key support.
    CLICK_ID_MAP: dict[str, tuple[str, str, str]] = {
        "gclid": ("google", "cpc", "Paid Search"),
        "gbraid": ("google", "cpc", "Paid Search"),
        "wbraid": ("google", "cpc", "Paid Search"),
        "msclkid": ("bing", "cpc", "Paid Search"),
        "fbclid": ("facebook", "cpc", "Paid Social"),
        "ttclid": ("tiktok", "cpc", "Paid Social"),
        "twclid": ("twitter", "cpc", "Paid Social"),
        "li_fat_id": ("linkedin", "cpc", "Paid Social"),
        "liEFatId": ("linkedin", "cpc", "Paid Social"),
        "rdt_cid": ("reddit", "cpc", "Paid Social"),
        "rdtCid": ("reddit", "cpc", "Paid Social"),
        "scid": ("snapchat", "cpc", "Paid Social"),
        "dclid": ("google", "display", "Display"),
        "epik": ("pinterest", "cpc", "Paid Social"),
        "irclickid": ("impact", "affiliate", "Affiliate"),
        "aff_id": ("unknown", "affiliate", "Affiliate"),
    }

    # Legacy camelCase click-id keys normalized to their registry identifiers.
    CLICK_ID_KEY_ALIASES: dict[str, str] = {
        "liEFatId": "li_fat_id",
        "rdtCid": "rdt_cid",
    }

    SOCIAL_DOMAINS: dict[str, str] = {
        "facebook.com": "facebook", "m.facebook.com": "facebook",
        "l.facebook.com": "facebook", "lm.facebook.com": "facebook",
        "fb.com": "facebook", "fb.me": "facebook",
        "messenger.com": "facebook",
        "instagram.com": "instagram", "l.instagram.com": "instagram",
        "twitter.com": "twitter", "t.co": "twitter",
        "x.com": "twitter", "mobile.twitter.com": "twitter",
        "linkedin.com": "linkedin", "lnkd.in": "linkedin",
        "reddit.com": "reddit", "old.reddit.com": "reddit",
        "out.reddit.com": "reddit",
        "tiktok.com": "tiktok", "vm.tiktok.com": "tiktok",
        "youtube.com": "youtube", "youtu.be": "youtube",
        "m.youtube.com": "youtube",
        "pinterest.com": "pinterest", "pin.it": "pinterest",
        "snapchat.com": "snapchat",
        "whatsapp.com": "whatsapp", "wa.me": "whatsapp",
        "telegram.org": "telegram", "t.me": "telegram",
        "discord.com": "discord", "discord.gg": "discord",
        "threads.net": "threads", "mastodon.social": "mastodon",
        "tumblr.com": "tumblr", "quora.com": "quora",
        "stackoverflow.com": "stackoverflow", "medium.com": "medium",
        "news.ycombinator.com": "hackernews", "bsky.app": "bluesky",
    }

    SEARCH_DOMAINS: dict[str, str] = {
        "google.com": "google", "google.co.uk": "google",
        "google.ca": "google", "google.com.au": "google",
        "google.de": "google", "google.fr": "google",
        "google.co.jp": "google", "google.co.in": "google",
        "google.com.br": "google", "bing.com": "bing",
        "yahoo.com": "yahoo", "search.yahoo.com": "yahoo",
        "duckduckgo.com": "duckduckgo", "baidu.com": "baidu",
        "yandex.ru": "yandex", "yandex.com": "yandex",
        "ecosia.org": "ecosia", "ask.com": "ask",
        "aol.com": "aol", "search.aol.com": "aol",
        "naver.com": "naver", "search.naver.com": "naver",
        "seznam.cz": "seznam", "sogou.com": "sogou",
        "so.com": "360search", "startpage.com": "startpage",
        "brave.com": "brave", "search.brave.com": "brave",
    }

    EMAIL_DOMAINS: dict[str, str] = {
        "mail.google.com": "gmail",
        "outlook.live.com": "outlook", "outlook.office365.com": "outlook",
        "outlook.office.com": "outlook", "mail.yahoo.com": "yahoo_mail",
        "mail.aol.com": "aol_mail", "mail.protonmail.com": "protonmail",
        "protonmail.com": "protonmail", "mail.zoho.com": "zoho_mail",
        "fastmail.com": "fastmail", "tutanota.com": "tutanota",
        "hey.com": "hey", "icloud.com": "icloud_mail",
        "mail.ru": "mail_ru", "yandex.mail": "yandex_mail",
    }

    # hostname → (provider, product).  Company home pages are intentionally not
    # listed unless the hostname itself is an end-user AI discovery surface.
    AI_DOMAINS: dict[str, tuple[str, str]] = {
        "chatgpt.com": ("openai", "chatgpt"),
        "chat.openai.com": ("openai", "chatgpt"),
        "perplexity.ai": ("perplexity", "perplexity"),
        "claude.ai": ("anthropic", "claude"),
        "gemini.google.com": ("google", "gemini"),
        "copilot.microsoft.com": ("microsoft", "copilot"),
        "copilot.cloud.microsoft": ("microsoft", "copilot"),
        "poe.com": ("quora", "poe"),
        "you.com": ("you.com", "you"),
        "phind.com": ("phind", "phind"),
        "grok.com": ("xai", "grok"),
        "meta.ai": ("meta", "meta_ai"),
        "chat.deepseek.com": ("deepseek", "deepseek"),
        "deepseek.com": ("deepseek", "deepseek"),
        "kimi.com": ("moonshot", "kimi"),
    }

    AI_SOURCE_ALIASES: dict[str, tuple[str, str]] = {
        "chatgpt": ("openai", "chatgpt"),
        "chatgpt.com": ("openai", "chatgpt"),
        "openai": ("openai", "chatgpt"),
        "perplexity": ("perplexity", "perplexity"),
        "perplexity.ai": ("perplexity", "perplexity"),
        "claude": ("anthropic", "claude"),
        "anthropic": ("anthropic", "claude"),
        "gemini": ("google", "gemini"),
        "google_gemini": ("google", "gemini"),
        "copilot": ("microsoft", "copilot"),
        "microsoft_copilot": ("microsoft", "copilot"),
        "poe": ("quora", "poe"),
        "you.com": ("you.com", "you"),
        "phind": ("phind", "phind"),
        "grok": ("xai", "grok"),
        "meta_ai": ("meta", "meta_ai"),
        "deepseek": ("deepseek", "deepseek"),
        "kimi": ("moonshot", "kimi"),
    }

    # Ordered, lower-case substring signatures.
    MACHINE_USER_AGENTS: tuple[tuple[str, str, Optional[str], Optional[str]], ...] = (
        ("proofpoint", "scanner", None, None),
        ("mimecast", "scanner", None, None),
        ("barracuda", "scanner", None, None),
        ("virustotal", "scanner", None, None),
        ("urlscan", "scanner", None, None),
        ("slackbot-linkexpanding", "link_preview", None, None),
        ("twitterbot", "link_preview", None, None),
        ("facebookexternalhit", "link_preview", None, None),
        ("linkedinbot", "link_preview", None, None),
        ("discordbot", "link_preview", None, None),
        ("gptbot", "crawler_discovery", "openai", "gptbot"),
        ("oai-searchbot", "crawler_discovery", "openai", "search"),
        ("claudebot", "crawler_discovery", "anthropic", "claude"),
        ("claude-web", "crawler_discovery", "anthropic", "claude"),
        ("perplexitybot", "crawler_discovery", "perplexity", "perplexity"),
        ("google-extended", "crawler_discovery", "google", "gemini"),
        ("bytespider", "crawler_discovery", "bytedance", None),
        ("ccbot", "crawler_discovery", "common_crawl", None),
    )

    AGENT_USER_AGENTS: tuple[tuple[str, str, str], ...] = (
        ("chatgpt-user", "openai", "chatgpt"),
        ("perplexity-user", "perplexity", "perplexity"),
        ("claude-user", "anthropic", "claude"),
    )

    MEDIUM_CHANNEL_MAP: dict[str, str] = {
        "cpc": "Paid Search", "ppc": "Paid Search",
        "paidsearch": "Paid Search", "paid-search": "Paid Search",
        "display": "Display", "banner": "Display", "cpm": "Display",
        "social": "Organic Social", "social-media": "Organic Social",
        "organic": "Organic Search", "email": "Email", "e-mail": "Email",
        "newsletter": "Email", "affiliate": "Affiliate",
        "partner": "Partner", "referral": "Referral",
        "ai": "AI Referral", "ai_referral": "AI Referral",
        "agent": "Agent Referral", "agent_referral": "Agent Referral",
        "video": "Video", "audio": "Audio", "sms": "SMS", "push": "Push",
    }

    def classify(
        self,
        referrer: str = "",
        referrer_domain: str = "",
        utm_source: Optional[str] = None,
        utm_medium: Optional[str] = None,
        utm_campaign: Optional[str] = None,
        click_ids: Optional[dict[str, str]] = None,
        landing_page: str = "",
        *,
        user_agent: str = "",
        verified_referral: Optional[dict[str, Any]] = None,
        explicit_actor_type: Optional[str] = None,
        declared_entry_method: Optional[str] = None,
    ) -> ClassifiedSource:
        """Classify raw source evidence without assigning a campaign."""
        del utm_campaign, landing_page  # campaign and destination are separate concerns
        click_ids = click_ids or {}
        entry_hint = self._entry_method_hint(declared_entry_method)
        domain, safe_referrer, path_hash = self.normalize_referrer(
            referrer=referrer, referrer_domain=referrer_domain,
        )

        machine = self._classify_user_agent(user_agent, domain, safe_referrer, path_hash)
        if machine is not None:
            return machine

        if verified_referral:
            return self._classify_verified_referral(
                verified_referral, domain, safe_referrer, path_hash,
                utm_source=utm_source,
            )

        for click_id, value in click_ids.items():
            canonical_key = self.CLICK_ID_KEY_ALIASES.get(click_id, click_id)
            if value and canonical_key in CLICK_ID_CLASSES:
                return self._classify_click_id(
                    click_id, canonical_key, utm_medium,
                    explicit_actor_type, domain, safe_referrer, path_hash,
                )

        if utm_source:
            return self._classify_utm(
                utm_source, utm_medium, explicit_actor_type,
                domain, safe_referrer, path_hash,
            )

        if domain:
            return self._classify_referrer_domain(
                domain,
                safe_referrer=safe_referrer,
                path_hash=path_hash,
                explicit_actor_type=explicit_actor_type,
                entry_hint=entry_hint,
            )

        evidence: tuple[str, ...] = ("no_external_source_evidence",)
        entry_method = "unknown"
        proof_level = "none"
        if entry_hint:
            # A platform-declared entry method (deep link, push, QR, …) is real
            # evidence about HOW the app was entered, but on its own it cannot
            # support a typed-URL/source claim — the class stays direct_unknown.
            entry_method = entry_hint
            proof_level = self._cap_proof("declared", entry_hint)
            evidence = evidence + (f"declared_entry_method:{entry_hint}",)
        return self._result(
            "(direct)", "(none)", SOURCE_CLASS_DEFAULTS["direct_unknown"]["label"], 0.5,
            source_class="direct_unknown", mediation="direct_entry",
            actor_type=explicit_actor_type or "human", journey_role="entry",
            verification="none",
            entry_method=entry_method, proof_level=proof_level,
            evidence=evidence,
        )

    def _classify_user_agent(
        self,
        user_agent: str,
        domain: str,
        safe_referrer: str,
        path_hash: Optional[str],
    ) -> Optional[ClassifiedSource]:
        ua = (user_agent or "").lower()
        if not ua:
            return None

        for signature, mediation, provider, product in self.MACHINE_USER_AGENTS:
            if signature in ua:
                source = provider or mediation
                return self._result(
                    source, "machine", "AI Crawler" if mediation == "crawler_discovery" else "Machine Referral",
                    0.98,
                    source_class="machine_referral", mediation=mediation,
                    ai_provider=provider, ai_product=product, actor_type="machine",
                    journey_role="excluded", verification="user_agent_signature",
                    domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                    attribution_eligible=False,
                    traffic_origin="external",
                    entry_method="web_referrer" if domain else "unknown",
                    proof_level="server_observed",
                    evidence=(f"user_agent:{signature}",),
                )

        for signature, provider, product in self.AGENT_USER_AGENTS:
            if signature in ua:
                return self._result(
                    provider, "agent_referral", "Agent Referral", 0.92,
                    source_class="agent_referral", mediation="agent_mediated_referral",
                    ai_provider=provider, ai_product=product, actor_type="agent",
                    journey_role="handoff", verification="user_agent_signature",
                    domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                    entry_method="web_referrer" if domain else "unknown",
                    proof_level="server_observed",
                    evidence=(f"user_agent:{signature}",),
                )
        return None

    def _classify_verified_referral(
        self,
        claim: dict[str, Any],
        domain: str,
        safe_referrer: str,
        path_hash: Optional[str],
        *,
        utm_source: Optional[str] = None,
    ) -> ClassifiedSource:
        mediation = str(
            claim.get("referral_mediation_type")
            or claim.get("mediation_type")
            or "agent_mediated_referral"
        )
        provider = self._clean_token(claim.get("ai_provider") or claim.get("provider")) or None
        product = self._clean_token(claim.get("ai_product") or claim.get("product")) or None
        actor = self._normalize_actor(
            claim.get("actor_type")
            or ("agent" if mediation in {"owned_agent_referral", "agent_mediated_referral"} else "human")
        )
        source = self._clean_token(claim.get("source")) or provider or product or "verified_referral"
        medium, channel, source_class = self._medium_channel_for_mediation(mediation)

        entry_method = self._entry_method_hint(claim.get("entry_method")) or "verified_source_link"
        claim_proof = str(claim.get("proof_level") or "").strip().lower()
        if claim_proof in PROOF_LEVELS and claim_proof != "none":
            proof_level = self._cap_proof(claim_proof, "verified_source_link")
        else:
            proof_level = "server_observed"

        conflicts: tuple[str, ...] = ()
        declared_source = self._clean_token(utm_source)
        if declared_source and declared_source not in {source, provider or "", product or ""}:
            # The server-verified link wins, but a disagreeing self-declared UTM
            # source is preserved as an explicit conflict — never dropped.
            conflicts = (f"verified_link_overrides_utm_declaration:{declared_source}",)

        return self._result(
            source, medium, channel, 1.0,
            source_class=source_class, mediation=mediation,
            ai_provider=provider, ai_product=product, actor_type=actor,
            journey_role=str(claim.get("journey_role") or "handoff"),
            verification="verified_referral_link",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
            verified_referral_link_id=str(
                claim.get("referral_link_id") or claim.get("verified_referral_link_id") or ""
            ) or None,
            entry_method=entry_method, proof_level=proof_level,
            conflicts=conflicts,
            evidence=("verified_referral_link",),
        )

    def _classify_click_id(
        self,
        click_id: str,
        canonical_key: str,
        utm_medium: Optional[str],
        explicit_actor_type: Optional[str],
        domain: str,
        safe_referrer: str,
        path_hash: Optional[str],
    ) -> ClassifiedSource:
        click_class = CLICK_ID_CLASSES[canonical_key]
        source_class = click_class["sourceClass"]
        source = click_class["source"]
        medium, channel = self._click_display(canonical_key, source_class)
        mediation = (
            "affiliate_referral" if source_class == "affiliate" else "ordinary_referral"
        )
        conflicts: tuple[str, ...] = ()
        medium_token = self._clean_token(utm_medium)
        if medium_token and medium_token in _ORGANIC_MEDIUM_TOKENS:
            # Paid click evidence outranks a self-declared organic label; the
            # suppressed declaration is recorded, never silently dropped.
            conflicts = (f"paid_click_id_overrides_organic_utm:{canonical_key}",)
        return self._result(
            source, medium, channel, 1.0,
            source_class=source_class,
            mediation=mediation,
            actor_type=explicit_actor_type or "human",
            journey_role="campaign",
            verification="verified_click_id",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
            entry_method="paid_click_id",
            proof_level=self._cap_proof("declared", "paid_click_id"),
            conflicts=conflicts,
            evidence=(f"click_id:{click_id}",),
        )

    def _classify_utm(
        self,
        utm_source: str,
        utm_medium: Optional[str],
        explicit_actor_type: Optional[str],
        domain: str,
        safe_referrer: str,
        path_hash: Optional[str],
    ) -> ClassifiedSource:
        source_token = self._clean_token(utm_source)
        medium = self._clean_token(utm_medium) or "referral"
        evidence = ("utm_source", "utm_medium" if utm_medium else "utm_source_only")
        ai_identity = self._ai_identity_for_source(source_token)
        if ai_identity:
            provider, product = ai_identity
            actor = self._normalize_actor(explicit_actor_type or "human")
            is_agent = medium in {"agent", "agent_referral"} or actor == "agent"
            mediation = (
                "agent_mediated_referral" if is_agent else "ai_mediated_human_referral"
            )
            return self._result(
                provider, "agent_referral" if actor == "agent" else "ai_referral",
                "Agent Referral" if actor == "agent" else "AI Referral", 0.95,
                source_class="agent_referral" if is_agent else "ai_referral",
                mediation=mediation,
                ai_provider=provider, ai_product=product, actor_type=actor,
                journey_role="handoff" if actor == "agent" else "discovery",
                verification="declared_campaign_evidence",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method="utm_declaration",
                proof_level=self._cap_proof("declared", "utm_declaration"),
                evidence=evidence,
            )

        rule = self._utm_source_medium_rule(source_token, medium)
        if rule is not None:
            source_class, source, economic_override = rule
            mediation = "ordinary_referral"
            if source_class == "affiliate":
                mediation = "affiliate_referral"
            elif source_class == "partner":
                mediation = "partner_referral"
            return self._result(
                source, medium,
                SOURCE_CLASS_DEFAULTS[source_class]["label"], 0.95,
                source_class=source_class, mediation=mediation,
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="campaign", verification="declared_campaign_evidence",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method="utm_declaration",
                proof_level=self._cap_proof("declared", "utm_declaration"),
                economic_class=economic_override,
                evidence=evidence + (f"utm_rule:{source_class}",),
            )

        # Unmatched but explicitly declared campaign evidence: keep the
        # declaration (source_class external_referral, channel from the
        # medium map) rather than inventing an organic/paid claim.
        return self._result(
            source_token, medium, self._channel_from_medium(medium), 0.95,
            source_class="external_referral", mediation="ordinary_referral",
            actor_type=self._normalize_actor(explicit_actor_type or "human"),
            journey_role="campaign", verification="declared_campaign_evidence",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
            entry_method="utm_declaration",
            proof_level=self._cap_proof("declared", "utm_declaration"),
            evidence=evidence + ("utm_rule:unmatched_declaration",),
        )

    @staticmethod
    def _utm_source_medium_rule(
        source_token: str, medium: str
    ) -> Optional[tuple[str, str, Optional[str]]]:
        """Co-evaluate declared source and medium against the shared registry.

        Returns ``(source_class, canonical_source, economic_class_override)``
        or None when no registry rule matches.
        """
        search_source = UTM_SEARCH_SOURCE_ALIASES.get(source_token)
        social_source = UTM_SOCIAL_SOURCE_ALIASES.get(source_token)
        tokens = MEDIUM_TOKENS

        if search_source:
            if medium in tokens["organic"]:
                return "organic_search", search_source, None
            if medium in tokens["paidSearch"] or medium in tokens["genericPaid"]:
                return "paid_search", search_source, None
        if social_source:
            if medium in tokens["organicSocial"] or medium in tokens["organic"]:
                return "organic_social", social_source, None
            if (
                medium in tokens["paidSocial"]
                or medium in tokens["genericPaid"]
                or medium in tokens["paidSearch"]
            ):
                # Paid-search-style tokens (cpc/ppc) on a social platform are
                # paid social spend, not paid search.
                return "paid_social", social_source, None
        if medium in tokens["email"]:
            return "email", source_token, None
        if medium in tokens["affiliate"]:
            return "affiliate", source_token, None
        if medium in tokens["partner"]:
            return "partner", source_token, None
        if medium in tokens["push"]:
            return "push", source_token, None
        if medium in tokens["sms"]:
            return "sms", source_token, None
        if medium in tokens["organic"] and not search_source and not social_source:
            # An organic claim from an unrecognized platform is preserved as a
            # declaration but never rendered as organic search.
            return "unknown", source_token, "unpaid"
        return None

    def _classify_referrer_domain(
        self,
        domain: str,
        *,
        safe_referrer: str = "",
        path_hash: Optional[str] = None,
        explicit_actor_type: Optional[str] = None,
        entry_hint: Optional[str] = None,
    ) -> ClassifiedSource:
        domain = self._normalize_domain(domain)
        safe_referrer = safe_referrer or (f"https://{domain}/" if domain else "")
        entry_method = entry_hint or "web_referrer"
        proof_level = self._cap_proof("domain_verified", entry_method)

        ai_identity = self._ai_identity_for_domain(domain)
        if ai_identity:
            provider, product = ai_identity
            return self._result(
                provider, "ai_referral", "AI Referral", 0.96,
                source_class="ai_referral", mediation="ai_mediated_human_referral",
                ai_provider=provider, ai_product=product,
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="discovery", verification="verified_domain",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method=entry_method, proof_level=proof_level,
                evidence=("known_ai_referrer_domain",),
            )

        if domain in self.EMAIL_DOMAINS:
            return self._result(
                self.EMAIL_DOMAINS[domain], "email", "Email", 0.9,
                source_class="email", mediation="ordinary_referral",
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="discovery", verification="verified_domain",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method=entry_method, proof_level=proof_level,
                evidence=("known_email_referrer_domain",),
            )

        search_source = self._match_search_domain(domain)
        if search_source:
            return self._result(
                search_source, "organic", "Organic Search", 0.9,
                source_class="organic_search", mediation="ordinary_referral",
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="discovery", verification="verified_domain",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method=entry_method, proof_level=proof_level,
                evidence=("known_search_referrer_domain",),
            )

        social_source = self._match_domain_table(domain, self.SOCIAL_DOMAINS)
        if social_source:
            return self._result(
                social_source, "social", "Organic Social", 0.9,
                source_class="organic_social", mediation="ordinary_referral",
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="discovery", verification="verified_domain",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                entry_method=entry_method, proof_level=proof_level,
                evidence=("known_social_referrer_domain",),
            )

        return self._result(
            domain, "referral", "Referral", 0.65,
            source_class="external_referral", mediation="unknown_external_referral",
            actor_type=self._normalize_actor(explicit_actor_type or "human"),
            journey_role="discovery", verification="inferred",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
            entry_method=entry_method, proof_level=proof_level,
            evidence=("external_referrer_domain",),
        )

    def _result(
        self,
        source: str,
        medium: str,
        channel: str,
        confidence: float,
        *,
        source_class: str,
        mediation: str,
        actor_type: str,
        journey_role: str,
        verification: str,
        domain: str = "",
        safe_referrer: str = "",
        path_hash: Optional[str] = None,
        ai_provider: Optional[str] = None,
        ai_product: Optional[str] = None,
        attribution_eligible: bool = True,
        verified_referral_link_id: Optional[str] = None,
        evidence: tuple[str, ...] = (),
        traffic_origin: Optional[str] = None,
        economic_class: Optional[str] = None,
        channel_family: Optional[str] = None,
        entry_method: str = "unknown",
        proof_level: str = "none",
        conflicts: tuple[str, ...] = (),
    ) -> ClassifiedSource:
        canonical_class = canonical_source_class(source_class)
        defaults = SOURCE_CLASS_DEFAULTS.get(
            canonical_class, SOURCE_CLASS_DEFAULTS["unknown"]
        )
        resolved_family = channel_family or defaults["channelFamily"]
        resolved_economic = economic_class or defaults["economicClass"]
        resolved_origin = traffic_origin or _FAMILY_TRAFFIC_ORIGIN.get(
            resolved_family, "external"
        )
        return ClassifiedSource(
            source=source,
            medium=medium,
            channel=channel,
            confidence=max(0.0, min(1.0, float(confidence))),
            source_class=canonical_class,
            referral_mediation_type=mediation,
            ai_provider=ai_provider,
            ai_product=ai_product,
            actor_type=self._normalize_actor(actor_type),
            journey_role=journey_role,
            verification_level=verification,
            normalized_referrer_domain=domain,
            normalized_referrer=safe_referrer,
            referrer_path_hash=path_hash,
            attribution_eligible=attribution_eligible,
            verified_referral_link_id=verified_referral_link_id,
            evidence=evidence,
            traffic_origin=resolved_origin,
            economic_class=resolved_economic,
            channel_family=resolved_family,
            entry_method=entry_method if entry_method in ENTRY_METHODS else "unknown",
            proof_level=proof_level if proof_level in PROOF_LEVELS else "none",
            evidence_conflicts=conflicts,
        )

    @staticmethod
    def _click_display(canonical_key: str, source_class: str) -> tuple[str, str]:
        """Display (medium, channel) for a canonical click-id key."""
        mapped = SourceClassifier.CLICK_ID_MAP.get(canonical_key)
        if mapped is not None:
            return mapped[1], mapped[2]
        by_class = {
            "paid_search": ("cpc", "Paid Search"),
            "paid_social": ("cpc", "Paid Social"),
            "display": ("display", "Display"),
            "affiliate": ("affiliate", "Affiliate"),
        }
        return by_class.get(source_class, ("cpc", "Paid Search"))

    @staticmethod
    def _entry_method_hint(value: Any) -> Optional[str]:
        token = str(value or "").strip().lower()
        return token if token in ENTRY_METHODS else None

    @staticmethod
    def _cap_proof(proof_level: str, entry_method: str) -> str:
        """Cap a proof level at what the entry method can justify on its own."""
        ceiling = ENTRY_METHOD_PROOF_CEILINGS.get(entry_method)
        if ceiling is None:
            return proof_level
        if _PROOF_RANK.get(proof_level, 0) > _PROOF_RANK.get(ceiling, 0):
            return ceiling
        return proof_level

    def _ai_identity_for_domain(self, domain: str) -> Optional[tuple[str, str]]:
        return self._match_domain_table(domain, self.AI_DOMAINS)

    def _ai_identity_for_source(self, source: str) -> Optional[tuple[str, str]]:
        return self.AI_SOURCE_ALIASES.get(source.lower().strip())

    def _match_search_domain(self, domain: str) -> Optional[str]:
        matched = self._match_domain_table(domain, self.SEARCH_DOMAINS)
        if matched:
            return matched
        if domain.startswith("google."):
            return "google"
        return None

    @staticmethod
    def _match_domain_table(domain: str, table: dict[str, Any]) -> Any:
        if domain in table:
            return table[domain]
        # Known product domains may legitimately add a regional/subdomain
        # prefix.  Suffix matching is boundary-safe ("evilchatgpt.com" cannot
        # match "chatgpt.com").
        for known, value in table.items():
            if domain.endswith(f".{known}"):
                return value
        return None

    def _channel_from_medium(self, medium: str) -> str:
        return self.MEDIUM_CHANNEL_MAP.get(self._clean_token(medium), "Other")

    @staticmethod
    def _medium_channel_for_mediation(mediation: str) -> tuple[str, str, str]:
        if mediation == "affiliate_referral":
            return "affiliate", "Affiliate", "affiliate"
        if mediation == "partner_referral":
            return "partner", "Partner", "partner"
        if mediation in {"agent_mediated_referral", "owned_agent_referral"}:
            return "agent_referral", "Agent Referral", "agent_referral"
        if mediation == "ai_mediated_human_referral":
            return "ai_referral", "AI Referral", "ai_referral"
        return "referral", "Referral", "external_referral"

    @classmethod
    def normalize_referrer(
        cls,
        *,
        referrer: str = "",
        referrer_domain: str = "",
    ) -> tuple[str, str, Optional[str]]:
        """Return ``(hostname, origin-only URL, path hash)``.

        Query strings, fragments, credentials, ports, and raw paths are never
        returned.  The hash is useful for controlled-placement diagnostics
        without retaining potentially identifying path contents.
        """
        domain = cls._normalize_domain(referrer_domain)
        parsed = None
        if referrer:
            try:
                candidate = referrer if "://" in referrer else f"https://{referrer}"
                parsed = urlparse(candidate)
                if not domain:
                    domain = cls._normalize_domain(parsed.hostname or "")
            except (TypeError, ValueError):
                parsed = None

        if not domain:
            return "", "", None

        scheme = "https"
        if parsed is not None and parsed.scheme.lower() in {"http", "https"}:
            scheme = parsed.scheme.lower()
        path_hash: Optional[str] = None
        if parsed is not None and parsed.path and parsed.path != "/":
            path_hash = hashlib.sha256(parsed.path.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return domain, f"{scheme}://{domain}/", path_hash

    @staticmethod
    def _extract_domain(referrer: str) -> str:
        if not referrer:
            return ""
        try:
            candidate = referrer if "://" in referrer else f"//{referrer}"
            return urlparse(candidate).hostname or ""
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        if not domain:
            return ""
        value = str(domain).strip().lower()
        try:
            candidate = value if "://" in value else f"//{value}"
            parsed = urlparse(candidate)
            value = parsed.hostname or value.split("/", 1)[0]
        except (TypeError, ValueError):
            value = value.split("/", 1)[0]
        value = value.strip(". ")
        if value.startswith("www."):
            value = value[4:]
        try:
            value = value.encode("idna").decode("ascii")
        except (UnicodeError, AttributeError):
            return ""
        return value[:253]

    @staticmethod
    def _clean_token(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_")[:120]

    @staticmethod
    def _normalize_actor(value: Any) -> str:
        actor = str(value or "unknown").strip().lower()
        aliases = {"bot": "machine", "crawler": "machine", "ai_agent": "agent"}
        actor = aliases.get(actor, actor)
        return actor if actor in {"human", "agent", "machine", "organization", "unknown"} else "unknown"
