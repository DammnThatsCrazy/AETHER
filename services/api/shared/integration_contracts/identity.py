"""Canonical provider identity (§11).

Identity in the Unified Integration Control Plane is *per-capability*. A
provider is never a single opaque entity — it is a family (e.g. ``shopify``),
a product within that family (e.g. ``admin``), and a single capability the
product exposes (e.g. ``orders_read``). The stable string form is
``family.product.capability``.

The per-capability rule is a hard honesty invariant: a feature flag, a
credential, or a webhook registered for one capability must never implicitly
enable another. Two identities that differ only in ``capability`` are distinct
objects with distinct string forms and are never equal — there is no widening
from one capability to its siblings.

``CapabilityKey`` is the *canonical* capability vocabulary (``domain.resource.
action``, e.g. ``commerce.orders.read``). It classifies what a capability does
in provider-neutral terms; a provider's ``capability`` segment maps onto one
canonical key but the two namespaces are kept separate on purpose.
"""

from __future__ import annotations

import re
from typing import NewType

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

# Distinct string subtypes for the three identity segments. They are ``str`` at
# runtime (pydantic treats a NewType as its supertype) but give call sites and
# type-checkers a stronger contract than a bare ``str``.
ProviderFamily = NewType("ProviderFamily", str)
ProductId = NewType("ProductId", str)
CapabilityId = NewType("CapabilityId", str)

# A single identity/capability segment: lowercase, starts with a letter, then
# letters/digits/underscores. Dots are reserved as the segment separator.
_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_IDENTITY_PARTS = 3
_CAPABILITY_KEY_PARTS = 3


class IdentityError(ValueError):
    """Raised when an identity or capability key is malformed."""


def _validate_segment(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _SEGMENT_RE.match(value):
        raise IdentityError(
            f"invalid {label} segment {value!r}: expected /^[a-z][a-z0-9_]*$/"
        )
    return value


# Canonical, provider-neutral capability keys. This is a curated, extensible
# vocabulary — membership is what makes a capability "canonical".
CANONICAL_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        "commerce.orders.read",
        "analytics.events.read",
        "market.prices.read",
        "payments.onramp.observe",
        "identity.accounts.resolve",
    }
)


class ProviderIdentity(BaseModel):
    """Frozen, per-capability provider identity.

    The canonical string form is ``family.product.capability``. Instances are
    immutable and hashable, so they are safe as dict keys / set members and
    equality is structural — two identities are equal iff all three segments
    match.
    """

    model_config = ConfigDict(frozen=True)

    family: ProviderFamily
    product: ProductId
    capability: CapabilityId

    @field_validator("family")
    @classmethod
    def _v_family(cls, v: str) -> str:
        return _validate_segment(v, label="family")

    @field_validator("product")
    @classmethod
    def _v_product(cls, v: str) -> str:
        return _validate_segment(v, label="product")

    @field_validator("capability")
    @classmethod
    def _v_capability(cls, v: str) -> str:
        return _validate_segment(v, label="capability")

    @property
    def key(self) -> str:
        """Stable ``family.product.capability`` string form."""
        return f"{self.family}.{self.product}.{self.capability}"

    def __str__(self) -> str:  # pragma: no cover - trivial delegation
        return self.key

    @classmethod
    def parse(cls, raw: str) -> "ProviderIdentity":
        """Parse a ``family.product.capability`` string into an identity."""
        if not isinstance(raw, str):
            raise IdentityError(f"identity must be a string, got {type(raw)!r}")
        parts = raw.split(".")
        if len(parts) != _IDENTITY_PARTS:
            raise IdentityError(
                f"identity {raw!r} must have exactly {_IDENTITY_PARTS} "
                "dot-separated segments (family.product.capability)"
            )
        family, product, capability = parts
        try:
            return cls(
                family=ProviderFamily(family),
                product=ProductId(product),
                capability=CapabilityId(capability),
            )
        except ValidationError as exc:  # normalize to the module error type
            raise IdentityError(str(exc)) from exc


class CapabilityKey(BaseModel):
    """Canonical capability key: ``domain.resource.action``.

    This is the provider-neutral classification of *what a capability does*
    (e.g. ``commerce.orders.read``), distinct from a specific provider's
    ``capability`` segment.
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    resource: str
    action: str

    @field_validator("domain")
    @classmethod
    def _v_domain(cls, v: str) -> str:
        return _validate_segment(v, label="capability domain")

    @field_validator("resource")
    @classmethod
    def _v_resource(cls, v: str) -> str:
        return _validate_segment(v, label="capability resource")

    @field_validator("action")
    @classmethod
    def _v_action(cls, v: str) -> str:
        return _validate_segment(v, label="capability action")

    @property
    def value(self) -> str:
        """Stable ``domain.resource.action`` string form."""
        return f"{self.domain}.{self.resource}.{self.action}"

    def __str__(self) -> str:  # pragma: no cover - trivial delegation
        return self.value

    @property
    def is_canonical(self) -> bool:
        """True iff this key is in :data:`CANONICAL_CAPABILITY_KEYS`."""
        return self.value in CANONICAL_CAPABILITY_KEYS

    @classmethod
    def parse(cls, raw: str) -> "CapabilityKey":
        """Parse a ``domain.resource.action`` string into a capability key."""
        if not isinstance(raw, str):
            raise IdentityError(f"capability key must be a string, got {type(raw)!r}")
        parts = raw.split(".")
        if len(parts) != _CAPABILITY_KEY_PARTS:
            raise IdentityError(
                f"capability key {raw!r} must have exactly {_CAPABILITY_KEY_PARTS} "
                "dot-separated segments (domain.resource.action)"
            )
        domain, resource, action = parts
        try:
            return cls(domain=domain, resource=resource, action=action)
        except ValidationError as exc:  # normalize to the module error type
            raise IdentityError(str(exc)) from exc


# ── Module-level parse/format helpers ──────────────────────────────────────


def parse_identity(raw: str) -> ProviderIdentity:
    """Parse ``family.product.capability`` into a :class:`ProviderIdentity`."""
    return ProviderIdentity.parse(raw)


def format_identity(
    family: str, product: str, capability: str
) -> str:
    """Validate the three segments and return the canonical string form."""
    try:
        return ProviderIdentity(
            family=ProviderFamily(family),
            product=ProductId(product),
            capability=CapabilityId(capability),
        ).key
    except ValidationError as exc:  # normalize to the module error type
        raise IdentityError(str(exc)) from exc


def parse_capability_key(raw: str) -> CapabilityKey:
    """Parse ``domain.resource.action`` into a :class:`CapabilityKey`."""
    return CapabilityKey.parse(raw)


def is_canonical_capability(raw: str) -> bool:
    """True iff ``raw`` is a well-formed, canonical capability key."""
    try:
        return parse_capability_key(raw).is_canonical
    except IdentityError:
        return False


__all__ = [
    "CANONICAL_CAPABILITY_KEYS",
    "CapabilityId",
    "CapabilityKey",
    "IdentityError",
    "ProductId",
    "ProviderFamily",
    "ProviderIdentity",
    "format_identity",
    "is_canonical_capability",
    "parse_capability_key",
    "parse_identity",
]
