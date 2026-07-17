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

    # Temporal provenance emission — every SDK stamps timezone/clock provenance
    # on the event context at occurrence time (temporal kernel evidence:
    # utcOffsetMinutes / timeZoneSource / clockSource on the wire context).
    # Server SDK emits server-clock provenance and never fabricates a device
    # offset, so utcOffsetMinutes is intentionally absent there. The Python
    # agentic package is a pure event-builder library relayed by the caller's
    # server (server clock authority applies at ingestion), so it is exempt.
    _require("web", web, ["utcOffsetMinutes", "timeZoneSource: 'device'", "clockSource: 'device'"],
             "temporal provenance emission")
    _require("server", server, ["timeZoneSource: 'server'", "clockSource: 'server'"],
             "temporal provenance emission")
    _require("ios", ios, ["utcOffsetMinutes", "timeZoneSource: \"device\"", "clockSource: \"device\""],
             "temporal provenance emission")
    _require("android", android,
             ["utcOffsetMinutes", "put(\"timeZoneSource\", \"device\")", "put(\"clockSource\", \"device\")"],
             "temporal provenance emission")
    _require("react-native", rn, ["utcOffsetMinutes", "timeZoneSource: 'device'", "clockSource: 'device'"],
             "temporal provenance emission")

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


    # Native durable queues must survive restart and exhausted transient retries.
    _require(
        "ios",
        ios,
        ["PersistedQueueEnvelope", "persistQueueLocked", "requeueBatch", "Quarantined corrupt durable queue"],
        "durable crash-safe queue [§2.6]",
    )
    _require(
        "android",
        android,
        ["QUEUE_FORMAT_VERSION", "persistQueue", "requeueBatch", "Quarantined corrupt durable queue"],
        "durable crash-safe queue [§2.6]",
    )

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

    # Every claimed parity cell must verify against the source tree (the parity
    # file's own contract note: a validator MUST fail when a cell claims
    # 'supported' but the evidence file/symbol is absent). The derivation also
    # feeds the release evidence bundle (scripts/release/collect_evidence.py).
    sys.path.insert(0, str(ROOT / "scripts" / "release"))
    try:
        from sdk_conformance import build_matrix  # noqa: E402
        _, conformance_failures = build_matrix(ROOT)
        for problem in conformance_failures:
            fail(f"sdk-parity.json claim not derivable from source: {problem}")
    except ImportError as exc:
        fail(f"scripts/release/sdk_conformance.py unavailable: {exc}")

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
    print("SDK runtime parity validation OK (observe / manifest-verify / batch-health / native durability present).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
