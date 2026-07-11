"""PR-A (root-suite coverage) — central consent PolicyDecision engine + the
signal-use matrix runtime reader. Runs under `make ci-check` / python-tests.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.policy import signal_use_matrix as matrix  # noqa: E402
from services.policy.engine import ConsentPolicyEngine  # noqa: E402
import services.security.audit_ledger as audit_mod  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    audit_mod._TENANT_TAIL.clear()
    audit_mod._TENANT_SEQ.clear()
    yield
    reset_in_memory_stores()


# --- signal-use matrix runtime reader (pure) --- #
def test_matrix_exact_purpose_and_no_link_for_fingerprint():
    assert matrix.required_purposes("credit") == ["credit"]
    assert matrix.explicit_opt_in_required("credit") is True
    assert matrix.explicit_opt_in_required("analytics") is False
    assert matrix.allows("device_fingerprint", "allow_identity_linking") is False


def test_validator_passes():
    from scripts import validate_policy_decisions as v

    assert v.main() == 0


# --- engine decisions --- #
async def test_engine_denies_without_exact_purpose():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="export_data", resource_type="export",
        purpose="credit", granted_purposes=["analytics", "marketing"],
    )
    assert d.allowed is False
    assert d.missing_purposes == ["credit"]
    assert d.policy_decision_id.startswith("cpd_")


async def test_engine_allows_with_consent_and_records_sensitive():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="render_profile360",
        resource_type="profile360.web2", purpose="credit", granted_purposes=["credit"],
    )
    assert d.allowed is True
    assert any(x["policy_decision_id"] == d.policy_decision_id
               for x in await eng.list_decisions("t1"))
