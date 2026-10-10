"""Resolve the tenant-safe release surface for the active deployment profile.

Combines two canonical config sources into one non-secret release descriptor:
  - ``config/deployment_profiles.yaml`` — the profile's release ``class``;
  - ``config/founding_tenant_release.yaml`` — the enabled route prefixes and
    excluded domains, which apply only when the active profile matches the
    manifest's declared profile.

Only non-secret, non-tenant-specific release metadata is exposed. This is the
single backend authority the capability contract (and the frontends, via it)
consult to know what the active profile actually offers.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml


def _config_dir() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "deployment_profiles.yaml"
        if candidate.exists():
            return candidate.parent
    return None


@lru_cache(maxsize=1)
def _profiles() -> dict:
    cfg = _config_dir()
    if cfg is None:
        return {}
    try:
        data = yaml.safe_load((cfg / "deployment_profiles.yaml").read_text()) or {}
        return data.get("profiles") or {}
    except Exception:  # pragma: no cover - malformed config: surface stays minimal
        return {}


@lru_cache(maxsize=1)
def _founding_manifest() -> dict:
    cfg = _config_dir()
    if cfg is None:
        return {}
    try:
        return yaml.safe_load((cfg / "founding_tenant_release.yaml").read_text()) or {}
    except Exception:  # pragma: no cover - malformed manifest: surface stays minimal
        return {}


def resolve_release_surface(active_profile: str) -> dict:
    """Return the non-secret release surface for ``active_profile``.

    ``enabled_route_prefixes`` / ``excluded_domains`` are populated only when
    the founding-tenant manifest declares the same profile; every other profile
    resolves to empty lists (no manifest narrowing).
    """
    prof = _profiles().get(active_profile) or {}
    release_class = str(prof.get("class", "")) or None

    manifest = _founding_manifest()
    enabled_prefixes: list[str] = []
    excluded_domains: list[str] = []
    if str(manifest.get("profile", "")) == active_profile:
        surface = manifest.get("release_surface") or {}
        enabled_prefixes = [str(p) for p in (surface.get("enabled_route_prefixes") or [])]
        excluded_domains = [str(d) for d in (surface.get("excluded_domains") or [])]

    return {
        "deployment_profile": active_profile,
        "release_class": release_class,
        "enabled_route_prefixes": enabled_prefixes,
        "excluded_domains": excluded_domains,
    }
