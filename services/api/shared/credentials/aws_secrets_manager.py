"""AWS Secrets Manager credential backend.

``boto3`` is imported lazily INSIDE methods so importing this module never
requires the AWS SDK. If boto3 or the required configuration is missing, methods
raise :class:`CredentialBackendNotConfigured`. No boto3 types appear in any
signature.

Secret material is stored as the revealed-plaintext JSON of the structured
credential (the same serialization the local backend encrypts); Secrets Manager
provides encryption at rest and rotation. Masked, secret-free metadata is kept
in the secret's tags/description-free JSON envelope so ``metadata``/``list`` can
answer without decrypting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.credentials.interface import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    CredentialBackend,
    CredentialBackendHealth,
    CredentialBackendNotConfigured,
    CredentialMetadata,
    make_metadata,
)
from shared.credentials.types import (
    StructuredCredential,
    as_structured,
    from_plaintext_json,
    masked_identifier,
    masked_metadata,
    to_plaintext_json,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.credentials.aws_secrets_manager")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AwsSecretsManagerCredentialBackend(CredentialBackend):
    """Credential backend backed by AWS Secrets Manager (lazy boto3)."""

    def __init__(
        self,
        secret_prefix: str = "aether/credentials",
        region: Optional[str] = None,
    ) -> None:
        self._prefix = secret_prefix.rstrip("/")
        self._region = region
        self._client: Optional[Any] = None

    def _secret_name(self, tenant_id: str, ref: str) -> str:
        return f"{self._prefix}/{tenant_id}/{ref}"

    def _get_client(self) -> Any:
        """Lazily build a boto3 Secrets Manager client.

        Raises :class:`CredentialBackendNotConfigured` when boto3 is unavailable
        or a client cannot be constructed (e.g. no region/credentials).
        """
        if self._client is not None:
            return self._client
        try:
            import boto3  # noqa: PLC0415 - lazy by design
        except ImportError as exc:
            raise CredentialBackendNotConfigured(
                "boto3 is required for the aws_secrets_manager credential backend"
            ) from exc
        import os

        region = self._region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not region:
            raise CredentialBackendNotConfigured(
                "AWS region not configured (set AWS_REGION) for the "
                "aws_secrets_manager credential backend"
            )
        try:
            self._client = boto3.client("secretsmanager", region_name=region)
        except Exception as exc:  # pragma: no cover - construction rarely fails offline
            raise CredentialBackendNotConfigured(
                f"could not create Secrets Manager client: {exc}"
            ) from exc
        return self._client

    async def create(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CredentialMetadata:
        cred = as_structured(credential)
        client = self._get_client()
        name = self._secret_name(tenant_id, ref)
        payload = self._envelope(cred, version=1, status=STATUS_ACTIVE, extra=metadata or {})
        try:
            client.create_secret(Name=name, SecretString=payload)
        except client.exceptions.ResourceExistsException:  # type: ignore[union-attr]
            client.put_secret_value(SecretId=name, SecretString=payload)
        return self._metadata_for(tenant_id, ref)  # type: ignore[return-value]

    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]:
        env = self._read_envelope(tenant_id, ref)
        if env is None or env.get("status") == STATUS_REVOKED:
            return None
        return from_plaintext_json(env["credential"])

    async def rotate(
        self,
        tenant_id: str,
        ref: str,
        credential: "StructuredCredential | str",
    ) -> CredentialMetadata:
        env = self._read_envelope(tenant_id, ref)
        if env is None:
            return await self.create(tenant_id, ref, credential)
        cred = as_structured(credential)
        client = self._get_client()
        payload = self._envelope(
            cred,
            version=int(env.get("version", 1)) + 1,
            status=STATUS_ACTIVE,
            extra=env.get("extra", {}),
            created_at=env.get("created_at"),
            rotated=True,
        )
        client.put_secret_value(SecretId=self._secret_name(tenant_id, ref), SecretString=payload)
        return self._metadata_for(tenant_id, ref)  # type: ignore[return-value]

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        env = self._read_envelope(tenant_id, ref)
        if env is None:
            return False
        env["status"] = STATUS_REVOKED
        env["revoked_at"] = _utc_now().isoformat()
        env["updated_at"] = env["revoked_at"]
        import json

        self._get_client().put_secret_value(
            SecretId=self._secret_name(tenant_id, ref), SecretString=json.dumps(env)
        )
        return True

    async def delete(self, tenant_id: str, ref: str) -> bool:
        client = self._get_client()
        try:
            client.delete_secret(
                SecretId=self._secret_name(tenant_id, ref),
                ForceDeleteWithoutRecovery=True,
            )
        except client.exceptions.ResourceNotFoundException:  # type: ignore[union-attr]
            return False
        return True

    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        return self._metadata_for(tenant_id, ref)

    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        client = self._get_client()
        prefix = f"{self._prefix}/{tenant_id}/"
        out: list[CredentialMetadata] = []
        paginator = client.get_paginator("list_secrets")
        for page in paginator.paginate(
            Filters=[{"Key": "name", "Values": [prefix]}]
        ):
            for entry in page.get("SecretList", []):
                name = entry.get("Name", "")
                if not name.startswith(prefix):
                    continue
                ref = name[len(prefix):]
                md = self._metadata_for(tenant_id, ref)
                if md is not None:
                    out.append(md)
        return out

    async def health_check(self) -> CredentialBackendHealth:
        try:
            self._get_client()
        except CredentialBackendNotConfigured as exc:
            return CredentialBackendHealth(
                backend="aws_secrets_manager", durable=True, healthy=False, detail=str(exc)
            )
        return CredentialBackendHealth(
            backend="aws_secrets_manager",
            durable=True,
            healthy=True,
            detail=f"prefix={self._prefix}",
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _envelope(
        self,
        cred: "StructuredCredential",
        *,
        version: int,
        status: str,
        extra: dict[str, Any],
        created_at: Optional[str] = None,
        rotated: bool = False,
    ) -> str:
        import json

        now = _utc_now().isoformat()
        return json.dumps(
            {
                "credential": to_plaintext_json(cred),
                "credential_type": cred.type,
                "version": version,
                "status": status,
                "extra": dict(extra),
                "masked_metadata": masked_metadata(cred),
                "masked_identifier": masked_identifier(cred),
                "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                "created_at": created_at or now,
                "updated_at": now,
                "rotated_at": now if rotated else None,
            }
        )

    def _read_envelope(self, tenant_id: str, ref: str) -> Optional[dict[str, Any]]:
        client = self._get_client()
        import json

        try:
            resp = client.get_secret_value(SecretId=self._secret_name(tenant_id, ref))
        except client.exceptions.ResourceNotFoundException:  # type: ignore[union-attr]
            return None
        return json.loads(resp["SecretString"])

    def _metadata_for(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        env = self._read_envelope(tenant_id, ref)
        if env is None:
            return None
        expires_raw = env.get("expires_at")
        merged = {**dict(env.get("extra", {})), **dict(env.get("masked_metadata", {}))}
        return make_metadata(
            tenant_id=tenant_id,
            ref=ref,
            credential_type=env.get("credential_type", "api_key"),
            version=int(env.get("version", 1)),
            lifecycle_status=env.get("status", STATUS_ACTIVE),
            masked_identifier=str(env.get("masked_identifier", "****")),
            created_at=datetime.fromisoformat(env["created_at"]),
            updated_at=datetime.fromisoformat(env["updated_at"]),
            rotated_at=datetime.fromisoformat(env["rotated_at"]) if env.get("rotated_at") else None,
            revoked_at=datetime.fromisoformat(env["revoked_at"]) if env.get("revoked_at") else None,
            expires_at=datetime.fromisoformat(expires_raw) if expires_raw else None,
            extra=merged,
        )


__all__ = ["AwsSecretsManagerCredentialBackend"]
