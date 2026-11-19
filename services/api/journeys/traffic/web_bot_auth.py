"""Web Bot Auth: verify HTTP Message Signatures (RFC 9421) from signing agents.

Agents that support Web Bot Auth (draft-meunier-web-bot-auth-architecture)
sign their requests with an Ed25519 key published at
``<signature-agent>/.well-known/http-message-signatures-directory``. A valid
signature proves the request came from the holder of that key, whatever its
User-Agent says. This is the only way to verify an agent driving a normal
browser (standard Chrome user-agent, no WebDriver flag).

Keys come from ``web_bot_auth_directories.json``, a reviewed snapshot written
by ``scripts/refresh_web_bot_auth_directories.py``; nothing is fetched at
request time. A well-formed signature from a signer missing from the snapshot
is reported as ``web_bot_auth_unknown_signer`` and is never verified.

Output carries the verdict, signer origin and key id only; no header values,
signatures or IP addresses.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from urllib.parse import urlsplit

DIRECTORIES_PATH = Path(__file__).with_name("web_bot_auth_directories.json")

WBA_TAG = "web-bot-auth"
VERIFIED = "web_bot_auth_verified"
UNKNOWN_SIGNER = "web_bot_auth_unknown_signer"
INVALID = "web_bot_auth_invalid"
EXPIRED = "web_bot_auth_expired"
REPLAY = "web_bot_auth_replay"

CLOCK_SKEW_SECONDS = 60
MAX_VALIDITY_SECONDS = 24 * 3600
_NONCE_CACHE_SIZE = 50_000


# ── RFC 8941 structured fields (the subset RFC 9421 signatures use) ─────────


class Token(str):
    """An sf-token (serialized without quotes)."""


BareItem = Union[str, int, float, bool, bytes, Token]


@dataclass(frozen=True)
class Item:
    value: Any  # BareItem, or list[Item] for an inner list
    params: tuple[tuple[str, BareItem], ...] = ()

    def param(self, key: str) -> Any:
        for k, v in self.params:
            if k == key:
                return v
        return None


class StructuredFieldError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def _peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def _sp(self) -> None:
        while self._peek() == " ":
            self.i += 1

    def _ows(self) -> None:
        while self._peek() in (" ", "\t"):
            self.i += 1

    def key(self) -> str:
        c = self._peek()
        if not (c.islower() or c == "*"):
            raise StructuredFieldError("bad key")
        start = self.i
        while self._peek() and (self._peek().islower() or self._peek().isdigit() or self._peek() in "_-.*"):
            self.i += 1
        return self.s[start:self.i]

    def bare_item(self) -> BareItem:
        c = self._peek()
        if c == '"':
            return self._string()
        if c == ":":
            return self._bytes()
        if c == "?":
            self.i += 1
            v = self._peek()
            if v not in ("0", "1"):
                raise StructuredFieldError("bad boolean")
            self.i += 1
            return v == "1"
        if c == "-" or c.isdigit():
            return self._number()
        if c.isalpha() or c == "*":
            start = self.i
            while self._peek() and (self._peek().isalnum() or self._peek() in "!#$%&'*+-.^_`|~:/"):
                self.i += 1
            return Token(self.s[start:self.i])
        raise StructuredFieldError("bad item")

    def _string(self) -> str:
        self.i += 1
        out = []
        while True:
            c = self._peek()
            if not c:
                raise StructuredFieldError("unterminated string")
            self.i += 1
            if c == "\\":
                n = self._peek()
                if n not in ('"', "\\"):
                    raise StructuredFieldError("bad escape")
                out.append(n)
                self.i += 1
            elif c == '"':
                return "".join(out)
            elif ord(c) < 0x20 or ord(c) > 0x7E:
                raise StructuredFieldError("bad string char")
            else:
                out.append(c)

    def _bytes(self) -> bytes:
        self.i += 1
        end = self.s.find(":", self.i)
        if end < 0:
            raise StructuredFieldError("unterminated byte sequence")
        raw = self.s[self.i:end]
        self.i = end + 1
        try:
            return base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as exc:
            raise StructuredFieldError("bad base64") from exc

    def _number(self) -> Union[int, float]:
        start = self.i
        if self._peek() == "-":
            self.i += 1
        while self._peek().isdigit() or self._peek() == ".":
            self.i += 1
        text = self.s[start:self.i]
        try:
            return float(text) if "." in text else int(text)
        except ValueError as exc:
            raise StructuredFieldError("bad number") from exc

    def params(self) -> tuple[tuple[str, BareItem], ...]:
        out: list[tuple[str, BareItem]] = []
        while self._peek() == ";":
            self.i += 1
            self._sp()
            k = self.key()
            v: BareItem = True
            if self._peek() == "=":
                self.i += 1
                v = self.bare_item()
            out.append((k, v))
        return tuple(out)

    def item_or_inner_list(self) -> Item:
        if self._peek() == "(":
            self.i += 1
            items: list[Item] = []
            while True:
                self._sp()
                if self._peek() == ")":
                    self.i += 1
                    return Item(items, self.params())
                items.append(Item(self.bare_item(), self.params()))
                if self._peek() not in (" ", ")"):
                    raise StructuredFieldError("bad inner list")
        return Item(self.bare_item(), self.params())

    def dictionary(self) -> "OrderedDict[str, Item]":
        out: "OrderedDict[str, Item]" = OrderedDict()
        self._sp()
        while self.i < len(self.s):
            k = self.key()
            if self._peek() == "=":
                self.i += 1
                out[k] = self.item_or_inner_list()
            else:
                out[k] = Item(True, self.params())
            self._ows()
            if self.i >= len(self.s):
                break
            if self._peek() != ",":
                raise StructuredFieldError("expected comma")
            self.i += 1
            self._ows()
            if self.i >= len(self.s):
                raise StructuredFieldError("trailing comma")
        return out


def parse_dictionary(text: str) -> "OrderedDict[str, Item]":
    return _Parser(text.strip()).dictionary()


def parse_item(text: str) -> Item:
    p = _Parser(text.strip())
    item = p.item_or_inner_list()
    if p.i != len(p.s):
        raise StructuredFieldError("trailing characters")
    return item


def _ser_bare(v: BareItem) -> str:
    if isinstance(v, bool):
        return "?1" if v else "?0"
    if isinstance(v, Token):
        return str(v)
    if isinstance(v, bytes):
        return ":" + base64.b64encode(v).decode() + ":"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ser_params(params: tuple[tuple[str, BareItem], ...]) -> str:
    return "".join(f";{k}" if v is True else f";{k}={_ser_bare(v)}" for k, v in params)


def serialize_item(item: Item) -> str:
    if isinstance(item.value, list):
        inner = " ".join(_ser_bare(i.value) + _ser_params(i.params) for i in item.value)
        return f"({inner}){_ser_params(item.params)}"
    return _ser_bare(item.value) + _ser_params(item.params)


# ── Key directory snapshot ──────────────────────────────────────────────────


@dataclass(frozen=True)
class _Key:
    signer: str
    kid: str
    public_key: Any
    nbf: Optional[float]
    exp: Optional[float]


@dataclass(frozen=True)
class _Signer:
    origin: str
    provider: str
    product: str
    actor_type: str


def _epoch_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v / 1000.0 if v > 1e11 else v  # some directories publish milliseconds


def normalize_origin(value: str) -> Optional[str]:
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    default = (parts.scheme == "https" and parts.port in (None, 443)) or (
        parts.scheme == "http" and parts.port in (None, 80)
    )
    return f"{parts.scheme}://{host}" if default else f"{parts.scheme}://{host}:{parts.port}"


@lru_cache(maxsize=1)
def _load_directories() -> tuple[dict[str, _Signer], dict[str, _Key]]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        raw = json.loads(DIRECTORIES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    signers: dict[str, _Signer] = {}
    keys: dict[str, _Key] = {}
    for origin, entry in (raw.get("signers") or {}).items():
        norm = normalize_origin(origin)
        if not norm:
            continue
        signers[norm] = _Signer(
            origin=norm,
            provider=str(entry.get("provider") or ""),
            product=str(entry.get("product") or ""),
            actor_type=str(entry.get("actor_type") or "agent"),
        )
        for k in entry.get("keys") or []:
            try:
                x = base64.urlsafe_b64decode(k["x"] + "=" * (-len(k["x"]) % 4))
                pub = Ed25519PublicKey.from_public_bytes(x)
            except (KeyError, ValueError, TypeError):
                continue
            keys[str(k["kid"])] = _Key(norm, str(k["kid"]), pub, _epoch_seconds(k.get("nbf")), _epoch_seconds(k.get("exp")))
    return signers, keys


# ── Replay guard (per process; best effort across replicas) ─────────────────

_nonce_lock = threading.Lock()
_seen_nonces: "OrderedDict[tuple[str, str], float]" = OrderedDict()


def _is_replay(kid: str, nonce: str, expires: float, now: float) -> bool:
    with _nonce_lock:
        while _seen_nonces:
            oldest_key, oldest_exp = next(iter(_seen_nonces.items()))
            if oldest_exp >= now and len(_seen_nonces) < _NONCE_CACHE_SIZE:
                break
            _seen_nonces.popitem(last=False)
        key = (kid, nonce)
        if key in _seen_nonces:
            return True
        _seen_nonces[key] = expires
        return False


def _reset_replay_cache_for_tests() -> None:
    with _nonce_lock:
        _seen_nonces.clear()


# ── Verification ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignedRequest:
    """What the server observed about the request being verified."""

    method: str
    authority: str  # host[:port] the request was addressed to
    path: str
    scheme: str = "https"
    query: str = ""
    headers: Mapping[str, str] = None  # type: ignore[assignment]


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    if value is None:
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
    return value


def _normalize_authority(authority: str, scheme: str) -> str:
    a = authority.strip().lower()
    if scheme == "https" and a.endswith(":443"):
        a = a[:-4]
    elif scheme == "http" and a.endswith(":80"):
        a = a[:-3]
    return a


def _component_value(component: Item, req: SignedRequest) -> Optional[str]:
    name = component.value
    if not isinstance(name, str) or isinstance(name, Token):
        return None
    if name == "@authority":
        return _normalize_authority(req.authority, req.scheme)
    if name == "@method":
        return req.method.upper()
    if name == "@path":
        return req.path or "/"
    if name == "@scheme":
        return req.scheme.lower()
    if name == "@query":
        return "?" + (req.query or "")
    if name == "@target-uri":
        q = f"?{req.query}" if req.query else ""
        return f"{req.scheme.lower()}://{_normalize_authority(req.authority, req.scheme)}{req.path or '/'}{q}"
    if name.startswith("@"):
        return None  # unsupported derived component
    raw = _header(req.headers, name)
    if raw is None:
        return None
    member_key = component.param("key")
    if member_key is not None:
        try:
            member = parse_dictionary(raw).get(str(member_key))
        except StructuredFieldError:
            return None
        return serialize_item(member) if member is not None else None
    if component.params:
        return None  # other component parameters (sf, bs, req, tr) are not supported
    return raw.strip()


def _signature_agent(req: SignedRequest, label: str, components: list[Item]) -> Optional[str]:
    raw = _header(req.headers, "Signature-Agent")
    if not raw:
        return None
    for c in components:
        if c.value == "signature-agent" and c.param("key") is not None:
            try:
                member = parse_dictionary(raw).get(str(c.param("key")))
            except StructuredFieldError:
                return None
            return normalize_origin(member.value) if member and isinstance(member.value, str) else None
    try:
        item = parse_item(raw)
        if isinstance(item.value, str) and not isinstance(item.value, Token):
            return normalize_origin(item.value)
    except StructuredFieldError:
        pass
    try:  # dictionary form without a key parameter: prefer the signature's own label
        members = parse_dictionary(raw)
        member = members.get(label) or (next(iter(members.values())) if len(members) == 1 else None)
        if member is not None and isinstance(member.value, str):
            return normalize_origin(member.value)
    except StructuredFieldError:
        pass
    return None


def verify_web_bot_auth(req: SignedRequest, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Verify a Web Bot Auth signature; ``None`` when the request carries none."""
    sig_input = _header(req.headers, "Signature-Input")
    sig_header = _header(req.headers, "Signature")
    if not sig_input or not sig_header:
        return None
    now = time.time() if now is None else now
    try:
        inputs = parse_dictionary(sig_input)
        signatures = parse_dictionary(sig_header)
    except StructuredFieldError:
        return {"verification": INVALID, "reason": "malformed_signature_headers"}

    label = next((k for k, v in inputs.items() if v.param("tag") == WBA_TAG), None)
    if label is None:
        return None  # an HTTP message signature, but not Web Bot Auth
    params_item = inputs[label]
    sig_item = signatures.get(label)
    if not isinstance(params_item.value, list) or sig_item is None or not isinstance(sig_item.value, bytes):
        return {"verification": INVALID, "reason": "missing_signature"}

    components: list[Item] = params_item.value
    kid = params_item.param("keyid")
    created = params_item.param("created")
    expires = params_item.param("expires")
    alg = params_item.param("alg")
    nonce = params_item.param("nonce")
    signer_origin = _signature_agent(req, label, components)
    base_result: dict[str, Any] = {"signature_agent": signer_origin, "keyid": kid if isinstance(kid, str) else None}

    names = [c.value for c in components]
    if "@authority" not in names:
        return {**base_result, "verification": INVALID, "reason": "authority_not_covered"}
    if _header(req.headers, "Signature-Agent") and "signature-agent" not in names:
        return {**base_result, "verification": INVALID, "reason": "signature_agent_not_covered"}
    if not isinstance(kid, str) or not isinstance(created, int) or not isinstance(expires, int):
        return {**base_result, "verification": INVALID, "reason": "missing_parameters"}
    if alg is not None and alg != "ed25519":
        return {**base_result, "verification": INVALID, "reason": "unsupported_alg"}
    if expires < created or expires - created > MAX_VALIDITY_SECONDS:
        return {**base_result, "verification": INVALID, "reason": "bad_validity_window"}
    if created > now + CLOCK_SKEW_SECONDS or expires < now - CLOCK_SKEW_SECONDS:
        return {**base_result, "verification": EXPIRED}

    signers, keys = _load_directories()
    key = keys.get(kid)
    if key is None or (signer_origin is not None and key.signer != signer_origin):
        return {**base_result, "verification": UNKNOWN_SIGNER}
    if (key.nbf is not None and now + CLOCK_SKEW_SECONDS < key.nbf) or (
        key.exp is not None and now - CLOCK_SKEW_SECONDS > key.exp
    ):
        return {**base_result, "verification": EXPIRED, "reason": "key_not_valid_now"}

    lines = []
    for c in components:
        value = _component_value(c, req)
        if value is None:
            return {**base_result, "verification": INVALID, "reason": "component_unavailable"}
        lines.append(f"{serialize_item(Item(c.value, c.params))}: {value}")
    lines.append(f'"@signature-params": {serialize_item(params_item)}')
    signature_base = "\n".join(lines).encode()

    from cryptography.exceptions import InvalidSignature

    try:
        key.public_key.verify(sig_item.value, signature_base)
    except InvalidSignature:
        return {**base_result, "verification": INVALID, "reason": "bad_signature"}

    if isinstance(nonce, str) and _is_replay(kid, nonce, float(expires), now):
        return {**base_result, "verification": REPLAY}

    signer = signers[key.signer]
    return {
        "verification": VERIFIED,
        "signature_agent": signer.origin,
        "keyid": kid,
        "provider": signer.provider,
        "product": signer.product,
        "actor_type": signer.actor_type,
    }


def verify_starlette_request(request: Any, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Verify an incoming ASGI/Starlette request.

    The authority and scheme are the ones the request was addressed to: the
    ``Host`` header, or ``X-Forwarded-Host`` / ``X-Forwarded-Proto`` only when the
    direct peer is a configured trusted proxy (the same rule as client-IP
    resolution, so a client cannot choose the authority it is verified against).
    """
    headers = getattr(request, "headers", None) or {}
    if not _header(headers, "Signature-Input"):
        return None
    url = getattr(request, "url", None)
    scheme = getattr(url, "scheme", None) or "https"
    authority = _header(headers, "Host") or getattr(url, "netloc", "") or ""
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None) if client else None
    if peer:
        from ingestion.ingestion.context_enricher import _is_trusted_proxy

        if _is_trusted_proxy(peer):
            fwd_host = _header(headers, "X-Forwarded-Host")
            fwd_proto = _header(headers, "X-Forwarded-Proto")
            if fwd_host:
                authority = fwd_host.split(",")[0].strip()
            if fwd_proto:
                scheme = fwd_proto.split(",")[0].strip().lower()
    signed = SignedRequest(
        method=str(getattr(request, "method", "GET")),
        authority=authority,
        path=getattr(url, "path", "/") or "/",
        scheme=scheme,
        query=getattr(url, "query", "") or "",
        headers=headers,
    )
    return verify_web_bot_auth(signed, now=now)


__all__ = [
    "EXPIRED",
    "INVALID",
    "REPLAY",
    "SignedRequest",
    "UNKNOWN_SIGNER",
    "VERIFIED",
    "parse_dictionary",
    "serialize_item",
    "verify_starlette_request",
    "verify_web_bot_auth",
]
