"""Notification Intelligence — Mobile Notification Projection (M1a).

Builds the **redacted push surface** for a mobile notification from the canonical
notification record. Follows decision-log D11:

  * the push ships ONLY the redacted projected fields — never raw payload / PII;
  * content is derived / truncated / redacted (entity names may surface, amounts
    and PII are replaced with ``[redacted]``, lengths are bounded);
  * the destination deep-link class reuses the continuation-plane surface
    vocabulary (``shared/continuation/models.py`` ``CONTINUATION_SURFACES``) so
    the mobile app routes with the same classes it already understands for
    deep-link resolution (``services/mobile/routes.py``) instead of a new class
    taxonomy;
  * a push with neither a projection nor any source content fails closed — it
    never falls back to dumping raw payload.

snake_case wire fields only (decision-log D6). ``MobileNotificationProjection``
is parity-tested against ``packages/shared/notification.ts`` by
``tests/contracts/test_notification_contract_parity.py``.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from pydantic import BaseModel, field_validator

from shared.continuation.models import CONTINUATION_SURFACES

# ── the projection field contract (snake_case, parity-tested) ────────────────
PROJECTION_FIELDS: tuple[str, ...] = (
    "push_title",
    "push_body",
    "push_summary",
    "push_deep_link_class",
    "push_category",
)

# Bounded push surfaces — a push is a short attention pointer, not a document.
PUSH_TITLE_MAX_CHARS = 80
PUSH_BODY_MAX_CHARS = 160
PUSH_SUMMARY_MAX_CHARS = 120

DEFAULT_DEEP_LINK_CLASS = "mission"
DEFAULT_PUSH_TITLE = "Aether notification"
DEFAULT_PUSH_BODY = "You have a new update."
DEFAULT_PUSH_CATEGORY = "alert"

_REDACTED = "[redacted]"

# Sensitive-value redaction: amounts, card/account digit runs, emails, phones.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b")
_LONG_DIGIT_RE = re.compile(r"\b\d{10,}\b")
_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9_$€£¥])(?:[$€£¥]\s*)?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?(?![A-Za-z0-9_%])"
)
# Ungrouped / large amounts the comma-form regex above cannot see: "1234.56",
# "12000", "200000.0", "$12000.00". Deliberately conservative so dates and
# versions survive: a bare 4-digit run is only redacted when it carries a
# decimal part (an amount), never when it is a year ("2026-01-01") or a version
# ("8.12.0"); 5+ digit runs are always amounts.
_LARGE_AMOUNT_RE = re.compile(
    r"(?<![\d.A-Za-z_$€£¥])(?:[$€£¥]\s*)?(?:"
    r"\d{5,}(?:\.\d{1,3})?"    # 5+ integer digits, optional decimals
    r"|\d{4}\.\d{1,3}"         # 4 integer digits carrying a decimal part
    r")(?![A-Za-z0-9%])"
)

# Deep-link path prefix → continuation-plane surface class. Only classes the
# continuation plane already understands are produced (see CONTINUATION_SURFACES).
# Plural route forms (e.g. ``/campaigns``) map to the same surface as the
# singular; ordered so the longest prefix wins.
_DEEP_LINK_CLASS_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/investigations", "investigation"),
    ("/investigation", "investigation"),
    ("/explorations", "exploration"),
    ("/exploration", "exploration"),
    ("/notifications", "notifications"),
    ("/profiles", "profile"),
    ("/profile", "profile"),
    ("/clusters", "cluster"),
    ("/cluster", "cluster"),
    ("/campaigns", "campaign"),
    ("/campaign", "campaign"),
    ("/exceptions", "exception"),
    ("/exception", "exception"),
    ("/incidents", "incident"),
    ("/incident", "incident"),
    ("/journeys", "journey"),
    ("/journey", "journey"),
    ("/noesis", "noesis"),
    ("/graphs", "graph"),
    ("/graph", "graph"),
    ("/mission", "mission"),
)


class MobileNotificationProjection(BaseModel):
    """Redacted push surface — the ONLY content a push may carry.

    Fields are snake_case (decision-log D6). ``push_deep_link_class`` is coerced
    to a continuation-plane surface; unknown classes degrade to ``mission`` so a
    push always routes somewhere safe and never fails on an invented class.
    """

    push_title: Optional[str] = None
    push_body: Optional[str] = None
    push_summary: Optional[str] = None
    push_deep_link_class: str = DEFAULT_DEEP_LINK_CLASS
    push_category: str = DEFAULT_PUSH_CATEGORY

    model_config = {"extra": "forbid"}

    @field_validator("push_deep_link_class")
    @classmethod
    def _known_surface(cls, v: str) -> str:
        if v not in CONTINUATION_SURFACES:
            return DEFAULT_DEEP_LINK_CLASS
        return v

    def as_payload(self) -> dict[str, Any]:
        """The projection as a plain dict keyed by ``PROJECTION_FIELDS``."""
        return {field: getattr(self, field) for field in PROJECTION_FIELDS}


def _redact(text: Optional[Any]) -> str:
    """Redact PII / sensitive values; returns ``""`` for ``None``/empty input."""
    if not text:
        return ""
    value = str(text)
    value = _EMAIL_RE.sub(_REDACTED, value)
    value = _PHONE_RE.sub(_REDACTED, value)
    value = _LONG_DIGIT_RE.sub(_REDACTED, value)
    value = _AMOUNT_RE.sub(_REDACTED, value)
    value = _LARGE_AMOUNT_RE.sub(_REDACTED, value)
    # Collapse adjacent redactions ("[redacted] [redacted]" → single marker).
    value = re.sub(r"(?:\s*\[redacted\]\s*)+", f" {_REDACTED} ", value).strip()
    return value


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _coerce_category(category: Any) -> str:
    """Enums → their value; categories stay open (inbox contract)."""
    if category is None:
        return DEFAULT_PUSH_CATEGORY
    if hasattr(category, "value"):
        return str(category.value)
    value = str(category)
    return value if value else DEFAULT_PUSH_CATEGORY


def _deep_link_class(deep_link: Optional[Any]) -> str:
    """Map a canonical notification deep link to a continuation-plane surface.

    Opaque continuation tokens (``cont_…``), full URLs and unknown routes all
    resolve to the default class — the mobile app either resolves the opaque id
    through the existing deep-link resolver or lands on the app home; nothing is
    invented and nothing leaks.
    """
    if not deep_link:
        return DEFAULT_DEEP_LINK_CLASS
    text = str(deep_link).strip()
    if text.startswith("cont_"):
        return DEFAULT_DEEP_LINK_CLASS
    path = text.split("?", 1)[0].rstrip("/")
    for prefix, cls in _DEEP_LINK_CLASS_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return cls
    return DEFAULT_DEEP_LINK_CLASS


def _first(*values: Any) -> Any:
    """First non-None value (explicit kwargs win over the record)."""
    for value in values:
        if value is not None:
            return value
    return None


def build_projection(
    record: Optional[Mapping[str, Any]] = None,
    *,
    title: Optional[Any] = None,
    body: Optional[Any] = None,
    summary: Optional[Any] = None,
    what: Optional[Any] = None,
    category: Optional[Any] = None,
    notification_class: Optional[Any] = None,
    severity: Optional[Any] = None,
    deep_link: Optional[Any] = None,
    link: Optional[Any] = None,
) -> MobileNotificationProjection:
    """Derive the redacted projection from a canonical notification record.

    ``record`` may be any notification-shaped mapping (an inbox row or an
    ``IntelligenceNotificationEvent``-style dict); explicit keyword arguments
    override record fields. The returned projection carries ONLY redacted,
    bounded, derived values — never raw payload or PII.
    """
    if record is not None:
        title = _first(title, record.get("title"))
        body = _first(body, record.get("body"))
        summary = _first(summary, record.get("summary"), record.get("what"))
        what = _first(what, record.get("what"))
        category = _first(category, record.get("category"))
        notification_class = _first(notification_class, record.get("notification_class"))
        severity = _first(severity, record.get("severity"))
        deep_link = _first(deep_link, record.get("deep_link"), record.get("link"))
        link = _first(link, record.get("link"))

    raw_summary = summary or what or body
    category_value = _coerce_category(category or notification_class)

    push_title = _redact(title) or DEFAULT_PUSH_TITLE
    push_body = _redact(body) or DEFAULT_PUSH_BODY
    push_summary = _redact(raw_summary) or DEFAULT_PUSH_BODY

    return MobileNotificationProjection(
        push_title=_truncate(push_title, PUSH_TITLE_MAX_CHARS),
        push_body=_truncate(push_body, PUSH_BODY_MAX_CHARS),
        push_summary=_truncate(push_summary, PUSH_SUMMARY_MAX_CHARS),
        push_deep_link_class=_deep_link_class(deep_link or link),
        push_category=category_value,
    )
