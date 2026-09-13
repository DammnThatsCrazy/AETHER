"""Boundary provider-family alias map (additive, ADR-0009).

Aether's provider id-spaces grew independently: the inbound connector registry
(``services/integrations/connectors/``), the measurement/ad connectors
(``services/measurement/connectors/``), the legacy provider adapters
(``shared/providers/categories.py``), and the campaign normalization map
(``services/campaign/normalization.py``) each name the same real platform
differently. ``twitter_ads`` (legacy adapters + recommendations) and ``x_ads``
(measurement runtime + campaign normalization) are the same advertising family;
``google_analytics`` names the connector the registry calls ``ga4``.

This module is the **single boundary alias map** (ADR-0009): it reconciles those
collisions into canonical catalog families **without renaming any runtime id
space**. Runtime keys stay stable; consumers that want canonical identity run an
id through :func:`canonical_family_id` and get the family the unified catalog
keys on. New collisions are added here, never in a caller's private table.

A family that the public vocabulary recognizes but that has **no backed runtime
yet** (``snapchat_ads``, ``pinterest_ads``) is recorded in
:data:`ALIAS_ONLY_FAMILIES` so surfaces can name it without ever fabricating
capability behind it (data-truth invariant §31).
"""

from __future__ import annotations

from typing import Mapping

# alias (as emitted by a legacy/boundary id-space) → canonical catalog family.
# Each entry documents the emitting id-space so the map stays auditable.
FAMILY_ALIASES: Mapping[str, str] = {
    # shared/providers/categories.py AD_PLATFORM + recommendations/* emit
    # twitter_ads; the measurement runtime and campaign normalization canonical
    # is x_ads. x_ads is the family the unified catalog keys on.
    "twitter_ads": "x_ads",
    # Legacy naming for the Google Analytics 4 inbound connector, which the
    # registry and catalog key as ga4.
    "google_analytics": "ga4",
    # Shared/providers marketing alias; the measurement runtime is meta_ads.
    "facebook_ads": "meta_ads",
    # Campaign normalization maps bing/bing_ads → microsoft_ads; the catalog
    # family is microsoft_ads.
    "bing_ads": "microsoft_ads",
}

# Public ad-platform families recognized today but with NO runtime connector
# (no measurement module, no account discovery). Naming them is fine — claiming
# capability behind them is not. Kept disjoint from the alias map so no chain
# resolves into an unbacked family.
ALIAS_ONLY_FAMILIES: frozenset[str] = frozenset(
    {"snapchat_ads", "pinterest_ads"}
)


def canonical_family_id(raw: str) -> str:
    """Resolve a boundary provider family id to its canonical catalog family.

    Lowercases/strips the input, applies :data:`FAMILY_ALIASES`, and passes
    through values that are not aliased (including :data:`ALIAS_ONLY_FAMILIES` —
    they are already canonical *names*; what they lack is a runtime, which is a
    capability question, not an identity question).
    """
    token = (raw or "").strip().lower()
    if not token:
        return token
    return FAMILY_ALIASES.get(token, token)


__all__ = [
    "ALIAS_ONLY_FAMILIES",
    "FAMILY_ALIASES",
    "canonical_family_id",
]
