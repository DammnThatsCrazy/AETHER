"""Per-recipient link tagging for outbound campaigns.

A link sent by hand is the same for everyone, so a click on it can never be
tied to a person. A campaign send must give every recipient their own copy of
each link. :func:`tag_links` rewrites one message body for one recipient:
every link to one of the tenant's own hosts gets ``ae=<signed click token>``
appended, carrying (campaign, message, link, recipient alias).

Rules:
  * only ``http(s)`` links whose host is in ``allowed_hosts`` are tagged — a
    token is a recipient-correlated credential and must only reach sites that
    run the Aether SDK, never third parties;
  * links carrying ESP merge tags (``{{ }}``, ``*| |*``, ``%%``) are left alone
    because the provider rewrites them at send time;
  * ``mailto:``, ``tel:``, anchors and relative links are never touched;
  * an existing ``ae`` token on a link is replaced, other parameters and the
    fragment are preserved;
  * ``link_id`` is deterministic per URL, so every recipient's copy of the
    same link shares one id.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from journeys.comms.click_token import CLICK_TOKEN_QUERY_PARAM, looks_like_click_token

# Issues a token for one link: (link_id) -> token.
TokenIssuer = Callable[[str], str]

_HREF_RE = re.compile(r"""(?P<prefix>\bhref\s*=\s*)(?P<quote>["'])(?P<url>.*?)(?P=quote)""", re.IGNORECASE | re.DOTALL)
_TEXT_URL_RE = re.compile(r"""https?://[^\s<>"')\]]+""", re.IGNORECASE)
_MERGE_TAG_RE = re.compile(r"\{\{|\}\}|\*\||\|\*|%%|\[\[|\]\]")
_TRAILING_PUNCT = ".,;:!?"


def link_id_for(url: str) -> str:
    """Deterministic link id shared by every recipient's copy of ``url``."""
    return "lnk_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def normalize_hosts(hosts: list[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    cleaned = set()
    for host in hosts:
        value = str(host or "").strip().lower().rstrip(".")
        if value.startswith("*."):
            value = value[2:]
        if value:
            cleaned.add(value)
    return frozenset(cleaned)


def _host_allowed(host: str, allowed: frozenset[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == a or host.endswith("." + a) for a in allowed)


def _strip_existing_token(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (k, v) for k, v in pairs
        if not (k == CLICK_TOKEN_QUERY_PARAM and looks_like_click_token(v))
    ]


def _tag_url(url: str, allowed: frozenset[str], issue: TokenIssuer) -> Optional[tuple[str, str]]:
    """Return (tagged_url, link_id), or None when the link must stay untouched."""
    if not url or _MERGE_TAG_RE.search(url):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if not _host_allowed(parsed.hostname, allowed):
        return None
    pairs = _strip_existing_token(parse_qsl(parsed.query, keep_blank_values=True))
    base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs, doseq=True), parsed.fragment))
    link_id = link_id_for(base)
    pairs.append((CLICK_TOKEN_QUERY_PARAM, issue(link_id)))
    tagged = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs, doseq=True), parsed.fragment)
    )
    return tagged, link_id


@dataclass
class TaggedBody:
    html: Optional[str] = None
    text: Optional[str] = None
    links: dict[str, str] = field(default_factory=dict)  # link_id -> untagged url


def tag_links(
    *,
    html: Optional[str],
    text: Optional[str],
    allowed_hosts: frozenset[str],
    issue: TokenIssuer,
) -> TaggedBody:
    """Rewrite one recipient's copy of a message body."""
    if not allowed_hosts:
        raise ValueError("allowed_hosts must list the tenant's own domains")
    result = TaggedBody()
    issued: dict[str, str] = {}

    def issue_once(link_id: str) -> str:
        # One token per (recipient, link) even if the link repeats in the body.
        if link_id not in issued:
            issued[link_id] = issue(link_id)
        return issued[link_id]

    def record(tagged: Optional[tuple[str, str]], original: str) -> Optional[str]:
        if tagged is None:
            return None
        url, link_id = tagged
        result.links.setdefault(link_id, original)
        return url

    if html is not None:
        def replace_href(match: re.Match[str]) -> str:
            raw = match.group("url")
            url = html_lib.unescape(raw)
            tagged = record(_tag_url(url.strip(), allowed_hosts, issue_once), url.strip())
            if tagged is None:
                return match.group(0)
            return f"{match.group('prefix')}{match.group('quote')}{html_lib.escape(tagged, quote=True)}{match.group('quote')}"

        result.html = _HREF_RE.sub(replace_href, html)

    if text is not None:
        def replace_text(match: re.Match[str]) -> str:
            url = match.group(0)
            trailing = ""
            while url and url[-1] in _TRAILING_PUNCT:
                trailing = url[-1] + trailing
                url = url[:-1]
            tagged = record(_tag_url(url, allowed_hosts, issue_once), url)
            return (tagged or url) + trailing

        result.text = _TEXT_URL_RE.sub(replace_text, text)

    return result


__all__ = ["TaggedBody", "link_id_for", "normalize_hosts", "tag_links"]
