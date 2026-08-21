"""TS <-> Python parity for the notification contract (C2).

`packages/shared/notification.ts` is a hand-authored twin of the
Python-authoritative `services/notification_intelligence/models.py`. The
vocabularies include values outside `[a-z_]` (``P0``..``P3``, ``action-request``),
so this test scrapes the const arrays with a permissive quote regex and compares
against `{e.value for e in Enum}`. Event field sets use the standard snake_case
scrape against `model_fields`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.notification_intelligence.models import (  # noqa: E402
    IntelligenceNotificationEvent,
    NotificationClass,
    NotificationLifecycleState,
    NotificationSeverity,
    OperatorActionType,
)
from services.notification_intelligence.projection import (  # noqa: E402
    PROJECTION_FIELDS,
    MobileNotificationProjection,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "notification.ts"


def _const_array(name: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in notification.ts"
    # Permissive: values include 'P0' and 'action-request'.
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in notification.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def _enum_values(enum) -> set[str]:
    return {e.value for e in enum}


def test_lifecycle_states_parity():
    assert _const_array("notificationLifecycleStates") == _enum_values(NotificationLifecycleState)


def test_severities_parity():
    assert _const_array("notificationSeverities") == _enum_values(NotificationSeverity)


def test_classes_parity():
    assert _const_array("notificationClasses") == _enum_values(NotificationClass)


def test_operator_action_types_parity():
    assert _const_array("operatorActionTypes") == _enum_values(OperatorActionType)


def test_event_field_parity():
    ts = _interface_fields("IntelligenceNotificationEvent")
    py = set(IntelligenceNotificationEvent.model_fields.keys())
    assert ts == py, f"IntelligenceNotificationEvent drift: TS-only={ts - py}, PY-only={py - ts}"


def test_projection_shape_parity():
    """MobileNotificationProjection (projection.py) ↔ notification.ts twin."""
    ts = _interface_fields("MobileNotificationProjection")
    py = set(MobileNotificationProjection.model_fields.keys())
    assert ts == py, (
        f"MobileNotificationProjection drift: TS-only={ts - py}, PY-only={py - ts}"
    )


def test_projection_fields_on_event_parity():
    """The redacted push-projection fields must be carried by the canonical
    notification event on BOTH sides (so a push never needs a second record)."""
    event_ts = _interface_fields("IntelligenceNotificationEvent")
    event_py = set(IntelligenceNotificationEvent.model_fields.keys())
    assert set(PROJECTION_FIELDS) <= event_ts, f"TS missing {set(PROJECTION_FIELDS) - event_ts}"
    assert set(PROJECTION_FIELDS) <= event_py, f"PY missing {set(PROJECTION_FIELDS) - event_py}"


def test_barrel_exports_notification():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './notification';" in index
