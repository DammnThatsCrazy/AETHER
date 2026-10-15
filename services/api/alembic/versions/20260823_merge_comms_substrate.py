"""Merge the enterprise-inquiries and computation-substrate heads into one lineage.

Merging origin/main introduced ``20260818_computation_substrate``
(computation-substrate #510), which branched from
``20260817_payment_provider_receipts`` at the same point our comms-follow-up
branch added ``20260806_enterprise_inquiries`` (durable enterprise-inquiry
capture). Both are heads, so ``alembic upgrade head`` fails with
"Multiple head revisions are present" — exactly the failure this repo hit
before with five heads (see ``20260714_merge_heads.py``).

This is a pure merge point — no schema changes. (Tuple-merge precedent:
``20260714_merge_heads.py``.)

Revision ID: 20260823_merge_comms_substrate
Revises: 20260806_enterprise_inquiries, 20260818_computation_substrate
Create Date: 2026-08-07
"""

from __future__ import annotations

revision = "20260823_merge_comms_substrate"
down_revision = (
    "20260806_enterprise_inquiries",
    "20260818_computation_substrate",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
