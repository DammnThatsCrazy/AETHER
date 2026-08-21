"""§32 plugin honesty validation — manifest claims vs present adapters (Team C).

A plugin is dishonest when its manifest overclaims a capability its adapter
surface does not provide, or underclaims a capability its adapter surface does
provide. :func:`capability_violations` collects every violation across the five
capability areas (auth, account, pull, webhook, reconciliation) in *both*
directions, plus the manifest-level invariants from
:func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`
and the identity cross-check from
:func:`plugin_identity_key <shared.integration_contracts.plugin.plugin_identity_key>`.

The registry runs :func:`assert_plugin_honest` on every registration, so a
plugin cannot ship a lying manifest into the runtime.
"""

from __future__ import annotations

from typing import Callable

from shared.integration_contracts.manifest import (
    ManifestValidationError,
    ProviderManifest,
    validate_manifest,
)
from shared.integration_contracts.plugin import (
    PluginValidationError,
    capability_set,
    plugin_identity_key,
)

# (capability accessor name, manifest-claims predicate). ``capability`` matches
# both the CapabilitySet field names and the plugin accessor names.
_CAPABILITY_CLAIMS: tuple[tuple[str, Callable[[ProviderManifest], bool]], ...] = (
    ("auth", lambda m: m.authentication.type != "none"),
    (
        "account",
        lambda m: m.accounts.discovery_supported or m.accounts.selection_required,
    ),
    ("pull", lambda m: m.sync.incremental or m.sync.initial_backfill),
    ("webhook", lambda m: m.webhooks.supported),
    ("reconciliation", lambda m: m.sync.reconciliation),
)


def capability_violations(plugin: object) -> list[str]:
    """Collect every §32 honesty violation for a plugin (empty list = honest).

    Checks, in order:

    1. the manifest passes :func:`validate_manifest` (manifest-level §32 rules);
    2. ``manifest().identity_key`` equals ``identity().key``;
    3. for each of the five capability areas, the manifest claims it iff the
       plugin exposes a non-``None`` adapter for it (both directions).

    A plugin whose accessors raise is itself a violation — never a silent pass.
    """
    violations: list[str] = []

    try:
        manifest = plugin.manifest()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - a raising accessor is a violation
        violations.append(f"manifest() raised: {exc!r}")
        return violations

    # 1. Manifest-level §32 invariants (structural honesty of the manifest).
    try:
        validate_manifest(manifest)
    except ManifestValidationError as exc:
        violations.extend(exc.violations)

    # 2. The manifest's declared identity must equal the identity object.
    #    Catch broadly: ``plugin_identity_key`` also invokes ``identity()``, and
    #    a raising accessor is itself a violation — never a silent pass.
    try:
        plugin_identity_key(plugin)
    except PluginValidationError as exc:
        violations.extend(exc.violations)
    except Exception as exc:  # noqa: BLE001 - a raising accessor is a violation
        violations.append(f"identity cross-check raised: {exc!r}")

    # 3. The five capability areas — both honesty directions.
    try:
        caps = capability_set(plugin)
    except Exception as exc:  # noqa: BLE001 - a raising accessor is a violation
        violations.append(f"capability accessor raised: {exc!r}")
        return violations

    for cap, claims_capability in _CAPABILITY_CLAIMS:
        claimed = claims_capability(manifest)
        present = getattr(caps, cap)
        if claimed and not present:
            violations.append(
                f"manifest claims capability {cap!r} but the plugin exposes no adapter"
            )
        elif present and not claimed:
            violations.append(
                f"plugin exposes a {cap}() adapter but the manifest does not claim it"
            )

    return violations


def assert_plugin_honest(plugin: object) -> None:
    """Raise :class:`PluginValidationError` unless the plugin is fully honest.

    Collects every violation and raises once so a caller sees them all at once.
    """
    violations = capability_violations(plugin)
    if violations:
        raise PluginValidationError(violations)
    return None


__all__ = [
    "assert_plugin_honest",
    "capability_violations",
]
