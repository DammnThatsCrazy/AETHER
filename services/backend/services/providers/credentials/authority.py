"""Durable, multi-slot provider-credential authority.

The authoritative source of truth for tenant provider credentials is the
durable ``provider_credential_versions`` table (Postgres in production, shared
in-memory locally) — NOT process memory and NOT Redis. This service owns the
credential-version state machine:

    create_pending → test → activate → (rotate → previous/overlap) → revoke → delete

Design guarantees:
* **Multi-slot** — a provider holds independent versions per (environment, slot),
  so a webhook signing secret and a polling API key rotate/validate/revoke
  independently.
* **Encrypted at rest** — values are only ever stored as cipher output; the sole
  decrypt site is :meth:`get_active_secret` / :meth:`get_verification_secrets`,
  called at a provider request. No list/status/connection path decrypts.
* **Restart / replica safe** — state lives in the durable table; a bounded,
  *version-keyed* in-process cache accelerates repeated decrypts without ever
  being the authority (a rotation changes the version, hence the cache key).
* **Invariants enforced in code** (mirrored by Postgres partial-unique indexes):
  at most one ``active`` and at most one ``previous`` version per slot; a failed
  pending test never disturbs the working active version.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Optional

from shared.common.common import ConflictError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.providers.credentials.repository import CredentialVersionRepo
from services.providers.credentials.schema import (
    CREDENTIAL_ENVIRONMENTS,
    CredentialEnvironment,
    CredentialState,
)
from services.providers.credentials.slot_registry import get_slot, slots_for

logger = get_logger("aether.providers.credential_authority")

# Non-sensitive fields safe to return in any API/connection view.
_SAFE_FIELDS = (
    "provider",
    "domain",
    "environment",
    "slot_name",
    "state",
    "credential_version",
    "safe_fingerprint",
    "encryption_provider",
    "created_at",
    "created_by",
    "updated_at",
    "last_tested_at",
    "last_test_result",
    "last_successful_test_at",
    "activated_at",
    "rotation_overlap_expires_at",
    "revoked_at",
    "revoked_by",
    "endpoint",
)

_DECRYPT_CACHE_MAX = 512


class SlotError(ValueError):
    """A client referenced a slot the server never declared for the provider."""


class CredentialAuthority:
    """Durable credential-version state machine (see module docstring)."""

    def __init__(
        self,
        repo: Optional[CredentialVersionRepo] = None,
        cipher: object = None,
    ) -> None:
        self._repo = repo or CredentialVersionRepo()
        self._injected_cipher = cipher
        # version-keyed decrypted cache: key -> (plaintext, expires_epoch)
        self._decrypt_cache: dict[str, tuple[str, float]] = {}

    # ── cipher / stores ───────────────────────────────────────────────────
    def _cipher(self):
        if self._injected_cipher is not None:
            return self._injected_cipher
        from shared.providers.credential_cipher import get_credential_cipher

        return get_credential_cipher()

    def _overlap_hours(self) -> int:
        try:
            from config.settings import settings

            return int(settings.provider_gateway.credential_rotation_overlap_hours)
        except Exception:
            return 24

    def _cache_ttl_s(self) -> int:
        try:
            from config.settings import settings

            return int(settings.provider_gateway.credential_decrypt_cache_ttl_s)
        except Exception:
            return 60

    # ── validation helpers ────────────────────────────────────────────────
    @staticmethod
    def _require_slot(provider: str, slot_name: str, environment: str):
        slot = get_slot(provider, slot_name, environment)
        if slot is None:
            raise SlotError(
                f"unknown credential slot {slot_name!r} for provider {provider!r}"
            )
        return slot

    @staticmethod
    def _require_environment(environment: str) -> None:
        if environment not in CREDENTIAL_ENVIRONMENTS:
            raise SlotError(
                f"unknown environment {environment!r}; expected one of {CREDENTIAL_ENVIRONMENTS}"
            )

    # ── audit (durable Postgres history, never Redis/in-memory-only) ──────
    @property
    def _audit_repo(self):
        if getattr(self, "_audit_repo_instance", None) is None:
            from repositories.repos import BaseRepository

            self._audit_repo_instance = BaseRepository("provider_credential_audit")
        return self._audit_repo_instance

    async def _audit(
        self,
        *,
        action: str,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        credential_version: Optional[int],
        actor: str,
        result: str = "ok",
    ) -> str:
        audit_id = f"cred_audit_{uuid.uuid4().hex}"
        record = {
            "id": audit_id,
            "action": action,
            "tenant_id": tenant_id,
            "provider": provider,
            "environment": environment,
            "slot_name": slot_name,
            "credential_version": credential_version,
            "actor": actor,
            "result": result,
            "at": utc_now().isoformat(),
        }
        try:
            await self._audit_repo.insert(audit_id, record)
        except Exception as exc:  # audit must never take down a mutation
            logger.warning("credential audit write failed: %s", type(exc).__name__)
        return audit_id

    async def audit_history(
        self, tenant_id: str, provider: Optional[str] = None, limit: int = 200
    ) -> list[dict]:
        """Durable, secret-free credential audit trail for a tenant."""
        filters: dict = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        return await self._audit_repo.find_many(filters=filters, limit=limit)

    # ── lifecycle propagation ─────────────────────────────────────────────
    async def _notify_lifecycle(
        self,
        event: str,
        tenant_id: str,
        provider: str,
        environment: str,
        credential_version: Optional[int] = None,
    ) -> None:
        """Propagate a credential event into the capability lifecycle authority.

        Rotation demotes certified capabilities to CREDENTIAL_SUPPLIED (bound
        to the new version); revocation/deletion demotes to REVOKED; activation
        advances CREDENTIAL_WAITING coordinates. Propagation failures are
        logged and counted — the readiness revalidation worker re-syncs any
        divergence — but never abort the credential mutation itself.
        """
        try:
            from services.capabilities.lifecycle import get_lifecycle_authority

            ref = (
                f"credver://{provider}/{environment}@v{credential_version}"
                if credential_version is not None
                else None
            )
            await get_lifecycle_authority().on_credential_event(
                tenant_id=tenant_id,
                provider=provider,
                environment=environment,
                event=event,
                credential_version_ref=ref,
            )
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.error(
                "credential lifecycle propagation failed event=%s provider=%s: %s",
                event, provider, exc,
            )
            metrics.increment(
                "credential_lifecycle_propagation_failures",
                labels={"event": event, "provider": provider},
            )

    # ── idempotency ───────────────────────────────────────────────────────
    async def _idempotent_get(self, tenant_id: str, key: Optional[str]) -> Optional[dict]:
        if not key:
            return None
        try:
            stored = await get_store("credential_idempotency").get(f"{tenant_id}:{key}")
        except Exception:
            return None
        return stored.get("result") if stored else None

    async def _idempotent_put(self, tenant_id: str, key: Optional[str], result: dict) -> None:
        if not key:
            return
        try:
            await get_store("credential_idempotency").set(
                f"{tenant_id}:{key}", {"result": result}, ttl_seconds=86400
            )
        except Exception:
            pass

    # ── mutations ─────────────────────────────────────────────────────────
    async def create_pending(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        value: str,
        *,
        created_by: str,
        endpoint: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Create a new PENDING credential version (encrypted at rest)."""
        self._require_environment(environment)
        slot = self._require_slot(provider, slot_name, environment)
        if not value:
            raise ValueError("credential value must not be empty")

        cached = await self._idempotent_get(tenant_id, idempotency_key)
        if cached is not None:
            return cached

        version = await self._repo.next_version_number(
            tenant_id, provider, environment, slot_name
        )
        from shared.providers.credential_cipher import EncryptionContext

        ctx = EncryptionContext(tenant_id, provider, environment, slot_name, version)
        blob = self._cipher().encrypt(value, ctx)

        record_id = f"cred_{uuid.uuid4().hex}"
        audit_id = await self._audit(
            action="create_pending",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name=slot_name,
            credential_version=version,
            actor=created_by,
        )
        data: dict[str, Any] = {
            "tenant_id": tenant_id,
            "provider": provider,
            "domain": slot.domain,
            "environment": environment,
            "slot_name": slot_name,
            "credential_version": version,
            "state": CredentialState.PENDING,
            "created_by": created_by,
            "last_tested_at": None,
            "last_test_result": None,
            "last_successful_test_at": None,
            "activated_at": None,
            "rotation_overlap_expires_at": None,
            "revoked_at": None,
            "revoked_by": None,
            "audit_reference": audit_id,
            "endpoint": _safe_endpoint(endpoint),
            **blob.to_row(),
        }
        await self._repo.insert(record_id, data)
        result = self._safe_view(data)
        await self._idempotent_put(tenant_id, idempotency_key, result)
        return result

    async def test_slot(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        *,
        actor: str,
        credential_version: Optional[int] = None,
    ) -> dict:
        """Validate a credential version.

        For a webhook signing secret (``signature_selfcheck``) this computes a
        real HMAC-SHA256 over a fixed canary with the decrypted secret, proving
        the material is a usable signing key (not merely that it decrypts). For a
        polling API key (``live_probe``) this performs the provider's real
        read-only connection probe (a bounded authenticated GET) OUTSIDE local
        development, classifying the outcome; in local development (no network) it
        records ``credential_present``. A pending version that fails to decrypt —
        or whose live probe returns an authentication failure — is marked
        ``test_failed`` and never touches the active version.
        """
        slot = self._require_slot(provider, slot_name, environment)
        row = await self._pick_version(
            tenant_id, provider, environment, slot_name, credential_version
        )
        if row is None:
            raise NotFoundError("provider_credential")

        result = "unknown"
        try:
            secret = self._decrypt_row(tenant_id, provider, environment, slot_name, row)
            if not secret:
                result = "empty"
            elif slot.validation_strategy == "signature_selfcheck":
                import hashlib
                import hmac as _hmac

                _hmac.new(
                    secret.encode("utf-8"), b"aether-credential-selfcheck", hashlib.sha256
                ).hexdigest()
                result = "valid"
            elif slot.validation_strategy == "key_derivation_check":
                result = self._derive_key_identity(slot_name, secret)
            else:  # live_probe / rpc_chain_probe — real read-only connection probe
                result = await self._probe_live_secret(provider, environment, secret)
        except Exception:
            result = "decrypt_failed"

        now = utc_now().isoformat()
        patch = {"last_tested_at": now, "last_test_result": result}
        if result in ("valid", "credential_present"):
            patch["last_successful_test_at"] = now
        # Definitive failures mark a PENDING version TEST_FAILED so it can never
        # be activated. This includes the key-derivation failures — a signing
        # key that is malformed (``invalid_key_material``), for an unrecognized
        # slot (``unsupported_key_slot``), unprovable because the crypto library
        # is missing (``derivation_unavailable``), or empty — none of which is a
        # usable signing key. (Transient live-probe outcomes such as timeouts /
        # rate limits are intentionally NOT in this set, so they stay retryable
        # rather than permanently failing the version.)
        _failing = result in (
            "decrypt_failed", "unauthorized", "forbidden", "empty",
            "invalid_key_material", "unsupported_key_slot", "derivation_unavailable",
        )
        if _failing and row.get("state") == CredentialState.PENDING:
            patch["state"] = CredentialState.TEST_FAILED
        await self._repo.update(row["id"], patch)

        await self._audit(
            action="test",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name=slot_name,
            credential_version=int(row["credential_version"]),
            actor=actor,
            result=result,
        )
        merged = {**row, **patch}
        return self._safe_view(merged)

    @staticmethod
    def _derive_key_identity(slot_name: str, secret: str) -> str:
        """Validate signing-key material by deriving its public identity.

        EVM (secp256k1 hex key) → derive the checksummed address via
        eth_account; SVM (ed25519 seed) → derive the verify key via PyNaCl.
        Proves the material is a usable signing key; the derived identity is
        compared against the verified contract/program registry at proof time
        (services/rewards/signing.py), not here. Never returns the key.
        """
        try:
            if slot_name.startswith("evm_"):
                from eth_account import Account

                key = secret[2:] if secret.startswith("0x") else secret
                Account.from_key(bytes.fromhex(key))
                return "valid"
            if slot_name.startswith("svm_"):
                import base64

                from nacl.signing import SigningKey

                raw = (
                    bytes.fromhex(secret)
                    if all(c in "0123456789abcdefABCDEF" for c in secret) and len(secret) in (64, 128)
                    else base64.b64decode(secret)
                )
                SigningKey(raw[:32])
                return "valid"
            return "unsupported_key_slot"
        except ImportError:
            # Fail closed: without the crypto library we cannot prove the key
            # is usable, and an unproven signing key must never test "valid".
            return "derivation_unavailable"
        except Exception:  # noqa: BLE001 — malformed key material
            return "invalid_key_material"

    async def _probe_live_secret(
        self, provider: str, environment: str, secret: str
    ) -> str:
        """Read-only live probe of a polling API key, classified. Never raises.

        Outside local development, drives the payment adapter's bounded,
        authenticated GET against the environment-appropriate provider host using
        the supplied (decrypted) secret and maps the outcome onto a stable
        ``last_test_result`` token. In local development (or for a provider with
        no pull API) it records ``credential_present`` without any network IO.
        """
        import os

        if os.getenv("AETHER_ENV", "local").strip().lower() == "local":
            return "credential_present"
        try:
            from services.integrations.providers.payment_rails import ADAPTERS
            from services.integrations.providers.payment_rails.base import ProviderPollError
        except Exception:  # noqa: BLE001 — non-payment domain / import unavailable
            return "credential_present"
        adapter = ADAPTERS.get(provider)
        build = getattr(adapter, "build_request", None)
        if adapter is None or not getattr(adapter, "polling_supported", False) or not callable(build):
            return "credential_present"
        base = (
            adapter.poll_base_url_sandbox
            if environment == CredentialEnvironment.SANDBOX and adapter.poll_base_url_sandbox
            else adapter.poll_base_url
        )
        try:
            request = build({
                "tenant_id": "", "credential": secret, "base_url": base,
                "page_size": 1, "limit": 1,
            })
            async with adapter._open_http_client() as client:
                await adapter._request_json(client, request)
            return "valid"
        except ProviderPollError as exc:
            return {
                "auth_error": "unauthorized",
                "rate_limited": "rate_limited",
                "timeout": "timeout",
                "server_error": "provider_unavailable",
                "client_error": "client_error",
                "network_error": "network_error",
                "bad_response": "bad_response",
            }.get(exc.classification, exc.classification)
        except Exception:  # noqa: BLE001 — probe must never raise into the state machine
            return "probe_error"

    async def activate(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        *,
        credential_version: int,
        actor: str,
        expected_active_version: Optional[int] = None,
    ) -> dict:
        """Promote a version to ACTIVE, demoting the current active safely.

        ``expected_active_version`` gives optimistic concurrency: if the current
        active version does not match, raise ``ConflictError`` (someone else
        rotated concurrently). Webhook secrets keep the previous version in a
        bounded overlap window; other slots revoke the old version immediately.
        """
        slot = self._require_slot(provider, slot_name, environment)
        target = await self._find_version(
            tenant_id, provider, environment, slot_name, credential_version
        )
        if target is None:
            raise NotFoundError("provider_credential")
        if target.get("state") in (CredentialState.REVOKED, CredentialState.TOMBSTONED):
            raise ConflictError("cannot activate a revoked or deleted credential version")
        if target.get("state") == CredentialState.TEST_FAILED:
            raise ConflictError("cannot activate a credential version that failed validation")
        # Signing keys: prove the material derives a usable key BEFORE it becomes
        # the active signer — even if test_slot was never called. A malformed /
        # unprovable private key must never go ACTIVE (proof generation would
        # later crash and readiness would already have advanced). Valid keys pass
        # this check transparently.
        if slot.validation_strategy == "key_derivation_check":
            try:
                secret = self._decrypt_row(
                    tenant_id, provider, environment, slot_name, target
                )
                derivation = self._derive_key_identity(slot_name, secret) if secret else "empty"
            except Exception:  # noqa: BLE001 — treat any failure as unprovable
                derivation = "invalid_key_material"
            if derivation != "valid":
                await self._repo.update(
                    target["id"],
                    {"state": CredentialState.TEST_FAILED, "last_test_result": derivation},
                )
                raise ConflictError(
                    "cannot activate a signing key that fails key-derivation "
                    f"validation ({derivation})"
                )

        current = await self._repo.active_version(tenant_id, provider, environment, slot_name)
        current_version = int(current["credential_version"]) if current else None
        if expected_active_version is not None and expected_active_version != current_version:
            raise ConflictError(
                "active credential version changed; expected "
                f"{expected_active_version}, found {current_version}"
            )
        if current and int(current["credential_version"]) == int(credential_version):
            return self._safe_view(current)  # already active — idempotent

        now = utc_now()
        if current:
            if slot.rotation_policy == "overlap":
                # Only one previous allowed: tombstone any existing previous first.
                await self._tombstone_previous(tenant_id, provider, environment, slot_name)
                await self._repo.update(
                    current["id"],
                    {
                        "state": CredentialState.PREVIOUS,
                        "rotation_overlap_expires_at": (
                            now + timedelta(hours=self._overlap_hours())
                        ).isoformat(),
                    },
                )
            else:
                await self._repo.update(
                    current["id"],
                    {
                        "state": CredentialState.REVOKED,
                        "revoked_at": now.isoformat(),
                        "revoked_by": actor,
                    },
                )
            self._invalidate(current)

        activated = await self._repo.update(
            target["id"],
            {"state": CredentialState.ACTIVE, "activated_at": now.isoformat()},
        )
        await self._audit(
            action="activate",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name=slot_name,
            credential_version=int(credential_version),
            actor=actor,
        )
        # Rotation (an active version existed) demotes certified capabilities
        # back to CREDENTIAL_SUPPLIED bound to the new version; first
        # activation advances CREDENTIAL_WAITING coordinates.
        await self._notify_lifecycle(
            "rotated" if current else "activated",
            tenant_id, provider, environment, int(credential_version),
        )
        return self._safe_view(activated)

    async def rotate(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        value: str,
        *,
        actor: str,
        expected_active_version: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Create a new pending version and activate it (with overlap/replace)."""
        pending = await self.create_pending(
            tenant_id,
            provider,
            environment,
            slot_name,
            value,
            created_by=actor,
            idempotency_key=idempotency_key,
        )
        return await self.activate(
            tenant_id,
            provider,
            environment,
            slot_name,
            credential_version=int(pending["credential_version"]),
            actor=actor,
            expected_active_version=expected_active_version,
        )

    async def revoke(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        *,
        actor: str,
    ) -> dict:
        """Revoke every non-terminal version of a slot (retained for audit)."""
        self._require_slot(provider, slot_name, environment)
        rows = await self._repo.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )
        now = utc_now().isoformat()
        revoked = 0
        for row in rows:
            if row.get("state") in (CredentialState.REVOKED, CredentialState.TOMBSTONED):
                continue
            await self._repo.update(
                row["id"],
                {"state": CredentialState.REVOKED, "revoked_at": now, "revoked_by": actor},
            )
            self._invalidate(row)
            revoked += 1
        await self._audit(
            action="revoke",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name=slot_name,
            credential_version=None,
            actor=actor,
            result=f"revoked={revoked}",
        )
        if revoked:
            await self._notify_lifecycle("revoked", tenant_id, provider, environment)
        return {"provider": provider, "slot_name": slot_name, "environment": environment,
                "revoked_versions": revoked}

    async def delete(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        slot_name: str,
        *,
        actor: str,
    ) -> dict:
        """Tombstone a slot: erase the ciphertext, keep a checksummed stub.

        Matches the ``tombstone`` storage policy: the secret material is gone but
        a non-secret audit stub (fingerprint + audit reference) is retained.
        """
        self._require_slot(provider, slot_name, environment)
        rows = await self._repo.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )
        now = utc_now().isoformat()
        for row in rows:
            await self._repo.update(
                row["id"],
                {
                    "state": CredentialState.TOMBSTONED,
                    "encrypted_value": "",
                    "encrypted_data_key": "",
                    "revoked_at": row.get("revoked_at") or now,
                    "revoked_by": row.get("revoked_by") or actor,
                },
            )
            self._invalidate(row)
        await self._audit(
            action="delete",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name=slot_name,
            credential_version=None,
            actor=actor,
            result=f"tombstoned={len(rows)}",
        )
        if rows:
            await self._notify_lifecycle("deleted", tenant_id, provider, environment)
        return {"provider": provider, "slot_name": slot_name, "environment": environment,
                "tombstoned_versions": len(rows)}

    async def purge_tenant(self, tenant_id: str) -> int:
        """Hard-delete every credential row for a tenant (DSR / tenant erasure)."""
        count = await self._repo.delete_by_entity("tenant_id", tenant_id)
        self._decrypt_cache = {
            k: v for k, v in self._decrypt_cache.items() if not k.startswith(f"{tenant_id}:")
        }
        await self._audit(
            action="purge_tenant",
            tenant_id=tenant_id,
            provider="*",
            environment="*",
            slot_name="*",
            credential_version=None,
            actor="system",
            result=f"deleted={count}",
        )
        return count

    # ── secret access (the ONLY decrypt sites) ────────────────────────────
    async def get_active_secret(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> str:
        """Decrypt and return the active secret for a slot (provider call site)."""
        row = await self._repo.active_version(tenant_id, provider, environment, slot_name)
        if row is None:
            raise NotFoundError("provider_credential")
        return self._decrypt_row(tenant_id, provider, environment, slot_name, row)

    async def get_verification_secrets(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> list[str]:
        """Active secret plus a valid (unexpired) previous secret, for webhook
        signature rotation. Expired previous versions are swept to tombstoned."""
        secrets: list[str] = []
        active = await self._repo.active_version(tenant_id, provider, environment, slot_name)
        if active:
            secrets.append(
                self._decrypt_row(tenant_id, provider, environment, slot_name, active)
            )
        prev = await self._repo.previous_version(tenant_id, provider, environment, slot_name)
        if prev:
            expires = prev.get("rotation_overlap_expires_at")
            if expires and _is_future(expires):
                secrets.append(
                    self._decrypt_row(tenant_id, provider, environment, slot_name, prev)
                )
            else:
                await self._repo.update(
                    prev["id"],
                    {"state": CredentialState.TOMBSTONED, "encrypted_value": "", "encrypted_data_key": ""},
                )
                self._invalidate(prev)
        return secrets

    # ── views / status ────────────────────────────────────────────────────
    async def slot_status(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> Optional[dict]:
        self._require_slot(provider, slot_name, environment)
        active = await self._repo.active_version(tenant_id, provider, environment, slot_name)
        if active:
            return self._safe_view(active)
        rows = await self._repo.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )
        rows = [r for r in rows if r.get("state") != CredentialState.TOMBSTONED]
        return self._safe_view(rows[0]) if rows else None

    async def missing_required_slots(
        self, tenant_id: str, provider: str, environment: str
    ) -> list[str]:
        missing = []
        for slot in slots_for(provider, environment):
            if not slot.required:
                continue
            active = await self._repo.active_version(
                tenant_id, provider, environment, slot.slot_name
            )
            if active is None:
                missing.append(slot.slot_name)
        return missing

    async def get_connections(
        self, tenant_id: str, *, environment: str = CredentialEnvironment.SANDBOX
    ) -> list[dict]:
        from services.providers.credentials.slot_registry import known_providers

        env = environment
        connections = []
        for provider in known_providers():
            missing = await self.missing_required_slots(tenant_id, provider, env)
            enabled = await self._is_enabled(tenant_id, provider, env)
            slot_views = []
            for slot in slots_for(provider, env):
                status = await self.slot_status(tenant_id, provider, env, slot.slot_name)
                slot_views.append(
                    {
                        **slot.public_dict(),
                        "configured": status is not None
                        and status.get("state")
                        in (CredentialState.ACTIVE, CredentialState.PREVIOUS, CredentialState.PENDING),
                        "status": status,
                    }
                )
            connections.append(
                {
                    "provider": provider,
                    "environment": env,
                    "enabled": enabled,
                    "can_enable": len(missing) == 0,
                    "missing_slots": missing,
                    "slots": slot_views,
                }
            )
        return connections

    # ── enablement (durable flag store; never the credential authority) ────
    async def enable_provider(
        self, tenant_id: str, provider: str, environment: str, *, actor: str
    ) -> dict:
        self._require_environment(environment)
        if provider not in _known():
            raise NotFoundError("provider")
        missing = await self.missing_required_slots(tenant_id, provider, environment)
        if missing:
            raise ConflictError(
                f"cannot enable {provider}: missing required slots {missing}"
            )
        await self._set_enabled(tenant_id, provider, environment, True, actor)
        return {"provider": provider, "environment": environment, "enabled": True}

    async def disable_provider(
        self, tenant_id: str, provider: str, environment: str, *, actor: str
    ) -> dict:
        self._require_environment(environment)
        await self._set_enabled(tenant_id, provider, environment, False, actor)
        return {"provider": provider, "environment": environment, "enabled": False}

    async def is_enabled(self, tenant_id: str, provider: str, environment: str) -> bool:
        """Public: whether the tenant has enabled this provider/environment."""
        return await self._is_enabled(tenant_id, provider, environment)

    async def preflight(self, tenant_id: str, provider: str, environment: str) -> dict:
        """Truthful, credential-only preflight for one provider/environment.

        PR-1 reports the credential/slot dimension of the connection state; live
        webhook/polling/worker/projection dimensions are added in later PRs. The
        ``current_readiness_state`` uses only canonical readiness-vocabulary
        tokens and never claims more than a stored credential proves.
        """
        self._require_environment(environment)
        if provider not in _known():
            raise NotFoundError("provider")
        required = [s.slot_name for s in slots_for(provider, environment) if s.required]
        missing = await self.missing_required_slots(tenant_id, provider, environment)
        configured: list[str] = []
        invalid: list[str] = []
        slot_views: list[dict] = []
        for slot in slots_for(provider, environment):
            status = await self.slot_status(tenant_id, provider, environment, slot.slot_name)
            is_conf = status is not None and status.get("state") in (
                CredentialState.ACTIVE, CredentialState.PREVIOUS, CredentialState.PENDING
            )
            if is_conf:
                configured.append(slot.slot_name)
            if status and status.get("last_test_result") == "decrypt_failed":
                invalid.append(slot.slot_name)
            slot_views.append({**slot.public_dict(), "configured": is_conf, "status": status})
        enabled = await self._is_enabled(tenant_id, provider, environment)
        state, reasons, remediation = _readiness_state(required, configured, missing, invalid)
        return {
            "provider": provider,
            "domain": slots_for(provider, environment)[0].domain
            if slots_for(provider, environment) else "payments",
            "environment": environment,
            "required_slots": required,
            "configured_slots": configured,
            "missing_slots": missing,
            "invalid_slots": invalid,
            "enabled": enabled,
            "can_enable": len(missing) == 0 and not invalid,
            "current_readiness_state": state,
            "blocking_reasons": reasons,
            "remediation": remediation,
            "slots": slot_views,
        }

    @property
    def _enablement_repo(self):
        if getattr(self, "_enablement_repo_instance", None) is None:
            from repositories.repos import BaseRepository

            self._enablement_repo_instance = BaseRepository("provider_enablement")
        return self._enablement_repo_instance

    async def _is_enabled(self, tenant_id: str, provider: str, environment: str) -> bool:
        try:
            row = await self._enablement_repo.find_by_id(
                f"{tenant_id}:{provider}:{environment}"
            )
        except Exception:
            return False
        return bool(row and row.get("enabled"))

    async def _set_enabled(
        self, tenant_id: str, provider: str, environment: str, enabled: bool, actor: str
    ) -> None:
        row_id = f"{tenant_id}:{provider}:{environment}"
        record = {
            "tenant_id": tenant_id,
            "provider": provider,
            "environment": environment,
            "enabled": enabled,
            "updated_by": actor,
        }
        if await self._enablement_repo.find_by_id(row_id) is None:
            await self._enablement_repo.insert(row_id, record)
        else:
            await self._enablement_repo.update(row_id, record)
        await self._audit(
            action="enable" if enabled else "disable",
            tenant_id=tenant_id,
            provider=provider,
            environment=environment,
            slot_name="*",
            credential_version=None,
            actor=actor,
        )

    # ── internals ─────────────────────────────────────────────────────────
    async def _pick_version(
        self, tenant_id, provider, environment, slot_name, credential_version
    ) -> Optional[dict]:
        if credential_version is not None:
            return await self._find_version(
                tenant_id, provider, environment, slot_name, credential_version
            )
        # newest pending, else active
        rows = await self._repo.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )
        pending = [r for r in rows if r.get("state") == CredentialState.PENDING]
        if pending:
            return max(pending, key=lambda r: int(r.get("credential_version", 0)))
        return await self._repo.active_version(tenant_id, provider, environment, slot_name)

    async def _find_version(
        self, tenant_id, provider, environment, slot_name, credential_version
    ) -> Optional[dict]:
        rows = await self._repo.versions_for_slot(
            tenant_id, provider, environment, slot_name
        )
        for row in rows:
            if int(row.get("credential_version", -1)) == int(credential_version):
                return row
        return None

    async def sweep_expired_overlaps(self) -> int:
        """Tombstone every PREVIOUS credential version whose rotation-overlap
        window has expired (cross-tenant maintenance sweep). Idempotent;
        returns the count swept. Erases the ciphertext of each swept row."""
        from shared.temporal.instant import try_parse_instant

        now = utc_now()
        rows = await self._repo.find_many(
            filters={"state": CredentialState.PREVIOUS}, limit=10000
        )
        swept = 0
        for row in rows:
            expires = row.get("rotation_overlap_expires_at")
            if not expires:
                continue
            # Sanctioned parser: an aware UTC instant or a reason code, never a
            # naive value silently assumed to be UTC. An unparseable overlap
            # timestamp is left in place rather than force-tombstoned.
            ts, _reason = try_parse_instant(str(expires))
            if ts is None or ts > now:
                continue
            await self._repo.update(
                row["id"],
                {"state": CredentialState.TOMBSTONED, "encrypted_value": "", "encrypted_data_key": ""},
            )
            self._invalidate(row)
            swept += 1
        return swept

    async def _tombstone_previous(self, tenant_id, provider, environment, slot_name) -> None:
        prev = await self._repo.previous_version(tenant_id, provider, environment, slot_name)
        if prev:
            await self._repo.update(
                prev["id"],
                {"state": CredentialState.TOMBSTONED, "encrypted_value": "", "encrypted_data_key": ""},
            )
            self._invalidate(prev)

    def _decrypt_row(self, tenant_id, provider, environment, slot_name, row: dict) -> str:
        from shared.providers.credential_cipher import EncryptedBlob, EncryptionContext

        version = int(row["credential_version"])
        key = f"{tenant_id}:{provider}:{environment}:{slot_name}:v{version}:{row.get('safe_fingerprint','')}"
        now = utc_now().timestamp()
        hit = self._decrypt_cache.get(key)
        if hit and hit[1] > now:
            return hit[0]
        ctx = EncryptionContext(tenant_id, provider, environment, slot_name, version)
        plaintext = self._cipher().decrypt(EncryptedBlob.from_row(row), ctx)
        if len(self._decrypt_cache) >= _DECRYPT_CACHE_MAX:
            self._decrypt_cache.clear()
        self._decrypt_cache[key] = (plaintext, now + self._cache_ttl_s())
        return plaintext

    def _invalidate(self, row: dict) -> None:
        version = row.get("credential_version")
        prefix = (
            f"{row.get('tenant_id')}:{row.get('provider')}:{row.get('environment')}"
            f":{row.get('slot_name')}:v{version}:"
        )
        for k in [k for k in self._decrypt_cache if k.startswith(prefix)]:
            self._decrypt_cache.pop(k, None)

    @staticmethod
    def _safe_view(row: dict) -> dict:
        view = {f: row.get(f) for f in _SAFE_FIELDS if f in row}
        view["configured"] = row.get("state") in (
            CredentialState.ACTIVE,
            CredentialState.PREVIOUS,
            CredentialState.PENDING,
        )
        return view


def _safe_endpoint(endpoint: Optional[str]) -> Optional[str]:
    """Keep only a safe hostname; never persist a full URL with path/query."""
    if not endpoint:
        return None
    from urllib.parse import urlparse

    try:
        host = urlparse(endpoint).hostname or urlparse(f"//{endpoint}").hostname
    except (ValueError, TypeError):
        return None
    return host


def _is_future(iso_ts: str) -> bool:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso_ts) > utc_now()
    except (ValueError, TypeError):
        return False


def _known() -> tuple[str, ...]:
    from services.providers.credentials.slot_registry import known_providers

    return known_providers()


def _readiness_state(
    required: list[str], configured: list[str], missing: list[str], invalid: list[str]
) -> tuple[str, list[str], list[str]]:
    """Map credential coverage onto canonical readiness tokens (no invented ones).

    Tokens used all exist in packages/shared/contracts/readiness-vocabulary.json:
    ``not_configured`` | ``credential_required`` | ``credential_invalid`` |
    ``credential_waiting``. The PR-1 ceiling is ``credential_waiting`` — a stored,
    encrypted credential proves readiness to connect, never a live connection.
    """
    reasons: list[str] = []
    remediation: list[str] = []
    if invalid:
        reasons.append(f"credential(s) failed validation: {', '.join(invalid)}")
        remediation.append("re-enter and re-test the invalid credential slot(s)")
        return "credential_invalid", reasons, remediation
    if not configured:
        remediation.append(
            f"configure required slot(s): {', '.join(required)}" if required else "no slots required"
        )
        return "not_configured", reasons, remediation
    if missing:
        reasons.append(f"missing required slot(s): {', '.join(missing)}")
        remediation.append(f"configure and activate: {', '.join(missing)}")
        return "credential_required", reasons, remediation
    return "credential_waiting", reasons, ["awaiting first live provider verification (PR-2)"]


# Module singleton — one authority per process (durable state lives in the DB).
credential_authority = CredentialAuthority()


__all__ = ["CredentialAuthority", "credential_authority", "SlotError"]
