"""
Aether Service — SDK Version-Compatibility Tiers (Invariant #18, WS-E 6).

The version-band model behind the SDK capability manifest. Today the backend
strips ``context.library.version`` and treats every SDK client identically; this
module declares the honest compatibility bands (mirroring the blueprint §18
matrix — 8.x supported / 7.x deprecated / 6.x read-compatible / 5.x
blocked-after-date) and the per-band capability set, and consults a client's
``library.version`` on ingress.

Serving + adoption:
* ``tiers_payload()`` is served (always readable, non-secret, static) as the SDK
  capability manifest at ``GET /v1/config/sdk/versions``.
* Ingestion *consultation* is flag-gated (``settings.sdk_version_compat``,
  ``AETHER_SDK_VERSION_COMPAT_ENABLED`` default OFF). When ON, /v1/batch
  attaches an advisory tier label (``normalized["sdk_tier"]``). When MODE is
  ``enforce`` it additionally REJECTS events whose SDK band is past its
  ``blocked_after`` date — inert until that date arrives, so the default tree
  never blocks anything. OFF keeps every client identical (today's behavior).

Nothing here is a promise about a specific SDK build: bands are advisory policy
data consumed by operators and by the advisory ingress seam. Enforcement is
fail-closed by date, never by band alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from config.settings import settings

# Recognition set for server-side SDK libraries (name is advisory; version does
# the real classification). Lower-cased substring matching.
_KNOWN_SDK_NAMES: frozenset[str] = frozenset({
    "@aether/web",
    "aether-web",
    "@aether/react-native",
    "aether-react-native",
    "react-native",
    "aether-ios",
    "aether-ios-sdk",
    "ios",
    "aether-android",
    "aether-android-sdk",
    "android",
    "aether",
})

# Canonical ingestion capability ids that per-band capability sets reference.
CAP_BATCH_INGESTION = "batch_ingestion"              # POST /v1/batch event submission
CAP_SERVER_SIDE = "server_side_ingestion"            # /v1/ingest/events + /v1/ingest/feed
CAP_ENVELOPE_B = "canonical_observation_envelope"    # Envelope-B observation model (schema v7+)
CAP_NORMALIZATION_SPINE = "normalization_spine"      # downstream observation-view reads
CAP_REPLAY = "idempotent_replay"                     # durable Bronze replay eligibility

# Full capability set for a currently-supported band.
_CAPS_FULL = (
    CAP_BATCH_INGESTION,
    CAP_SERVER_SIDE,
    CAP_ENVELOPE_B,
    CAP_NORMALIZATION_SPINE,
    CAP_REPLAY,
)
# Pre-Envelope-B bands (schema v6 era): flat SDK submission only.
_CAPS_FLAT = (CAP_BATCH_INGESTION, CAP_SERVER_SIDE, CAP_REPLAY)

# 5.x blocked-after-date (blueprint §18). Enforcement (mode=enforce) only ever
# rejects a 5.x event on/after this date; before it, 5.x stays read-compatible-
# on-ingress (accepted with an advisory). Far enough out that nothing in the
# current tree is blocked.
BLOCKED_AFTER_DATE = "2027-01-31"
_DEPRECATED_AFTER_DATE = "2027-06-30"  # advisory signal for 7.x deprecation


@dataclass(frozen=True)
class SdkVersionBand:
    """One SDK version compatibility band (advisory policy data)."""

    id: str
    status: str  # supported | deprecated | read_compatible | blocked | unsupported | unclassified
    label: str
    min_version: Optional[str]  # inclusive lower bound (None = open / unclassified)
    max_version_exclusive: Optional[str]  # exclusive upper bound (None = open)
    deprecated_after: Optional[str]
    blocked_after: Optional[str]
    capabilities: tuple[str, ...]
    note: str = ""

    def includes(self, version: "_ParsedVersion") -> bool:
        if self.min_version is None and self.max_version_exclusive is None:
            # Open sentinel (unclassified): never matches a real parseable version.
            return False
        if self.min_version is not None:
            lower = _parse_version(self.min_version)
            if lower is not None and version < lower:
                return False
        if self.max_version_exclusive is not None:
            upper = _parse_version(self.max_version_exclusive)
            if upper is not None and version >= upper:
                return False
        return True


@dataclass(frozen=True)
class _ParsedVersion:
    major: int
    minor: int
    patch: int

    def __lt__(self, other: "_ParsedVersion") -> bool:
        return (self.major, self.minor, self.patch) < (
            other.major, other.minor, other.patch,
        )

    def __le__(self, other: "_ParsedVersion") -> bool:
        return (self.major, self.minor, self.patch) <= (
            other.major, other.minor, other.patch,
        )

    def __ge__(self, other: "_ParsedVersion") -> bool:
        return (self.major, self.minor, self.patch) >= (
            other.major, other.minor, other.patch,
        )


# Ordered bands consulted from newest to oldest; the first inclusive match wins.
SDK_VERSION_BANDS: tuple[SdkVersionBand, ...] = (
    SdkVersionBand(
        id="supported",
        status="supported",
        label="Supported",
        min_version="8.0.0",
        max_version_exclusive=None,
        deprecated_after=None,
        blocked_after=None,
        capabilities=_CAPS_FULL,
        note="Current canonical SDK band (8.x). Full ingestion capability set.",
    ),
    SdkVersionBand(
        id="deprecated",
        status="deprecated",
        label="Deprecated",
        min_version="7.0.0",
        max_version_exclusive="8.0.0",
        deprecated_after=_DEPRECATED_AFTER_DATE,
        blocked_after=None,
        capabilities=_CAPS_FULL,
        note="7.x — still fully served; scheduled to move to read-compatible.",
    ),
    SdkVersionBand(
        id="read_compatible",
        status="read_compatible",
        label="Read-compatible",
        min_version="6.0.0",
        max_version_exclusive="7.0.0",
        deprecated_after=None,
        blocked_after=None,
        capabilities=_CAPS_FLAT,
        note="6.x — flat SDK submission only (pre-Envelope-B).",
    ),
    SdkVersionBand(
        id="blocked",
        status="blocked",
        label="Blocked after date",
        min_version="5.0.0",
        max_version_exclusive="6.0.0",
        deprecated_after=None,
        blocked_after=BLOCKED_AFTER_DATE,
        capabilities=_CAPS_FLAT,
        note=(
            f"5.x — rejected by enforce-mode ingress on/after "
            f"{BLOCKED_AFTER_DATE}; advisory before then."
        ),
    ),
    SdkVersionBand(
        id="unsupported",
        status="unsupported",
        label="Unsupported",
        min_version=None,
        max_version_exclusive="5.0.0",
        deprecated_after=None,
        blocked_after=BLOCKED_AFTER_DATE,
        capabilities=(),
        note="<5.0.0 — outside every supported band; advisory only.",
    ),
)

# Sentinel for missing / unparseable version (or unrecognized library name).
UNCLASSIFIED_BAND = SdkVersionBand(
    id="unclassified",
    status="unclassified",
    label="Unclassified",
    min_version=None,
    max_version_exclusive=None,
    deprecated_after=None,
    blocked_after=None,
    capabilities=(),
    note="Unknown SDK version or library name — never blocked; advisory only.",
)


def _parse_version(version: Optional[str]) -> Optional[_ParsedVersion]:
    """Parse a ``major.minor.patch`` (patch optional) semver-ish string."""
    if not version:
        return None
    core = str(version).strip().lstrip("v").split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts[:3]):
        return None
    major = int(parts[0])
    minor = int(parts[1])
    patch = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
    return _ParsedVersion(major, minor, patch)


def sdk_name_known(name: Optional[str]) -> bool:
    """Whether the reported SDK library name is a recognized server-side SDK."""
    if not name:
        return False
    lowered = str(name).strip().lower()
    return any(known in lowered for known in _KNOWN_SDK_NAMES)


def classify_sdk_version(version: Optional[str], name: Optional[str] = None) -> SdkVersionBand:
    """Classify a client ``library.version`` into a compatibility band."""
    parsed = _parse_version(version)
    if parsed is None:
        return UNCLASSIFIED_BAND
    if name is not None and not sdk_name_known(name):
        # A real, parseable version from an unrecognized library is still
        # classified by version (harmless), but flagged as unknown-name.
        for band in SDK_VERSION_BANDS:
            if band.includes(parsed):
                return band
        return UNCLASSIFIED_BAND
    for band in SDK_VERSION_BANDS:
        if band.includes(parsed):
            return band
    return UNCLASSIFIED_BAND


def _utc_today_iso() -> str:
    return date.fromtimestamp(datetime.now(timezone.utc).timestamp()).isoformat()


def version_tiers_enabled() -> bool:
    return settings.sdk_version_compat.enabled


def compat_mode() -> str:
    return (settings.sdk_version_compat.mode or "off").lower()


def _blocked_effective(band: SdkVersionBand) -> bool:
    """Whether the band's blocked-after date has arrived (date-only gate)."""
    if not band.blocked_after:
        return False
    return _utc_today_iso() >= band.blocked_after


def sdk_version_advisory(library: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Advisory tier label for one event's ``context.library``.

    Returns None when the version-compat flag is OFF or the client reported no
    library block (today's behavior: all clients treated identically). A
    returned dict is additive metadata only and is never a rejection by itself.
    """
    if not version_tiers_enabled():
        return None
    if not library:
        return None
    name = library.get("name")
    version = library.get("version")
    band = classify_sdk_version(version, name)
    return {
        "consulted": True,
        "mode": compat_mode(),
        "tier": band.id,
        "label": band.label,
        "capabilities": list(band.capabilities),
        "blocked_after": band.blocked_after,
        "source": {"name": name, "version": version},
    }


def sdk_version_ingress_blocked(library: Optional[dict[str, Any]]) -> bool:
    """Enforce-mode rejection decision for one event's ``context.library``.

    True ONLY when: the version-compat flag is ON, mode == "enforce", the client
    reported a library block, its band is blocked-after-date, AND that date has
    arrived. Inert by default (flag OFF) and before the blocked-after date.
    """
    if not version_tiers_enabled():
        return False
    if compat_mode() != "enforce":
        return False
    if not library:
        return False
    band = classify_sdk_version(library.get("version"), library.get("name"))
    return band.status in ("blocked", "unsupported") and _blocked_effective(band)


def tiers_payload() -> dict[str, Any]:
    """SDK capability-manifest block served at GET /v1/config/sdk/versions."""
    return {
        "schema_version": "1.0.0",
        "enabled": version_tiers_enabled(),
        "mode": compat_mode(),
        "blocked_after_date": BLOCKED_AFTER_DATE,
        "tiers": [
            {
                "id": band.id,
                "status": band.status,
                "label": band.label,
                "min_version": band.min_version,
                "max_version_exclusive": band.max_version_exclusive,
                "deprecated_after": band.deprecated_after,
                "blocked_after": band.blocked_after,
                "capabilities": list(band.capabilities),
                "note": band.note,
            }
            for band in SDK_VERSION_BANDS
        ],
        "unclassified": {
            "id": UNCLASSIFIED_BAND.id,
            "label": UNCLASSIFIED_BAND.label,
            "note": UNCLASSIFIED_BAND.note,
        },
    }
