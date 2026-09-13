"""touchpoint facts: durable properties, revenue_usd, is_conversion

``services/campaign/routes.py::record_touchpoint`` has always built a
touchpoint dict that includes ``properties``, ``revenue_usd``, and
``is_conversion`` and echoed it straight back in the API response — but
``silver_campaign_touchpoint_facts`` had no columns for any of the three, so
``TouchpointRepository.upsert_from_campaign_touchpoint`` silently dropped
them before the row ever reached storage. The response implied durable
persistence that never happened.

Adds three backward-compatible columns:

- ``properties``     JSONB   — arbitrary touchpoint metadata, defaults to
  ``'{}'::jsonb`` (same convention as the existing ``provenance`` column on
  this table).
- ``revenue_usd``     NUMERIC(18,6) — nullable, no default. Same
  representation already used for every other money column in this
  migration family: ``canonical_conversions.gross_value`` and
  ``revenue_adjustments.amount`` (see ``20260622_measurement_core.py``) are
  both nullable/plain ``NUMERIC(18,6)`` with no implicit zero-coercion.
  NUMERIC (never FLOAT/DOUBLE PRECISION) so revenue is never persisted as a
  binary float — see docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md.
- ``is_conversion``   BOOLEAN — ``NOT NULL DEFAULT FALSE``, the same
  convention already used by this table's ``is_view_through`` /
  ``is_click_through`` columns.

All three are additive, nullable-or-defaulted, and require no backfill —
historical rows read back as ``properties={}``, ``revenue_usd=NULL``,
``is_conversion=FALSE``.

Revision ID: 20260823_touchpoint_conversion_fields
Revises: 20260823_merge_comms_substrate
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op

revision = "20260823_touchpoint_conversion_fields"
down_revision = "20260823_merge_comms_substrate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE silver_campaign_touchpoint_facts
            ADD COLUMN IF NOT EXISTS properties     JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS revenue_usd     NUMERIC(18,6),
            ADD COLUMN IF NOT EXISTS is_conversion   BOOLEAN NOT NULL DEFAULT FALSE;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE silver_campaign_touchpoint_facts
            DROP COLUMN IF EXISTS is_conversion,
            DROP COLUMN IF EXISTS revenue_usd,
            DROP COLUMN IF EXISTS properties;
    """)
