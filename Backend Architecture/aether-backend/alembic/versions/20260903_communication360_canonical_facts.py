"""communication360 canonical facts — typed JSONB fact store (Phase 3, D2).

The Communication360 convergence projection owns ONE canonical-authority fact
table (``communication360_facts``) for the Phase-2 ratified object families
(``services/communication360/contracts.py``): information / claim binding /
transformation (R2), conversation / provider-thread / matter, communication
acts + request/commitment/response-expectation, participant bindings (R3),
knowledge/interpretation/context records (R4), authority evaluations, and
provider capability/quality.

The table is intentionally separate from the shipped ``silver_comms_facts``
path (typed read-over for the message spine stays on that silver table — never
duplicated here). This table is typed JSONB storage: envelope columns are the
tenant-scoped query spine (tenant_id, kind, occurred_at) while the ratified
object payload rides ``payload`` as the full contract JSONB document. Decision
D2 (typed JSONB) keeps the migration additive and lets Phase 5/6 add object
families without DDL churn.

``kind`` discriminator values (TEXT, NOT NULL) — one per Phase-3 object family
the Phase-4 provider persists:

information, information_transformation, conversation, provider_thread, matter,
communication_act, request, commitment, response_expectation,
participant_binding, knowledge_state, interpretation, context_inclusion,
authority_evaluation, provider_capability, communication_quality.

Revision ID: 20260903_communication360_canonical_facts
Revises: 20260901_credential_turnkey_tables
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision = "20260903_communication360_canonical_facts"
down_revision = "20260901_credential_turnkey_tables"
branch_labels = None
depends_on = None

#: Phase-3 ``kind`` discriminators (TEXT values; documented in the module
#: docstring above). Not enforced as a CHECK — a new Phase 5/6 object family
#: must land without a migration — but kept as the authoritative vocabulary the
#: repository registry aligns to.
COMMUNICATION360_KINDS: tuple[str, ...] = (
    "information",
    "information_transformation",
    "conversation",
    "provider_thread",
    "matter",
    "communication_act",
    "request",
    "commitment",
    "response_expectation",
    "participant_binding",
    "knowledge_state",
    "interpretation",
    "context_inclusion",
    "authority_evaluation",
    "provider_capability",
    "communication_quality",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS communication360_facts (
            fact_id           TEXT        NOT NULL,
            tenant_id         TEXT        NOT NULL,
            kind              TEXT        NOT NULL,
            source_event_id   TEXT,
            source_event_type TEXT,
            actor_id          TEXT,
            agent_id          TEXT,
            occurred_at       TIMESTAMPTZ,
            received_at       TIMESTAMPTZ,
            idempotency_key   TEXT        NOT NULL,
            run_id            TEXT,
            context_hash      TEXT,
            payload           JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, fact_id),
            UNIQUE (tenant_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS communication360_facts_kind_occurred
            ON communication360_facts (tenant_id, kind, occurred_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS communication360_facts CASCADE;")
