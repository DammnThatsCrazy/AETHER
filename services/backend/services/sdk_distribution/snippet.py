"""The install snippet — the one tag an operator pastes into their site.

Everything the loader needs is in the attributes: the publishable key, the site
it is installed on, and (optionally) behaviours like autocapture and consent
mode. There is no follow-up JS, because a second step is a second thing that
can be forgotten — and an install that half-happened still looks like traffic
that stopped.

This is the *only* place the attribute contract is written on the server side.
The loader interprets it in exactly one place too (``packages/web/src/loader/
auto-init.ts``); the two are held to each other by
``scripts/validate_sdk_quickstart_snippet.py``, so a snippet this module emits
cannot name an attribute the loader ignores.
"""

from __future__ import annotations

from html import escape

#: The stable loader URL. Kept as a literal here rather than derived from the
#: version: the whole point of `v1.js` is that it does not move when the SDK
#: does, so customer HTML never needs re-editing. `scripts/
#: validate_sdk_distribution_artifacts.py` holds the bundle banner to this value.
LOADER_URL = "https://cdn.aether.network/v1.js"

#: Attribute names, mirrored from the loader's ATTRIBUTE_MAP. Only the ones the
#: server emits are listed; the loader accepts more (debug, channel).
ATTR_KEY = "data-key"
ATTR_SITE = "data-site"

#: Prefix carried by a publishable key. Distinguishing the class in the
#: credential itself is what lets the loader warn when a *secret* key has been
#: pasted into page HTML — a mistake that is otherwise silent, because a secret
#: key works fine there right up until someone reads it out of View Source.
PUBLISHABLE_KEY_PREFIX = "pk_"


def is_publishable_key(raw_key: str) -> bool:
    return (raw_key or "").startswith(PUBLISHABLE_KEY_PREFIX)


def build_snippet(
    *,
    site_id: str,
    api_key: str,
    loader_url: str = LOADER_URL,
    autocapture: str | None = None,
    consent_mode: str | None = None,
) -> str:
    """Render the install snippet for one site.

    ``api_key`` is interpolated as given: the raw key exists only in the
    response that minted it, so a caller that wants a snippet must pass it
    straight through rather than fetching it back from somewhere.
    """
    attributes = [(ATTR_KEY, api_key), (ATTR_SITE, site_id)]
    if autocapture:
        attributes.append(("data-autocapture", autocapture))
    if consent_mode:
        attributes.append(("data-consent", consent_mode))

    rendered = " ".join(f'{name}="{escape(value, quote=True)}"' for name, value in attributes)
    return f'<script async src="{loader_url}" {rendered}></script>'
