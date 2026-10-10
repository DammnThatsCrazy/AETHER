"""Kyber — the Olympus Labs internal operating plane for Aether.

Kyber is not an Aether tenant surface. Every Kyber user is an Olympus workforce
principal (``identity/``) authenticating through Google Workspace, bound to an
approved personal device (``devices/``), holding a durable server-side session
(``sessions/``), whose authority is decided entirely on the backend from
granular capabilities, disclosure levels and purpose-bound tenant scopes
(``access/``).

No Aether tenant — including one holding the legacy ``admin`` permission — may
authenticate into Kyber, and no customer authentication path may create a
workforce principal.
"""
