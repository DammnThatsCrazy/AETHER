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
6. direct entry

Raw referrer URLs are never returned.  Only a normalized hostname, an origin-
only URL, and (when present) a one-way path hash are emitted for persistence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse


SOURCE_CLASSIFIER_VERSION = "2.0"


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

    def evidence_payload(self) -> dict[str, Any]:
        """JSON-safe evidence summary suitable for the Silver fact ledger."""
        return {
            "signals": list(self.evidence),
            "classifier_version": self.classifier_version,
            "verification_level": self.verification_level,
            "normalized_referrer_domain": self.normalized_referrer_domain or None,
            "referrer_path_hash": self.referrer_path_hash,
        }


class SourceClassifier:
    """Classify raw landing evidence without resolving campaign identity."""

    CLICK_ID_MAP: dict[str, tuple[str, str, str]] = {
        "gclid": ("google", "cpc", "Paid Search"),
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
    ) -> ClassifiedSource:
        """Classify raw source evidence without assigning a campaign."""
        del utm_campaign, landing_page  # campaign and destination are separate concerns
        click_ids = click_ids or {}
        domain, safe_referrer, path_hash = self.normalize_referrer(
            referrer=referrer, referrer_domain=referrer_domain,
        )

        machine = self._classify_user_agent(user_agent, domain, safe_referrer, path_hash)
        if machine is not None:
            return machine

        if verified_referral:
            return self._classify_verified_referral(
                verified_referral, domain, safe_referrer, path_hash,
            )

        for click_id, value in click_ids.items():
            if value and click_id in self.CLICK_ID_MAP:
                source, medium, channel = self.CLICK_ID_MAP[click_id]
                mediation = "affiliate_referral" if medium == "affiliate" else "ordinary_referral"
                return self._result(
                    source, medium, channel, 1.0,
                    source_class="affiliate" if medium == "affiliate" else "paid",
                    mediation=mediation,
                    actor_type=explicit_actor_type or "human",
                    journey_role="campaign",
                    verification="verified_click_id",
                    domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                    evidence=(f"click_id:{click_id}",),
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
            )

        return self._result(
            "(direct)", "(none)", "Direct", 0.5,
            source_class="direct", mediation="direct_entry",
            actor_type=explicit_actor_type or "human", journey_role="entry",
            verification="none", evidence=("no_external_source_evidence",),
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
                    evidence=(f"user_agent:{signature}",),
                )

        for signature, provider, product in self.AGENT_USER_AGENTS:
            if signature in ua:
                return self._result(
                    provider, "agent_referral", "Agent Referral", 0.92,
                    source_class="ai_referral", mediation="agent_mediated_referral",
                    ai_provider=provider, ai_product=product, actor_type="agent",
                    journey_role="handoff", verification="user_agent_signature",
                    domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                    evidence=(f"user_agent:{signature}",),
                )
        return None

    def _classify_verified_referral(
        self,
        claim: dict[str, Any],
        domain: str,
        safe_referrer: str,
        path_hash: Optional[str],
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
            evidence=("verified_referral_link",),
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
        ai_identity = self._ai_identity_for_source(source_token)
        if ai_identity:
            provider, product = ai_identity
            actor = self._normalize_actor(explicit_actor_type or "human")
            mediation = (
                "agent_mediated_referral"
                if medium in {"agent", "agent_referral"} or actor == "agent"
                else "ai_mediated_human_referral"
            )
            return self._result(
                provider, "agent_referral" if actor == "agent" else "ai_referral",
                "Agent Referral" if actor == "agent" else "AI Referral", 0.95,
                source_class="ai_referral", mediation=mediation,
                ai_provider=provider, ai_product=product, actor_type=actor,
                journey_role="handoff" if actor == "agent" else "discovery",
                verification="declared_campaign_evidence",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
                evidence=("utm_source", "utm_medium" if utm_medium else "utm_source_only"),
            )

        mediation = "ordinary_referral"
        source_class = "campaign"
        if medium == "affiliate":
            mediation, source_class = "affiliate_referral", "affiliate"
        elif medium == "partner":
            mediation, source_class = "partner_referral", "partner"
        return self._result(
            source_token, medium, self._channel_from_medium(medium), 0.95,
            source_class=source_class, mediation=mediation,
            actor_type=self._normalize_actor(explicit_actor_type or "human"),
            journey_role="campaign", verification="declared_campaign_evidence",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
            evidence=("utm_source", "utm_medium" if utm_medium else "utm_source_only"),
        )

    def _classify_referrer_domain(
        self,
        domain: str,
        *,
        safe_referrer: str = "",
        path_hash: Optional[str] = None,
        explicit_actor_type: Optional[str] = None,
    ) -> ClassifiedSource:
        domain = self._normalize_domain(domain)
        safe_referrer = safe_referrer or (f"https://{domain}/" if domain else "")

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
                evidence=("known_ai_referrer_domain",),
            )

        if domain in self.EMAIL_DOMAINS:
            return self._result(
                self.EMAIL_DOMAINS[domain], "email", "Email", 0.9,
                source_class="email", mediation="ordinary_referral",
                actor_type=self._normalize_actor(explicit_actor_type or "human"),
                journey_role="discovery", verification="verified_domain",
                domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
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
                evidence=("known_social_referrer_domain",),
            )

        return self._result(
            domain, "referral", "Referral", 0.65,
            source_class="external_referral", mediation="unknown_external_referral",
            actor_type=self._normalize_actor(explicit_actor_type or "human"),
            journey_role="discovery", verification="inferred",
            domain=domain, safe_referrer=safe_referrer, path_hash=path_hash,
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
    ) -> ClassifiedSource:
        return ClassifiedSource(
            source=source,
            medium=medium,
            channel=channel,
            confidence=max(0.0, min(1.0, float(confidence))),
            source_class=source_class,
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
        )

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
            return "agent_referral", "Agent Referral", "ai_referral"
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
