"""Allow ``canonical_conversions.exchange_rate`` to be NULL (unconverted money).

Revision ID: 20260925_conversion_exchange_rate_nullable
Revises: 20260924_identity_observation_entity_nullable
Create Date: 2026-09-25

``20260622_measurement_core`` declared ``exchange_rate NUMERIC(18,8) NOT NULL
DEFAULT 1.0``. When no FX rate is known for a non-USD conversion the column
therefore had to hold *something*, and it held ``1.0`` -- so a EUR or JPY order
was stored with USD parity and could be counted as the same USD amount. The
write path (``ConversionRepository.upsert``) now records an unknown rate as
``NULL`` and marks the row unconverted in ``provenance.fx_conversion``
(``priced = false``), preserving the native amount and currency
(docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md: unknown is never guessed).

The default is dropped too: an insert that omits the rate must not be given
parity silently. Same-currency rows are written with an explicit ``1.0`` by the
repository, and readers treat a same-currency row as parity regardless.

ADDITIVE (relaxes a constraint; no data rewrite). The downgrade restores the
constraint and fails loudly while unconverted rows exist, rather than
fabricating a 1.0 rate for them.
"""

from __future__ import annotations

from alembic import op

revision = "20260925_conversion_exchange_rate_nullable"
down_revision = "20260924_identity_observation_entity_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE canonical_conversions "
        "ALTER COLUMN exchange_rate DROP DEFAULT, "
        "ALTER COLUMN exchange_rate DROP NOT NULL"
    )


def downgrade() -> None:
    # Fails (by design) if unconverted conversions exist: they must be priced
    # or removed explicitly before the old constraint can hold again.
    op.execute(
        "ALTER TABLE canonical_conversions "
        "ALTER COLUMN exchange_rate SET DEFAULT 1.0, "
        "ALTER COLUMN exchange_rate SET NOT NULL"
    )
