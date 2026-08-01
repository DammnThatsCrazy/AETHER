"""TS <-> Python parity for the mobile installation contract (C3).

`packages/shared/installation.ts` and `shared/mobile/models.py` are hand-authored
twins. Pins the platform / app-kind / push-provider / trust-state vocabularies and
the MobileInstallation / InstallationRegistration / PushSubscription /
InstallationRevocation field sets. Wire fields are snake_case.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.mobile.models import (  # noqa: E402
    INSTALLATION_APP_KINDS,
    INSTALLATION_PLATFORMS,
    INSTALLATION_TRUST_STATES,
    PUSH_PROVIDERS,
    InstallationRegistration,
    InstallationRevocation,
    MobileInstallation,
    PushSubscription,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "installation.ts"


def _const_array(name: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in installation.ts"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in installation.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_platforms_parity():
    assert _const_array("installationPlatforms") == set(INSTALLATION_PLATFORMS)


def test_app_kinds_parity():
    assert _const_array("installationAppKinds") == set(INSTALLATION_APP_KINDS)


def test_push_providers_parity():
    assert _const_array("pushProviders") == set(PUSH_PROVIDERS)


def test_trust_states_parity():
    assert _const_array("installationTrustStates") == set(INSTALLATION_TRUST_STATES)


def test_installation_field_parity():
    ts = _interface_fields("MobileInstallation")
    py = set(MobileInstallation.model_fields.keys())
    assert ts == py, f"MobileInstallation drift: TS-only={ts - py}, PY-only={py - ts}"


def test_registration_field_parity():
    assert _interface_fields("InstallationRegistration") == set(InstallationRegistration.model_fields)


def test_push_subscription_field_parity():
    ts = _interface_fields("PushSubscription")
    py = set(PushSubscription.model_fields.keys())
    assert ts == py, f"PushSubscription drift: TS-only={ts - py}, PY-only={py - ts}"


def test_revocation_field_parity():
    assert _interface_fields("InstallationRevocation") == set(InstallationRevocation.model_fields)


def test_barrel_exports_installation():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './installation';" in index
