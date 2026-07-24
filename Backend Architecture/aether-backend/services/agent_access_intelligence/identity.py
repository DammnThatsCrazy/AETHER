"""Artifact / publisher identity for observed capabilities (PR 2, Phase B2, monoprompt §9.3).

**There is no ``verified`` state, and this module cannot create one.**

Nothing in this backend can cryptographically verify who published a third-party MCP
server or provider tool. ``services/sdk_config/service.py`` HMAC-signs *our own* SDK
manifest with a key we hold; it says nothing about a third party's artifact. There is no
SBOM ingest, no signature verification, no publisher registry, and no transparency log.
Offering a ``verified`` state would therefore be a fabricated assurance — an operator
would read it as "someone checked this publisher," and no one did.

So this module derives only what is honestly derivable from an observation:

``publisher_ref``
    A stable grouping key over the *observed origin* of a capability — the host of its
    sanitized ``server_url``, falling back to ``provider``. It answers "are these two
    capabilities claiming the same origin?" It does **not** answer "is that origin
    who it says it is?" The raw host is kept alongside as ``publisher_label`` for
    display; the digest is what identity comparisons key on, so a ``:`` or ``*`` in an
    observed value can never widen a scope match elsewhere (same reasoning as
    ``authority.server_ref_for``).

``artifact_digest``
    A digest over the capability's identity tuple. Its value is not that it proves
    provenance — it cannot — but that a *change* in a capability's identity becomes
    detectable even when the origin is unverifiable. A server that silently starts
    presenting a different protocol version or tool surface under the same name produces
    a different digest, and §9.5 drift compares exactly that.

``identity_state``
    Derived, never stored: ``observed_only`` (nothing declared) / ``declared``
    (a declaration exists and its digest matches) / ``drifted`` (a declaration exists and
    the digests disagree). A stored state field could disagree with the rows it summarizes;
    a derived one cannot.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlsplit

__all__ = [
    "IDENTITY_FIELDS",
    "IdentityState",
    "asserted_identity_fields",
    "publisher_label_for",
    "publisher_ref_for",
    "artifact_digest_for",
    "declaration_id_for",
    "identity_state_for",
]


class IdentityState(str, Enum):
    """How an observed capability's identity relates to what the tenant declared.

    Deliberately has no ``verified`` member — see the module docstring. Adding one
    without a real verification source would be a fabricated control.
    """

    OBSERVED_ONLY = "observed_only"  # no declaration for this capability
    DECLARED = "declared"            # a declaration exists and the digests agree
    DRIFTED = "drifted"              # a declaration exists and the digests disagree


def publisher_label_for(
    server_url: Optional[str], provider: Optional[str] = None
) -> Optional[str]:
    """Human-readable origin: the URL host, else the opaque server name, else provider.

    Expects an ALREADY-SANITIZED ``server_url`` (``catalog_service._sanitize_server_url``
    strips ``user:pass@`` userinfo). Taking the host of a sanitized URL is what keeps
    credentials out of the label; this function does not re-sanitize, because doing so
    silently would hide the fact that the caller skipped it.
    """
    value = (server_url or "").strip()
    if value:
        try:
            parts = urlsplit(value)
        except ValueError:
            parts = None
        if parts is not None:
            host = (parts.hostname or "").strip().lower()
            if host:
                return host
            # Opaque server name (no scheme/authority) — it is the origin we observed.
            if not parts.scheme and "/" not in value:
                return value.lower()
    provider_value = (provider or "").strip().lower()
    return provider_value or None


def publisher_ref_for(
    server_url: Optional[str], provider: Optional[str] = None
) -> Optional[str]:
    """Stable digest key for the observed origin, or ``None`` when nothing was observed.

    ``None`` is a real answer — an observation with neither a server URL nor a provider
    has no origin to group by, and inventing a placeholder ref would silently merge every
    such capability into one fake publisher.
    """
    label = publisher_label_for(server_url, provider)
    if not label:
        return None
    return "pub_" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:24]


# The fields whose change means "this is not the same artifact any more", in a fixed
# order. Explicitly enumerated rather than derived from the dict, so adding an unrelated
# field to a capability record (`observation_count`, `last_seen_at`) cannot silently
# invalidate every stored digest and report the whole inventory as drifted.
#
# `server` is synthetic: it resolves to `server_name` falling back to `server_url`,
# matching `catalog_service._server_key`, so both sides agree on what "the server" is.
IDENTITY_FIELDS: tuple[str, ...] = (
    "provider",
    "server",
    "tool_name",
    "protocol_version",
    "capability_kind",
)


def _norm_field(record: dict[str, Any], name: str) -> str:
    """One identity field, normalized to its comparable form.

    Enum members are unwrapped BEFORE stringifying. For `class CapabilityKind(str, Enum)`,
    `str(member)` is "CapabilityKind.MCP_TOOL", not "mcp_tool" — while the stored row
    (written via `model_dump(mode="json")`) and any declaration hold the plain value.
    Without this the digest computed at upsert time would disagree with one recomputed
    from the row's own stored fields, and a declaration — which can only ever carry a
    plain string — could never match, so every declared capability would report `drifted`.
    """
    if name == "server":
        value = record.get("server_name") or record.get("server_url")
    else:
        value = record.get(name)
    if value is None:
        return ""
    value = getattr(value, "value", value)
    return str(value).strip().lower()


def artifact_digest_for(
    record: dict[str, Any], fields: Optional[Sequence[str]] = None
) -> str:
    """Digest over a capability's identity, optionally restricted to ``fields``.

    Not provenance — a digest of unverified fields is still unverified. Its job is to make
    *change* detectable: the same capability observed later with a different protocol
    version or kind digests differently, which is what drift compares.

    ``fields`` exists because **a declaration asserts a subset**. An operator declares the
    identity they actually know — provider, server, tool — and has no way to know the
    ``capability_kind`` this service derives internally, or the ``protocol_version`` the
    server happens to be speaking today. Digesting the full tuple on both sides made every
    ordinary declaration compare unequal, so the drift surface reported a permanent HIGH
    "no longer matches what was observed" for capabilities that had never changed once.
    Drift means *reality diverged from what you asserted*; you cannot diverge from an
    assertion nobody made. Callers therefore digest the observed row over the same field
    subset the declaration recorded (`asserted_identity_fields`).

    The subset is order-normalized against ``IDENTITY_FIELDS`` and each entry is
    name-prefixed, so digests taken over different subsets can never collide.
    """
    if fields is None:
        selected: tuple[str, ...] = IDENTITY_FIELDS
    else:
        wanted = set(fields)
        selected = tuple(name for name in IDENTITY_FIELDS if name in wanted)
    raw = "|".join(f"{name}={_norm_field(record, name)}" for name in selected)
    return "art_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def asserted_identity_fields(record: dict[str, Any]) -> list[str]:
    """The identity fields a record actually states, in canonical order.

    This is a declaration's comparable surface. Blank/absent fields are not assertions and
    are excluded, so omitting a field the operator does not know can never later be read
    as drift.
    """
    return [name for name in IDENTITY_FIELDS if _norm_field(record, name)]


def declaration_id_for(
    tenant_id: str,
    provider: Optional[str],
    server_key: Optional[str],
    tool_name: Optional[str],
) -> str:
    """Deterministic declaration identity.

    Keyed by the **same** tuple as ``models.capability_id_for`` so a declaration and the
    observation it describes join exactly, with no fuzzy matching: one declaration per
    (tenant, provider, server, tool). Re-declaring the same capability updates that row
    instead of accumulating duplicates that would each report their own drift verdict.
    """
    raw = f"{tenant_id}|{provider or ''}|{server_key or ''}|{tool_name or ''}"
    return "dec_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def identity_state_for(
    observed_digest: Optional[str], declared_digest: Optional[str]
) -> IdentityState:
    """Derive the identity state from the two digests.

    ``declared_digest`` being absent means **no declaration exists** for this capability,
    which is ``observed_only`` — a normal state in a system whose premise is observing
    things nobody declared.

    It does NOT mean "declared but incomparable". That state must never reach here: a
    declaration whose digest is missing is an unresolved comparison, and resolving it
    toward the reassuring ``declared`` would be exactly the failure this module exists to
    prevent. ``declarations.digest_map`` is what guarantees it — it skips any row missing
    either half rather than emitting an empty digest, so the only way to get ``None`` here
    is a genuine absence. If a caller ever sources declared digests some other way, it owns
    that same guarantee.
    """
    if not declared_digest:
        return IdentityState.OBSERVED_ONLY
    if observed_digest and observed_digest == declared_digest:
        return IdentityState.DECLARED
    return IdentityState.DRIFTED
