"""TS <-> Python parity for the delivery receipt/attempt contract (C2).

`packages/shared/delivery-receipt.ts` is a hand-authored twin of the
Python-authoritative delivery models (`services/delivery/models.py`). The enum
vocabularies are `str, Enum` classes, so the parity compares against
`{e.value for e in Enum}` (the template variant for enum-backed vocab). Field sets
are compared against `model_fields`. Wire fields are snake_case.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.delivery.models import (  # noqa: E402
    DeliveryAttempt,
    DeliveryAttemptOutcome,
    DeliveryChannel,
    DeliveryJobState,
    ExternalOutcomeType,
    ProviderReceipt,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "delivery-receipt.ts"


def _const_array(name: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in delivery-receipt.ts"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in delivery-receipt.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def _enum_values(enum) -> set[str]:
    return {e.value for e in enum}


def test_delivery_channels_parity():
    assert _const_array("deliveryChannels") == _enum_values(DeliveryChannel)


def test_delivery_job_states_parity():
    assert _const_array("deliveryJobStates") == _enum_values(DeliveryJobState)


def test_delivery_attempt_outcomes_parity():
    assert _const_array("deliveryAttemptOutcomes") == _enum_values(DeliveryAttemptOutcome)


def test_external_outcome_types_parity():
    assert _const_array("externalOutcomeTypes") == _enum_values(ExternalOutcomeType)


def test_provider_receipt_field_parity():
    ts = _interface_fields("ProviderReceipt")
    py = set(ProviderReceipt.model_fields.keys())
    assert ts == py, f"ProviderReceipt drift: TS-only={ts - py}, PY-only={py - ts}"


def test_delivery_attempt_field_parity():
    ts = _interface_fields("DeliveryAttempt")
    py = set(DeliveryAttempt.model_fields.keys())
    assert ts == py, f"DeliveryAttempt drift: TS-only={ts - py}, PY-only={py - ts}"


def test_barrel_exports_delivery_receipt():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './delivery-receipt';" in index
