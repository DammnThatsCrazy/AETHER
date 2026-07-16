"""Tests for validated tenant-specific reconciliation expectations."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from services.reconciliation.expectations import (
    ExpectationConfigError,
    get_expectation,
    registry_snapshot,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_tenant_override_inherits_defaults_without_cross_tenant_leakage(tmp_path):
    config = _write(
        tmp_path / "expectations.json",
        {
            "version": 1,
            "defaults": {
                "sessions": {"freshness_sla_seconds": 7200},
            },
            "tenants": {
                "tenant-strict": {
                    "sessions": {"min_events": 5},
                }
            },
        },
    )

    strict = get_expectation("sessions", "tenant-strict", path=config)
    other = get_expectation("sessions", "tenant-other", path=config)

    assert strict.min_events == 5
    assert strict.freshness_sla_seconds == 7200
    assert other.min_events == 1
    assert other.freshness_sla_seconds == 7200


def test_registry_snapshot_reports_effective_tenant_policy(tmp_path):
    config = _write(
        tmp_path / "expectations.json",
        {
            "version": 1,
            "defaults": {},
            "tenants": {
                "tenant-a": {
                    "wallets": {"freshness_sla_seconds": 60},
                }
            },
        },
    )

    snapshot = registry_snapshot("tenant-a", path=config)
    wallets = next(row for row in snapshot if row["dimension"] == "wallets")
    assert wallets["freshness_sla_seconds"] == 60


@pytest.mark.parametrize(
    "override",
    [
        {"sessions": {"min_events": -1}},
        {"sessions": {"freshness_sla_seconds": 0}},
        {"unknown": {"min_events": 1}},
        {"sessions": {"unrecognized": True}},
    ],
)
def test_invalid_operator_config_is_rejected(tmp_path, override):
    config = _write(
        tmp_path / "expectations.json",
        {"version": 1, "defaults": override, "tenants": {}},
    )

    with pytest.raises(ExpectationConfigError):
        registry_snapshot(path=config)
