"""Compatibility wrapper for the canonical entity resolver worker.

The production implementation lives under ``workers.enrichment.entity_resolver``.
This module is retained so legacy imports continue to work without shipping the
old scaffold implementation.
"""

from workers.enrichment.entity_resolver import EntityResolverWorker

__all__ = ["EntityResolverWorker"]
