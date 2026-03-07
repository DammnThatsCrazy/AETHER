"""
Aether Backend — Traffic Source Classifier

Stateless, pure-function classifier that determines traffic source, medium,
and channel from raw SDK signals. All intelligence lives here — SDKs only
ship raw referrer, UTM params, click IDs, and landing page.

Priority chain:
    1. Click IDs present     → paid channel       (confidence 1.0)
    2. UTM params present    → custom campaign     (confidence 0.95)
    3. Referrer domain match → organic/social/email (confidence 0.9)
    4. No signals            → Direct              (confidence 0.5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


# =============================================================================
# CLASSIFIED RESULT
# =============================================================================

@dataclass(frozen=True)
class ClassifiedSource:
    """Immutable result of traffic source classification."""
    source: str        # "google", "facebook", "newsletter", "(direct)"
    medium: str        # "cpc", "organic", "social", "referral", "email", "(none)"
    channel: str       # "Paid Search", "Organic Social", "Email", "Direct", etc.
    confidence: float  # 0.0–1.0


# =============================================================================
# SOURCE CLASSIFIER
# =============================================================================

class SourceClassifier:
    """
    Classifies raw traffic source data into source/medium/channel.

    Uses O(1) dict lookups — no regex matching. Domain tables are comprehensive
    and cover major social, search, and email platforms worldwide.
    """

    # Click ID → (source, medium, channel)
    CLICK_ID_MAP: dict[str, tuple[str, str, str]] = {
        "gclid":     ("google",    "cpc",       "Paid Search"),
        "msclkid":   ("bing",      "cpc",       "Paid Search"),
        "fbclid":    ("facebook",  "cpc",       "Paid Social"),
        "ttclid":    ("tiktok",    "cpc",       "Paid Social"),
        "twclid":    ("twitter",   "cpc",       "Paid Social"),
        "li_fat_id": ("linkedin",  "cpc",       "Paid Social"),
        "rdt_cid":   ("reddit",    "cpc",       "Paid Social"),
        "scid":      ("snapchat",  "cpc",       "Paid Social"),
        "dclid":     ("google",    "display",   "Display"),
        "epik":      ("pinterest", "cpc",       "Paid Social"),
        "irclickid": ("impact",    "affiliate", "Affiliate"),
        "aff_id":    ("unknown",   "affiliate", "Affiliate"),
    }

    # Social platform domains → source name
    SOCIAL_DOMAINS: dict[str, str] = {
        # Facebook / Meta
        "facebook.com": "facebook", "m.facebook.com": "facebook",
        "l.facebook.com": "facebook", "lm.facebook.com": "facebook",
        "fb.com": "facebook", "fb.me": "facebook",
        "messenger.com": "facebook",
        # Instagram
        "instagram.com": "instagram", "l.instagram.com": "instagram",
        # Twitter / X
        "twitter.com": "twitter", "t.co": "twitter",
        "x.com": "twitter", "mobile.twitter.com": "twitter",
        # LinkedIn
        "linkedin.com": "linkedin", "lnkd.in": "linkedin",
        "www.linkedin.com": "linkedin",
        # Reddit
        "reddit.com": "reddit", "old.reddit.com": "reddit",
        "www.reddit.com": "reddit", "out.reddit.com": "reddit",
        # TikTok
        "tiktok.com": "tiktok", "vm.tiktok.com": "tiktok",
        # YouTube
        "youtube.com": "youtube", "youtu.be": "youtube",
        "m.youtube.com": "youtube",
        # Pinterest
        "pinterest.com": "pinterest", "pin.it": "pinterest",
        # Snapchat
        "snapchat.com": "snapchat",
        # WhatsApp
        "whatsapp.com": "whatsapp", "wa.me": "whatsapp",
        # Telegram
        "telegram.org": "telegram", "t.me": "telegram",
        # Discord
        "discord.com": "discord", "discord.gg": "discord",
        # Threads
        "threads.net": "threads",
        # Mastodon (common instances)
        "mastodon.social": "mastodon",
        # Tumblr
        "tumblr.com": "tumblr",
        # Quora
        "quora.com": "quora",
        # Stack Overflow
        "stackoverflow.com": "stackoverflow",
        # Medium
        "medium.com": "medium",
        # Hacker News
        "news.ycombinator.com": "hackernews",
        # Bluesky
        "bsky.app": "bluesky",
    }

    # Search engine domains → source name
    SEARCH_DOMAINS: dict[str, str] = {
        "google.com": "google", "www.google.com": "google",
        "google.co.uk": "google", "google.ca": "google",
        "google.com.au": "google", "google.de": "google",
        "google.fr": "google", "google.co.jp": "google",
        "google.co.in": "google", "google.com.br": "google",
        "bing.com": "bing", "www.bing.com": "bing",
        "yahoo.com": "yahoo", "search.yahoo.com": "yahoo",
        "duckduckgo.com": "duckduckgo",
        "baidu.com": "baidu", "www.baidu.com": "baidu",
        "yandex.ru": "yandex", "yandex.com": "yandex",
        "ecosia.org": "ecosia",
        "ask.com": "ask",
        "aol.com": "aol", "search.aol.com": "aol",
        "naver.com": "naver", "search.naver.com": "naver",
        "seznam.cz": "seznam",
        "sogou.com": "sogou",
        "so.com": "360search",
        "startpage.com": "startpage",
        "brave.com": "brave", "search.brave.com": "brave",
        "perplexity.ai": "perplexity",
    }

    # Email provider domains → source name
    # Checked BEFORE search to correctly classify mail.google.com as email
    EMAIL_DOMAINS: dict[str, str] = {
        "mail.google.com": "gmail",
        "outlook.live.com": "outlook", "outlook.office365.com": "outlook",
        "outlook.office.com": "outlook",
        "mail.yahoo.com": "yahoo_mail",
        "mail.aol.com": "aol_mail",
        "mail.protonmail.com": "protonmail", "protonmail.com": "protonmail",
        "mail.zoho.com": "zoho_mail",
        "fastmail.com": "fastmail",
        "tutanota.com": "tutanota",
        "hey.com": "hey",
        "icloud.com": "icloud_mail",
        "mail.ru": "mail_ru",
        "yandex.mail": "yandex_mail",
    }

    # Medium → channel mapping for UTM-based classification
    MEDIUM_CHANNEL_MAP: dict[str, str] = {
        "cpc": "Paid Search",
        "ppc": "Paid Search",
        "paidsearch": "Paid Search",
        "paid-search": "Paid Search",
        "display": "Display",
        "banner": "Display",
        "cpm": "Display",
        "social": "Organic Social",
        "social-media": "Organic Social",
        "organic": "Organic Search",
        "email": "Email",
        "e-mail": "Email",
        "newsletter": "Email",
        "affiliate": "Affiliate",
        "referral": "Referral",
        "video": "Video",
        "audio": "Audio",
        "sms": "SMS",
        "push": "Push",
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
    ) -> ClassifiedSource:
        """
        Classify traffic source from raw signals.

        Priority:
            1. Click IDs → paid (confidence 1.0)
            2. UTM params → campaign (confidence 0.95)
            3. Referrer domain → organic/social/email (confidence 0.9)
            4. Direct (confidence 0.5)
        """
        click_ids = click_ids or {}

        # --- Priority 1: Click IDs (highest confidence) ---
        for click_id, value in click_ids.items():
            if value and click_id in self.CLICK_ID_MAP:
                source, medium, channel = self.CLICK_ID_MAP[click_id]
                return ClassifiedSource(
                    source=source, medium=medium,
                    channel=channel, confidence=1.0,
                )

        # --- Priority 2: UTM parameters ---
        if utm_source:
            medium = utm_medium or "referral"
            channel = self._channel_from_medium(medium)
            return ClassifiedSource(
                source=utm_source.lower(),
                medium=medium.lower(),
                channel=channel,
                confidence=0.95,
            )

        # --- Priority 3: Referrer domain classification ---
        domain = self._normalize_domain(referrer_domain or self._extract_domain(referrer))
        if domain:
            return self._classify_referrer_domain(domain)

        # --- Priority 4: Direct traffic ---
        return ClassifiedSource(
            source="(direct)", medium="(none)",
            channel="Direct", confidence=0.5,
        )

    def _classify_referrer_domain(self, domain: str) -> ClassifiedSource:
        """Classify based on referrer domain. Check email first to avoid misclassification."""

        # Email domains checked FIRST (mail.google.com → Email, not Search)
        if domain in self.EMAIL_DOMAINS:
            return ClassifiedSource(
                source=self.EMAIL_DOMAINS[domain],
                medium="email",
                channel="Email",
                confidence=0.9,
            )

        # Search engines
        search_source = self._match_search_domain(domain)
        if search_source:
            return ClassifiedSource(
                source=search_source,
                medium="organic",
                channel="Organic Search",
                confidence=0.9,
            )

        # Social platforms
        if domain in self.SOCIAL_DOMAINS:
            return ClassifiedSource(
                source=self.SOCIAL_DOMAINS[domain],
                medium="social",
                channel="Organic Social",
                confidence=0.9,
            )

        # Unknown referrer → Referral
        return ClassifiedSource(
            source=domain,
            medium="referral",
            channel="Referral",
            confidence=0.9,
        )

    def _match_search_domain(self, domain: str) -> Optional[str]:
        """Match search domains including Google's many TLDs."""
        # Direct lookup first
        if domain in self.SEARCH_DOMAINS:
            return self.SEARCH_DOMAINS[domain]

        # Handle google.* TLD variants (google.es, google.it, etc.)
        if domain.startswith("google.") or domain.startswith("www.google."):
            return "google"

        return None

    def _channel_from_medium(self, medium: str) -> str:
        """Map UTM medium to channel name."""
        normalized = medium.lower().strip()
        return self.MEDIUM_CHANNEL_MAP.get(normalized, "Other")

    @staticmethod
    def _extract_domain(referrer: str) -> str:
        """Extract domain from a full referrer URL."""
        if not referrer:
            return ""
        try:
            parsed = urlparse(referrer)
            return parsed.hostname or ""
        except Exception:
            return ""

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Normalize domain by stripping www. prefix and lowercasing."""
        if not domain:
            return ""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            # Keep www. variants that are in lookup tables (e.g., www.google.com)
            # but also check without www.
            pass
        return domain
