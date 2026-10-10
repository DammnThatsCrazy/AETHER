"""Kyber device trust — the BYOD plane.

Kyber runs on personal machines. That is a deliberate choice, not a compromise:
buying laptops does not make a device trustworthy, and pretending it does tends
to replace real controls with an inventory list. What the platform does instead
is refuse to treat any device as trusted until **three independent things** line
up, each verified server-side and each revocable:

1. **A WebAuthn platform credential** with ``userVerification: required``
   (:mod:`.webauthn`) — proves *who*.
2. **A browser-profile-bound device-proof key** (:mod:`.device_proof`) — a
   non-extractable ECDSA P-256 keypair whose private half never leaves the
   browser profile it was generated in. Proves *where from*.
3. **A server-issued, approved device grant** (:mod:`.approvals`) — a
   second-actor decision the platform can withdraw in one write. Proves
   *permitted*.

The second factor is the one that is easy to leave out and expensive to omit.
Platform passkeys **sync** across an operator's personal machines through their
personal account. A credential enrolled on a laptop will be offered on the
operator's other laptop, and an assertion made there verifies perfectly well.
It still fails, because that machine holds neither the proof key nor an approved
grant — it is a new device, pending, until someone else approves it.

:mod:`.risk` turns the by-products of enforcing all this — counter regressions,
proof-failure bursts, withdrawn approvals, browser-family changes — into a
deterministic, explainable risk state stored alongside the device.
"""
from __future__ import annotations

from .approvals import (
    GRANT_COOKIE_NAME,
    MAX_REGISTRATION_DAYS,
    MIN_REGISTRATION_DAYS,
    USABILITY_REASONS,
    DeviceApprovalService,
    device_approval_service,
    grant_hash,
)
from .device_proof import (
    DeviceProofService,
    device_proof_service,
    load_p256_public_key,
)
from .repository import (
    DeviceApprovalEventRepository,
    DeviceProofChallengeRepository,
    DeviceProofKeyRepository,
    TrustedDeviceRepository,
    WebAuthnChallengeRepository,
    WebAuthnCredentialRepository,
)
from .risk import DeviceRiskService, browser_family, device_risk_service
from .webauthn import (
    SETTINGS_NEEDED,
    WEBAUTHN_AVAILABLE,
    WebAuthnService,
    relying_party,
    webauthn_service,
)

__all__ = [
    "GRANT_COOKIE_NAME",
    "MAX_REGISTRATION_DAYS",
    "MIN_REGISTRATION_DAYS",
    "SETTINGS_NEEDED",
    "USABILITY_REASONS",
    "WEBAUTHN_AVAILABLE",
    "DeviceApprovalEventRepository",
    "DeviceApprovalService",
    "DeviceProofChallengeRepository",
    "DeviceProofKeyRepository",
    "DeviceProofService",
    "DeviceRiskService",
    "TrustedDeviceRepository",
    "WebAuthnChallengeRepository",
    "WebAuthnCredentialRepository",
    "WebAuthnService",
    "browser_family",
    "device_approval_service",
    "device_proof_service",
    "device_risk_service",
    "grant_hash",
    "load_p256_public_key",
    "relying_party",
    "webauthn_service",
]
