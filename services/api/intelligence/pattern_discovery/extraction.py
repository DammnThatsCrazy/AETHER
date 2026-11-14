"""Schema-on-read extraction: raw / semi-structured evidence -> candidate observations.

Aether's canonical normalizers only understand payloads they were written for.
This module interprets *anything*: arbitrary nested JSON ``properties``,
unfamiliar webhook bodies, error messages, notes, tool traces and agent
transcripts. It produces three things:

1. **Extracted events** – one per input row, carrying the acting entity, a
   behavioural *token* (event type + outcome, or event type + message template
   for free text), typed attributes (device, IP, wallet, payment instrument,
   email, host, learned identifiers ...) and counterparty links.
2. **Field profiles** – per ``(source, event_type)`` schema statistics (paths,
   type mix, cardinality, presence). These feed schema-drift detection and the
   *learned identifier* pass: a field nobody modelled whose values behave like
   identifiers becomes a linkage attribute named ``field:<path>``.
3. **Candidate observations** – the attribute assertions themselves, always
   ``claim_state="inferred"`` with the extractor and a confidence. They are
   evidence for patterns, never canonical facts.

Privacy: values of sensitive types (email, phone, payment instrument, IP, user
agent, learned fields, anything found inside free text) are replaced by a
tenant-salted digest before they leave this module. Card numbers are detected
by Luhn check and never retained in any form other than that digest.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from shared.temporal.instant import coerce_utc_lenient

MAX_DEPTH = 6
MAX_LEAVES = 300
MAX_TEXT_CHARS = 8_000
MAX_DISTINCT_TRACKED = 2_000

# ── Semantic value detectors ─────────────────────────────────────────────────
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,24}$")
_EMAIL_IN = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,24}")
_EVM = re.compile(r"^0x[a-fA-F0-9]{40}$")
_EVM_IN = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC = re.compile(r"^(bc1[a-z0-9]{25,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
_IPV4 = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")
_IPV4_IN = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_IPV6 = re.compile(r"^[0-9a-fA-F:]{2,39}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_UUID_IN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_URL = re.compile(r"^(https?|wss?)://\S+$", re.IGNORECASE)
_URL_IN = re.compile(r"\b(?:https?|wss?)://[^\s\"'<>]+", re.IGNORECASE)
_PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_HEXHASH = re.compile(r"^(0x)?[a-fA-F0-9]{32,128}$")
_DIGITS = re.compile(r"^\d[\d \-]{11,22}\d$")
_DIGITS_IN = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
_USER_AGENT = re.compile(r"^(Mozilla|Dalvik|okhttp|curl|python-requests|Go-http-client|axios)/", re.IGNORECASE)
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?![A-Za-z])")
_HEX_TOKEN = re.compile(r"\b(?:0x)?[a-fA-F0-9]{8,}\b")
_QUOTED = re.compile(r"(['\"`])(?:(?!\1).){1,200}\1")
_WS = re.compile(r"\s+")

#: Attribute types whose raw value is never retained.
SENSITIVE_TYPES = frozenset({"email", "phone", "payment_instrument", "ip", "user_agent"})

#: Attribute types that link entities (used by the shared-attribute detector).
LINKAGE_TYPES = frozenset({
    "email", "phone", "payment_instrument", "ip", "device", "wallet", "host",
    "account_ref", "user_agent", "identifier",
})

#: Last-path-segment hints -> attribute type (substring match, first wins).
_KEY_HINTS: tuple[tuple[str, str], ...] = (
    ("card_fingerprint", "payment_instrument"),
    ("payment_method", "payment_instrument"),
    ("instrument", "payment_instrument"),
    ("card", "payment_instrument"),
    ("iban", "payment_instrument"),
    ("bank_account", "payment_instrument"),
    ("device_fingerprint", "device"),
    ("fingerprint", "device"),
    ("device", "device"),
    ("idfa", "device"),
    ("gaid", "device"),
    ("wallet", "wallet"),
    ("address", "wallet"),
    ("email", "email"),
    ("phone", "phone"),
    ("msisdn", "phone"),
    ("user_agent", "user_agent"),
    ("useragent", "user_agent"),
    ("ip", "ip"),
    ("host", "host"),
    ("endpoint", "host"),
    ("server_url", "host"),
    ("url", "host"),
    ("account_id", "account_ref"),
    ("account", "account_ref"),
)
#: Keys whose value is a counterparty of the acting entity, with the relation.
_COUNTERPARTY_KEYS: tuple[tuple[str, str], ...] = (
    ("to_address", "TRANSACTS_WITH"),
    ("recipient", "TRANSACTS_WITH"),
    ("counterparty", "TRANSACTS_WITH"),
    ("beneficiary", "TRANSACTS_WITH"),
    ("payee", "TRANSACTS_WITH"),
    ("destination", "TRANSACTS_WITH"),
    ("to", "TRANSACTS_WITH"),
    ("target", "TARGETS"),
    ("delegated_by", "DELEGATED_BY"),
    ("delegator", "DELEGATED_BY"),
    ("on_behalf_of", "DELEGATED_BY"),
    ("principal", "DELEGATED_BY"),
    ("parent_agent", "SPAWNED_BY"),
    ("spawned_by", "SPAWNED_BY"),
    ("invited_by", "INVITED_BY"),
    ("referrer", "INVITED_BY"),
    ("referred_by", "INVITED_BY"),
)
_TEXT_KEYS = ("message", "error", "reason", "note", "notes", "comment", "description",
              "transcript", "log", "detail", "details", "text", "body", "content", "output",
              "prompt", "response", "stack", "trace")
_OUTCOME_KEYS = ("status", "outcome", "result", "state", "success", "ok", "error", "failed",
                 "decline_code", "error_code")
_FAIL_WORDS = frozenset({"fail", "failed", "failure", "error", "errored", "declined", "denied",
                         "rejected", "blocked", "timeout", "timed_out", "invalid", "reverted",
                         "insufficient_funds", "fraud", "cancelled", "canceled", "aborted"})
_OK_WORDS = frozenset({"ok", "success", "succeeded", "successful", "completed", "complete",
                       "approved", "confirmed", "settled", "accepted", "done", "paid", "captured"})
_AMOUNT_KEYS = ("amount", "value", "total", "price", "amount_usd", "usd_value")
#: Field names that hold categories, never identities (excluded from learning).
_CATEGORY_KEYS = frozenset({
    "status", "state", "type", "kind", "result", "outcome", "reason", "currency", "country",
    "region", "method", "category", "level", "plan", "tier", "channel", "platform", "os",
    "browser", "locale", "lang", "language", "mode", "env", "environment", "version",
    "source", "medium", "campaign", "action", "event", "name", "title", "role", "network",
    "chain", "symbol", "unit", "decline_code", "error_code", "code",
})


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _is_pan(value: str) -> bool:
    if not _DIGITS.fullmatch(value):
        return False
    digits = re.sub(r"[ \-]", "", value)
    return 13 <= len(digits) <= 19 and _luhn(digits)


def digest(tenant_id: str, attr_type: str, value: str) -> str:
    """Tenant-salted, type-scoped, irreversible digest used for sensitive values."""
    norm = value.strip().lower()
    return "h:" + hashlib.sha256(f"{tenant_id}\x00{attr_type}\x00{norm}".encode()).hexdigest()[:24]


def host_of(value: str) -> Optional[str]:
    try:
        host = urlparse(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _key_hint(path: str) -> Optional[str]:
    last = path.rsplit(".", 1)[-1].replace("[]", "").lower()
    for hint, attr_type in _KEY_HINTS:
        if last == hint or last.endswith("_" + hint) or last.startswith(hint + "_") or (
            len(hint) > 4 and hint in last
        ):
            return attr_type
    return None


def classify_value(value: str, path: str = "") -> Optional[tuple[str, float]]:
    """Semantic type of a scalar string and the extractor's confidence, or None.

    Pattern evidence (the value's own shape) beats key hints; a key hint alone
    yields a lower confidence. Timestamps and generic hashes are typed so they
    are *not* mistaken for identifiers, but are not linkage attributes.
    """
    v = value.strip()
    if not v or len(v) > 2048:
        return None
    hint = _key_hint(path)
    if _EMAIL.fullmatch(v):
        return "email", 0.95
    if _EVM.fullmatch(v) or (hint == "wallet" and _BTC.fullmatch(v)):
        return "wallet", 0.95
    if _is_pan(v):
        return "payment_instrument", 0.95
    if _IPV4.fullmatch(v) or (hint == "ip" and ":" in v and _IPV6.fullmatch(v) and v.count(":") >= 2):
        return "ip", 0.9
    if _PHONE.fullmatch(v):
        return "phone", 0.85
    if _URL.fullmatch(v):
        return "host", 0.85
    if _USER_AGENT.match(v):
        return "user_agent", 0.85
    if _ISO_TS.fullmatch(v):
        return "timestamp", 0.9
    if hint in {"device", "payment_instrument", "account_ref", "user_agent", "phone", "email"}:
        if " " not in v and 4 <= len(v) <= 256:
            return hint, 0.7
    if hint == "host" and " " not in v and "." in v:
        return "host", 0.7
    if hint == "wallet" and " " not in v and 26 <= len(v) <= 64:
        return "wallet", 0.6
    if _UUID.fullmatch(v):
        return "identifier", 0.6
    if _HEXHASH.fullmatch(v):
        return "hash", 0.6
    return None


def message_template(text: str) -> tuple[str, str]:
    """Collapse a free-text message to its template (Drain-style masking).

    Variable parts (numbers, hex ids, UUIDs, IPs, emails, URLs, quoted strings)
    become ``<*>`` so ``"card 4242 declined for order 991"`` and
    ``"card 1881 declined for order 12"`` share one template. Returns the
    template and a short stable id.
    """
    t = text[:MAX_TEXT_CHARS]
    for rx in (_URL_IN, _EMAIL_IN, _UUID_IN, _EVM_IN, _IPV4_IN, _QUOTED, _HEX_TOKEN, _NUMBER_TOKEN):
        t = rx.sub("<*>", t)
    t = _WS.sub(" ", t).strip().lower()
    t = re.sub(r"(<\*>[ ,;:]*){2,}", "<*> ", t).strip()
    words = t.split(" ")[:24]
    template = " ".join(words)
    return template, "tmpl_" + hashlib.sha256(template.encode()).hexdigest()[:10]


def text_tokens(text: str) -> list[tuple[str, str]]:
    """Identifier-like tokens embedded in free text: ``[(type, raw_value)]``."""
    t = text[:MAX_TEXT_CHARS]
    found: list[tuple[str, str]] = []
    found += [("email", m) for m in _EMAIL_IN.findall(t)]
    found += [("wallet", m) for m in _EVM_IN.findall(t)]
    found += [("ip", m) for m in _IPV4_IN.findall(t)]
    for url in _URL_IN.findall(t):
        host = host_of(url)
        if host:
            found.append(("host", host))
    for m in _DIGITS_IN.findall(t):
        digits = re.sub(r"[ \-]", "", m)
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append(("payment_instrument", digits))
    return list(dict.fromkeys(found))[:50]


def flatten(payload: Any, prefix: str = "", depth: int = 0,
            out: Optional[list[tuple[str, Any]]] = None) -> list[tuple[str, Any]]:
    """Leaves of an arbitrary JSON value as ``(dotted.path, scalar)``.

    List positions collapse to ``[]`` so the schema is shape-level, not
    index-level. Depth and leaf counts are bounded; deeper structure is
    reported as an ``object`` leaf rather than silently dropped.
    """
    out = [] if out is None else out
    if len(out) >= MAX_LEAVES:
        return out
    if isinstance(payload, dict):
        if depth >= MAX_DEPTH:
            out.append((prefix or "$", {"__truncated__": True}))
            return out
        for key in sorted(payload, key=str)[:200]:
            path = f"{prefix}.{key}" if prefix else str(key)
            flatten(payload[key], path, depth + 1, out)
    elif isinstance(payload, list):
        if depth >= MAX_DEPTH:
            out.append((prefix or "$", {"__truncated__": True}))
            return out
        for item in payload[:50]:
            flatten(item, f"{prefix}[]" if prefix else "[]", depth + 1, out)
    else:
        out.append((prefix or "$", payload))
    return out


def value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    return "other"


def outcome_of(event_type: str, properties: dict[str, Any]) -> Optional[str]:
    """``ok`` / ``fail`` when the payload says how the action ended, else None."""
    et = event_type.lower()
    if any(w in et for w in ("fail", "error", "declin", "denied", "reject", "revert")):
        return "fail"
    if any(w in et.split("_") for w in ("succeeded", "success", "completed", "approved", "confirmed")):
        return "ok"
    for key in _OUTCOME_KEYS:
        if key not in properties:
            continue
        val = properties[key]
        if isinstance(val, bool):
            if key in ("success", "ok"):
                return "ok" if val else "fail"
            if key in ("failed", "error"):
                return "fail" if val else "ok"
            continue
        if isinstance(val, str):
            low = val.strip().lower().replace(" ", "_")
            if low in _FAIL_WORDS or any(w in low for w in ("fail", "declin", "denied", "error")):
                return "fail"
            if low in _OK_WORDS:
                return "ok"
            if key in ("error", "decline_code", "error_code") and low:
                return "fail"
        if isinstance(val, (int, float)) and key == "status" and 100 <= val < 600:
            return "fail" if val >= 400 else "ok"
    return None


def _amount_of(properties: dict[str, Any]) -> Optional[float]:
    for key in _AMOUNT_KEYS:
        val = properties.get(key)
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val.replace(",", ""))
            except ValueError:
                continue
    return None


def entity_of(row: dict[str, Any]) -> Optional[str]:
    """The acting entity of a row as ``kind:id`` (identity hints, not resolution)."""
    props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
    for key, kind in (("canonical_entity_id", "entity"), ("user_id", "user")):
        if row.get(key):
            return f"{kind}:{row[key]}"
    for key in ("agent_id", "agent_ref"):
        if row.get(key) or props.get(key):
            return f"agent:{row.get(key) or props.get(key)}"
    if row.get("anonymous_id"):
        return f"anon:{row['anonymous_id']}"
    if row.get("session_id"):
        return f"session:{row['session_id']}"
    return None


@dataclass
class Attribute:
    type: str
    value: str
    path: str
    extractor: str
    confidence: float

    @property
    def key(self) -> str:
        return f"{self.type}={self.value}"


@dataclass
class ExtractedEvent:
    event_id: str
    entity: Optional[str]
    ts: Optional[datetime]
    event_type: str
    source: str
    token: str
    outcome: Optional[str]
    amount: Optional[float]
    attributes: list[Attribute] = field(default_factory=list)
    counterparties: list[tuple[str, str]] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)


@dataclass
class FieldProfile:
    """Schema statistics for one ``(source, event_type, path)``."""

    path: str
    count: int = 0
    kinds: Counter = field(default_factory=Counter)
    semantic: Counter = field(default_factory=Counter)
    distinct: set = field(default_factory=set)
    distinct_overflow: bool = False
    whitespace: int = 0
    total_len: int = 0
    entities_by_value: dict = field(default_factory=lambda: defaultdict(set))

    def observe(self, value: Any, entity: Optional[str], tenant_id: str) -> None:
        self.count += 1
        kind = value_kind(value)
        self.kinds[kind] += 1
        if kind != "string":
            return
        s = value
        self.total_len += len(s)
        if " " in s.strip():
            self.whitespace += 1
        d = digest(tenant_id, "field", s)
        if len(self.distinct) < MAX_DISTINCT_TRACKED:
            self.distinct.add(d)
            if entity and len(self.entities_by_value) < MAX_DISTINCT_TRACKED:
                self.entities_by_value[d].add(entity)
        else:
            self.distinct_overflow = True

    @property
    def dominant_kind(self) -> str:
        return self.kinds.most_common(1)[0][0] if self.kinds else "null"

    def identifier_like(self) -> bool:
        """Does this field behave like an identifier nobody modelled?

        Strings, no whitespace, moderate length, neither constant nor unique
        per row, and at least one value reused by more than one entity (so it
        can actually link things)."""
        strings = self.kinds.get("string", 0)
        if strings < 5 or strings < 0.8 * self.count:
            return False
        if self.semantic and self.semantic.most_common(1)[0][0] in {"timestamp", "hash"}:
            return False
        if self.whitespace > 0.05 * strings:
            return False
        avg = self.total_len / max(strings, 1)
        if not 4 <= avg <= 128:
            return False
        if self.path.rsplit(".", 1)[-1].replace("[]", "").lower() in _CATEGORY_KEYS:
            return False
        ratio = len(self.distinct) / strings
        if not 0.02 <= ratio <= 0.95 and not self.distinct_overflow:
            return False
        if len(self.distinct) < 3:
            return False
        sizes = sorted((len(e) for e in self.entities_by_value.values()), reverse=True)
        total = sum(sizes) or 1
        if sizes and sizes[0] / total > 0.6:
            return False  # one value dominates: a default / category, not an identifier
        return any(n >= 2 for n in sizes)

    def to_dict(self) -> dict[str, Any]:
        strings = self.kinds.get("string", 0)
        return {
            "path": self.path,
            "count": self.count,
            "kinds": dict(self.kinds),
            "dominant_kind": self.dominant_kind,
            "semantic": dict(self.semantic),
            "distinct": len(self.distinct),
            "distinct_capped": self.distinct_overflow,
            "free_text_ratio": round(self.whitespace / strings, 3) if strings else 0.0,
            "identifier_like": self.identifier_like(),
        }


@dataclass
class ExtractionResult:
    events: list[ExtractedEvent]
    profiles: dict[str, dict[str, FieldProfile]]   # "source|event_type" -> path -> profile
    event_counts: Counter
    stats: dict[str, Any]

    def profile_summary(self) -> dict[str, Any]:
        return {
            group: {
                "events": self.event_counts[group],
                "fields": {p: prof.to_dict() for p, prof in sorted(paths.items())},
            }
            for group, paths in sorted(self.profiles.items())
        }

    def candidate_observations(self, tenant_id: str, limit: int = 5_000) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ev in self.events:
            for attr in ev.attributes:
                out.append({
                    "observation_id": "obs_" + hashlib.sha256(
                        f"{tenant_id}\x00{ev.event_id}\x00{attr.key}\x00{attr.path}".encode()
                    ).hexdigest()[:20],
                    "tenant_id": tenant_id,
                    "source_event_id": ev.event_id,
                    "entity": ev.entity,
                    "attribute_type": attr.type,
                    "attribute_value": attr.value,
                    "field_path": attr.path,
                    "extractor": attr.extractor,
                    "confidence": attr.confidence,
                    "claim_state": "inferred",
                    "occurred_at": ev.ts.isoformat() if ev.ts else None,
                })
                if len(out) >= limit:
                    return out
        return out


def _stored_value(tenant_id: str, attr_type: str, raw: str) -> str:
    if attr_type in SENSITIVE_TYPES or attr_type.startswith("field:"):
        return digest(tenant_id, attr_type, raw)
    if attr_type == "host":
        return host_of(raw) or raw.lower()
    if attr_type == "wallet":
        return raw.lower() if raw.startswith("0x") else raw
    return raw


def _counterparty(path: str, value: Any) -> Optional[tuple[str, str]]:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    last = path.rsplit(".", 1)[-1].replace("[]", "").lower()
    for key, relation in _COUNTERPARTY_KEYS:
        if last == key or last.startswith(key + "_") or last.endswith("_" + key):
            v = str(value).strip()
            if not v or len(v) > 256:
                return None
            if _EVM.fullmatch(v):
                return relation, f"wallet:{v.lower()}"
            kind = "agent" if relation == "SPAWNED_BY" or "agent" in last else (
                "user" if relation in ("DELEGATED_BY", "INVITED_BY") else "entity"
            )
            return relation, f"{kind}:{v}"
    return None


def _text_fields(row: dict[str, Any], leaves: Iterable[tuple[str, Any]]) -> list[tuple[str, str]]:
    out = []
    for path, value in leaves:
        if not isinstance(value, str) or len(value) < 12:
            continue
        last = path.rsplit(".", 1)[-1].replace("[]", "").lower()
        if (" " in value.strip() and len(value) >= 20) or any(k in last for k in _TEXT_KEYS):
            out.append((path, value))
    raw = row.get("text") or row.get("raw_text")
    if isinstance(raw, str) and raw.strip():
        out.append(("$text", raw))
    return out[:10]


def extract_events(rows: Iterable[dict[str, Any]], tenant_id: str) -> ExtractionResult:
    """Two passes: (1) flatten, type and profile every payload; (2) promote
    learned identifier fields into linkage attributes. Rows of other tenants
    are ignored, never mixed in."""
    profiles: dict[str, dict[str, FieldProfile]] = defaultdict(dict)
    event_counts: Counter = Counter()
    staged: list[tuple[ExtractedEvent, str, list[tuple[str, Any]]]] = []
    skipped = Counter()

    for row in rows:
        if not isinstance(row, dict):
            skipped["not_an_object"] += 1
            continue
        if row.get("tenant_id") not in (None, "", tenant_id):
            skipped["foreign_tenant"] += 1
            continue
        props = row.get("properties")
        if isinstance(props, str):
            props = {"$text": props}
        props = props if isinstance(props, dict) else {}
        event_type = str(row.get("event_type") or row.get("type") or row.get("event") or "unknown")[:120]
        source = str(row.get("source") or "unknown")[:80]
        group = f"{source}|{event_type}"
        event_counts[group] += 1
        entity = entity_of(row)
        ts = coerce_utc_lenient(row.get("occurred_at") or row.get("timestamp") or row.get("received_at"))
        leaves = flatten(props)
        attrs: list[Attribute] = []
        counterparties: list[tuple[str, str]] = []
        group_profiles = profiles[group]
        for path, value in leaves:
            prof = group_profiles.get(path)
            if prof is None:
                if len(group_profiles) >= MAX_LEAVES * 2:
                    continue
                prof = group_profiles[path] = FieldProfile(path=path)
            prof.observe(value, entity, tenant_id)
            cp = _counterparty(path, value)
            if cp and cp[1] != entity:
                counterparties.append(cp)
            if isinstance(value, str):
                typed = classify_value(value, path)
                if typed:
                    prof.semantic[typed[0]] += 1
                    attr_type, conf = typed
                    if attr_type in LINKAGE_TYPES:
                        raw = host_of(value) if attr_type == "host" else value
                        if raw:
                            attrs.append(Attribute(attr_type, _stored_value(tenant_id, attr_type, raw),
                                                   path, "json_semantic", conf))
        templates: list[str] = []
        for path, text in _text_fields(row, leaves):
            _template, tid = message_template(text)
            templates.append(tid)
            for attr_type, raw in text_tokens(text):
                attrs.append(Attribute(attr_type, _stored_value(tenant_id, attr_type, raw),
                                       path, "text_token", 0.6))
        outcome = outcome_of(event_type, props)
        token = event_type + (f"!{outcome}" if outcome else "")
        if not outcome and templates and any(k in event_type.lower() for k in ("error", "log", "exception", "message")):
            token = f"{event_type}#{templates[0]}"
        dedup: dict[str, Attribute] = {}
        for a in attrs:
            prev = dedup.get(a.key)
            if prev is None or a.confidence > prev.confidence:
                dedup[a.key] = a
        ev = ExtractedEvent(
            event_id=str(row.get("event_id") or row.get("id") or hashlib.sha256(
                repr(sorted(row.items(), key=lambda kv: str(kv[0]))).encode()).hexdigest()[:16]),
            entity=entity, ts=ts, event_type=event_type, source=source, token=token,
            outcome=outcome, amount=_amount_of(props), attributes=list(dedup.values()),
            counterparties=list(dict.fromkeys(counterparties))[:20], templates=templates,
        )
        staged.append((ev, group, leaves))

    learned: dict[str, set[str]] = {
        group: {path for path, prof in paths.items()
                if not prof.semantic and prof.identifier_like() and not path.endswith("_at")}
        for group, paths in profiles.items()
    }
    learned_attrs = 0
    for ev, group, leaves in staged:
        paths = learned.get(group) or set()
        if not paths:
            continue
        have = {a.path for a in ev.attributes}
        for path, value in leaves:
            if path in paths and path not in have and isinstance(value, str) and value.strip():
                attr_type = f"field:{path}"
                ev.attributes.append(Attribute(attr_type, _stored_value(tenant_id, attr_type, value),
                                               path, "learned_identifier", 0.55))
                learned_attrs += 1

    events = [ev for ev, _, _ in staged]
    return ExtractionResult(
        events=events,
        profiles=dict(profiles),
        event_counts=event_counts,
        stats={
            "rows": len(events),
            "skipped": dict(skipped),
            "with_entity": sum(1 for e in events if e.entity),
            "with_timestamp": sum(1 for e in events if e.ts),
            "attributes": sum(len(e.attributes) for e in events),
            "learned_identifier_fields": sorted({f"{g}:{p}" for g, ps in learned.items() for p in ps}),
            "learned_identifier_attributes": learned_attrs,
            "free_text_templates": len({t for e in events for t in e.templates}),
            "event_groups": len(event_counts),
        },
    )


def extract_payload(payload: Any, tenant_id: str, *, event_type: Optional[str] = None,
                    text: Optional[str] = None) -> dict[str, Any]:
    """Schema-on-read preview for one arbitrary payload (operator tooling)."""
    row: dict[str, Any] = {
        "tenant_id": tenant_id, "event_id": "preview", "event_type": event_type or "preview",
        "source": "preview", "occurred_at": datetime.now(timezone.utc).isoformat(),
        "properties": payload if isinstance(payload, dict) else {"value": payload},
    }
    if text:
        row["text"] = text
    result = extract_events([row], tenant_id)
    ev = result.events[0]
    templates = []
    for _path, t in _text_fields(row, flatten(row["properties"])):
        template, tid = message_template(t)
        templates.append({"template_id": tid, "template": template})
    return {
        "event_type": ev.event_type,
        "token": ev.token,
        "outcome": ev.outcome,
        "amount": ev.amount,
        "attributes": [
            {"type": a.type, "value": a.value, "path": a.path, "extractor": a.extractor,
             "confidence": a.confidence, "claim_state": "inferred"}
            for a in ev.attributes
        ],
        "counterparties": [{"relation": r, "entity": e} for r, e in ev.counterparties],
        "templates": templates,
        "fields": result.profile_summary().get(f"preview|{ev.event_type}", {}).get("fields", {}),
    }
