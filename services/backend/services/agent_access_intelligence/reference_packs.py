"""Reference pack loader — curated, versioned descriptions of agent-access providers.

A *reference pack* (``config/agent_access_reference_packs/*.yaml``) describes one
provider in the vocabulary ``services/agentic_observability/provider_framework.py``
already defines: a ``provider_id``, the ``CapabilityKind`` an observation defaults
to, which observation fields carry the server/tool identity, and the
``approved_scope_baselines`` mapping consumed *verbatim* by
``provider_framework.compute_permission_findings``.

Purity: this module reads one directory of YAML and nothing else. No network, no
clock, no database, no writes. Import has no side effects beyond binding the
``CapabilityKind`` vocabulary; packs are read lazily on first call and cached at
module level (keyed by directory), so repeated lookups do no further I/O.

**A malformed pack raises — it is never skipped.** That rule is load-bearing rather
than fastidious: ``compute_permission_findings`` looks up
``approved_scope_baselines[grant.grant_id]`` and defaults a missing key to ``[]``,
so a dropped pack does not fail closed in the obvious direction — it removes that
provider's baselines entirely, and a caller that expected the pack to supply them
gets a scope-comparison result built from nothing. Failing the load is the only way
that stays visible.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Optional

import yaml

from services.agent_access_intelligence.models import CapabilityKind

#: Pack schema version this loader understands. A pack declaring anything else is
#: rejected rather than best-effort parsed.
SCHEMA_VERSION = 1

#: Canonical pack directory: <repo root>/config/agent_access_reference_packs.
PACK_DIR = (
    Path(__file__).resolve().parents[4] / "config" / "agent_access_reference_packs"
)

#: Both suffixes are read. A stray ``.yml`` pack must not be invisible — an ignored
#: file is a silently dropped pack, the exact failure this module refuses to have.
PACK_SUFFIXES = (".yaml", ".yml")

PACK_STATUSES = ("reference", "example")
BASELINE_STATUSES = ("asserted", "none_asserted")

_REQUIRED_FIELDS = (
    "schema_version",
    "pack_id",
    "pack_version",
    "pack_status",
    "provider_id",
    "display_name",
    "capability_kind_defaults",
    "naming_hints",
    "baseline_status",
    "approved_scope_baselines",
)

_CAPABILITY_KINDS = frozenset(k.value for k in CapabilityKind)

# Parsed packs, keyed by resolved directory path. Populated on first load.
_PACK_CACHE: dict[str, list[dict[str, Any]]] = {}


class ReferencePackError(ValueError):
    """A pack is unreadable, malformed, or violates the pack schema.

    Always names the offending file and field. Raised — never swallowed — so a bad
    pack cannot quietly vanish and take a provider's scope baselines with it.
    """


def pack_violations(data: Any, source: str, filename_stem: str) -> list[str]:
    """Return every schema violation in one pack. Empty list == valid.

    Shared by the loader and ``scripts/validate_reference_packs.py`` so the CI gate
    and the runtime loader can never disagree about what a valid pack is.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"{source}: pack must be a YAML mapping, got {type(data).__name__}"]

    for field in _REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"{source}: missing required field '{field}'")

    schema_version = data.get("schema_version")
    if "schema_version" in data and schema_version != SCHEMA_VERSION:
        errors.append(
            f"{source}: field 'schema_version' must be {SCHEMA_VERSION}, got {schema_version!r}"
        )

    pack_id = data.get("pack_id")
    if "pack_id" in data:
        if not isinstance(pack_id, str) or not pack_id.strip():
            errors.append(f"{source}: field 'pack_id' must be a non-empty string, got {pack_id!r}")
        elif pack_id != filename_stem:
            errors.append(
                f"{source}: field 'pack_id' is {pack_id!r} but must match the filename stem "
                f"{filename_stem!r}"
            )

    for field in ("pack_version", "provider_id", "display_name"):
        if field in data:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"{source}: field '{field}' must be a non-empty string, got {value!r}"
                )

    pack_status = data.get("pack_status")
    if "pack_status" in data and pack_status not in PACK_STATUSES:
        errors.append(
            f"{source}: field 'pack_status' must be one of {list(PACK_STATUSES)}, got {pack_status!r}"
        )

    # A reference pack claims to describe something real, so it must say where that
    # claim comes from. Without this, an invented pack is indistinguishable from a
    # grounded one.
    if pack_status == "reference":
        grounded = data.get("grounded_in")
        if not isinstance(grounded, list) or not grounded:
            errors.append(
                f"{source}: field 'grounded_in' must be a non-empty list for "
                f"pack_status 'reference' (name the repo files each claim comes from)"
            )
        elif not all(isinstance(g, str) and g.strip() for g in grounded):
            errors.append(f"{source}: field 'grounded_in' must contain only non-empty strings")

    defaults = data.get("capability_kind_defaults")
    if "capability_kind_defaults" in data:
        if not isinstance(defaults, dict):
            errors.append(
                f"{source}: field 'capability_kind_defaults' must be a mapping, "
                f"got {type(defaults).__name__}"
            )
        else:
            default_kind = defaults.get("default")
            if default_kind not in _CAPABILITY_KINDS:
                errors.append(
                    f"{source}: field 'capability_kind_defaults.default' must be a CapabilityKind "
                    f"({sorted(_CAPABILITY_KINDS)}), got {default_kind!r}"
                )
            by_object_type = defaults.get("by_object_type", {})
            if not isinstance(by_object_type, dict):
                errors.append(
                    f"{source}: field 'capability_kind_defaults.by_object_type' must be a mapping, "
                    f"got {type(by_object_type).__name__}"
                )
            else:
                for object_type, kind in by_object_type.items():
                    if kind not in _CAPABILITY_KINDS:
                        errors.append(
                            f"{source}: field 'capability_kind_defaults.by_object_type[{object_type!r}]' "
                            f"must be a CapabilityKind ({sorted(_CAPABILITY_KINDS)}), got {kind!r}"
                        )

    naming_hints = data.get("naming_hints")
    if "naming_hints" in data:
        if not isinstance(naming_hints, dict):
            errors.append(
                f"{source}: field 'naming_hints' must be a mapping, "
                f"got {type(naming_hints).__name__}"
            )
        else:
            for hint_key, hint_value in naming_hints.items():
                if not isinstance(hint_value, list) or not all(
                    isinstance(v, str) for v in hint_value
                ):
                    errors.append(
                        f"{source}: field 'naming_hints[{hint_key!r}]' must be a list of strings, "
                        f"got {hint_value!r}"
                    )

    baseline_status = data.get("baseline_status")
    if "baseline_status" in data and baseline_status not in BASELINE_STATUSES:
        errors.append(
            f"{source}: field 'baseline_status' must be one of {list(BASELINE_STATUSES)}, "
            f"got {baseline_status!r}"
        )

    baselines = data.get("approved_scope_baselines")
    if "approved_scope_baselines" in data:
        if not isinstance(baselines, dict):
            errors.append(
                f"{source}: field 'approved_scope_baselines' must be a mapping of "
                f"grant_id -> list[str], got {type(baselines).__name__}"
            )
        else:
            for grant_id, scopes in baselines.items():
                if not isinstance(grant_id, str) or not grant_id.strip():
                    errors.append(
                        f"{source}: field 'approved_scope_baselines' has a non-string key "
                        f"{grant_id!r} (keys are AuthorizationGrantRecord.grant_id)"
                    )
                if not isinstance(scopes, list) or not all(
                    isinstance(s, str) and s.strip() for s in scopes
                ):
                    errors.append(
                        f"{source}: field 'approved_scope_baselines[{grant_id!r}]' must be a list "
                        f"of non-empty scope strings, got {scopes!r}"
                    )
            # An empty baselines map is a legitimate, deliberate posture (every scope
            # gets reported). It must be DECLARED so a truncated or half-written pack
            # cannot pass as an intentional no-baseline pack.
            if not baselines and baseline_status != "none_asserted":
                errors.append(
                    f"{source}: 'approved_scope_baselines' is empty but 'baseline_status' is "
                    f"{baseline_status!r} — declare baseline_status: none_asserted to ship a pack "
                    f"with no approved scopes"
                )
            if baselines and baseline_status == "none_asserted":
                errors.append(
                    f"{source}: 'baseline_status' is 'none_asserted' but "
                    f"'approved_scope_baselines' has {len(baselines)} entries"
                )

    return errors


def _read_pack(path: Path) -> dict[str, Any]:
    """Parse and validate a single pack file. Raises ReferencePackError."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReferencePackError(f"{path.name}: cannot read pack file ({exc})") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ReferencePackError(f"{path.name}: invalid YAML ({exc})") from exc

    errors = pack_violations(data, path.name, path.stem)
    if errors:
        raise ReferencePackError("; ".join(errors))
    return data


def load_reference_packs(directory: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """Load every pack in ``directory`` (default: ``PACK_DIR``), sorted by ``pack_id``.

    Parsed packs are cached at module level per directory; callers get a deep copy so
    a caller mutating its result cannot corrupt another caller's view.

    Raises ``ReferencePackError`` if the directory is missing, a pack is malformed, or
    two packs declare the same ``pack_id``. No pack is ever skipped.
    """
    base = Path(directory) if directory is not None else PACK_DIR
    base = base.resolve()
    key = str(base)

    cached = _PACK_CACHE.get(key)
    if cached is None:
        if not base.is_dir():
            raise ReferencePackError(f"reference pack directory not found: {base}")

        paths = sorted(p for p in base.iterdir() if p.suffix in PACK_SUFFIXES and p.is_file())
        packs: list[dict[str, Any]] = []
        seen: dict[str, str] = {}
        for path in paths:
            pack = _read_pack(path)
            pack_id = pack["pack_id"]
            if pack_id in seen:
                raise ReferencePackError(
                    f"{path.name}: duplicate pack_id {pack_id!r} — already declared by "
                    f"{seen[pack_id]}"
                )
            seen[pack_id] = path.name
            packs.append(pack)

        cached = sorted(packs, key=lambda p: p["pack_id"])
        _PACK_CACHE[key] = cached

    return copy.deepcopy(cached)


def get_reference_pack(
    pack_id: str, directory: Optional[Path | str] = None
) -> Optional[dict[str, Any]]:
    """Return the pack with ``pack_id``, or ``None`` if no such pack exists.

    ``None`` here means "no pack by that id", never "a pack existed but failed to
    parse" — a malformed pack raises out of ``load_reference_packs``.
    """
    for pack in load_reference_packs(directory):
        if pack["pack_id"] == pack_id:
            return pack
    return None


def approved_scope_baselines_for(
    provider_id: str, directory: Optional[Path | str] = None
) -> dict[str, list[str]]:
    """Return the approved scope baselines for ``provider_id``.

    The return value is the exact shape ``compute_permission_findings`` takes as its
    ``approved_scope_baselines`` argument: ``{grant_id: [scope, ...]}``.

    Matching is on ``provider_id`` exactly, so a template pack
    (``pack_status: example``) can never contribute its fictional scopes to a real
    provider. An unknown provider — or a provider whose pack declares
    ``baseline_status: none_asserted`` — yields ``{}``, which makes
    ``compute_permission_findings`` report every observed scope for review rather
    than approve it.

    Raises ``ReferencePackError`` if two packs for the same provider disagree about a
    grant's baseline; silently picking one would decide a scope question by file
    ordering.
    """
    merged: dict[str, list[str]] = {}
    origin: dict[str, str] = {}
    for pack in load_reference_packs(directory):
        if pack["provider_id"] != provider_id:
            continue
        for grant_id, scopes in pack["approved_scope_baselines"].items():
            if grant_id in merged and merged[grant_id] != scopes:
                raise ReferencePackError(
                    f"conflicting approved_scope_baselines for provider {provider_id!r} "
                    f"grant {grant_id!r}: pack {origin[grant_id]!r} says {merged[grant_id]} but "
                    f"pack {pack['pack_id']!r} says {scopes}"
                )
            merged[grant_id] = list(scopes)
            origin[grant_id] = pack["pack_id"]
    return merged


def clear_pack_cache() -> None:
    """Drop the module-level parse cache. For tests; not used at runtime."""
    _PACK_CACHE.clear()
