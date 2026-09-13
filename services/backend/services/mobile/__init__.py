"""Mobile gateway — installation registration + push subscriptions (C3).

Thin projection over repositories/installation_repo.py: binds every operation to
the authenticated scope, forces app_kind onto the authenticated plane, and hashes
push tokens (only the token_hash is stored; the encrypted token belongs in the
credential platform). See docs/source-of-truth/MOBILE_PLATFORM.md.
"""
