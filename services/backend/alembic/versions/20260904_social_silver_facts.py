"""Social Silver fact tables (M3) — durable home for the six social projectors.

Creates the six ``silver_social_*_facts`` tables that the M3 Social Silver
projectors (``services/silver/projectors/social_*.py``) write to:

* ``silver_social_identity_facts``        (social_identity_observed)
* ``silver_social_connection_facts``      (social_connection_observed)
* ``silver_social_interaction_facts``     (social_interaction_observed)
* ``silver_social_content_facts``         (social_content_observed)
* ``silver_social_community_facts``       (social_community_membership_observed)
* ``silver_social_metric_facts``          (social_metric_observed)

These tables already feed ``services/silver/generated_ownership.py`` /
``services/silver/dispatcher.py`` (the six projectors are registered and route
their event types) and the generic ``SilverFactWriter`` column-introspection
path had NO DDL to find — against a real pool ``_persist_generic`` logged
``silver_write_unknown_table`` and returned 0, so the rows were only ever held
in the in-memory ``_local_tables`` fallback. This revision gives them a real
forward-write path (DDL here + ``services/silver/repositories/social_facts.py``,
special-cased in the writer exactly like ``silver_comms_facts`` and
``silver_campaign_touchpoint_facts``).

Column contract
---------------
Each table = the shared Social-Silver base columns (``BaseProjector._base_row``
ownership columns) + canonical provenance columns (``source_scope`` /
``evidence_basis`` / ``rights_ref`` / ``provider_identity`` /
``provider_record_ref``) + the projector's own domain columns. The projector
docstrings name this exact shape: "columns = BaseProjector._base_row columns +
provenance columns + the domain columns below". Idempotent replay is enforced
by a partial unique index on ``(tenant_id, idempotency_key)`` (rows where the
key is NULL are untouched) — the same arbiter ``silver_comms_facts`` /
``silver_import_facts`` use.

Two deliberate typing deviations from the 2026-06-22 ``_SILVER_COMMON`` block,
each documented in the Social-Silver plane and required by the projector output:

* ``fact_id`` is TEXT (not UUID). The connection projector synthesizes a natural
  composite fact id (``<provider>:<source>:<target>:<connection_type>``) that is
  not a UUID, and the other five tables either never emit ``fact_id`` (the DB
  ``DEFAULT gen_random_uuid()::text`` fills it) or carry natural text keys of
  the same kind. Binding those as UUID would corrupt/abort the write.
* ``source_event_id`` is TEXT (not UUID), mirroring ``silver_import_facts``:
  social Bronze events may carry a deterministic non-UUID message id.

``occurred_at`` is nullable (an event without a timestamp is honest NULL, never
a fabricated now()) and ``payload`` stays the canonical JSONB envelope. Column
sets are a superset-compatible match with every key the six projectors emit
(excluding ``surface`` / ``sequence_key`` — ephemeral envelope helpers no other
silver fact table persists).

Re-parented on re-cut onto the origin/main lineage: this lane was authored against 20260901_credential_turnkey_tables, which the #596 communication360 merge (20260904_merge_communication360_head) already folded to a single head; down_revision now names that merge head (pure six-table addition, no schema overlap with the merged revisions).

Revision ID: 20260904_social_silver_facts
Revises: 20260904_merge_communication360_head
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op

revision = "20260904_social_silver_facts"
down_revision = "20260904_merge_communication360_head"
branch_labels = None
depends_on = None

# Shared Social-Silver base columns. Trailing line has no comma; the helper
# inserts the per-table domain columns (and created_at / PK) after it.
_SOCIAL_COMMON = """
    fact_id                 TEXT         NOT NULL DEFAULT gen_random_uuid()::text,
    tenant_id               TEXT         NOT NULL,
    source_event_id         TEXT         NOT NULL,
    source_event_type       TEXT         NOT NULL,
    actor_id                TEXT,
    user_id                 TEXT,
    anonymous_id            TEXT,
    org_id                  TEXT,
    occurred_at             TIMESTAMPTZ,
    received_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    consent_snapshot_id     TEXT,
    privacy_class           TEXT         NOT NULL DEFAULT 'behavioral',
    idempotency_key         TEXT,
    payload                 JSONB        NOT NULL DEFAULT '{}'::jsonb,
    source_scope            TEXT,
    evidence_basis          TEXT,
    rights_ref              TEXT,
    provider_identity       TEXT,
    provider_record_ref     TEXT
"""


def _create_social_silver_table(table: str, extra_cols: str, extra_indices: str = "") -> str:
    """One ``silver_social_*_facts`` table + its tenant/idempotency indexes.

    ``extra_cols`` is a comma-prefixed, newline-delimited block of domain
    columns whose final line has no trailing comma (the helper appends
    ``created_at`` and the PK after it).
    """
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_SOCIAL_COMMON},
            {extra_cols},
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, fact_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS {table}_idem
            ON {table} (tenant_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS {table}_occurred
            ON {table} (tenant_id, occurred_at DESC);
        {extra_indices}
    """


def upgrade() -> None:
    # --- Social identity facts (social_identity_observed) --------------------
    op.execute(_create_social_silver_table(
        "silver_social_identity_facts",
        """
        social_identity_id       TEXT         NOT NULL,
        canonical_entity_ref     TEXT,
        provider_account_id      TEXT         NOT NULL,
        handle                   TEXT,
        display_name             TEXT,
        canonical_url            TEXT,
        account_type             TEXT         NOT NULL DEFAULT 'unknown',
        verification_state       TEXT         NOT NULL DEFAULT 'unknown',
        platform_role            TEXT,
        provider_profile_created_at TIMESTAMPTZ,
        first_observed_at        TIMESTAMPTZ,
        last_observed_at         TIMESTAMPTZ,
        valid_from               TIMESTAMPTZ,
        valid_to                 TIMESTAMPTZ,
        resolution_state         TEXT         NOT NULL DEFAULT 'unresolved',
        resolution_confidence    NUMERIC(6,5),
        identity_evidence_refs   JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_identity_facts_social_id
            ON silver_social_identity_facts (tenant_id, social_identity_id);
        """,
    ))

    # --- Social connection facts (social_connection_observed) ----------------
    op.execute(_create_social_silver_table(
        "silver_social_connection_facts",
        """
        source_social_identity_ref   TEXT NOT NULL,
        target_social_identity_ref   TEXT NOT NULL,
        connection_type              TEXT NOT NULL,
        directionality               TEXT,
        observed_at                  TIMESTAMPTZ,
        valid_from                   TIMESTAMPTZ,
        valid_to                     TIMESTAMPTZ,
        proof_level                  TEXT,
        claim_type                   TEXT,
        evidence_refs                JSONB,
        contradictory_evidence_refs  JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_connection_facts_edge
            ON silver_social_connection_facts
               (tenant_id, source_social_identity_ref, target_social_identity_ref);
        """,
    ))

    # --- Social interaction facts (social_interaction_observed) --------------
    op.execute(_create_social_silver_table(
        "silver_social_interaction_facts",
        """
        interaction_id            TEXT NOT NULL,
        actor_social_identity_ref TEXT NOT NULL,
        target_social_identity_ref TEXT,
        content_ref               TEXT,
        parent_content_ref        TEXT,
        community_ref             TEXT,
        interaction_type          TEXT NOT NULL,
        observed_at               TIMESTAMPTZ,
        machine_classification    TEXT,
        human_qualification       TEXT,
        semantic_ref              TEXT,
        campaign_ref              TEXT,
        incentive_context_ref     TEXT,
        evidence_refs             JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_interaction_facts_actor
            ON silver_social_interaction_facts
               (tenant_id, actor_social_identity_ref, occurred_at DESC);
        """,
    ))

    # --- Social content facts (social_content_observed) ----------------------
    op.execute(_create_social_silver_table(
        "silver_social_content_facts",
        """
        content_id                  TEXT NOT NULL,
        author_social_identity_ref  TEXT NOT NULL,
        provider_content_id         TEXT NOT NULL,
        content_type                TEXT NOT NULL,
        provider_content_subtype    TEXT,
        parent_content_ref          TEXT,
        root_content_ref            TEXT,
        published_at                TIMESTAMPTZ,
        edited_at                   TIMESTAMPTZ,
        deleted_at                  TIMESTAMPTZ,
        content_hash                TEXT,
        semantic_ref                TEXT,
        narrative_refs              JSONB,
        campaign_ref                TEXT,
        incentive_context_ref       TEXT,
        evidence_refs               JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_content_facts_author
            ON silver_social_content_facts
               (tenant_id, author_social_identity_ref, occurred_at DESC);
        """,
    ))

    # --- Social community facts (social_community_membership_observed) -------
    op.execute(_create_social_silver_table(
        "silver_social_community_facts",
        """
        membership_id             TEXT NOT NULL,
        social_identity_ref       TEXT NOT NULL,
        community_ref             TEXT NOT NULL,
        membership_role           TEXT NOT NULL DEFAULT 'unknown',
        provider_membership_role  TEXT,
        valid_from                TIMESTAMPTZ,
        valid_to                  TIMESTAMPTZ,
        observed_at               TIMESTAMPTZ,
        evidence_refs             JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_community_facts_member
            ON silver_social_community_facts
               (tenant_id, social_identity_ref, community_ref);
        """,
    ))

    # --- Social metric facts (social_metric_observed) ------------------------
    op.execute(_create_social_silver_table(
        "silver_social_metric_facts",
        """
        metric_observation_id   TEXT NOT NULL,
        social_identity_ref     TEXT,
        metric_name             TEXT NOT NULL,
        value                   NUMERIC(24,6),
        unit                    TEXT,
        status                  TEXT NOT NULL,
        metric_window           JSONB,
        population              TEXT,
        observed_at             TIMESTAMPTZ,
        computation_ref         TEXT,
        quality                 TEXT,
        evidence_refs           JSONB
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_social_metric_facts_identity_metric
            ON silver_social_metric_facts
               (tenant_id, social_identity_ref, metric_name)
            WHERE social_identity_ref IS NOT NULL;
        """,
    ))


def downgrade() -> None:
    tables = [
        "silver_social_identity_facts",
        "silver_social_connection_facts",
        "silver_social_interaction_facts",
        "silver_social_content_facts",
        "silver_social_community_facts",
        "silver_social_metric_facts",
    ]
    for t in reversed(tables):
        op.execute(f"DROP INDEX IF EXISTS {t}_idem")
        op.execute(f"DROP INDEX IF EXISTS {t}_occurred")
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
