"""GovernanceDomain twin parity: backend Literal ↔ TS public union.

``services/security/contracts.py`` (backend ``GovernanceDomain`` Literal) and
``packages/shared/security-governance.ts`` (exported ``GovernanceDomain`` union)
must enumerate the same domain set — the frontend types every governance-domain
payload (roles, grants, capability surfacing) against the TS union, and the
backend authorizes against the Python Literal.  A domain added on one side only
silently widens the other's accept/reject behavior, so this test pins the two
sets together (and doubles as the ownership-map pairing surface for a
``package_public_type`` change).

The union is parsed textually so the assertion is a value-set comparison, not an
import of the compiled package.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import get_args

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.security.contracts import GovernanceDomain  # noqa: E402

TS_TWIN = Path(__file__).resolve().parents[2] / "packages" / "shared" / "security-governance.ts"


def _ts_governance_domains() -> set[str]:
    """Extract the quoted ``| '...'`` members of the GovernanceDomain union.

    A line scan rather than a ``(.*?);`` regex because the block's own trailing
    comment contains semicolons (``...administration; ``kyber_tenant`` ...``) that
    would otherwise truncate the capture before the last members.
    """
    source = TS_TWIN.read_text(encoding="utf-8")
    lines = source.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("export type GovernanceDomain")
    )
    members: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue  # blank or comment lines inside the union
        match = re.match(r"\| '([a-zA-Z0-9_]+)'", stripped)
        if match is not None:
            members.append(match.group(1))
            continue
        break  # reached the next declaration — union terminated
    assert members, "GovernanceDomain union members not found in security-governance.ts"
    return set(members)


def _py_governance_domains() -> set[str]:
    return set(get_args(GovernanceDomain))


def test_ts_union_matches_backend_literal() -> None:
    ts = _ts_governance_domains()
    py = _py_governance_domains()
    assert ts == py, (
        "GovernanceDomain twin drift: "
        f"TS-only={sorted(ts - py)} python-only={sorted(py - ts)}. "
        "Update BOTH packages/shared/security-governance.ts and "
        "services/security/contracts.py GovernanceDomain."
    )


def test_data_exchange_domain_is_in_both_sides() -> None:
    """Regression anchor for the Data Exchange RBAC integration (M3)."""
    assert "data_exchange" in _ts_governance_domains()
    assert "data_exchange" in _py_governance_domains()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
