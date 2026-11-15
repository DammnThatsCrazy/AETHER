#!/usr/bin/env python3
"""Read-only evidence check for a real cross-device run (XD-1) on a live tenant.

Run it AFTER a person has done the scenario on real devices against staging:
tap the ad (or open the partner link), install, browse in the iOS/Android app,
create a journey handoff, open it on a desktop browser, browse, then log in.
Record the two anonymous IDs (SDK getAnonymousId on each device) and, if the
person logged in, the profile ID. This script then reads the backend and writes
an evidence file with one pass/fail row per check. It never writes data.

    AETHER_CERT_API_KEY=... python scripts/cross_device_certification.py \\
        --base-url https://api.staging.example \\
        --mobile-anonymous-id <id> --desktop-anonymous-id <id> \\
        [--profile-id <id>] [--expect-acquisition ios_apple_ads_attribution] \\
        --out evidence/xd1-<date>.json

Passing this is evidence for ONE real run on one tenant. It is not a measured
accuracy rate: precision/recall need the labelled pilot dataset
(identity/identity/calibration_evaluation.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

Fetch = Callable[[str], dict[str, Any]]


def http_fetch(base_url: str, api_key: str, timeout: float = 20.0) -> Fetch:
    def fetch(path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied URL
            return json.loads(response.read().decode("utf-8"))
    return fetch


def _journeys(fetch: Fetch, identity_id: str) -> list[dict[str, Any]]:
    body = fetch("/v1/journeys?" + urllib.parse.urlencode({"profile_id": identity_id}))
    return [j for j in body.get("data") or [] if isinstance(j, dict)]


def _steps(fetch: Fetch, journey_id: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(20):
        query = {"limit": 200, **({"cursor": cursor} if cursor else {})}
        body = fetch(f"/v1/journeys/{urllib.parse.quote(journey_id)}/steps?" + urllib.parse.urlencode(query))
        data = body.get("data")
        page = data.get("items", data.get("steps", [])) if isinstance(data, dict) else (data or [])
        steps.extend(s for s in page if isinstance(s, dict))
        meta = body.get("pagination") or body.get("meta") or {}
        cursor = meta.get("next_cursor")
        if not cursor:
            break
    return steps


def _row(check: str, passed: bool, observed: Any, expectation: str) -> dict[str, Any]:
    return {"check": check, "passed": bool(passed), "expectation": expectation, "observed": observed}


def certify(fetch: Fetch, *, mobile_id: str, desktop_id: str, profile_id: Optional[str],
            expect_acquisition: Optional[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    mobile = [j for j in _journeys(fetch, mobile_id) if j.get("journey_type") == "anonymous"]
    desktop = [j for j in _journeys(fetch, desktop_id) if j.get("journey_type") == "anonymous"]
    rows.append(_row("continuation_root_owns_journey", len(mobile) == 1,
                     {"mobile_current": len(mobile), "desktop_current": len(desktop)},
                     "exactly one current anonymous journey, owned by the mobile (root) anonymous ID"))
    rows.append(_row("redeemed_end_retired", not desktop, {"desktop_current": len(desktop)},
                     "the desktop anonymous ID has no standalone current journey"))
    steps = _steps(fetch, str(mobile[0]["journey_id"])) if len(mobile) == 1 else []
    platforms = sorted({str(s.get("platform")) for s in steps if s.get("platform")})
    sessions = sorted({str(s.get("session_id")) for s in steps if s.get("session_id")})
    rows.append(_row("journey_spans_devices", len(sessions) >= 2,
                     {"sessions": len(sessions), "platforms": platforms},
                     "steps from at least two sessions (mobile and desktop)"))
    hops = [s.get("transition_evidence") or {} for s in steps]
    explicit = [h for h in hops if h.get("link_basis") == "explicit_handoff"]
    rows.append(_row("explicit_handoff_hop", len(explicit) >= 1,
                     {"explicit_hops": len(explicit),
                      "identity_merge": sorted({str(h.get("identity_merge")) for h in explicit})},
                     "at least one hop labelled explicit_handoff with identity_merge=not_performed"))
    if expect_acquisition:
        first = steps[0] if steps else {}
        rows.append(_row("acquisition_is_first_step", first.get("entry_method") == expect_acquisition,
                         {"entry_method": first.get("entry_method"), "proof_level": first.get("proof_level"),
                          "activity_type": first.get("activity_type")},
                         f"first step entry_method == {expect_acquisition}"))
    if profile_id:
        profile = [j for j in _journeys(fetch, profile_id) if j.get("journey_type") != "anonymous"]
        profile_steps = _steps(fetch, str(profile[0]["journey_id"])) if len(profile) == 1 else []
        profile_sessions = {str(s.get("session_id")) for s in profile_steps if s.get("session_id")}
        rows.append(_row("profile_journey_includes_pre_login_mobile", set(sessions) <= profile_sessions
                         and bool(sessions),
                         {"profile_journeys": len(profile), "profile_sessions": len(profile_sessions)},
                         "the logged-in profile journey contains every session of the continuation"))
        if expect_acquisition:
            first = profile_steps[0] if profile_steps else {}
            rows.append(_row("profile_journey_starts_at_acquisition",
                             first.get("entry_method") == expect_acquisition,
                             {"entry_method": first.get("entry_method")},
                             f"profile journey first step entry_method == {expect_acquisition}"))
    return {
        "scenario": "XD-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(r["passed"] for r in rows),
        "checks": rows,
        "scope": "one real run on one tenant; not a measured identity accuracy rate",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-env", default="AETHER_CERT_API_KEY")
    parser.add_argument("--mobile-anonymous-id", required=True)
    parser.add_argument("--desktop-anonymous-id", required=True)
    parser.add_argument("--profile-id")
    parser.add_argument("--expect-acquisition", choices=[
        "ios_apple_ads_attribution", "android_install_referrer", "verified_source_link"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"set {args.api_key_env} to a read-capable tenant API key", file=sys.stderr)
        return 2
    report = certify(
        http_fetch(args.base_url, api_key),
        mobile_id=args.mobile_anonymous_id, desktop_id=args.desktop_anonymous_id,
        profile_id=args.profile_id, expect_acquisition=args.expect_acquisition,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for row in report["checks"]:
        print(("PASS " if row["passed"] else "FAIL ") + row["check"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
