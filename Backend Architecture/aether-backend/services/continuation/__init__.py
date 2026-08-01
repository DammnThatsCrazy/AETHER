"""Cross-device continuation plane service + routes (C1).

Thin orchestration over repositories/continuation_repo.py: binds every operation
to the authenticated scope (``t:{tenant_id}``), converts between the
ContinuationContext contract and the repository's dict interface, and mints the
backend selection token at handoff. See docs/source-of-truth/CROSS_DEVICE_CONTINUITY.md.
"""
