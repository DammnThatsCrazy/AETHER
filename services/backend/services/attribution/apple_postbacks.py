"""Apple AdAttributionKit / SKAdNetwork postback ingestion.

Apple postbacks are CAMPAIGN-LEVEL, PLATFORM-VERIFIED aggregate evidence.
They are explicitly SEPARATE from user-level deterministic acquisition
evidence: ingesting a postback never creates a touchpoint, never resolves a
user or install to a campaign, and never upgrades a Direct / Unknown install.
Rows are stored with proof_level "platform_verified" as campaign-level
measurement input only.

Signature verification: Apple postbacks carry a P-256 ``attribution-signature``
(ECDSA over SHA-256).  This module reconstructs Apple's documented signed
parameter string in the exact per-version field order (SKAdNetwork 2.1 / 2.2 /
3.0 / 4.0, the last shared with AdAttributionKit), joined by the U+2063
INVISIBLE SEPARATOR, and verifies it against Apple's published SKAdNetwork
public key using ``cryptography`` (ec.ECDSA, SECP256R1, SHA-256).  The
verification key is a module constant (``APPLE_SKADNETWORK_PUBLIC_KEY_B64``,
operator-overridable via ``AETHER_APPLE_SKADNETWORK_PUBLIC_KEY_B64``) and is
injectable for tests via the ``_apple_public_key`` seam without weakening the
production path.  signature_status records the truth:

    "verified"   — signature cryptographically verified against the Apple key
    "invalid"    — a known-version signature FAILED verification; the postback
                   is REJECTED (HTTP 422) and never stored as attributed
    "unverified" — a signature is present but its version's exact signed-field
                   order is unknown to this module (or the key is unloadable);
                   stored honestly as low-trust, never as "verified"
    "missing"    — the postback carried no signature field

No row is ever marked verified without real cryptographic verification.

Route (registered in main.py like every other service router):
    POST /v1/attribution/apple-postbacks

Parsing is version-tolerant across AdAttributionKit (kebab-case) and older
SKAdNetwork payload spellings; idempotency is keyed on the postback /
transaction identifier so Apple's redelivery retries never double-store.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from repositories.repos import get_pool
from shared.auth.auth import Role, TenantContext
from shared.decorators import require_api_key

logger = logging.getLogger("aether.attribution.apple_postbacks")

router = APIRouter(prefix="/v1/attribution", tags=["apple-postbacks"])

PROOF_LEVEL = "platform_verified"

SIGNATURE_STATUS_VERIFIED = "verified"
SIGNATURE_STATUS_INVALID = "invalid"
SIGNATURE_STATUS_UNVERIFIED = "unverified"
SIGNATURE_STATUS_MISSING = "missing"

# -----------------------------------------------------------------------------
# Apple SKAdNetwork / AdAttributionKit attribution-signature verification.
#
# Apple signs each install-validation postback (versions 2.1+ and
# AdAttributionKit) with a single published NIST P-256 (prime256v1) key using
# ECDSA over SHA-256.  The signed message is the postback's fields concatenated
# in a documented, version-specific order, joined by the U+2063 INVISIBLE
# SEPARATOR.  See Apple, "Verifying an install-validation postback".
#
# Provenance / trust: the constant below is Apple's widely-published
# SKAdNetwork verification key (Base64 SubjectPublicKeyInfo, DER).  It decodes
# to a valid SECP256R1 public key (asserted at import-adjacent test time).
# Operators MUST confirm it against Apple's current documentation for their
# integration and may override it WITHOUT code changes by setting
# AETHER_APPLE_SKADNETWORK_PUBLIC_KEY_B64.  The verification machinery is fully
# implemented here regardless of key provenance; if the configured key is
# absent/unloadable, signatures are recorded honestly as "unverified" (never
# falsely "verified").
# -----------------------------------------------------------------------------
APPLE_SKADNETWORK_PUBLIC_KEY_B64 = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEWdp8GPcGqmhgzEFj9Z2nSpQVddaya"
    "Pe4FMzqM9wib1+aHaaIzoHoLN9zW4K8y4SPykE3YVK3sVqW6Af0lfx3gg=="
)

# Apple joins the signed parameters with this single invisible code point.
_SIGNATURE_SEPARATOR = "\u2063"  # U+2063 INVISIBLE SEPARATOR

# Postback versions whose exact signed-field ordering is known to this module.
# Unknown/older versions are recorded "unverified" rather than guessed.
_KNOWN_SIGNED_VERSIONS = frozenset({"2.1", "2.2", "3.0", "4.0"})

_LOCAL_APPLE_POSTBACKS: dict[str, dict[str, Any]] = {}

_verifier_public_key: Optional[ec.EllipticCurvePublicKey] = None


def _configured_public_key_b64() -> str:
    return os.getenv(
        "AETHER_APPLE_SKADNETWORK_PUBLIC_KEY_B64", APPLE_SKADNETWORK_PUBLIC_KEY_B64
    )


def _apple_public_key() -> Optional[ec.EllipticCurvePublicKey]:
    """Return Apple's SKAdNetwork P-256 verification key (cached).

    Test seam: monkeypatch this function to inject a test P-256 public key; the
    production path always loads the configured Apple key.  Returns None only
    when the configured key cannot be loaded, in which case callers record
    signature_status="unverified" (never a false "verified").
    """

    global _verifier_public_key
    if _verifier_public_key is None:
        try:
            der = base64.b64decode(_configured_public_key_b64(), validate=True)
            key = load_der_public_key(der)
        except (binascii.Error, ValueError) as exc:
            logger.error("apple_skadnetwork_public_key_unloadable: %s", exc)
            return None
        if not isinstance(key, ec.EllipticCurvePublicKey):
            logger.error("apple_skadnetwork_public_key_not_ec")
            return None
        _verifier_public_key = key
    return _verifier_public_key


def _reset_verifier_key_cache_for_tests() -> None:
    """Drop the cached key so a test env override / restore takes effect."""

    global _verifier_public_key
    _verifier_public_key = None


def _sig_component(value: Any) -> Optional[str]:
    """Format one field exactly as Apple represents it in the signed string."""

    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    return text or None


def _build_signed_message(payload: dict[str, Any], version: Optional[str]) -> Optional[str]:
    """Reconstruct Apple's signed parameter string for a known version.

    Returns None when the version's field order is unknown, or when a required
    signed field is absent (so we never attempt a guaranteed-failing verify and
    mislabel an incomplete payload as tampered).
    """

    if version not in _KNOWN_SIGNED_VERSIONS:
        return None

    ad_network = _first(payload, "ad-network-id", "adNetworkId")
    app_id = _first(payload, "app-id", "appId")
    transaction_id = _first(payload, "transaction-id", "transactionId")
    redownload = _first(payload, "redownload")
    source_app_id = _first(payload, "source-app-id", "sourceAppId")
    fidelity_type = _first(payload, "fidelity-type", "fidelityType")
    did_win = _first(payload, "did-win", "didWin")

    if version == "4.0":
        source_identifier = _first(payload, "source-identifier", "sourceIdentifier")
        source_domain = _first(payload, "source-domain", "sourceDomain")
        seq = _first(payload, "postback-sequence-index", "postbackSequenceIndex")
        ordered: list[Any] = [
            version, ad_network, source_identifier, app_id, transaction_id, redownload,
        ]
        # App-sourced postbacks carry source-app-id; web-sourced carry
        # source-domain. Apple includes whichever is present (typically only on
        # winning postbacks); the field is omitted entirely when neither is set.
        if source_app_id is not None:
            ordered.append(source_app_id)
        elif source_domain is not None:
            ordered.append(source_domain)
        ordered += [fidelity_type, did_win, seq]
    else:  # 2.1 / 2.2 / 3.0 use campaign-id
        campaign_id = _first(payload, "campaign-id", "campaignId")
        ordered = [version, ad_network, campaign_id, app_id, transaction_id, redownload]
        if source_app_id is not None:
            ordered.append(source_app_id)
        if version in ("2.2", "3.0"):
            ordered.append(fidelity_type)
        if version == "3.0":
            ordered.append(did_win)

    components = [_sig_component(value) for value in ordered]
    if any(component is None for component in components):
        return None
    return _SIGNATURE_SEPARATOR.join(components)


def _evaluate_signature(payload: dict[str, Any]) -> str:
    """Classify the attribution-signature honestly.

    verified  → known version, signature validates against the Apple key
    invalid   → known version, signature present but verification failed
    unverified→ signature present but version order unknown or key unloadable
    missing   → no signature field
    """

    signature = _first(
        payload, "attribution-signature", "attributionSignature", "signature"
    )
    if not (isinstance(signature, str) and signature.strip()):
        return SIGNATURE_STATUS_MISSING

    version = _as_str(_first(payload, "version", "postback-version"))
    message = _build_signed_message(payload, version)
    if message is None:
        return SIGNATURE_STATUS_UNVERIFIED

    key = _apple_public_key()
    if key is None:
        return SIGNATURE_STATUS_UNVERIFIED

    try:
        raw_signature = base64.b64decode(signature.strip(), validate=True)
    except (binascii.Error, ValueError):
        return SIGNATURE_STATUS_INVALID

    try:
        key.verify(raw_signature, message.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return SIGNATURE_STATUS_INVALID
    return SIGNATURE_STATUS_VERIFIED


async def _pool() -> Any:
    return await get_pool()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _first(payload: dict[str, Any], *keys: str) -> Any:
    """Version-tolerant field access across kebab-case / camelCase spellings."""

    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:255] or None


class MalformedPostbackError(ValueError):
    """Raised when a payload cannot be reduced to a storable postback."""


def reduce_postback(payload: Any) -> dict[str, Any]:
    """Reduce a raw postback JSON body to the stored row shape.

    Tolerates AdAttributionKit and SKAdNetwork 3/4 spellings; rejects payloads
    that lack any idempotency identifier or any campaign/source identity.
    """

    if not isinstance(payload, dict) or not payload:
        raise MalformedPostbackError("postback body must be a non-empty JSON object")

    idempotency_key = _as_str(
        _first(
            payload,
            "postback-id",
            "postbackId",
            "transaction-id",
            "transactionId",
            "attribution-report-id",
        )
    )
    if idempotency_key is None:
        raise MalformedPostbackError(
            "postback is missing an idempotency identifier "
            "(postback-id / transaction-id)"
        )

    campaign_identity = {
        "ad_network_id": _as_str(_first(payload, "ad-network-id", "adNetworkId")),
        # AdAttributionKit source-identifier supersedes SKAdNetwork campaign-id;
        # both spellings are accepted and stored under both names.
        "source_identifier": _as_str(
            _first(payload, "source-identifier", "sourceIdentifier", "campaign-id", "campaignId")
        ),
        "source_app_id": _as_str(_first(payload, "source-app-id", "sourceAppId")),
        "source_domain": _as_str(_first(payload, "source-domain", "sourceDomain")),
        "app_id": _as_str(_first(payload, "app-id", "appId")),
    }
    if not campaign_identity["ad_network_id"] and not campaign_identity["source_identifier"]:
        raise MalformedPostbackError(
            "postback is missing campaign identity (ad-network-id / source-identifier)"
        )

    environment = _as_str(
        _first(payload, "postback-environment", "environment")
    ) or "production"
    if environment not in {"production", "sandbox"}:
        environment = "production"

    signature_status = _evaluate_signature(payload)

    reduced_payload = {
        **campaign_identity,
        "version": _as_str(_first(payload, "version", "postback-version")),
        "postback_sequence_index": _as_int(
            _first(payload, "postback-sequence-index", "postbackSequenceIndex")
        ),
        "did_win": _first(payload, "did-win", "didWin"),
        "redownload": payload.get("redownload"),
        "country_or_region": _as_str(
            _first(payload, "country-or-region", "countryOrRegion")
        ),
    }

    return {
        "idempotency_key": idempotency_key,
        "reduced_payload": {k: v for k, v in reduced_payload.items() if v is not None},
        "coarse_conversion_value": _as_str(
            _first(payload, "coarse-conversion-value", "coarseConversionValue")
        ),
        "fine_conversion_value": _as_int(
            _first(payload, "fine-conversion-value", "conversion-value", "conversionValue")
        ),
        "environment": environment,
        "signature_status": signature_status,
        "proof_level": PROOF_LEVEL,
    }


class ApplePostbackRepository:
    """Idempotent, tenant-scoped storage of reduced Apple postback rows.

    Durable SQL (``apple_attribution_postbacks``, migration
    20260803_deferred_attribution) with the standard in-memory fallback when
    no pool is configured (local/test).
    """

    async def store(self, tenant_id: str, reduced: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(tenant_id).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        now = _now()
        row = {
            "apple_postback_id": str(uuid4()),
            "tenant_id": tenant_id,
            "idempotency_key": reduced["idempotency_key"],
            "reduced_payload": reduced["reduced_payload"],
            "coarse_conversion_value": reduced["coarse_conversion_value"],
            "fine_conversion_value": reduced["fine_conversion_value"],
            "environment": reduced["environment"],
            "signature_status": reduced["signature_status"],
            "proof_level": reduced["proof_level"],
            "received_at": now,
        }

        pool = await _pool()
        if pool is None:
            local_key = f"{tenant_id}::{reduced['idempotency_key']}"
            existing = _LOCAL_APPLE_POSTBACKS.get(local_key)
            if existing is not None:
                return {**self._public(existing), "duplicate": True}
            _LOCAL_APPLE_POSTBACKS[local_key] = row
            return {**self._public(row), "duplicate": False}

        inserted = await pool.fetchrow(
            """
            INSERT INTO apple_attribution_postbacks (
                apple_postback_id, tenant_id, idempotency_key, reduced_payload,
                coarse_conversion_value, fine_conversion_value, environment,
                signature_status, proof_level, received_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING *
            """,
            row["apple_postback_id"],
            tenant_id,
            row["idempotency_key"],
            json.dumps(row["reduced_payload"]),
            row["coarse_conversion_value"],
            row["fine_conversion_value"],
            row["environment"],
            row["signature_status"],
            row["proof_level"],
            now,
        )
        if inserted is None:
            existing_row = await pool.fetchrow(
                """
                SELECT * FROM apple_attribution_postbacks
                WHERE tenant_id = $1 AND idempotency_key = $2
                """,
                tenant_id,
                row["idempotency_key"],
            )
            return {**self._public(dict(existing_row)), "duplicate": True}
        return {**self._public(dict(inserted)), "duplicate": False}

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("reduced_payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        return {
            "apple_postback_id": str(row["apple_postback_id"]),
            "idempotency_key": row["idempotency_key"],
            "reduced_payload": payload or {},
            "coarse_conversion_value": row.get("coarse_conversion_value"),
            "fine_conversion_value": row.get("fine_conversion_value"),
            "environment": row.get("environment"),
            "signature_status": row.get("signature_status"),
            "proof_level": row.get("proof_level"),
            "received_at": (
                row["received_at"].isoformat()
                if isinstance(row.get("received_at"), datetime)
                else row.get("received_at")
            ),
        }


_repository = ApplePostbackRepository()


def reset_apple_postbacks_for_tests() -> None:
    """Clear only the local fallback; never mutates the database."""

    _LOCAL_APPLE_POSTBACKS.clear()


# =============================================================================
# RBAC — mirrors the _require_* pattern in services/traffic/routes.py.
# Postbacks arrive via the tenant's own forwarding endpoint or a service
# integration, so a write-capable credential is required.
# =============================================================================

def _postback_access_allowed(tenant: TenantContext, permission: str) -> bool:
    if tenant.role in {Role.ADMIN, Role.EDITOR, Role.SERVICE}:
        return True
    return tenant.has_permission(permission)


async def _require_apple_postback_write(
    tenant: TenantContext = Depends(require_api_key),
) -> TenantContext:
    if not _postback_access_allowed(tenant, "apple_postbacks:write"):
        raise HTTPException(status_code=403, detail="Apple-postback write access required")
    return tenant


class ApplePostbackRequest(BaseModel):
    """Raw postback body as forwarded from the tenant's postback endpoint."""

    postback: dict[str, Any] = Field(default_factory=dict)


@router.post("/apple-postbacks", status_code=201)
async def ingest_apple_postback(
    body: ApplePostbackRequest,
    tenant: TenantContext = Depends(_require_apple_postback_write),
) -> dict[str, Any]:
    """Ingest one AdAttributionKit/SKAdNetwork-style postback.

    Campaign-level platform evidence only: no touchpoint is created and no
    user-level attribution is derived. Redelivered postbacks (same
    postback/transaction id) are acknowledged as duplicates, not re-stored.
    """

    try:
        reduced = reduce_postback(body.postback)
    except MalformedPostbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # A known-version signature that fails cryptographic verification is a
    # forged/tampered postback: reject it and store nothing.
    if reduced["signature_status"] == SIGNATURE_STATUS_INVALID:
        logger.warning(
            "Apple postback REJECTED (invalid signature) tenant=%s key=%s",
            tenant.tenant_id,
            reduced["idempotency_key"],
        )
        raise HTTPException(
            status_code=422, detail="attribution-signature failed verification"
        )

    stored = await _repository.store(tenant.tenant_id, reduced)
    logger.info(
        "Apple postback %s tenant=%s duplicate=%s signature=%s",
        stored["idempotency_key"],
        tenant.tenant_id,
        stored["duplicate"],
        stored["signature_status"],
    )
    return {"postback": stored}
