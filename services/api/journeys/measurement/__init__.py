"""Aether Canonical Measurement Domain.

Owns all measurement responsibilities:
  - Campaign touchpoint ingestion and storage
  - Canonical conversion ledger
  - Revenue adjustments (refunds, chargebacks)
  - Actual advertising spend ingestion
  - Versioned journey compilation
  - Per-conversion attribution with persisted runs and credits
  - Gold materialization triggers
  - Measurement quality and freshness reporting

This domain is the single source of truth for all attribution, ROAS, CPA,
and related metrics. All other services must read from this domain's APIs
rather than computing attribution independently.
"""
