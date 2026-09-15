"""Which SDK version the platform ships, and where one install sits relative to it.

The install verifier has to answer "is this site running the version we want?"
and the backend has no runtime view of the CDN bundle, so the answer has to be
stated here. Stating it *twice* is the real hazard: a version literal that drifts
silently would report every healthy install as out of date, which is worse than
reporting nothing, because an operator would go and change working code.

So this is a mirror, not a second authority. ``packages/shared/sdk-version.ts``
owns the value; ``scripts/validate_sdk_release_alignment.py`` fails the build
when this copy disagrees with it — the same arrangement that already holds the
loader's standalone copy of ``CONTRACT_SCHEMA_VERSION`` to the shared constant.
"""

from __future__ import annotations

from typing import Optional

from services.ingestion.sdk_version_tiers import (
    classify_sdk_version,
    compare_sdk_versions,
)

#: The canonical SDK release version, mirrored from packages/shared/sdk-version.ts.
CANONICAL_SDK_VERSION = "0.1.0-alpha.0"

# Drift status — how one install's reported version relates to the shipped one.
DRIFT_CURRENT = "current"
DRIFT_BEHIND = "behind"
DRIFT_AHEAD = "ahead"
DRIFT_UNKNOWN = "unknown"


def classify_install_drift(reported: Optional[str]) -> str:
    """Compare a reported version against the shipped one.

    ``ahead`` is deliberately its own status rather than being folded into
    ``current``: a client running a version this backend has never heard of is
    not a healthy install, it is a cache serving something unexpected, and the
    two want different responses.
    """
    order = compare_sdk_versions(reported, CANONICAL_SDK_VERSION)
    if order is None:
        return DRIFT_UNKNOWN
    if order == 0:
        return DRIFT_CURRENT
    return DRIFT_BEHIND if order < 0 else DRIFT_AHEAD


def describe_install_version(
    reported: Optional[str], name: Optional[str] = None
) -> dict:
    """The version half of a site-install record.

    One function so the projection and the read endpoints cannot disagree about
    what an install's version fields mean.
    """
    return {
        "loader_version": reported,
        "compatibility_tier": classify_sdk_version(reported, name).id,
        "desired_version": CANONICAL_SDK_VERSION,
        "drift_status": classify_install_drift(reported),
    }
