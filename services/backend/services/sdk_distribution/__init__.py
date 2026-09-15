"""SDK distribution — sites, install snippets, and first-heartbeat verification.

The layer that answers "is the SDK actually installed on the customer's site,
and is it the version we intend?" A publishable key (see ``shared.auth.auth``)
is bound to the sites registered here; the snippet generated here is what
installs the loader on those sites; the heartbeat in ``service.py`` is what
proves the install worked.

Deliberately separate from ``services/sdk_health``: that module is *operational*
health for SDKs that are already running (periodic queue-depth and latency
heartbeats, fleet scoring). This one is about the install itself — the one-shot
handshake that happens before there is anything to be healthy.
"""
