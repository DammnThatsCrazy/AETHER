"""Synthetic evidence for pattern discovery tests.

``normal_traffic`` is a population following ordinary product flows with
per-user devices, IPs and cards. ``fraud_ring`` is 14 accounts sharing two
devices, one IP, one card fingerprint and one destination wallet, running the
same card-testing sequence in lockstep, with an unmodelled ``partner_ref``
field that links them.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

T = "tenant-pd"
RING_SIZE = 14


def ev(i, entity_field, entity_id, event_type, ts, tenant=T, source="sdk", **props):
    row = {"tenant_id": tenant, "event_id": f"e{i}", "event_type": event_type, "source": source,
           "occurred_at": ts.isoformat(), "properties": props}
    row[entity_field] = entity_id
    return row


def normal_traffic(seed: int, day: int, users: int = 200, tenant: str = T) -> list[dict]:
    rnd = random.Random(seed)
    rows: list[dict] = []
    i = seed * 100_000
    base = datetime(2026, 11, day, 8, tzinfo=timezone.utc)
    for u in range(users):
        t = base + timedelta(minutes=rnd.randint(0, 600))
        flow = ["page_view", "login", "browse", "browse", "add_to_cart"]
        if rnd.random() < 0.6:
            flow.append("checkout")
        for et in flow:
            t += timedelta(seconds=rnd.randint(5, 120))
            i += 1
            props = {"device_id": f"dev-{u}", "ip": f"10.0.{u % 250}.{rnd.randint(1, 250)}"}
            if et == "checkout":
                props.update(status="succeeded", amount=rnd.randint(5, 80), card_fingerprint=f"cf_{u}")
            rows.append(ev(i, "user_id", f"u{u}", et, t, tenant=tenant, **props))
    return rows


def fraud_ring(day: int, tenant: str = T) -> list[dict]:
    rows: list[dict] = []
    i = 900_000
    base = datetime(2026, 11, day, 14, tzinfo=timezone.utc)
    for k in range(RING_SIZE):
        for rep in range(2):
            t = base + timedelta(minutes=rep * 90, seconds=k * 2)
            steps = [("login", {}), ("add_card", {"status": "declined"}), ("add_card", {"status": "declined"}),
                     ("add_card", {"status": "approved"}), ("withdraw", {"amount": 900, "to": "0x" + "c" * 40})]
            for et, extra in steps:
                t += timedelta(seconds=20)
                i += 1
                props = {"device_id": f"ringdev-{k % 2}", "ip": "203.0.113.7", "card_fingerprint": "cf_ring",
                         "partner_ref": f"PX-{k % 3}", **extra}
                if et == "withdraw":
                    props["note"] = f"withdrawal to external wallet ref {k} failed kyc check 22"
                rows.append(ev(i, "user_id", f"r{k}", et, t, tenant=tenant, **props))
    return rows


def ring_keys() -> set[str]:
    return {f"user:r{k}" for k in range(RING_SIZE)}


class FakeEventReader:
    """Stands in for AnalyticsRepository.query_events."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple] = []

    async def query_events(self, tenant_id, params, limit=100):
        self.calls.append((tenant_id, dict(params), limit))
        return [r for r in self.rows if r.get("tenant_id") == tenant_id][:limit]


class FakeRiskStore:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    async def upsert_scoped(self, tenant_id, natural_id, data):
        self.rows[(tenant_id, natural_id)] = data
        return data


class ConsentResult:
    def __init__(self, allowed, receipt_id=None, reason_code=None):
        self.allowed, self.receipt_id, self.reason_code = allowed, receipt_id, reason_code


def consent_reader(denied: frozenset = frozenset()):
    """Grants analytics consent to every subject except ``denied`` ids."""
    calls = []

    async def reader(*, tenant_id, subject_id, anonymous_id, purpose):
        calls.append((tenant_id, subject_id, anonymous_id, purpose))
        ident = subject_id or anonymous_id
        if ident in denied:
            return ConsentResult(False, reason_code="consent_receipt_missing")
        return ConsentResult(True, receipt_id=f"rcpt-{ident}")

    reader.calls = calls
    return reader
