"""Generators that derive documentation artifacts from repository sources.

Each module under this package reads a canonical source file (e.g.
``packages/shared/events.ts``, ``.env.example``) and emits a structured
JSON file under ``docs/_generated/`` that MDX pages render via Contentlayer
(once ``apps/docs/`` ships). Generators are deterministic and idempotent:
running them twice on the same input produces byte-identical output.
"""
