"""Deterministic machine-engagement classification (Phase 14, ADR-C8).

Separates provider-reported engagement from human-qualified engagement using
deterministic rules only — no model inference in the ingest path. Models may
enrich these classifications asynchronously later, but never overwrite the
deterministic evidence recorded here.

Outputs per event:
  - suspected_machine_activity: bool
  - machine_activity_probability: 0.0–1.0 (rule-derived, not a model score)
  - engagement_confidence: 0.0–1.0
  - engagement_strength: none/weak/probable/strong/deterministic
  - classifier_version
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from services.comms.contracts import EngagementStrength

CLASSIFIER_VERSION = "rules-1.0"

# Known security-scanner / link-checker user-agent fragments (lower-cased).
_SCANNER_UA_PATTERNS: tuple[str, ...] = (
    "googleimageproxy",          # Gmail image proxy (opens)
    "yahoocachesystem",
    "barracuda", "proofpoint", "mimecast", "symantec", "trendmicro",
    "microsoft office", "urldefense", "safelinks",
    "python-requests", "curl/", "wget/", "go-http-client", "okhttp",
    "headlesschrome", "phantomjs", "slackbot", "bitlybot",
    "linkcheck", "validator", "monitoring", "uptime",
    "bot", "crawler", "spider",
)

# Apple Mail Privacy Protection and similar proxy-open signatures.
_PRIVACY_PROXY_UA_PATTERNS: tuple[str, ...] = (
    "applecoremedia", "apple mail", "cfnetwork",
    "googleimageproxy",
)

_DATACENTER_IP_CLASSES = ("datacenter", "hosting", "proxy", "cloud")

# Clicks landing within this window of delivery are characteristic of
# pre-fetch scanners, not humans.
_SCANNER_CLICK_WINDOW_SECONDS = 2.0


@dataclass
class EngagementClassification:
    suspected_machine_activity: bool
    machine_activity_probability: float
    engagement_confidence: float
    engagement_strength: EngagementStrength
    classifier_version: str = CLASSIFIER_VERSION
    signals: list[str] = field(default_factory=list)


def _ua_matches(user_agent: str, patterns: tuple[str, ...]) -> Optional[str]:
    ua = user_agent.lower()
    for p in patterns:
        if p in ua:
            return p
    return None


def classify_engagement(
    event_type: str,
    *,
    user_agent: Optional[str] = None,
    ip_class: Optional[str] = None,
    seconds_since_delivery: Optional[float] = None,
    clicked_all_links: bool = False,
    has_follow_up_session: bool = False,
    has_authenticated_session: bool = False,
    provider_flags: Optional[dict[str, Any]] = None,
) -> EngagementClassification:
    """Classify a single open/click event as human or machine.

    Deterministic rule cascade — the strongest human evidence (authenticated
    post-click session) always wins over weaker machine signals, and known
    scanner signatures always classify as machine.
    """
    signals: list[str] = []
    machine_prob = 0.0

    is_open = event_type in ("email_opened", "notification_opened")
    is_click = event_type in ("email_clicked", "notification_clicked")

    flags = provider_flags or {}
    if flags.get("is_machine") or flags.get("bot_detected"):
        signals.append("provider_machine_flag")
        machine_prob = 1.0

    if user_agent:
        scanner = _ua_matches(user_agent, _SCANNER_UA_PATTERNS)
        if scanner:
            signals.append(f"scanner_ua:{scanner}")
            machine_prob = max(machine_prob, 0.95)
        elif is_open and _ua_matches(user_agent, _PRIVACY_PROXY_UA_PATTERNS):
            signals.append("privacy_proxy_ua")
            machine_prob = max(machine_prob, 0.7)

    if ip_class and ip_class.lower() in _DATACENTER_IP_CLASSES:
        signals.append(f"ip_class:{ip_class}")
        machine_prob = max(machine_prob, 0.8 if is_click else 0.6)

    if (
        is_click
        and seconds_since_delivery is not None
        and 0 <= seconds_since_delivery <= _SCANNER_CLICK_WINDOW_SECONDS
    ):
        signals.append("click_within_scanner_window")
        machine_prob = max(machine_prob, 0.9)

    if clicked_all_links:
        signals.append("repeated_link_pattern")
        machine_prob = max(machine_prob, 0.9)

    # Human-positive evidence overrides machine heuristics (never the
    # provider's explicit machine flag or a scanner UA signature).
    hard_machine = machine_prob >= 0.95
    if has_authenticated_session and not hard_machine:
        signals.append("authenticated_post_click_session")
        return EngagementClassification(
            suspected_machine_activity=False,
            machine_activity_probability=min(machine_prob, 0.1),
            engagement_confidence=1.0,
            engagement_strength=EngagementStrength.DETERMINISTIC,
            signals=signals,
        )
    if has_follow_up_session and not hard_machine:
        signals.append("follow_up_sdk_session")
        return EngagementClassification(
            suspected_machine_activity=False,
            machine_activity_probability=min(machine_prob, 0.2),
            engagement_confidence=0.9,
            engagement_strength=EngagementStrength.STRONG,
            signals=signals,
        )

    suspected = machine_prob >= 0.7
    if suspected:
        return EngagementClassification(
            suspected_machine_activity=True,
            machine_activity_probability=machine_prob,
            engagement_confidence=round(1.0 - machine_prob, 4),
            engagement_strength=EngagementStrength.NONE,
            signals=signals,
        )

    # No machine evidence: opens are weak (pixel-only), clicks probable.
    if is_open:
        return EngagementClassification(
            suspected_machine_activity=False,
            machine_activity_probability=machine_prob,
            engagement_confidence=0.5,
            engagement_strength=EngagementStrength.WEAK,
            signals=signals,
        )
    if is_click:
        return EngagementClassification(
            suspected_machine_activity=False,
            machine_activity_probability=machine_prob,
            engagement_confidence=0.75,
            engagement_strength=EngagementStrength.PROBABLE,
            signals=signals,
        )
    # Replies and other engagement default to strong human evidence.
    return EngagementClassification(
        suspected_machine_activity=False,
        machine_activity_probability=machine_prob,
        engagement_confidence=0.9,
        engagement_strength=EngagementStrength.STRONG,
        signals=signals,
    )


# ── Automated-response detection (Phase 13) ───────────────────────────────────

_AUTO_RESPONSE_SUBJECT_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^auto(?:matic)?[-\s:]*reply",
        r"^out of (?:the )?office",
        r"^ooo[:\s]",
        r"^away from (?:the )?office",
        r"^automatic response",
        r"^delivery status notification",
        r"^undeliver(?:able|ed)",
        r"^mail delivery (?:failed|subsystem)",
        r"^returned mail",
        r"^vacation re(?:sponse|ply)",
    )
)

_AUTO_RESPONSE_HEADERS: dict[str, tuple[str, ...]] = {
    # header (lower-case) → values indicating automation ("*" = any value)
    "auto-submitted": ("auto-replied", "auto-generated"),
    "x-autoreply": ("*",),
    "x-autorespond": ("*",),
    "precedence": ("bulk", "junk", "auto_reply"),
    "x-auto-response-suppress": ("*",),
    "x-failed-recipients": ("*",),
}


def detect_automated_response(
    *,
    subject: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    from_address_local: Optional[str] = None,
) -> Optional[str]:
    """Return the automation kind if the inbound message is machine-generated.

    Kinds: ``delivery_status_notification``, ``out_of_office``,
    ``auto_response``, ``mail_loop``. Returns None for human replies.
    """
    hdrs = {k.lower(): (v or "") for k, v in (headers or {}).items()}

    if from_address_local and from_address_local.lower() in (
        "mailer-daemon", "postmaster", "no-reply", "noreply", "bounce", "bounces",
    ):
        return "delivery_status_notification"

    for header, markers in _AUTO_RESPONSE_HEADERS.items():
        value = hdrs.get(header)
        if value is None:
            continue
        if "*" in markers or value.lower() in markers:
            if header == "x-failed-recipients":
                return "delivery_status_notification"
            return "auto_response"

    # Loop detection: too many Received hops recorded by the provider
    received_count = hdrs.get("x-received-count")
    if received_count and received_count.isdigit() and int(received_count) > 25:
        return "mail_loop"

    if subject:
        for pat in _AUTO_RESPONSE_SUBJECT_PATTERNS:
            if pat.search(subject.strip()):
                if "deliver" in pat.pattern or "returned" in pat.pattern or "mail delivery" in pat.pattern:
                    return "delivery_status_notification"
                if "office" in pat.pattern or "ooo" in pat.pattern or "away" in pat.pattern or "vacation" in pat.pattern:
                    return "out_of_office"
                return "auto_response"
    return None
