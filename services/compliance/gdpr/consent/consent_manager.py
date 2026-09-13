"""
Aether GDPR — Consent Management (Article 7)
Granular, purpose-based consent with immutable audit trail.

Purposes:  analytics | marketing | web3
Sources:   banner | settings | api | dnt
Storage:   DynamoDB with append-only audit log
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from config.compliance_config import CONSENT_CONFIG, ConsentPurpose
from shared.logger import cst_log


class ConsentAction(str, Enum):
    GRANT = "grant"
    REVOKE = "revoke"


class ConsentSource(str, Enum):
    BANNER = "cookie_banner"
    SETTINGS = "privacy_settings"
    API = "api"
    DNT = "do_not_track"


@dataclass
class ConsentRecord:
    """Immutable consent record — one per action (append-only audit trail)."""
    id: str = field(default_factory=lambda: f"cst_{uuid.uuid4().hex[:12]}")
    tenant_id: str = ""
    user_id: str = ""
    purpose: str = ""
    action: ConsentAction = ConsentAction.GRANT
    granted: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: ConsentSource = ConsentSource.BANNER
    policy_version: str = ""
    ip_address_hash: str = ""
    user_agent_hash: str = ""

    def to_dynamo_item(self) -> dict:
        return {
            "PK": f"CONSENT#{self.tenant_id}#{self.user_id}",
            "SK": f"{self.purpose}#{self.timestamp}",
            "id": self.id,
            "purpose": self.purpose,
            "action": self.action.value,
            "granted": self.granted,
            "source": self.source.value,
            "policy_version": self.policy_version,
            "ip_hash": self.ip_address_hash,
            "ua_hash": self.user_agent_hash,
            "timestamp": self.timestamp,
        }


@dataclass
class UserConsentState:
    """Current consent state for a user across all purposes."""
    tenant_id: str
    user_id: str
    purposes: dict = field(default_factory=dict)
    last_updated: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# CONSENT MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class ConsentManager:
    """
    Manages granular, purpose-based consent with full audit trail.
    Every grant/revoke is recorded as an immutable ConsentRecord.
    """

    def __init__(self):
        self._records: list = []
        self._states: dict = {}

    def _state_key(self, tenant_id: str, user_id: str) -> str:
        return f"{tenant_id}:{user_id}"

    def _get_or_create_state(self, tenant_id: str, user_id: str) -> UserConsentState:
        key = self._state_key(tenant_id, user_id)
        if key not in self._states:
            self._states[key] = UserConsentState(tenant_id=tenant_id, user_id=user_id)
        return self._states[key]

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16] if value else ""

    def grant(self, tenant_id: str, user_id: str, purpose: ConsentPurpose,
              policy_version: str = "", source: ConsentSource = ConsentSource.BANNER,
              ip_address: str = "", user_agent: str = "") -> ConsentRecord:
        """Grant consent for a specific purpose."""
        record = ConsentRecord(
            tenant_id=tenant_id, user_id=user_id,
            purpose=purpose.value, action=ConsentAction.GRANT, granted=True,
            source=source, policy_version=policy_version,
            ip_address_hash=self._hash(ip_address),
            user_agent_hash=self._hash(user_agent),
        )
        self._records.append(record)

        state = self._get_or_create_state(tenant_id, user_id)
        state.purposes[purpose.value] = True
        state.last_updated = record.timestamp

        cst_log(f"CONSENT GRANTED: {user_id} → {purpose.value} (source: {source.value})")
        return record

    def revoke(self, tenant_id: str, user_id: str, purpose: ConsentPurpose,
               source: ConsentSource = ConsentSource.SETTINGS) -> ConsentRecord:
        """Revoke consent for a specific purpose."""
        record = ConsentRecord(
            tenant_id=tenant_id, user_id=user_id,
            purpose=purpose.value, action=ConsentAction.REVOKE, granted=False,
            source=source,
        )
        self._records.append(record)

        state = self._get_or_create_state(tenant_id, user_id)
        state.purposes[purpose.value] = False
        state.last_updated = record.timestamp

        cst_log(f"CONSENT REVOKED: {user_id} → {purpose.value} (source: {source.value})")
        return record

    def grant_all(self, tenant_id: str, user_id: str,
                  policy_version: str = "", source: ConsentSource = ConsentSource.BANNER) -> list:
        """Grant consent for all purposes."""
        records = []
        for p in ConsentPurpose:
            records.append(self.grant(tenant_id, user_id, p, policy_version, source))
        return records

    def revoke_all(self, tenant_id: str, user_id: str,
                   source: ConsentSource = ConsentSource.SETTINGS) -> list:
        """Revoke consent for all purposes."""
        records = []
        for p in ConsentPurpose:
            records.append(self.revoke(tenant_id, user_id, p, source))
        return records

    def handle_dnt(self, tenant_id: str, user_id: str, dnt_value: str) -> Optional[list]:
        """Handle Do-Not-Track header. DNT:1 → revoke all."""
        if dnt_value == "1" and CONSENT_CONFIG.dnt_respected:
            cst_log(f"DNT:1 received for {user_id} — revoking all consent")
            return self.revoke_all(tenant_id, user_id, ConsentSource.DNT)
        return None

    def check_consent(self, tenant_id: str, user_id: str, purpose: ConsentPurpose) -> bool:
        """Check if user has active consent for a purpose. Used by SDK enforcement."""
        state = self._states.get(self._state_key(tenant_id, user_id))
        if not state:
            return False
        return state.purposes.get(purpose.value, False)

    def get_state(self, tenant_id: str, user_id: str) -> UserConsentState:
        """Get current consent state for a user."""
        return self._get_or_create_state(tenant_id, user_id)

    def get_audit_trail(self, tenant_id: str, user_id: str) -> list:
        """Get full audit trail for a user's consent history."""
        return [r for r in self._records
                if r.tenant_id == tenant_id and r.user_id == user_id]

    def consent_report(self, tenant_id: str) -> dict:
        """Generate consent analytics for a tenant."""
        tenant_records = [r for r in self._records if r.tenant_id == tenant_id]
        grants = sum(1 for r in tenant_records if r.action == ConsentAction.GRANT)
        revokes = sum(1 for r in tenant_records if r.action == ConsentAction.REVOKE)

        by_purpose: dict = {}
        for r in tenant_records:
            by_purpose.setdefault(r.purpose, {"grants": 0, "revokes": 0})
            if r.action == ConsentAction.GRANT:
                by_purpose[r.purpose]["grants"] += 1
            else:
                by_purpose[r.purpose]["revokes"] += 1

        return {
            "tenant_id": tenant_id,
            "total_records": len(tenant_records),
            "grants": grants,
            "revokes": revokes,
            "grant_rate": f"{grants / max(len(tenant_records), 1) * 100:.0f}%",
            "by_purpose": by_purpose,
        }

    @property
    def stats(self) -> dict:
        return {
            "total_records": len(self._records),
            "unique_users": len(self._states),
        }
