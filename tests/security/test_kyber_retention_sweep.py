"""The Kyber retention sweeper must delete finished state and nothing else.

Two failure modes matter here and they are not symmetric. A sweeper that
deletes too little leaves rows to accumulate — an operational problem. A
sweeper that deletes too much destroys either a live operator session (an
outage, mid-incident) or security evidence (an investigation that can no longer
be run). The tests below weight accordingly: every deletion path is checked
once, and every *protection* — live sessions, in-window rows, legal-class
evidence tables, legal holds — is checked explicitly.

The window assertions exist because this module was written to close a gap
where the correct retention window was computed and then never applied. Proving
the cutoff moves when the configured window moves is the whole point: a
hardcoded 7 would rebuild that bug one layer up.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-retention-test")

from repositories.repos import BaseRepository, reset_in_memory_stores  # noqa: E402
from services.kyber.access.contracts import SessionStatus  # noqa: E402
from services.kyber.retention import (  # noqa: E402
    ALL_SESSION_STATUSES,
    KYBER_EVIDENCE_TABLES,
    LIVE_SESSION_STATUSES,
    SWEEP_RULES,
    SWEPT_RESOURCE_TYPES,
    TERMINAL_SESSION_STATUSES,
    KyberRetentionSweeper,
    build_kyber_retention_coro,
)
from shared.temporal.clock import FixedClock  # noqa: E402

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


class _Table(BaseRepository):
    """Concrete repository over one table, for seeding rows."""

    def __init__(self, table_name: str) -> None:
        super().__init__(table_name)


class _NoHolds:
    """Legal-hold repository stub with no holds."""

    async def find_many(self, filters=None, limit=50, offset=0, **kwargs) -> list[dict]:
        return []


class _OneHold:
    """Legal-hold repository stub with a single active, unscoped hold."""

    def __init__(self, resource_type: str = "") -> None:
        self.resource_type = resource_type

    async def find_many(self, filters=None, limit=50, offset=0, **kwargs) -> list[dict]:
        if offset:
            return []
        return [
            {
                "hold_id": "hold_test",
                "tenant_id": "t1",
                "resource_type": self.resource_type,
                "status": "active",
            }
        ]


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _sweeper(**kwargs: Any) -> KyberRetentionSweeper:
    kwargs.setdefault("clock", FixedClock(NOW))
    kwargs.setdefault("short_lived_days", 7)
    kwargs.setdefault("hold_repo", _NoHolds())
    kwargs.setdefault("audit_enabled", False)
    return KyberRetentionSweeper(**kwargs)


def _iso(delta_days: float = 0.0) -> str:
    return (NOW - timedelta(days=delta_days)).isoformat()


async def _seed_session(session_id: str, *, status: str, age_days: float) -> None:
    await _Table("kyber_workforce_sessions").insert(
        session_id,
        {
            "session_id": session_id,
            "token_hash": f"hash-{session_id}",
            "operator_id": "op-1",
            "status": status,
            "created_at": _iso(age_days + 1),
            "updated_at": _iso(age_days),
            "revoked_at": _iso(age_days) if status in ("revoked", "expired") else None,
        },
    )


async def _seed_challenge(
    challenge_id: str,
    *,
    table: str = "kyber_webauthn_challenges",
    consumed: bool = False,
    expires_in_minutes: float = 5.0,
    age_days: float = 1.0,
) -> None:
    await _Table(table).insert(
        challenge_id,
        {
            "challenge_id": challenge_id,
            "challenge": "opaque",
            "subject_id": "op-1",
            "purpose": "registration",
            "issued_at": _iso(age_days),
            "expires_at": (NOW + timedelta(minutes=expires_in_minutes)).isoformat(),
            "consumed_at": _iso(age_days) if consumed else None,
        },
    )


async def _ids(table: str) -> set[str]:
    rows = await _Table(table).find_many({}, limit=500)
    return {str(r.get("id")) for r in rows}


# ── Live state is never swept ────────────────────────────────────────────────

@pytest.mark.parametrize("status", sorted(LIVE_SESSION_STATUSES))
async def test_live_session_is_never_swept_regardless_of_age(status):
    """Age is not a reason to end a session. Only ending it is."""
    await _seed_session("ks-live", status=status, age_days=4000)

    result = await _sweeper().sweep_table("kyber_workforce_sessions")

    assert result["deleted"] == 0
    assert await _ids("kyber_workforce_sessions") == {"ks-live"}


async def test_session_status_literals_are_fully_classified():
    """A new SessionStatus must be classified, not silently treated as terminal."""
    declared = {str(v) for v in get_args(SessionStatus)}
    assert declared == ALL_SESSION_STATUSES
    assert TERMINAL_SESSION_STATUSES | LIVE_SESSION_STATUSES == declared
    assert not (TERMINAL_SESSION_STATUSES & LIVE_SESSION_STATUSES)


# ── Terminal state ages out ──────────────────────────────────────────────────

async def test_revoked_session_older_than_window_is_swept():
    await _seed_session("ks-old", status="revoked", age_days=30)

    result = await _sweeper().sweep_table("kyber_workforce_sessions")

    assert result["deleted"] == 1
    assert await _ids("kyber_workforce_sessions") == set()


async def test_revoked_session_inside_window_is_kept():
    await _seed_session("ks-recent", status="revoked", age_days=2)

    result = await _sweeper().sweep_table("kyber_workforce_sessions")

    assert result["deleted"] == 0
    assert await _ids("kyber_workforce_sessions") == {"ks-recent"}


async def test_expired_session_older_than_window_is_swept():
    await _seed_session("ks-exp", status="expired", age_days=30)

    assert (await _sweeper().sweep_table("kyber_workforce_sessions"))["deleted"] == 1


async def test_step_up_grant_is_swept_only_once_terminal_and_aged():
    repo = _Table("kyber_step_up_grants")
    await repo.insert(
        "su-live",
        {
            "grant_id": "su-live",
            "session_id": "ks-1",
            "operator_id": "op-1",
            "created_at": _iso(0.001),
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        },
    )
    await repo.insert(
        "su-consumed",
        {
            "grant_id": "su-consumed",
            "session_id": "ks-1",
            "operator_id": "op-1",
            "created_at": _iso(31),
            "updated_at": _iso(30),
            "expires_at": _iso(30),
            "consumed_at": _iso(30),
        },
    )
    await repo.insert(
        "su-expired-recent",
        {
            "grant_id": "su-expired-recent",
            "session_id": "ks-1",
            "operator_id": "op-1",
            "created_at": _iso(1),
            "updated_at": _iso(1),
            "expires_at": _iso(1),
        },
    )

    result = await _sweeper().sweep_table("kyber_step_up_grants")

    assert result["deleted"] == 1
    assert await _ids("kyber_step_up_grants") == {"su-live", "su-expired-recent"}


@pytest.mark.parametrize(
    "table", ["kyber_webauthn_challenges", "kyber_device_proof_challenges"]
)
async def test_consumed_challenge_is_swept_and_live_one_is_not(table):
    await _seed_challenge("ch-consumed", table=table, consumed=True, age_days=1)
    await _seed_challenge(
        "ch-live", table=table, consumed=False, expires_in_minutes=5, age_days=0.0
    )

    result = await _sweeper().sweep_table(table)

    assert result["deleted"] == 1
    assert await _ids(table) == {"ch-live"}


async def test_expired_challenge_inside_the_derived_floor_is_kept():
    """The floor is derived from the policy window, so it is not zero."""
    await _Table("kyber_webauthn_challenges").insert(
        "ch-just-expired",
        {
            "challenge_id": "ch-just-expired",
            "subject_id": "op-1",
            "purpose": "registration",
            "created_at": (NOW - timedelta(minutes=10)).isoformat(),
            "updated_at": (NOW - timedelta(minutes=10)).isoformat(),
            "expires_at": (NOW - timedelta(minutes=5)).isoformat(),
        },
    )

    result = await _sweeper().sweep_table("kyber_webauthn_challenges")

    assert result["deleted"] == 0
    assert await _ids("kyber_webauthn_challenges") == {"ch-just-expired"}


# ── Evidence is untouchable ──────────────────────────────────────────────────

async def test_full_sweep_never_touches_legal_class_evidence_tables():
    """Security evidence must outlive the session that produced it."""
    for table in KYBER_EVIDENCE_TABLES:
        await _Table(table).insert(
            f"ev-{table}",
            {
                "id": f"ev-{table}",
                "operator_id": "op-1",
                "status": "revoked",
                "consumed_at": _iso(4000),
                "revoked_at": _iso(4000),
                "expires_at": _iso(4000),
                "created_at": _iso(4001),
                "updated_at": _iso(4000),
            },
        )
    await _seed_session("ks-old", status="revoked", age_days=4000)

    summary = await _sweeper().sweep()

    assert summary["deleted_total"] == 1
    for table in KYBER_EVIDENCE_TABLES:
        assert await _ids(table) == {f"ev-{table}"}, f"{table} lost evidence rows"


async def test_evidence_tables_are_classed_legal_and_never_ruled():
    """The guard is the policy registry, not just the absence of a rule."""
    sweeper = _sweeper()
    for table in KYBER_EVIDENCE_TABLES:
        policy = sweeper.policy(table)
        assert policy.retention_class == "legal", table
        assert policy.delete_behavior == "preserve", table
        assert table not in SWEPT_RESOURCE_TYPES


async def test_a_legal_class_table_is_refused_even_if_asked_directly():
    await _Table("kyber_access_decisions").insert(
        "dec-1", {"id": "dec-1", "status": "revoked", "created_at": _iso(4000)}
    )

    result = await _sweeper().sweep_table("kyber_access_decisions")

    assert result["status"] == "skipped"
    assert result["deleted"] == 0
    assert await _ids("kyber_access_decisions") == {"dec-1"}


async def test_every_swept_table_is_short_lived_hard_delete_in_the_registry():
    sweeper = _sweeper()
    for rule in SWEEP_RULES:
        policy = sweeper.policy(rule.resource_type)
        assert policy.retention_class == "short_lived", rule.resource_type
        assert policy.delete_behavior == "hard_delete", rule.resource_type


async def test_active_legal_hold_blocks_the_sweep():
    await _seed_session("ks-old", status="revoked", age_days=4000)

    result = await _sweeper(hold_repo=_OneHold()).sweep_table("kyber_workforce_sessions")

    assert result["status"] == "skipped"
    assert result["reason"] == "legal_hold_active"
    assert await _ids("kyber_workforce_sessions") == {"ks-old"}


# ── The window comes from configuration, not a constant ──────────────────────

async def test_cutoff_moves_with_the_configured_short_lived_window():
    """A hardcoded window would rebuild the bug this module closes."""
    short = await _sweeper(short_lived_days=1).sweep_table("kyber_workforce_sessions")
    long = await _sweeper(short_lived_days=90).sweep_table("kyber_workforce_sessions")

    assert short["window_seconds"] == timedelta(days=1).total_seconds()
    assert long["window_seconds"] == timedelta(days=90).total_seconds()
    assert short["cutoff"] > long["cutoff"]
    assert short["retention_class"] == "short_lived"


async def test_a_session_swept_at_seven_days_survives_a_ninety_day_window():
    await _seed_session("ks-30d", status="revoked", age_days=30)

    kept = await _sweeper(short_lived_days=90).sweep_table("kyber_workforce_sessions")
    assert kept["deleted"] == 0
    assert await _ids("kyber_workforce_sessions") == {"ks-30d"}

    swept = await _sweeper(short_lived_days=7).sweep_table("kyber_workforce_sessions")
    assert swept["deleted"] == 1


async def test_challenge_floor_is_derived_from_the_window_not_a_second_knob():
    rule = next(r for r in SWEEP_RULES if r.resource_type == "kyber_webauthn_challenges")
    narrow = _sweeper(short_lived_days=7).window_for(rule)
    wide = _sweeper(short_lived_days=70).window_for(rule)

    assert narrow == timedelta(days=7) / rule.window_divisor
    assert wide == narrow * 10
    assert narrow < timedelta(days=7)


# ── Bounded work per run ─────────────────────────────────────────────────────

async def test_per_run_cap_bounds_deletions_and_reports_more_remaining():
    for i in range(5):
        await _seed_session(f"ks-{i}", status="revoked", age_days=30)

    sweeper = _sweeper(max_per_table=2)
    first = await sweeper.sweep_table("kyber_workforce_sessions")

    assert first["deleted"] == 2
    assert first["more_remaining"] is True
    assert len(await _ids("kyber_workforce_sessions")) == 3

    second = await sweeper.sweep_table("kyber_workforce_sessions")
    third = await sweeper.sweep_table("kyber_workforce_sessions")
    assert second["deleted"] == 2
    assert third["deleted"] == 1
    assert third["more_remaining"] is False
    assert await _ids("kyber_workforce_sessions") == set()


# ── Run summary + worker wiring ──────────────────────────────────────────────

async def test_sweep_summary_reports_every_table_and_audits_once():
    recorded: list[dict[str, Any]] = []

    class _Ledger:
        async def record(self, **kwargs):
            recorded.append(kwargs)
            return kwargs

    import services.security.audit_ledger as ledger_module

    original = ledger_module.audit_ledger
    ledger_module.audit_ledger = _Ledger()  # type: ignore[assignment]
    try:
        await _seed_session("ks-old", status="revoked", age_days=30)
        summary = await _sweeper(audit_enabled=True).sweep()
    finally:
        ledger_module.audit_ledger = original  # type: ignore[assignment]

    assert set(summary["tables"]) == set(SWEPT_RESOURCE_TYPES)
    assert summary["deleted_total"] == 1
    assert not summary["errors"]
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["event_type"] == "kyber.retention.swept"
    assert entry["actor_id"] == "system"
    assert entry["resource_type"] == "kyber_retention"
    assert entry["outcome"] == "allowed"
    assert entry["metadata"]["deleted_by_resource_type"]["kyber_workforce_sessions"] == 1


async def test_unknown_resource_type_is_not_swept():
    result = await _sweeper().sweep_table("kyber_not_a_table")

    assert result["status"] == "skipped"
    assert result["deleted"] == 0


async def test_worker_spec_is_registered_under_the_maintenance_role():
    from services.runtime.roles import ROLE_TO_SPEC_NAMES

    assert "kyber_retention_sweep" in ROLE_TO_SPEC_NAMES["maintenance"]


async def test_build_coro_factory_returns_a_fresh_coroutine():
    first = build_kyber_retention_coro()
    second = build_kyber_retention_coro()
    assert first is not second
    first.close()
    second.close()
