"""Google Workspace OpenID Connect, executed entirely on the backend.

Kyber uses the authorization-code flow with PKCE. The browser never receives
an ``id_token``, an ``access_token`` or a refresh token: it receives an opaque
server-side session cookie after the backend has already exchanged the code,
verified the token and resolved the workforce principal. Nothing about the
resulting authority is derivable from anything the browser holds.

Every validation below fails closed and names a distinct reason. There is no
path where a missing key, an unavailable JWT implementation or an unreadable
discovery document degrades into "accept anyway" — the absence of the means to
verify is itself a denial.

Google is the password authority. Kyber holds no second password, so account
recovery, MFA policy and suspension all live in Google Workspace, and a
suspended Google account cannot complete this flow at all.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from shared.logger.logger import get_logger, metrics

# Imported at module scope so a stubbed or absent implementation is detected
# once, explicitly, rather than surfacing as an attribute error mid-flow.
try:  # pragma: no cover - import shape differs only in constrained sandboxes
    import jwt as _jwt_module
except ImportError:  # pragma: no cover
    _jwt_module = None  # type: ignore[assignment]

logger = get_logger("aether.kyber.identity.oidc")

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

#: The only issuer values Google is permitted to assert.
ACCEPTED_ISSUERS: frozenset[str] = frozenset(
    {"https://accounts.google.com", "accounts.google.com"}
)

#: Clock skew tolerated on ``exp`` / ``iat``, in seconds.
CLOCK_LEEWAY_SECONDS = 120

#: Environments where a mock identity provider may be constructed at all.
MOCK_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"local", "dev", "test"})

DEFAULT_DISCOVERY_TTL_SECONDS = 3600
DEFAULT_TRANSACTION_TTL_SECONDS = 600

__all__ = [
    "ACCEPTED_ISSUERS",
    "CLOCK_LEEWAY_SECONDS",
    "GoogleOidcClient",
    "MockOidcProvider",
    "OidcConfig",
    "OidcError",
    "OidcIdentity",
    "OidcTransaction",
    "OidcTransactionStore",
    "get_oidc_client",
    "oidc_transaction_store",
    "reset_oidc_client_cache",
]


class OidcError(Exception):
    """A fail-closed OIDC rejection carrying a stable, non-disclosing reason."""

    def __init__(self, reason: str, message: Optional[str] = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


@dataclass(frozen=True)
class OidcIdentity:
    """A verified Google identity. Never carries a token or a credential."""

    google_subject: str
    email: str
    email_verified: bool
    display_name: Optional[str] = None
    hosted_domain: Optional[str] = None
    raw_claims: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OidcConfig:
    """Deployment configuration for the Google OIDC flow.

    Read from the environment here rather than from ``config/settings.py``:
    this module must be importable and testable without the full settings
    object, and the founder-bootstrap path needs the same values before any
    principal exists.
    """

    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    hosted_domain: Optional[str] = None
    discovery_url: str = GOOGLE_DISCOVERY_URL
    provider: str = "google"

    @classmethod
    def from_env(cls) -> "OidcConfig":
        hosted_domain = (os.getenv("KYBER_GOOGLE_HOSTED_DOMAIN") or "").strip()
        return cls(
            client_id=(os.getenv("KYBER_GOOGLE_CLIENT_ID") or "").strip(),
            client_secret=(os.getenv("KYBER_GOOGLE_CLIENT_SECRET") or "").strip(),
            redirect_uri=(os.getenv("KYBER_GOOGLE_REDIRECT_URI") or "").strip(),
            hosted_domain=hosted_domain or None,
            discovery_url=(
                os.getenv("KYBER_GOOGLE_DISCOVERY_URL") or GOOGLE_DISCOVERY_URL
            ).strip(),
            provider=(os.getenv("KYBER_OIDC_PROVIDER") or "google").strip().lower(),
        )


# ── Server-side state / nonce / PKCE storage ──────────────────────────────────

@dataclass
class OidcTransaction:
    """One in-flight login. Lives only between ``/auth/login`` and the callback."""

    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    created_at: float
    expires_at: float
    next_path: Optional[str] = None
    client_ip: Optional[str] = None


class OidcTransactionStore:
    """Single-use, TTL-bounded store for login state, nonce and PKCE verifier.

    In-memory is the correct scope here. A transaction is created by one
    request and consumed by the very next one from the same browser, minutes
    later at most; persisting it would add a durable record of an attempted
    login without adding any security. Consuming a state deletes it, so a
    replayed callback finds nothing and is denied.
    """

    def __init__(self, *, ttl_seconds: int = DEFAULT_TRANSACTION_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._transactions: dict[str, OidcTransaction] = {}

    def start(
        self,
        *,
        redirect_uri: str,
        next_path: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> OidcTransaction:
        self.purge_expired()
        now = time.time()
        verifier = _generate_code_verifier()
        transaction = OidcTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=verifier,
            code_challenge=_code_challenge(verifier),
            redirect_uri=redirect_uri,
            created_at=now,
            expires_at=now + self._ttl,
            next_path=next_path,
            client_ip=client_ip,
        )
        self._transactions[transaction.state] = transaction
        return transaction

    def consume(self, state: str) -> Optional[OidcTransaction]:
        """Return and delete the transaction for ``state``, if it is still live."""
        self.purge_expired()
        transaction = self._transactions.pop(state, None)
        if transaction is None:
            return None
        if transaction.expires_at <= time.time():
            return None
        return transaction

    def purge_expired(self) -> int:
        now = time.time()
        stale = [s for s, t in self._transactions.items() if t.expires_at <= now]
        for state in stale:
            self._transactions.pop(state, None)
        return len(stale)

    def clear(self) -> None:
        self._transactions.clear()

    def __len__(self) -> int:
        return len(self._transactions)


oidc_transaction_store = OidcTransactionStore()


def _generate_code_verifier() -> str:
    # RFC 7636 allows 43..128 characters from the unreserved set.
    return secrets.token_urlsafe(64)[:128]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ── Google client ─────────────────────────────────────────────────────────────

class GoogleOidcClient:
    """Authorization-code + PKCE client for Google Workspace."""

    def __init__(
        self,
        config: Optional[OidcConfig] = None,
        *,
        discovery_ttl_seconds: int = DEFAULT_DISCOVERY_TTL_SECONDS,
        http_timeout_seconds: float = 10.0,
    ) -> None:
        self.config = config or OidcConfig.from_env()
        self._discovery_ttl = discovery_ttl_seconds
        self._http_timeout = http_timeout_seconds
        self._discovery: Optional[dict[str, Any]] = None
        self._discovery_fetched_at: float = 0.0
        self._jwks: Optional[dict[str, Any]] = None
        self._jwks_fetched_at: float = 0.0

    @property
    def provider_name(self) -> str:
        return "google"

    # ── Discovery and keys ────────────────────────────────────────────────────

    async def discovery_document(self, *, force: bool = False) -> dict[str, Any]:
        """Fetch and cache Google's OpenID configuration."""
        now = time.time()
        if (
            not force
            and self._discovery is not None
            and (now - self._discovery_fetched_at) < self._discovery_ttl
        ):
            return self._discovery
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.get(self.config.discovery_url)
                response.raise_for_status()
                document = response.json()
        except Exception as exc:  # noqa: BLE001 - every failure is one denial
            raise OidcError("discovery_unavailable", str(exc)) from exc
        if not isinstance(document, dict):
            raise OidcError("discovery_unavailable", "discovery document was not an object")
        self._discovery = document
        self._discovery_fetched_at = now
        return document

    async def jwks(self, *, force: bool = False) -> dict[str, Any]:
        """Fetch and cache the signing keys named by the discovery document."""
        now = time.time()
        if (
            not force
            and self._jwks is not None
            and (now - self._jwks_fetched_at) < self._discovery_ttl
        ):
            return self._jwks
        try:
            document = await self.discovery_document()
            jwks_uri = document.get("jwks_uri") or GOOGLE_JWKS_URI
        except OidcError:
            jwks_uri = GOOGLE_JWKS_URI
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.get(jwks_uri)
                response.raise_for_status()
                keys = response.json()
        except Exception as exc:  # noqa: BLE001
            raise OidcError("jwks_unavailable", str(exc)) from exc
        if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list):
            raise OidcError("jwks_unavailable", "JWKS document had no key set")
        self._jwks = keys
        self._jwks_fetched_at = now
        return keys

    # ── Authorization request ─────────────────────────────────────────────────

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        """Build the Google consent URL for this login attempt."""
        if not self.config.client_id:
            raise OidcError("client_not_configured", "KYBER_GOOGLE_CLIENT_ID is not set")
        if not redirect_uri:
            raise OidcError("redirect_uri_missing", "a redirect_uri is required")
        endpoint = GOOGLE_AUTHORIZATION_ENDPOINT
        if self._discovery:
            endpoint = self._discovery.get("authorization_endpoint") or endpoint
        params: dict[str, str] = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        if self.config.hosted_domain:
            # A hint only. The `hd` claim is what is actually enforced.
            params["hd"] = self.config.hosted_domain
        return f"{endpoint}?{urlencode(params)}"

    # ── Code exchange ─────────────────────────────────────────────────────────

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: Optional[str] = None,
    ) -> OidcIdentity:
        """Exchange an authorization code for a verified identity."""
        if not code or not code_verifier:
            raise OidcError("code_missing", "an authorization code and verifier are required")
        if not self.config.client_id or not self.config.client_secret:
            raise OidcError("client_not_configured", "Google OIDC client is not configured")

        try:
            document = await self.discovery_document()
            token_endpoint = document.get("token_endpoint") or GOOGLE_TOKEN_ENDPOINT
        except OidcError:
            token_endpoint = GOOGLE_TOKEN_ENDPOINT

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": redirect_uri,
        }
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.post(token_endpoint, data=payload)
        except Exception as exc:  # noqa: BLE001
            raise OidcError("token_endpoint_unavailable", str(exc)) from exc
        if response.status_code >= 400:
            metrics.increment("kyber_oidc_failure_total", labels={"reason": "code_exchange"})
            raise OidcError("code_exchange_failed", f"HTTP {response.status_code}")

        body = response.json()
        id_token = body.get("id_token") if isinstance(body, dict) else None
        if not id_token:
            raise OidcError("id_token_missing", "token response carried no id_token")

        claims = await self.verify_id_token(id_token, nonce=nonce)
        identity = self.identity_from_claims(claims)
        metrics.increment("kyber_oidc_success_total")
        return identity

    # ── Verification ──────────────────────────────────────────────────────────

    async def verify_id_token(
        self, id_token: str, *, nonce: Optional[str] = None
    ) -> dict[str, Any]:
        """Verify the ID token signature, then its claims. Both must pass."""
        claims = await self._verify_signature(id_token)
        self.validate_claims(claims, nonce=nonce)
        return claims

    async def _verify_signature(self, id_token: str) -> dict[str, Any]:
        """Verify the RS256 signature against the JWKS key matching ``kid``.

        A stubbed or missing ``jwt`` implementation is a denial. It must never
        become a silent bypass, so the capability check happens before any use
        and raises its own reason.
        """
        jwt = _require_jwt()
        try:
            header = jwt.get_unverified_header(id_token)
        except Exception as exc:  # noqa: BLE001
            raise OidcError("id_token_malformed", str(exc)) from exc
        kid = header.get("kid") if isinstance(header, dict) else None
        if not kid:
            raise OidcError("id_token_kid_missing", "id_token header carried no kid")

        key_set = await self.jwks()
        jwk = _select_jwk(key_set, kid)
        if jwk is None:
            # A rotated key is the common cause; refresh once, then give up.
            key_set = await self.jwks(force=True)
            jwk = _select_jwk(key_set, kid)
        if jwk is None:
            raise OidcError("signing_key_unknown", "no JWKS key matched the id_token kid")

        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
        except Exception as exc:  # noqa: BLE001
            raise OidcError("signing_key_unusable", str(exc)) from exc

        try:
            claims = jwt.decode(
                id_token,
                public_key,
                algorithms=[str(jwk.get("alg") or header.get("alg") or "RS256")],
                audience=self.config.client_id,
                issuer="https://accounts.google.com",
                leeway=CLOCK_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001
            metrics.increment("kyber_oidc_failure_total", labels={"reason": "signature"})
            raise OidcError("id_token_signature_invalid", str(exc)) from exc
        if not isinstance(claims, dict):
            raise OidcError("id_token_malformed", "decoded id_token was not a claim set")
        return claims

    def validate_claims(
        self,
        claims: dict[str, Any],
        *,
        nonce: Optional[str] = None,
        at: Optional[float] = None,
    ) -> dict[str, Any]:
        """Validate an ID token's claims independently of its signature.

        Kept separate from signature verification so the policy is testable and
        auditable on its own. Both halves run on every real login.
        """
        now = at if at is not None else time.time()

        issuer = str(claims.get("iss") or "")
        if issuer not in ACCEPTED_ISSUERS:
            self._deny("issuer_invalid")

        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        expected = self.config.client_id
        if not expected:
            self._deny("client_not_configured")
        if expected not in [str(a) for a in audiences if a is not None]:
            self._deny("audience_invalid")

        exp = _as_epoch(claims.get("exp"))
        if exp is None:
            self._deny("expiry_missing")
        elif exp + CLOCK_LEEWAY_SECONDS < now:
            self._deny("token_expired")

        iat = _as_epoch(claims.get("iat"))
        if iat is None:
            self._deny("issued_at_missing")
        elif iat - CLOCK_LEEWAY_SECONDS > now:
            self._deny("token_not_yet_valid")

        if nonce is not None:
            presented = str(claims.get("nonce") or "")
            if not presented or not secrets.compare_digest(presented, nonce):
                self._deny("nonce_mismatch")

        if claims.get("email_verified") is not True:
            self._deny("email_unverified")
        if not str(claims.get("email") or "").strip():
            self._deny("email_missing")
        if not str(claims.get("sub") or "").strip():
            self._deny("subject_missing")

        if self.config.hosted_domain:
            if str(claims.get("hd") or "") != self.config.hosted_domain:
                self._deny("hosted_domain_mismatch")

        return claims

    @staticmethod
    def identity_from_claims(claims: dict[str, Any]) -> OidcIdentity:
        return OidcIdentity(
            google_subject=str(claims.get("sub") or ""),
            email=str(claims.get("email") or "").strip().lower(),
            email_verified=claims.get("email_verified") is True,
            display_name=(claims.get("name") or None),
            hosted_domain=(claims.get("hd") or None),
            raw_claims=dict(claims),
        )

    @staticmethod
    def _deny(reason: str) -> None:
        metrics.increment("kyber_oidc_failure_total", labels={"reason": reason})
        logger.warning(f"kyber oidc rejected reason={reason}")
        raise OidcError(reason)


def _require_jwt() -> Any:
    """Return a JWT implementation that can actually verify RS256, or deny.

    ``tests/conftest.py`` substitutes a namespace stub for ``jwt`` when the
    cffi C-extension is unavailable. That stub can neither read a header nor
    verify a signature, so treating it as usable would turn an unverifiable
    token into an accepted one.
    """
    module = _jwt_module
    if module is None:
        raise OidcError("jwt_unavailable", "PyJWT is not installed")
    algorithms = getattr(module, "algorithms", None)
    if (
        not hasattr(module, "get_unverified_header")
        or algorithms is None
        or not hasattr(algorithms, "RSAAlgorithm")
    ):
        raise OidcError(
            "jwt_unavailable",
            "the installed jwt module cannot verify RS256 signatures",
        )
    return module


def _select_jwk(key_set: dict[str, Any], kid: str) -> Optional[dict[str, Any]]:
    for key in key_set.get("keys", []):
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


def _as_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Mock provider ─────────────────────────────────────────────────────────────

class MockOidcProvider:
    """A local/test stand-in with the same interface as :class:`GoogleOidcClient`.

    It refuses to exist outside ``local``/``dev``/``test``. A mock identity
    provider reachable in production would be a complete authentication bypass,
    so the guard is a constructor error rather than a runtime branch.
    """

    def __init__(
        self,
        config: Optional[OidcConfig] = None,
        *,
        environment: Optional[str] = None,
    ) -> None:
        env = (environment or os.getenv("AETHER_ENV") or "local").strip().lower()
        if env not in MOCK_ALLOWED_ENVIRONMENTS:
            raise RuntimeError(
                f"MockOidcProvider cannot be constructed in AETHER_ENV={env!r}; "
                "it is permitted only in local, dev and test"
            )
        self.environment = env
        self.config = config or OidcConfig.from_env()
        self._identities: dict[str, OidcIdentity] = {}

    @property
    def provider_name(self) -> str:
        return "mock"

    def register_identity(
        self,
        code: str,
        *,
        google_subject: str,
        email: str,
        display_name: Optional[str] = None,
        email_verified: bool = True,
        hosted_domain: Optional[str] = None,
    ) -> OidcIdentity:
        """Seed the identity a given authorization code will resolve to."""
        identity = OidcIdentity(
            google_subject=google_subject,
            email=email.strip().lower(),
            email_verified=email_verified,
            display_name=display_name,
            hosted_domain=hosted_domain,
            raw_claims={
                "iss": "https://accounts.google.com",
                "sub": google_subject,
                "email": email.strip().lower(),
                "email_verified": email_verified,
                "name": display_name,
                "hd": hosted_domain,
            },
        )
        self._identities[code] = identity
        return identity

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        params = {
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
            "mock": "1",
        }
        return f"/v1/kyber/auth/mock-consent?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: Optional[str] = None,
    ) -> OidcIdentity:
        identity = self._identities.get(code)
        if identity is None:
            raise OidcError("code_exchange_failed", "no mock identity for that code")
        if not identity.email_verified:
            raise OidcError("email_unverified")
        if self.config.hosted_domain and identity.hosted_domain != self.config.hosted_domain:
            raise OidcError("hosted_domain_mismatch")
        return identity


# ── Selection ─────────────────────────────────────────────────────────────────

_client_cache: dict[str, Any] = {}


def get_oidc_client() -> Any:
    """Return the configured OIDC client for this deployment.

    The mock provider is selected only when ``KYBER_OIDC_PROVIDER=mock`` *and*
    the environment permits it; the provider's own constructor enforces the
    second half, so a misconfigured production deployment fails loudly at
    selection rather than authenticating anyone.
    """
    config = OidcConfig.from_env()
    env = (os.getenv("AETHER_ENV") or "local").strip().lower()
    cache_key = f"{config.provider}:{env}:{config.client_id}:{config.hosted_domain}"
    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached
    client: Any
    if config.provider == "mock":
        client = MockOidcProvider(config, environment=env)
    else:
        client = GoogleOidcClient(config)
    _client_cache[cache_key] = client
    return client


def reset_oidc_client_cache() -> None:
    """Drop the memoised client. Used by tests and by config reloads."""
    _client_cache.clear()
