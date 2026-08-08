"""Tests for the ephemeral TTL lease lifecycle (demo/preview fail-closed guard).

Guards the class of drift where an ephemeral environment could be left running
forever — the historical failure mode the ``ttl_cleanup_required`` declaration
exists to prevent. The lease is an absolute UTC ``expires-at`` SSM parameter at
``/aether/{profile}/{env}/lifecycle/expires-at``; the guard fails closed so a
missing, unreadable, malformed or expired lease all mean "expired".

The mutation cases are the point: a fail-closed guard that has never been shown
to trip on a real violation is weak evidence, so every rule here is tested by
deliberately breaking the invariant and asserting the guard trips, per the
parity-test philosophy.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"


def _load(name: str):
    if str(RELEASE) not in sys.path:
        sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# parse_lease
# ---------------------------------------------------------------------------
def test_parse_lease_happy_path():
    """A well-formed absolute UTC timestamp parses to a timezone-aware datetime."""
    mod = _load("ephemeral_ttl_guard")
    value = _utc_iso(_now() + timedelta(hours=2))
    parsed = mod.parse_lease(value)
    assert parsed is not None
    assert parsed.tzinfo is not None
    # Round-trips through the same UTC format.
    assert parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value


def test_parse_lease_malformed():
    """Garbage in the lease parses to None (which the guard reads as expired)."""
    mod = _load("ephemeral_ttl_guard")
    for junk in ("not-a-date", "2026-13-99T99:99:99Z", "abc", 42, b"bytes"):
        assert mod.parse_lease(junk) is None


def test_parse_lease_empty():
    """An absent/empty lease parses to None — fail closed."""
    mod = _load("ephemeral_ttl_guard")
    for empty in (None, "", "   ", "\n\t"):
        assert mod.parse_lease(empty) is None


# ---------------------------------------------------------------------------
# is_expired
# ---------------------------------------------------------------------------
def test_is_expired_expired():
    """A past deadline, and None, are both expired."""
    mod = _load("ephemeral_ttl_guard")
    now = _now()
    assert mod.is_expired(now - timedelta(seconds=1), now) is True
    assert mod.is_expired(now - timedelta(hours=5), now) is True
    # Fail closed: no lease at all is expired.
    assert mod.is_expired(None, now) is True


def test_is_expired_not_expired():
    """A future deadline is not expired."""
    mod = _load("ephemeral_ttl_guard")
    now = _now()
    assert mod.is_expired(now + timedelta(seconds=1), now) is False
    assert mod.is_expired(now + timedelta(hours=6), now) is False


# ---------------------------------------------------------------------------
# evaluate — fail-closed decision with an injectable read_lease
# ---------------------------------------------------------------------------
def _evaluate(mod, read_lease, now=None):
    return mod.evaluate("demo", "demo", read_lease, now or _now())


def test_evaluate_missing_lease_is_expired():
    """A missing lease (None) reads as expired — fail closed."""
    mod = _load("ephemeral_ttl_guard")
    d = _evaluate(mod, lambda p, e: None)
    assert d["expired"] is True
    assert d["action"] == "scale-to-zero + floor-zeroing"
    assert d["lease_path"] == "/aether/demo/demo/lifecycle/expires-at"


def test_evaluate_unreadable_lease_is_expired():
    """A read_lease that raises reads as expired — fail closed."""
    mod = _load("ephemeral_ttl_guard")

    def boom(p, e):
        raise RuntimeError("throttled")

    d = _evaluate(mod, boom)
    assert d["expired"] is True
    assert "unreadable" in d["reason"]


def test_evaluate_malformed_lease_is_expired():
    """An unparseable lease reads as expired — fail closed."""
    mod = _load("ephemeral_ttl_guard")
    d = _evaluate(mod, lambda p, e: "garbage-not-a-date")
    assert d["expired"] is True
    assert "no parseable" in d["reason"]


def test_evaluate_expired_lease_is_expired():
    """A lease whose deadline is past reads as expired."""
    mod = _load("ephemeral_ttl_guard")
    past = _utc_iso(_now() - timedelta(hours=1))
    d = _evaluate(mod, lambda p, e: past)
    assert d["expired"] is True
    assert d["action"] == "scale-to-zero + floor-zeroing"


def test_evaluate_future_lease_is_live():
    """A future lease is live, with the action being a no-op."""
    mod = _load("ephemeral_ttl_guard")
    future = _utc_iso(_now() + timedelta(hours=3))
    d = _evaluate(mod, lambda p, e: future)
    assert d["expired"] is False
    assert d["action"] == "none"
    assert d["expires_at"] is not None
    assert d["remaining_seconds"] > 0


# ---------------------------------------------------------------------------
# Repo-structural mutation tests
# ---------------------------------------------------------------------------
def _make_tree(tmp_path: Path) -> dict:
    """A minimal live repo tree carrying the fail-closed cron workflow."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ephemeral-ttl-guard.yml").write_text(
        "name: Ephemeral TTL guard\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '17 * * * *'\n"
        "jobs:\n"
        "  guard:\n"
        "    runs-on: ubuntu-latest\n"
        "    strategy:\n"
        "      matrix:\n"
        "        include:\n"
        "          - profile: demo\n"
        "            env: demo\n"
        "          - profile: preview\n"
        "            env: preview\n"
    )
    return {"root": tmp_path}


def test_check_passes_on_current_tree():
    """The real tree satisfies every ephemeral TTL structural invariant."""
    mod = _load("ephemeral_ttl_guard")
    assert mod.check() == 0


def test_guard_validator_passes_on_current_tree():
    """The validator exits 0 against the current tree."""
    rc = subprocess.run(
        [sys.executable, str(RELEASE / "ephemeral_ttl_guard.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
    )
    assert rc.returncode == 0, rc.stderr.decode()


def test_check_fails_when_workflow_missing(monkeypatch, tmp_path):
    """Removing the fail-closed cron workflow trips the structural guard."""
    mod = _load("ephemeral_ttl_guard")
    tree = _make_tree(tmp_path)
    wf = tree["root"] / ".github" / "workflows" / "ephemeral-ttl-guard.yml"
    wf.unlink()
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_check_fails_when_demo_removed_from_matrix(monkeypatch, tmp_path):
    """Removing demo from the workflow matrix trips the structural guard."""
    mod = _load("ephemeral_ttl_guard")
    tree = _make_tree(tmp_path)
    wf = tree["root"] / ".github" / "workflows" / "ephemeral-ttl-guard.yml"
    wf.write_text(wf.read_text().replace("- profile: demo\n", ""))
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_check_fails_when_lease_path_format_drifts(monkeypatch, tmp_path):
    """Changing the lease path template away from expires-at trips the guard."""
    mod = _load("ephemeral_ttl_guard")
    tree = _make_tree(tmp_path)
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    monkeypatch.setattr(mod, "LEASE_PATH_TEMPLATE", "/aether/{profile}/{env}/lifecycle/awake-until")
    assert mod.check() != 0


def test_parse_lease_and_evaluate_share_one_lease_path():
    """lease_path is the single source of truth for the SSM parameter name."""
    mod = _load("ephemeral_ttl_guard")
    assert mod.lease_path("demo", "demo") == "/aether/demo/demo/lifecycle/expires-at"
    assert mod.lease_path("preview", "preview") == "/aether/preview/preview/lifecycle/expires-at"
