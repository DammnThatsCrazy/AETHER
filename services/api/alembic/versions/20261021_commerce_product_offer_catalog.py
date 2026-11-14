"""Canonical tenant-scoped product and offer catalog revisions.

Revision ID: 20261021_commerce_product_offer_catalog
Revises: 20261018_comms_consent_lineage
Create Date: 2026-10-21

Each row is one immutable source revision. Explicit tenant/product/offer IDs
and observed timestamps support exact historical reads; evidence and source
payloads remain JSONB so the shared evidence contract can grow additively.
"""

from alembic import op

revision = "20261021_commerce_product_offer_catalog"
down_revision = "20261018_comms_consent_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_catalog_products (
            tenant_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            lifecycle_state TEXT NOT NULL,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            observed_at TIMESTAMPTZ NOT NULL,
            source_provider TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            evidence_refs JSONB NOT NULL,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, product_id, revision_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
            CHECK (lifecycle_state IN ('draft','active','paused','retired','expired')),
            CHECK (length(btrim(tenant_id)) > 0 AND length(btrim(product_id)) > 0),
            CHECK (length(btrim(title)) > 0 AND length(btrim(source_provider)) > 0),
            CHECK (length(btrim(source_record_id)) > 0 AND length(btrim(revision_id)) > 0),
            CHECK (jsonb_typeof(evidence_refs) = 'array'),
            CHECK (jsonb_typeof(data) = 'object')
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_catalog_offers (
            tenant_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            lifecycle_state TEXT NOT NULL,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            observed_at TIMESTAMPTZ NOT NULL,
            source_provider TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            evidence_refs JSONB NOT NULL,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, offer_id, revision_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
            CHECK (lifecycle_state IN ('draft','active','paused','retired','expired')),
            CHECK (length(btrim(tenant_id)) > 0 AND length(btrim(offer_id)) > 0),
            CHECK (length(btrim(product_id)) > 0 AND length(btrim(title)) > 0),
            CHECK (length(btrim(source_provider)) > 0 AND length(btrim(source_record_id)) > 0),
            CHECK (length(btrim(revision_id)) > 0),
            CHECK (jsonb_typeof(evidence_refs) = 'array'),
            CHECK (jsonb_typeof(data) = 'object')
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS commerce_catalog_products_asof "
        "ON commerce_catalog_products (tenant_id, product_id, observed_at DESC, revision_id DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS commerce_catalog_offers_asof "
        "ON commerce_catalog_offers (tenant_id, offer_id, observed_at DESC, revision_id DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS commerce_catalog_offers_product_asof "
        "ON commerce_catalog_offers (tenant_id, product_id, offer_id, observed_at DESC, revision_id DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS commerce_catalog_offers_product_asof;")
    op.execute("DROP INDEX IF EXISTS commerce_catalog_offers_asof;")
    op.execute("DROP INDEX IF EXISTS commerce_catalog_products_asof;")
    op.execute("DROP TABLE IF EXISTS commerce_catalog_offers;")
    op.execute("DROP TABLE IF EXISTS commerce_catalog_products;")
