"""scripts/cross_device_certification.py turns backend reads into pass/fail evidence."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("xd_cert", ROOT / "scripts/cross_device_certification.py")
xd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xd)


def _fetch(routes):
    def fetch(path):
        for prefix, body in routes.items():
            if path.startswith(prefix):
                return body
        return {"data": []}
    return fetch


STEPS = [
    {"session_id": "phone", "platform": "ios", "entry_method": "ios_apple_ads_attribution"},
    {"session_id": "phone", "platform": "ios"},
    {"session_id": "desk", "platform": "web",
     "transition_evidence": {"link_basis": "explicit_handoff", "identity_merge": "not_performed"}},
    {"session_id": "desk", "platform": "web"},
]


def test_a_complete_run_passes_every_check():
    fetch = _fetch({
        "/v1/journeys?profile_id=anon-m": {"data": [{"journey_id": "j1", "journey_type": "anonymous"}]},
        "/v1/journeys?profile_id=anon-d": {"data": []},
        "/v1/journeys?profile_id=p1": {"data": [{"journey_id": "j2", "journey_type": "profile"}]},
        "/v1/journeys/j1/steps": {"data": STEPS, "pagination": {"next_cursor": None}},
        "/v1/journeys/j2/steps": {"data": STEPS, "pagination": {"next_cursor": None}},
    })
    report = xd.certify(fetch, mobile_id="anon-m", desktop_id="anon-d", profile_id="p1",
                        expect_acquisition="ios_apple_ads_attribution")
    assert report["passed"], report
    assert {r["check"] for r in report["checks"]} == {
        "continuation_root_owns_journey", "redeemed_end_retired", "journey_spans_devices",
        "explicit_handoff_hop", "acquisition_is_first_step",
        "profile_journey_includes_pre_login_mobile", "profile_journey_starts_at_acquisition",
    }


def test_separate_device_journeys_fail():
    fetch = _fetch({
        "/v1/journeys?profile_id=anon-m": {"data": [{"journey_id": "j1", "journey_type": "anonymous"}]},
        "/v1/journeys?profile_id=anon-d": {"data": [{"journey_id": "j3", "journey_type": "anonymous"}]},
        "/v1/journeys/j1/steps": {"data": STEPS[:2], "pagination": {}},
    })
    report = xd.certify(fetch, mobile_id="anon-m", desktop_id="anon-d", profile_id=None,
                        expect_acquisition=None)
    failed = {r["check"] for r in report["checks"] if not r["passed"]}
    assert not report["passed"]
    assert failed == {"redeemed_end_retired", "journey_spans_devices", "explicit_handoff_hop"}


def test_cli_requires_an_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AETHER_CERT_API_KEY", raising=False)
    code = xd.main(["--base-url", "http://x", "--mobile-anonymous-id", "a", "--desktop-anonymous-id", "b",
                    "--out", str(tmp_path / "e.json")])
    assert code == 2
