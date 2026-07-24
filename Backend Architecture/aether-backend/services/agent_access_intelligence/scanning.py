"""Pure tool/schema scanning for observed capabilities (PR 2, Phase B2 — monoprompt §9.4).

``scan_capability`` turns one catalog record into a list of ``CapabilityFinding``. It is a
**pure function**: no network, no DNS, no repository access, no clock, no environment reads.
The same record always yields the same findings, in the same order. That is a correctness
requirement, not a performance one — a findings surface that changes because *our* DNS view
changed is not evidence about the tenant's capability, and an operator cannot act on it.

Findings describe a capability we have **already observed**. They are not a pre-flight
safety check on an outbound request, and nothing here authorizes or blocks anything.

─── Reuse decision 1: reuse ``_ip_is_unsafe`` / ``_BLOCKED_HOSTS``, NOT ``_is_unsafe_destination``

``services.security.policy_engine._is_unsafe_destination`` is the right primitive for
*webhook dispatch*: it calls ``_resolve_host`` (synchronous DNS) and fails **closed** —
a name that does not resolve is reported unsafe. That is correct there, because the caller
is about to send a request to that URL and an unresolvable/rebinding name must not be
trusted.

It is wrong here. We are describing something already seen. A host that does not resolve
*from this network* is not evidence of danger — legitimate internal, air-gapped, and
customer-VPC MCP servers are unresolvable from us by design. Calling ``_is_unsafe_destination``
would mark them all unsafe, flooding a security surface with false positives until operators
stop reading it. It would also make the output depend on DNS state and inject a blocking
socket call into a pure function.

So this module reuses only the **pure** primitives — ``_ip_is_unsafe`` for literal IP
addresses and ``_BLOCKED_HOSTS`` for the deny set — and performs **no resolution at all**.
An unresolvable hostname yields no origin finding, on purpose. Do not "fix" this by
switching to ``_is_unsafe_destination``; that would be a regression, not a hardening.

─── Reuse decision 2: reuse ``INJECTION_PATTERNS`` as vocabulary, NOT noesis's matching

``services.noesis.service`` matches ``INJECTION_PATTERNS`` with ``if pattern in low`` over
free-form user prose. That is fine there: the input is a sentence, and a false positive
costs one rejected question.

``INJECTION_PATTERNS`` contains the single words ``"dan"`` and ``"bypass"``. Substring
matching those against short mechanical tool identifiers fires on ``abundance_report``,
``redundancy_check``, ``standardize`` and ``bypass_cache`` — ordinary tool names, reported
as injection-shaped. In a security surface that is a false-positive generator, and it
trains operators to ignore the finding.

This module matches on **token boundaries** instead. The tool name is normalized by
splitting on non-alphanumerics, then:

  * multi-word patterns (``"ignore previous"``, ``"system prompt"``, …) match an
    **adjacent token sequence** anywhere in the name — ``ignore_previous_instructions`` fires;
  * single-word patterns (``"dan"``, ``"bypass"``, ``"jailbreak"``) match only when they are
    the **entire** identifier. One generic English word embedded in a compound name is not
    evidence: ``bypass_cache`` names a cache operation, while a tool called exactly
    ``bypass`` names nothing else.

The finding is *shape*, never intent — the summary says so.
"""

from __future__ import annotations

import ipaddress
from enum import Enum
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel

from services.agentic_observability.models import RiskLevel
from services.noesis.models import INJECTION_PATTERNS
from services.security.policy_engine import _BLOCKED_HOSTS, _ip_is_unsafe

# The sentinel `_sanitize_server_url` (catalog_service) writes in place of a credential
# query value. Seeing it in a stored URL is evidence the capability was configured with a
# secret in its URL — the secret itself was never persisted and never appears in evidence.
_REDACTION_SENTINEL = "REDACTED"

# Schemes considered to carry transport security. `wss` belongs here: MCP servers are
# commonly reached over WebSocket, and wss IS TLS — reporting it as insecure transport
# would be factually wrong and is exactly the false-positive class this module exists to
# avoid. `ws` and `http` are correctly absent.
_TLS_SCHEMES = frozenset({"https", "wss"})

# Patterns split by shape once at import — see "Reuse decision 2" above.
_MULTI_WORD_PATTERNS: tuple[tuple[str, ...], ...] = tuple(
    sorted(tuple(p.split()) for p in INJECTION_PATTERNS if len(p.split()) > 1)
)
_SINGLE_WORD_PATTERNS: tuple[str, ...] = tuple(
    sorted(p for p in INJECTION_PATTERNS if len(p.split()) == 1)
)


class FindingCode(str, Enum):
    CREDENTIAL_IN_URL = "credential_in_url"
    INSECURE_TRANSPORT = "insecure_transport"
    PRIVATE_NETWORK_ORIGIN = "private_network_origin"
    BLOCKED_HOST_ORIGIN = "blocked_host_origin"
    INJECTION_SHAPED_TOOL_NAME = "injection_shaped_tool_name"
    UNPARSEABLE_ORIGIN = "unparseable_origin"


_RISK_BY_CODE: dict[FindingCode, RiskLevel] = {
    FindingCode.CREDENTIAL_IN_URL: RiskLevel.HIGH,
    FindingCode.INSECURE_TRANSPORT: RiskLevel.HIGH,
    FindingCode.PRIVATE_NETWORK_ORIGIN: RiskLevel.MEDIUM,
    FindingCode.BLOCKED_HOST_ORIGIN: RiskLevel.MEDIUM,
    FindingCode.INJECTION_SHAPED_TOOL_NAME: RiskLevel.MEDIUM,
    FindingCode.UNPARSEABLE_ORIGIN: RiskLevel.LOW,
}


class CapabilityFinding(BaseModel):
    """One observation about an observed capability. Flat, so it round-trips through
    ``BaseRepository`` JSONB and through the API surface unchanged."""

    code: FindingCode
    risk_level: RiskLevel
    summary: str
    evidence: str
    capability_id: Optional[str] = None


def _finding(code: FindingCode, summary: str, evidence: str, capability_id: Optional[str]) -> CapabilityFinding:
    return CapabilityFinding(
        code=code,
        risk_level=_RISK_BY_CODE[code],
        summary=summary,
        evidence=evidence,
        capability_id=capability_id,
    )


def _split_origin(raw: str) -> tuple[str, str, str]:
    """``(scheme, authority, query)`` for an observed server URL. Raises ``ValueError``
    on input ``urlsplit`` rejects.

    A scheme is only believed when the value actually carries a ``://`` authority marker.
    That guard matters: ``urlsplit("localhost:8080")`` returns ``scheme='localhost'`` and
    ``urlsplit("user:pass@host/x")`` returns ``scheme='user'`` — so trusting ``.scheme``
    would report an opaque ``host:port`` server name as an insecure-transport finding while
    simultaneously losing its host. Without ``://`` we cannot tell a scheme from a port, so
    the value is treated as an opaque name (the conservative direction: absence of an
    observable scheme is not evidence of plaintext) and re-split with a forced authority so
    ``host:port`` and ``user:pass@host`` are still read correctly.
    """
    parts = urlsplit(raw)
    if parts.scheme and raw[len(parts.scheme):].startswith("://"):
        return parts.scheme.lower(), parts.netloc, parts.query
    opaque = urlsplit(raw if raw.startswith("//") else "//" + raw)
    return "", opaque.netloc, opaque.query


def _host_from_authority(authority: str) -> str:
    """Host of an authority string, with userinfo and port removed. No resolution."""
    host = authority.rsplit("@", 1)[-1]
    if host.startswith("["):  # bracketed IPv6 literal
        return host[1:].split("]", 1)[0].lower()
    if host.count(":") == 1:
        head, _, tail = host.partition(":")
        if tail.isdigit() or tail == "":
            return head.lower()
    return host.lower()


def _userinfo(authority: str) -> Optional[str]:
    if "@" not in authority:
        return None
    return authority.rsplit("@", 1)[0]


def _normalize_tokens(name: str) -> list[str]:
    """Lowercase tokens of a tool identifier: ``systemPrompt.dump-v2`` → ``['system',
    'prompt', 'dump', 'v2']``.

    Splits on non-alphanumerics *and* on lower→upper transitions, because MCP tool names
    are written in both ``snake_case`` and ``camelCase`` and a matcher that only understands
    one of them silently misses half the surface. Splitting more never re-creates the
    substring false positives it exists to prevent: ``abundanceReport`` becomes
    ``['abundance', 'report']``, and neither token is ``dan``.
    """
    tokens: list[str] = []
    current: list[str] = []
    previous = ""
    for ch in name:
        if not ch.isalnum():
            if current:
                tokens.append("".join(current).lower())
                current = []
            previous = ch
            continue
        if ch.isupper() and previous and (previous.islower() or previous.isdigit()) and current:
            tokens.append("".join(current).lower())
            current = []
        current.append(ch)
        previous = ch
    if current:
        tokens.append("".join(current).lower())
    return tokens


def _matched_injection_patterns(tool_name: str) -> list[str]:
    """Token-boundary matches of ``INJECTION_PATTERNS`` against a tool identifier."""
    tokens = _normalize_tokens(tool_name)
    if not tokens:
        return []
    matched: list[str] = []
    for pattern in _MULTI_WORD_PATTERNS:
        width = len(pattern)
        for start in range(len(tokens) - width + 1):
            if tuple(tokens[start:start + width]) == pattern:
                matched.append(" ".join(pattern))
                break
    if len(tokens) == 1 and tokens[0] in _SINGLE_WORD_PATTERNS:
        # Single-word patterns are evidence only as the whole identifier — see module docstring.
        matched.append(tokens[0])
    return sorted(set(matched))


def _scan_origin(raw_url: str, capability_id: Optional[str]) -> list[CapabilityFinding]:
    findings: list[CapabilityFinding] = []
    try:
        scheme, authority, query = _split_origin(raw_url)
        query_pairs = parse_qsl(query, keep_blank_values=True)
    except ValueError as exc:
        return [
            _finding(
                FindingCode.UNPARSEABLE_ORIGIN,
                "Stored server URL could not be parsed; its origin was not evaluated.",
                f"server_url is not parseable as a URL ({exc.__class__.__name__})",
                capability_id,
            )
        ]

    # ── Credential in URL. Never emit the credential itself, only its position. ──
    credential_evidence: list[str] = []
    userinfo = _userinfo(authority)
    if userinfo is not None and ":" in userinfo:
        credential_evidence.append("userinfo (user:pass@) present in the URL authority; value withheld")
    redacted_keys = sorted({k for k, v in query_pairs if v == _REDACTION_SENTINEL})
    if redacted_keys:
        credential_evidence.append(
            "query parameter(s) "
            + ", ".join(repr(k) for k in redacted_keys)
            + " hold the catalog redaction sentinel, so a credential was configured in this URL"
        )
    if credential_evidence:
        findings.append(
            _finding(
                FindingCode.CREDENTIAL_IN_URL,
                "Capability was configured with a credential embedded in its server URL.",
                "; ".join(credential_evidence),
                capability_id,
            )
        )

    # ── Transport. Absence of a scheme is NOT evidence of plaintext: an opaque server
    #    name simply tells us nothing about how it is reached. Say nothing in that case. ──
    if scheme and scheme not in _TLS_SCHEMES:
        findings.append(
            _finding(
                FindingCode.INSECURE_TRANSPORT,
                "Capability server URL uses a scheme without transport security.",
                f"scheme {scheme!r}",
                capability_id,
            )
        )

    host = _host_from_authority(authority)
    if not host:
        return findings

    if host in _BLOCKED_HOSTS:
        findings.append(
            _finding(
                FindingCode.BLOCKED_HOST_ORIGIN,
                "Capability server host is on the blocked-destination list.",
                f"host {host!r} is in the blocked-host set",
                capability_id,
            )
        )

    # ── Literal IPs only. No DNS: an unresolvable name is not evidence (see docstring). ──
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return findings
    if _ip_is_unsafe(ip):
        findings.append(
            _finding(
                FindingCode.PRIVATE_NETWORK_ORIGIN,
                "Capability server URL points at a private, loopback or reserved IP literal.",
                f"host is the IP literal {host}",
                capability_id,
            )
        )
    return findings


def scan_capability(record: dict[str, Any]) -> list[CapabilityFinding]:
    """Scan one capability record. Pure — no I/O, no DNS, no clock, no repository.

    A record with neither ``server_url`` nor ``tool_name`` yields **no** findings: absent
    data is not a finding, and inventing one about what we did not observe would violate the
    honesty rule the catalog is built on.
    """
    capability_id = record.get("capability_id")
    capability_id = capability_id if isinstance(capability_id, str) and capability_id else None

    findings: list[CapabilityFinding] = []

    raw_url = record.get("server_url")
    if isinstance(raw_url, str) and raw_url.strip():
        findings.extend(_scan_origin(raw_url.strip(), capability_id))

    tool_name = record.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        matched = _matched_injection_patterns(tool_name)
        if matched:
            findings.append(
                _finding(
                    FindingCode.INJECTION_SHAPED_TOOL_NAME,
                    "Tool name matches a known prompt-injection phrase shape (shape only, not intent).",
                    "tool name matches pattern(s) " + ", ".join(repr(m) for m in matched),
                    capability_id,
                )
            )

    # Deterministic order so the surface is stable across calls and diffable across runs.
    # At most one finding per code is produced, so sorting by code is a total order;
    # evidence is included in the key to keep the sort total if that ever changes.
    findings.sort(key=lambda f: (f.code.value, f.evidence))
    return findings


def scan_capabilities(records: Iterable[dict[str, Any]]) -> list[CapabilityFinding]:
    """Scan many records. Findings are grouped per record, in input order, each record's
    findings sorted by code — the per-record order from ``scan_capability`` is preserved
    rather than re-sorted globally, so a finding stays next to the capability it describes."""
    out: list[CapabilityFinding] = []
    for record in records:
        out.extend(scan_capability(record))
    return out
