#!/usr/bin/env python3
"""Validate SDK runtime parity across web / server / iOS / Android / React Native
/ Python (Truth Kernel §2.6, §2.8, §2.9).

Native parity is grep-based by design (no generated native registries — see the
Truth Kernel non-goals). This gate asserts that each SDK actually exposes the
canonical runtime surface it is supposed to:

  - `observe()` — the canonical event-capture entry point on every client SDK
    (§2.6). Server SDK captures via `track()` and is exempt.
  - Manifest signature verification (§2.9) — iOS + Android reject unsigned /
    invalid-signature remote manifests (HMAC-SHA256, fail-closed).
  - Batch-response health metrics (§2.8) — accepted / duplicate / rejected /
    dropped-by-consent / queue-depth surfaced to SDK consumers.

If an SDK legitimately lacks a capability, this gate must be updated in the same
change — silence is not parity.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages"

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _sdk_text(sdk_rel: str, exts: tuple[str, ...]) -> str:
    """Concatenate the source of one SDK subtree (best-effort)."""
    base = PKG / sdk_rel
    if not base.exists():
        return ""
    chunks: list[str] = []
    for ext in exts:
        for f in base.rglob(f"*{ext}"):
            # Skip build output and dependencies.
            parts = set(f.parts)
            if "dist" in parts or "node_modules" in parts or "build" in parts:
                continue
            try:
                chunks.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
    return "\n".join(chunks)


def _require(sdk_label: str, text: str, tokens: list[str], capability: str) -> None:
    if not text:
        fail(f"{sdk_label}: source not found for {capability}")
        return
    missing = [t for t in tokens if t not in text]
    if missing:
        fail(f"{sdk_label}: {capability} missing token(s) {missing}")


def main() -> int:
    if not PKG.exists():
        fail("packages/ directory not found")
        return _report()

    ts = (".ts",)
    swift = (".swift",)
    kt = (".kt",)
    py = (".py",)

    web = _sdk_text("web/src", ts)
    server = _sdk_text("server/src", ts)
    ios = _sdk_text("ios/Sources", swift)
    android = _sdk_text("android/src/main", kt)
    rn = _sdk_text("react-native/src", ts)
    python = _sdk_text("python", py)

    # §2.6 — canonical observe() on every client SDK.
    _require("web", web, ["observe("], "observe() [§2.6]")
    _require("ios", ios, ["func observe("], "observe() [§2.6]")
    _require("android", android, ["fun observe("], "observe() [§2.6]")
    _require("react-native", rn, ["observe("], "observe() [§2.6]")

    # §2.9 — manifest signature verification on iOS + Android (fail-closed HMAC).
    _require("ios", ios, ["verifyManifestSignature"], "manifest signature verification [§2.9]")
    _require("android", android, ["verifyManifestSignature"], "manifest signature verification [§2.9]")

    # §2.8 — batch-response health metrics surfaced to SDK consumers.
    _require("server", server, ["BatchHealth", "dropped_by_consent", "queue_depth"],
             "batch health metrics [§2.8]")
    _require("web", web, ["dropped_by_consent", "queue_depth"], "batch health metrics [§2.8]")
    _require("ios", ios, ["BatchHealth", "droppedByConsent", "queueDepth"],
             "batch health metrics [§2.8]")
    _require("android", android, ["BatchHealth", "droppedByConsent", "queueDepth"],
             "batch health metrics [§2.8]")
    _require("python", python, ["parse_batch_health", "dropped_by_consent", "queue_depth"],
             "batch health metrics [§2.8]")

    # §2.6 — the canonical, machine-checkable parity matrix must exist and parse.
    parity = PKG / "shared" / "sdk-parity.json"
    if not parity.exists():
        fail("missing canonical parity matrix packages/shared/sdk-parity.json")
    else:
        try:
            import json
            data = json.loads(parity.read_text(encoding="utf-8"))
            if not data.get("capabilities") or not data.get("sdks"):
                fail("packages/shared/sdk-parity.json must declare 'capabilities' and 'sdks'")
        except Exception as exc:
            fail(f"packages/shared/sdk-parity.json is not valid JSON: {exc}")

    return _report()


def _report() -> int:
    if ERRORS:
        print("SDK runtime parity validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        print(
            "\nEvery client SDK must expose canonical observe(), iOS/Android must "
            "verify manifest signatures, and batch health metrics must be surfaced. "
            "See docs/source-of-truth/SDK_RUNTIME_PARITY.md."
        )
        return 1
    print("SDK runtime parity validation OK (observe / manifest-verify / batch-health present).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
