"""PR-B — durable value snapshot persistence (write -> read back)."""
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
from services.value.repositories import ValueSnapshotService  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def test_record_and_list_valuation_snapshot():
    svc = ValueSnapshotService()
    await svc.record_valuation("t1", {
        "id": "v1",
        "native": {"amount": "1.5", "currency": "ETH"},
        "valuation": {"usd_value": "4500", "valuation_method": "market_price"},
    })
    rows = await svc.list_valuations("t1")
    assert len(rows) == 1
    assert rows[0]["usd_value"] == "4500"
    # Tenant isolation.
    assert await svc.list_valuations("t2") == []


async def test_record_rollup_snapshot_preserves_unpriced_and_status():
    svc = ValueSnapshotService()
    rec = await svc.record_rollup("t1", "portfolio", {
        "total_usd": None, "rollup_status": "partial",
        "unpriced_count": 2, "excluded_count": 1,
    })
    assert rec["total_usd"] is None      # unknown stays None, never 0
    assert rec["rollup_status"] == "partial"
    assert rec["unpriced_count"] == 2
