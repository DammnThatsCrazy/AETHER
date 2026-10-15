"""The provider plugin contract — a self-contained provider runtime unit.

A :class:`ProviderPlugin` is a set of accessor methods: identity, manifest, one
optional adapter per capability, and a normalizer. ``runtime_checkable`` makes
structural :func:`isinstance` checks work, so the runtime can screen a candidate
object as a plugin before invoking it.

Two honest-surface helpers sit next to the protocol:

* :func:`plugin_identity_key` — cross-checks the manifest's declared identity
  against the identity object; a mismatch is a hard :class:`PluginValidationError`.
* :func:`capability_set` — derives an honest :class:`CapabilitySet` from which
  adapter accessors actually return a non-``None`` adapter.

:class:`CapabilitySet` is frozen so a plugin's declared capabilities cannot be
mutated after discovery.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from shared.integration_contracts.capabilities import (
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    ReportAdapter,
    StreamAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import ProviderManifest
from shared.integration_contracts.normalization import EventNormalizer


class CapabilitySet(BaseModel):
    """Which capability adapters a plugin exposes (honest, frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth: bool = False
    account: bool = False
    pull: bool = False
    webhook: bool = False
    report: bool = False
    stream: bool = False
    reconciliation: bool = False


class PluginValidationError(ValueError):
    """Raised when a plugin violates a plugin-level honesty invariant.

    ``violations`` carries every failure so a caller sees them all at once.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


@runtime_checkable
class ProviderPlugin(Protocol):
    """The structural contract every provider plugin must satisfy.

    Each capability accessor returns the adapter instance or ``None`` when the
    capability is not implemented. ``normalizer()`` is always present.
    """

    def identity(self) -> ProviderIdentity: ...

    def manifest(self) -> ProviderManifest: ...

    def auth(self) -> Optional[AuthAdapter]: ...

    def account(self) -> Optional[AccountAdapter]: ...

    def pull(self) -> Optional[PullAdapter]: ...

    def webhook(self) -> Optional[WebhookAdapter]: ...

    def report(self) -> Optional[ReportAdapter]: ...

    def stream(self) -> Optional[StreamAdapter]: ...

    def reconciliation(self) -> Optional[ReconciliationAdapter]: ...

    def normalizer(self) -> EventNormalizer: ...


def plugin_identity_key(plugin: object) -> str:
    """Return ``manifest().identity_key``, asserting it equals ``identity().key``.

    Raises :class:`PluginValidationError` when the two disagree — the manifest
    and identity object must describe the same ``family.product.capability``.
    """
    manifest_obj = plugin.manifest()  # type: ignore[attr-defined]
    identity_obj = plugin.identity()  # type: ignore[attr-defined]
    key = manifest_obj.identity_key
    if key != identity_obj.key:
        raise PluginValidationError(
            [
                f"manifest identity_key {key!r} does not equal "
                f"identity().key {identity_obj.key!r}"
            ]
        )
    return key


def capability_set(plugin: object) -> CapabilitySet:
    """Honest capability set: bool per adapter accessor returning non-``None``."""
    return CapabilitySet(
        auth=plugin.auth() is not None,  # type: ignore[attr-defined]
        account=plugin.account() is not None,  # type: ignore[attr-defined]
        pull=plugin.pull() is not None,  # type: ignore[attr-defined]
        webhook=plugin.webhook() is not None,  # type: ignore[attr-defined]
        report=plugin.report() is not None,  # type: ignore[attr-defined]
        stream=plugin.stream() is not None,  # type: ignore[attr-defined]
        reconciliation=plugin.reconciliation() is not None,  # type: ignore[attr-defined]
    )


__all__ = [
    "CapabilitySet",
    "PluginValidationError",
    "ProviderPlugin",
    "capability_set",
    "plugin_identity_key",
]
