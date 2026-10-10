"""WS-D Silver exact-money additive schema (item 7 / Invariant #13).

Adds exact-decimal money columns to the two Silver money fact tables and widens
the legacy ``silver_revenue_facts.amount``/``currency`` columns so a typed money
ABSENCE can be stored (``None``) instead of the historical collapse to
``0.0`` / ``'USD'``.

This is an additive WIDENING only — no column is removed and no constraint is
tightened in ``upgrade()``:

* ``silver_revenue_facts.amount``    DROP NOT NULL + DROP DEFAULT (was
  ``NUMERIC(20,4) NOT NULL``); value semantics unchanged when WS-D flags are
  OFF because the default-OFF projector always supplies a number.
* ``silver_revenue_facts.currency``  DROP NOT NULL + DROP DEFAULT (was
  ``TEXT NOT NULL DEFAULT 'USD'``).
* ``silver_revenue_facts``           ADD ``amount_exact NUMERIC(38,18)``,
  ``currency_exact TEXT`` — the canonical exact-money surface (financial
  normalization ``NUMERIC(38,18)`` convention).
* ``silver_outcome_facts``           ADD ``value_amount_exact NUMERIC(38,18)``,
  ``value_currency_exact TEXT`` (legacy value_amount/value_currency were already
  nullable; left untouched).

SQLite note: SQLite cannot DROP NOT NULL via ALTER, so the widening alter steps
are skipped on ``sqlite`` and only the additive ``op.add_column`` calls run
(dev/test only — the production path is PostgreSQL, where the widening applies).

Flag-gated write path: ``AETHER_SILVER_EXACT_MONEY_ENABLED`` (default OFF, see
``docs/architecture/BACKEND_INTERPRETATION_WS_D.md``). No production default
flip: with the flag OFF the projectors emit byte-for-byte the same rows they
did before this migration.

Revision ID: 20260906_wsd_silver_exact_money
Revises: 20260906_merge_data_exchange_head
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the single lane head ``20260906_merge_data_exchange_head``.
When the WS-D branch is combined with sibling WS lanes that each add a migration
off that head, a NEW tuple-merge revision must be created with
``down_revision = (<this revision>, <sibling revision>, ...)`` exactly like
``20260906_merge_data_exchange_head``/``20260904_merge_communication360_head``.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260906_wsd_silver_exact_money"
down_revision = "20260906_merge_data_exchange_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if not dialect.startswith("sqlite"):
        # Widen the legacy revenue money columns (widening only: default-OFF
        # writers always supply values, so nothing observable changes with WS-D
        # flags OFF). SQLite cannot DROP NOT NULL via ALTER and is skipped.
        op.alter_column(
            "silver_revenue_facts",
            "amount",
            existing_type=sa.Numeric(20, 4),
            nullable=True,
            existing_nullable=False,
            existing_server_default=None,
        )
        op.alter_column(
            "silver_revenue_facts",
            "currency",
            existing_type=sa.Text(),
            nullable=True,
            existing_nullable=False,
            existing_server_default="USD",
        )
        try:
            # Remove the legacy 'USD' DEFAULT clause explicitly (a bare
            # server_default=None on some dialects leaves the DEFAULT behind).
            op.execute(
                "ALTER TABLE silver_revenue_facts "
                "ALTER COLUMN currency DROP DEFAULT"
            )
        except Exception:  # noqa: BLE001 - no DEFAULT present on some dialects
            pass

    # Additive exact-money columns (financial-normalization NUMERIC(38,18)).
    op.add_column(
        "silver_revenue_facts",
        sa.Column("amount_exact", sa.Numeric(38, 18), nullable=True),
    )
    op.add_column(
        "silver_revenue_facts",
        sa.Column("currency_exact", sa.Text(), nullable=True),
    )
    op.add_column(
        "silver_outcome_facts",
        sa.Column("value_amount_exact", sa.Numeric(38, 18), nullable=True),
    )
    op.add_column(
        "silver_outcome_facts",
        sa.Column("value_currency_exact", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("silver_outcome_facts", "value_currency_exact")
    op.drop_column("silver_outcome_facts", "value_amount_exact")
    op.drop_column("silver_revenue_facts", "currency_exact")
    op.drop_column("silver_revenue_facts", "amount_exact")

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect.startswith("sqlite"):
        return
    op.alter_column(
        "silver_revenue_facts",
        "currency",
        existing_type=sa.Text(),
        nullable=False,
        existing_nullable=True,
        server_default="USD",
    )
    op.alter_column(
        "silver_revenue_facts",
        "amount",
        existing_type=sa.Numeric(20, 4),
        nullable=False,
        existing_nullable=True,
    )
