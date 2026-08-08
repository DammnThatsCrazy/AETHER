#!/usr/bin/env python3
"""Generate store privacy manifests for the two shipping Expo apps.

For each of apps/aether-mobile and apps/kyber-mobile this reads an auditable,
per-app data-flow declaration (``privacy-data-flows.yaml``) and emits two
store-facing artifacts, derived deterministically and validated against the
platform's own governance sources:

  * ``PrivacyInfo.xcprivacy`` — an Apple Privacy Manifest, mirroring the structure
    of the hand-authored SDK manifest (packages/ios/.../PrivacyInfo.xcprivacy):
    NSPrivacyTracking, NSPrivacyTrackingDomains, NSPrivacyAccessedAPITypes, and
    NSPrivacyCollectedDataTypes (grouped by data type, with Linked/Tracking/Purposes).
  * ``data-safety.json`` — a machine-readable Google Play Data Safety declaration:
    per collected field, its Play data type/category, collected/shared flags,
    purposes, identity-linkage, and tracking use, plus an overall security block.

The declaration is the ONLY thing the generator trusts. It is validated FAIL-CLOSED:

  * every ``purpose`` must be a real key in the 12-purpose consent registry
    (packages/shared/contracts/consent-registry.json);
  * every ``classification`` must be a real tier in the backend DataClassification
    taxonomy, and where ``field`` is a known key in that module's
    FIELD_CLASSIFICATIONS registry the declared tier must equal classify_field(field);
  * ``apple_data_type`` / ``apple_purpose`` / ``play_purpose`` must be members of
    the Apple / Google Play vocabularies.

A data-flow that names a purpose absent from the registry (or an unknown tier /
vocabulary value) raises ManifestError and the CLI exits 2 — no manifest is written.

Output is DETERMINISTIC (stable ordering, no timestamps/random) so a drift gate is
stable.

Usage:
  python scripts/generate_privacy_manifests.py            # write the 4 artifacts
  python scripts/generate_privacy_manifests.py --check    # regenerate in memory and
                                                          # diff against disk; exit 1
                                                          # on drift, 2 on validation
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "apps"
CONSENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"
CLASSIFICATION_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "shared" / "privacy" / "classification.py"
)

# The two shipping apps. App-level facts (name, bundle ids, plane) are read from
# each app's app.json so this stays in lockstep with the real Expo config.
APP_KEYS = ["aether-mobile", "kyber-mobile"]

# ── Apple / Google Play vocabularies (fail-closed membership sets) ──────────────
# Apple NSPrivacyCollectedDataType identifiers are emitted as
# ``NSPrivacyCollectedDataType<Value>``; we validate the short token.
APPLE_DATA_TYPES: frozenset[str] = frozenset(
    {
        "DeviceID",
        "ProductInteraction",
        "UserID",
        "PurchaseHistory",
        "CrashData",
        "PerformanceData",
        "OtherDiagnosticData",
        "PreciseLocation",
        "CoarseLocation",
        "EmailAddress",
        "Name",
        "PhoneNumber",
        "PhysicalAddress",
        "PaymentInfo",
        "OtherDataTypes",
    }
)
# Apple purposes are emitted as ``NSPrivacyCollectedDataTypePurpose<Value>``.
APPLE_PURPOSES: frozenset[str] = frozenset(
    {
        "AppFunctionality",
        "Analytics",
        "ProductPersonalization",
        "ThirdPartyAdvertising",
        "DeveloperAdvertising",
        "Other",
    }
)
# Google Play Data Safety collection/sharing purposes.
PLAY_PURPOSES: frozenset[str] = frozenset(
    {
        "Account management",
        "Advertising or marketing",
        "Analytics",
        "App functionality",
        "Developer communications",
        "Fraud prevention, security, and compliance",
        "Personalization",
    }
)

REQUIRED_FIELDS = (
    "field",
    "apple_data_type",
    "apple_purpose",
    "play_category",
    "play_data_type",
    "play_purpose",
    "purpose",
    "linked",
    "tracking",
    "classification",
)

# The mobile-plane stores a principal DSR erasure ACTUALLY removes. This is the
# app's real deletion surface — the tenant-scoped tables the backend
# ``consent.erasure`` job erases for a principal (services/consent/erasure_jobs.py)
# and that the DSR-coverage gate binds (scripts/release/check_dsr_coverage.py). It
# deliberately does NOT come from a purpose's ``dsrDeleteScope`` in the consent
# registry: the analytics purpose's scope (events/sessions/profiles) describes
# analytics facts these apps never store, so citing it would claim a governance
# artifact that does not govern the erased mobile tables. Kept a static constant so
# generation stays deterministic and --check remains reproducible.
DELETION_SURFACE = (
    "continuations and continuation selections",
    "mobile installations and push subscriptions",
    "the sync change log",
)


class ManifestError(Exception):
    """Raised when a data-flow declaration fails validation. Fail closed."""


# ── Governance sources ─────────────────────────────────────────────────────────
def _ensure_pydantic_available() -> None:
    """Guarantee ``pydantic`` is importable for classification.py.

    The classification module reads its enums (DataClassification) and the plain
    FIELD_CLASSIFICATIONS dict — the values we need — but it also defines a couple
    of pydantic models at import time. When the real pydantic is installed (backend
    CI, the project venv) we use it. When it is absent we register a minimal stub so
    the module still execs and yields the AUTHENTIC enum/dict values from source;
    the stub only affects model classes we never touch.
    """
    try:  # pragma: no cover - exercised only where pydantic is installed
        import pydantic  # noqa: F401

        return
    except ImportError:
        pass

    import types

    stub = types.ModuleType("pydantic")

    class _StubBaseModel:  # minimal: accept kwargs, set attributes
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def _stub_field(default: Any = None, *, default_factory: Any = None, **_: Any) -> Any:
        return default_factory() if default_factory is not None else default

    stub.BaseModel = _StubBaseModel  # type: ignore[attr-defined]
    stub.Field = _stub_field  # type: ignore[attr-defined]
    sys.modules["pydantic"] = stub


def load_classification_module() -> Any:
    """Load the backend classification module standalone (no package __init__).

    Importing the ``shared`` package would pull Flask decorators; loading the file
    directly gives us DataClassification + classify_field with no side effects.
    """
    if not CLASSIFICATION_PY.exists():  # pragma: no cover - defensive
        raise ManifestError(f"classification module not found: {CLASSIFICATION_PY}")
    _ensure_pydantic_available()
    spec = importlib.util.spec_from_file_location(
        "aether_privacy_classification", CLASSIFICATION_PY
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_consent_purposes() -> set[str]:
    """Return the set of valid purpose keys from the consent registry."""
    with CONSENT_REGISTRY.open(encoding="utf-8") as fh:
        registry = json.load(fh)
    purposes = {p["key"] for p in registry.get("purposes", [])}
    if not purposes:  # pragma: no cover - defensive
        raise ManifestError("consent registry has no purposes")
    return purposes


def load_data_flows(app_key: str) -> list[dict[str, Any]]:
    path = APPS_DIR / app_key / "privacy-data-flows.yaml"
    if not path.exists():
        raise ManifestError(f"{app_key}: missing privacy-data-flows.yaml ({path})")
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    flows = doc.get("data_flows")
    if not isinstance(flows, list) or not flows:
        raise ManifestError(f"{app_key}: privacy-data-flows.yaml has no data_flows")
    return flows


def load_app_meta(app_key: str) -> dict[str, str]:
    path = APPS_DIR / app_key / "app.json"
    if not path.exists():
        raise ManifestError(f"{app_key}: missing app.json ({path})")
    with path.open(encoding="utf-8") as fh:
        expo = json.load(fh).get("expo", {})
    meta = {
        "name": expo.get("name", app_key),
        "app_kind": expo.get("extra", {}).get("appKind", ""),
        "ios_bundle_id": expo.get("ios", {}).get("bundleIdentifier", ""),
        "android_package": expo.get("android", {}).get("package", ""),
        "version": expo.get("version", ""),
    }
    for k in ("app_kind", "ios_bundle_id", "android_package"):
        if not meta[k]:
            raise ManifestError(f"{app_key}: app.json missing expo {k}")
    return meta


# ── Validation ─────────────────────────────────────────────────────────────────
def validate_flows(
    app_key: str,
    flows: list[dict[str, Any]],
    consent_purposes: set[str],
    classification_mod: Any,
) -> None:
    """Validate every entry. Raise ManifestError on the first violation."""
    valid_tiers = {c.value for c in classification_mod.DataClassification}
    field_registry = classification_mod.FIELD_CLASSIFICATIONS
    seen: set[str] = set()

    for entry in flows:
        for key in REQUIRED_FIELDS:
            if key not in entry:
                raise ManifestError(f"{app_key}: data-flow missing required key {key!r}: {entry!r}")

        field = entry["field"]
        if field in seen:
            raise ManifestError(f"{app_key}: duplicate field {field!r} in data flows")
        seen.add(field)

        purpose = entry["purpose"]
        if purpose not in consent_purposes:
            raise ManifestError(
                f"{app_key}: field {field!r} declares consent purpose {purpose!r}, "
                f"which is NOT in the consent registry "
                f"({sorted(consent_purposes)}). Refusing to generate."
            )

        classification = entry["classification"]
        if classification not in valid_tiers:
            raise ManifestError(
                f"{app_key}: field {field!r} declares classification {classification!r}, "
                f"which is NOT a DataClassification tier ({sorted(valid_tiers)})."
            )
        # If the field is a known key in the backend registry, the declared tier
        # must match — this catches drift between the manifest and the taxonomy.
        if field in field_registry:
            resolved = field_registry[field].value
            if resolved != classification:
                raise ManifestError(
                    f"{app_key}: field {field!r} declares classification "
                    f"{classification!r} but FIELD_CLASSIFICATIONS resolves it to "
                    f"{resolved!r}."
                )

        if entry["apple_data_type"] not in APPLE_DATA_TYPES:
            raise ManifestError(
                f"{app_key}: field {field!r} apple_data_type "
                f"{entry['apple_data_type']!r} is not an Apple data type."
            )
        if entry["apple_purpose"] not in APPLE_PURPOSES:
            raise ManifestError(
                f"{app_key}: field {field!r} apple_purpose {entry['apple_purpose']!r} "
                f"is not an Apple purpose."
            )
        if entry["play_purpose"] not in PLAY_PURPOSES:
            raise ManifestError(
                f"{app_key}: field {field!r} play_purpose {entry['play_purpose']!r} "
                f"is not a Google Play Data Safety purpose."
            )
        for flag in ("linked", "tracking"):
            if not isinstance(entry[flag], bool):
                raise ManifestError(f"{app_key}: field {field!r} {flag!r} must be a bool")


# ── Apple plist emission ───────────────────────────────────────────────────────
def _plist_bool(value: bool) -> str:
    return "<true/>" if value else "<false/>"


def build_xcprivacy(app_key: str, app_meta: dict[str, str], flows: list[dict[str, Any]]) -> str:
    """Build the Apple Privacy Manifest, mirroring the SDK manifest's structure.

    Collected-data entries are grouped by (data type, linked, tracking) — Apple's
    manifest is keyed by data TYPE, not by field — so the two DeviceID fields
    collapse into one DeviceID declaration, matching the SDK plist shape.
    """
    tracking = any(bool(e["tracking"]) for e in flows)

    # group key -> sorted set of apple purposes
    groups: dict[tuple[str, bool, bool], set[str]] = {}
    for e in flows:
        key = (e["apple_data_type"], bool(e["linked"]), bool(e["tracking"]))
        groups.setdefault(key, set()).add(e["apple_purpose"])

    t = "\t"
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    )
    lines.append('<plist version="1.0">')
    lines.append("<dict>")
    lines.append(
        f"{t}<!-- GENERATED by scripts/generate_privacy_manifests.py from "
        f"apps/{app_key}/privacy-data-flows.yaml. Do not edit by hand; run "
        f"`make privacy-manifest-check`."
    )
    lines.append(
        f"{t}     {app_meta['name']} ({app_meta['ios_bundle_id']}) does not track users "
        f"across apps or companies, so NSPrivacyTracking is false and there are no "
        f"tracking domains. -->"
    )
    lines.append(f"{t}<key>NSPrivacyTracking</key>")
    lines.append(f"{t}{_plist_bool(tracking)}")
    lines.append(f"{t}<key>NSPrivacyTrackingDomains</key>")
    lines.append(f"{t}<array/>")
    lines.append(
        f"{t}<!-- The app's own persistence is Keychain/Keystore-backed "
        f"(expo-secure-store), which is NOT a required-reason API; no "
        f"NSPrivacyAccessedAPIType applies to first-party storage. -->"
    )
    lines.append(f"{t}<key>NSPrivacyAccessedAPITypes</key>")
    lines.append(f"{t}<array/>")
    lines.append(f"{t}<key>NSPrivacyCollectedDataTypes</key>")
    lines.append(f"{t}<array>")
    for (data_type, linked, track), purposes in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
    ):
        lines.append(f"{t}{t}<dict>")
        lines.append(f"{t}{t}{t}<key>NSPrivacyCollectedDataType</key>")
        lines.append(
            f"{t}{t}{t}<string>NSPrivacyCollectedDataType{data_type}</string>"
        )
        lines.append(f"{t}{t}{t}<key>NSPrivacyCollectedDataTypeLinked</key>")
        lines.append(f"{t}{t}{t}{_plist_bool(linked)}")
        lines.append(f"{t}{t}{t}<key>NSPrivacyCollectedDataTypeTracking</key>")
        lines.append(f"{t}{t}{t}{_plist_bool(track)}")
        lines.append(f"{t}{t}{t}<key>NSPrivacyCollectedDataTypePurposes</key>")
        lines.append(f"{t}{t}{t}<array>")
        for purpose in sorted(purposes):
            lines.append(
                f"{t}{t}{t}{t}<string>NSPrivacyCollectedDataTypePurpose{purpose}</string>"
            )
        lines.append(f"{t}{t}{t}</array>")
        lines.append(f"{t}{t}</dict>")
    lines.append(f"{t}</array>")
    lines.append("</dict>")
    lines.append("</plist>")
    return "\n".join(lines) + "\n"


# ── Google Play Data Safety emission ───────────────────────────────────────────
def build_data_safety(
    app_key: str, app_meta: dict[str, str], flows: list[dict[str, Any]]
) -> str:
    """Build the Google Play Data Safety declaration (deterministic JSON)."""
    collected = []
    shares_any = False
    for e in sorted(flows, key=lambda x: x["field"]):
        shared = bool(e.get("shared", False))
        shares_any = shares_any or shared
        collected.append(
            {
                "field": e["field"],
                "play_category": e["play_category"],
                "play_data_type": e["play_data_type"],
                "collected": True,
                "shared": shared,
                "processing_is_optional": False,
                "purposes": [e["play_purpose"]],
                "linked_to_identity": bool(e["linked"]),
                "used_for_tracking": bool(e["tracking"]),
                "consent_purpose": e["purpose"],
                "classification": e["classification"],
            }
        )

    doc = {
        "$schema": "aether/play-data-safety/v1",
        "generated_by": "scripts/generate_privacy_manifests.py",
        "source_declaration": f"apps/{app_key}/privacy-data-flows.yaml",
        "app": {
            "name": app_meta["name"],
            "app_kind": app_meta["app_kind"],
            "package_name": app_meta["android_package"],
        },
        "data_collection": {
            "collects_data": True,
            "shares_data": shares_any,
        },
        "security_practices": {
            "data_encrypted_in_transit": True,
            "user_can_request_data_deletion": True,
            "deletion_mechanism": (
                "Data deletion is available through the Aether platform's "
                "data-subject erasure flow (backend consent/erasure API, "
                "request_type=erasure); the app has no in-app account-deletion "
                "UI. A submitted erasure request removes the principal's mobile "
                "records server-side: "
                f"{', '.join(DELETION_SURFACE)}."
            ),
            "committed_to_play_families_policy": True,
            "independent_security_review": False,
        },
        "collected_data": collected,
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ── Orchestration ──────────────────────────────────────────────────────────────
def build_manifests(
    app_key: str,
    consent_purposes: set[str],
    classification_mod: Any,
) -> dict[Path, str]:
    """Validate + build both artifacts for one app. Returns path -> content."""
    flows = load_data_flows(app_key)
    app_meta = load_app_meta(app_key)
    validate_flows(app_key, flows, consent_purposes, classification_mod)
    app_dir = APPS_DIR / app_key
    return {
        app_dir / "PrivacyInfo.xcprivacy": build_xcprivacy(app_key, app_meta, flows),
        app_dir / "data-safety.json": build_data_safety(app_key, app_meta, flows),
    }


def build_all() -> dict[Path, str]:
    consent_purposes = load_consent_purposes()
    classification_mod = load_classification_module()
    artifacts: dict[Path, str] = {}
    for app_key in APP_KEYS:
        artifacts.update(build_manifests(app_key, consent_purposes, classification_mod))
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and diff against on-disk artifacts; do not write.",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = build_all()
    except ManifestError as exc:
        print(f"ERROR: privacy manifest validation failed: {exc}", file=sys.stderr)
        return 2

    if args.check:
        drifted: list[str] = []
        for path, content in sorted(artifacts.items()):
            rel = path.relative_to(ROOT)
            if not path.exists():
                drifted.append(f"  MISSING: {rel}")
            elif path.read_text(encoding="utf-8") != content:
                drifted.append(f"  DRIFT:   {rel}")
        if drifted:
            print("Privacy manifests are OUT OF DATE with privacy-data-flows.yaml:")
            print("\n".join(drifted))
            print("Run: python scripts/generate_privacy_manifests.py")
            return 1
        print(f"Privacy manifests up to date ({len(artifacts)} artifacts across {len(APP_KEYS)} apps).")
        return 0

    for path, content in sorted(artifacts.items()):
        path.write_text(content, encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")
    print(f"Generated {len(artifacts)} privacy artifacts for {len(APP_KEYS)} apps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
