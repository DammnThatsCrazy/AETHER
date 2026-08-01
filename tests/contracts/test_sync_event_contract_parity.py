"""TS <-> Python parity for the client-sync feed contract (C1).

`packages/shared/sync-event.ts` and `shared/client_sync/models.py` are
hand-authored twins. Pins the exactly-ten change-type vocabulary and the
SyncEvent / ClientSyncResponse field sets. Wire fields are snake_case
(decision-log D6).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.client_sync.models import (  # noqa: E402
    SYNC_CHANGE_TYPES,
    ClientSyncResponse,
    SyncEvent,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "sync-event.ts"

# The ten change types are a fixed contract, not just TS<->Py parity.
EXPECTED_CHANGE_TYPES = {
    "notification_changed",
    "continuation_changed",
    "saved_view_changed",
    "conversation_changed",
    "watchlist_changed",
    "incident_changed",
    "command_receipt_changed",
    "preference_changed",
    "session_revoked",
    "installation_revoked",
}


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in sync-event.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S
    )
    assert m, f"interface {interface} not found in sync-event.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_change_types_are_the_canonical_ten():
    assert set(SYNC_CHANGE_TYPES) == EXPECTED_CHANGE_TYPES
    assert len(SYNC_CHANGE_TYPES) == 10


def test_change_types_parity():
    assert set(_const_array("syncChangeTypes")) == set(SYNC_CHANGE_TYPES)


def test_sync_event_field_parity():
    ts_fields = _interface_fields("SyncEvent")
    py_fields = set(SyncEvent.model_fields.keys())
    assert ts_fields == py_fields, (
        f"SyncEvent drift: TS-only={ts_fields - py_fields}, PY-only={py_fields - ts_fields}"
    )


def test_client_sync_response_field_parity():
    assert _interface_fields("ClientSyncResponse") == set(ClientSyncResponse.model_fields)


def test_barrel_exports_sync_event():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './sync-event';" in index
