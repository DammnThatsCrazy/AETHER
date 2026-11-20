"""Google Play Integrity verdict decoding and evaluation.

The Android SDK requests an integrity token with Aether's single-use challenge
as its nonce. The server decodes it through Google
(``playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken``) with the
tenant-configured service account, then checks:

- the request package is allowed and ``nonce`` / ``requestHash`` equals the
  challenge, issued within the challenge TTL;
- ``appIntegrity.appRecognitionVerdict`` is ``PLAY_RECOGNIZED`` for that package
  (and, when configured, the signing-certificate digest matches);
- ``deviceIntegrity.deviceRecognitionVerdict`` grades the device.

The HTTP transport is injectable; tests never contact Google.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

SCOPE = "https://www.googleapis.com/auth/playintegrity"
DECODE_URL = "https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken"

#: (method, url, headers, form_or_json, is_form) -> (status, json_body)
Transport = Callable[[str, str, dict[str, str], dict[str, Any], bool], Awaitable[tuple[int, dict[str, Any]]]]


class PlayIntegrityError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PlayIntegrityResult:
    verdict: str  # verified | basic | virtual | failed
    package_name: str
    reasons: tuple[str, ...]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def service_account_assertion(account: dict[str, Any], now: Optional[int] = None) -> str:
    """RS256 JWT-bearer assertion for Google's OAuth token endpoint."""
    now = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if account.get("private_key_id"):
        header["kid"] = account["private_key_id"]
    claims = {
        "iss": account["client_email"],
        "scope": SCOPE,
        "aud": account.get("token_uri") or "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    key = serialization.load_pem_private_key(account["private_key"].encode(), password=None)
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]
    return f"{signing_input}.{_b64url(signature)}"


async def default_transport(method, url, headers, payload, is_form):  # pragma: no cover - network
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        if is_form:
            resp = await client.request(method, url, headers=headers, data=payload)
        else:
            resp = await client.request(method, url, headers=headers, json=payload)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body


async def decode_token(
    integrity_token: str,
    package_name: str,
    service_account_json: str,
    transport: Transport = default_transport,
) -> dict[str, Any]:
    """Return Google's ``tokenPayloadExternal`` for one integrity token."""
    try:
        account = json.loads(service_account_json)
        assertion = service_account_assertion(account)
    except (ValueError, KeyError, TypeError) as exc:
        raise PlayIntegrityError("service_account_invalid") from exc
    token_uri = account.get("token_uri") or "https://oauth2.googleapis.com/token"
    status, body = await transport(
        "POST", token_uri, {}, {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}, True,
    )
    access_token = body.get("access_token") if status == 200 else None
    if not access_token:
        raise PlayIntegrityError("google_auth_failed")
    status, body = await transport(
        "POST", DECODE_URL.format(package=package_name),
        {"Authorization": f"Bearer {access_token}"}, {"integrity_token": integrity_token}, False,
    )
    payload = body.get("tokenPayloadExternal") if status == 200 else None
    if not isinstance(payload, dict):
        raise PlayIntegrityError("decode_failed")
    return payload


def evaluate_payload(
    payload: dict[str, Any],
    *,
    challenge: str,
    allowed_packages: Iterable[str],
    certificate_digests: Iterable[str] = (),
    issued_at_ms: int,
    max_age_ms: int,
) -> PlayIntegrityResult:
    """Grade a decoded payload. Raises on a request mismatch (wrong nonce/package)."""
    request = payload.get("requestDetails") or {}
    package = request.get("requestPackageName")
    allowed = set(allowed_packages)
    if package not in allowed:
        raise PlayIntegrityError("package_not_allowed")
    if challenge not in (request.get("nonce"), request.get("requestHash")):
        raise PlayIntegrityError("nonce_mismatch")
    ts = request.get("timestampMillis")
    try:
        ts_ms = int(ts)
    except (TypeError, ValueError) as exc:
        raise PlayIntegrityError("timestamp_missing") from exc
    if ts_ms < issued_at_ms - 60_000 or ts_ms > issued_at_ms + max_age_ms + 60_000:
        raise PlayIntegrityError("timestamp_out_of_window")

    reasons: list[str] = []
    app = payload.get("appIntegrity") or {}
    app_ok = app.get("appRecognitionVerdict") == "PLAY_RECOGNIZED" and app.get("packageName") == package
    digests = set(certificate_digests)
    if app_ok and digests and not digests.intersection(app.get("certificateSha256Digest") or []):
        app_ok = False
        reasons.append("certificate_digest_mismatch")
    if not app_ok:
        reasons.append(f"app_{str(app.get('appRecognitionVerdict') or 'unevaluated').lower()}")

    device = set((payload.get("deviceIntegrity") or {}).get("deviceRecognitionVerdict") or [])
    if not app_ok:
        verdict = "failed"
    elif {"MEETS_STRONG_INTEGRITY", "MEETS_DEVICE_INTEGRITY"} & device:
        verdict = "verified"
    elif "MEETS_VIRTUAL_INTEGRITY" in device:
        verdict = "virtual"
    elif "MEETS_BASIC_INTEGRITY" in device:
        verdict = "basic"
    else:
        verdict = "failed"
        reasons.append("no_device_integrity")
    return PlayIntegrityResult(verdict=verdict, package_name=str(package), reasons=tuple(reasons))


__all__ = [
    "PlayIntegrityError",
    "PlayIntegrityResult",
    "decode_token",
    "evaluate_payload",
    "service_account_assertion",
]
