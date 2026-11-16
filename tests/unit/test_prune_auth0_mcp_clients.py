"""Stale self-registered MCP client pruning (dry run by default)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prune_auth0_mcp_clients", ROOT / "scripts/prune_auth0_mcp_clients.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["prune_auth0_mcp_clients"] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[union-attr]

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


class FakeAuth0:
    def __init__(self):
        self.deleted: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.logs = {"fresh": "2026-11-10T00:00:00Z", "old": "2026-09-01T00:00:00Z"}

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url))
        if url.endswith("/oauth/token"):
            return {"access_token": "t"}
        if "/api/v2/clients?" in url:
            return [
                {"client_id": "fresh", "name": "Cursor", "is_first_party": False},
                {"client_id": "old", "name": "Old host", "is_first_party": False},
                {"client_id": "never", "name": "Bot", "is_first_party": False},
                {"client_id": "kept", "name": "Partner", "is_first_party": False},
                {"client_id": "spa", "name": "Aether SPA", "is_first_party": True},
            ]
        if "/api/v2/logs?" in url:
            for client_id, date in self.logs.items():
                if f"client_id%3A%22{client_id}%22" in url:
                    return [{"date": date}]
            return []
        if method == "DELETE":
            self.deleted.append(url.rsplit("/", 1)[1])
            return None
        raise AssertionError(url)


def _env(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "m2m")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret")


def test_dry_run_reports_stale_third_party_clients_and_deletes_nothing(monkeypatch, capsys):
    _env(monkeypatch)
    fake = FakeAuth0()
    assert MODULE.main(["--keep", "kept"], http=fake, now=NOW) == 0
    out = capsys.readouterr().out
    assert '"client_id": "old"' in out and '"would_delete"' in out
    assert '"client_id": "spa"' not in out
    assert '"client_id": "kept"' not in out
    assert fake.deleted == []
    assert not any(method == "DELETE" for method, _ in fake.calls)


def test_apply_deletes_only_idle_or_never_used_third_party_clients(monkeypatch):
    _env(monkeypatch)
    fake = FakeAuth0()
    assert MODULE.main(["--apply", "--keep", "kept", "--max-idle-days", "30"], http=fake, now=NOW) == 0
    assert sorted(fake.deleted) == ["never", "old"]


def test_missing_credentials_fail_closed(monkeypatch, capsys):
    for name in ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert MODULE.main([], http=FakeAuth0(), now=NOW) == 1
    assert "could not evaluate" in capsys.readouterr().err
