"""kyber workforce identity — principals, invitations, devices, sessions, scopes

Additive tables for the Kyber workforce identity plane. Olympus operators stop
being modelled as Aether tenants: a Kyber user is a workforce principal with an
invite-created record, an approved personal device, a durable server-side
session, and purpose-bound tenant access scopes.

Every table follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so the runtime JSONB repositories and this migration
agree, plus typed convenience columns for indexing and reporting.

Uniqueness is enforced on the JSONB expressions the repositories actually query
(``data->>'...'``), not on the mirrored typed columns — a constraint on a column
the read path never touches would be decorative. The typed columns exist so
operators can query and index this data with plain SQL.

No secret is stored anywhere here. Invitation tokens, session tokens and device
grants are persisted as sha256 digests; WebAuthn and device-proof keys are
public keys only. Purely additive; no destructive changes. Fully reversible.

Revision ID: 20260809_kyber_workforce
Revises: 20260808_provider_evidence
Create Date: 2026-08-09

The revision id is kept under 32 characters because Alembic's
``alembic_version.version_num`` column is ``VARCHAR(32)``; a longer id fails at
stamp time with ``StringDataRightTruncation`` rather than at authoring time.
"""

from __future__ import annotations

from alembic import op

revision = "20260809_kyber_workforce"
down_revision = "20260808_provider_evidence"
branch_labels = None
depends_on = None


# Workforce records are deliberately NOT tenant-scoped: an Olympus operator is
# not a tenant. The `tenant_id` column is retained for BaseRepository shape
# compatibility and stays NULL for every row except access scopes and access
# decisions, which name the tenant they were granted against.
_TABLES: dict[str, str] = {
    # ── Identity ──────────────────────────────────────────────────────────────
    "olympus_workforce_principals": """
        CREATE TABLE IF NOT EXISTS olympus_workforce_principals (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            google_subject TEXT,
            email TEXT,
            display_name TEXT,
            employment_status TEXT,
            department TEXT,
            kyber_enabled BOOLEAN,
            activated_at TIMESTAMPTZ,
            suspended_at TIMESTAMPTZ,
            offboarded_at TIMESTAMPTZ,
            last_directory_sync_at TIMESTAMPTZ,
            last_login_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Single-use invitations. Only the sha256 of the token is stored.
    "olympus_workforce_invitations": """
        CREATE TABLE IF NOT EXISTS olympus_workforce_invitations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            token_hash TEXT,
            email TEXT,
            status TEXT,
            invited_by TEXT,
            expires_at TIMESTAMPTZ,
            accepted_at TIMESTAMPTZ,
            accepted_by_operator_id TEXT,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "olympus_role_bindings": """
        CREATE TABLE IF NOT EXISTS olympus_role_bindings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            operator_id TEXT,
            role_template_id TEXT,
            environment TEXT,
            granted_by TEXT,
            granted_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Per-principal capability overrides. `effect` may be 'allow' or 'deny';
    # a live 'deny' always beats a role template that would allow.
    "olympus_capability_grants": """
        CREATE TABLE IF NOT EXISTS olympus_capability_grants (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            operator_id TEXT,
            capability_id TEXT,
            effect TEXT,
            environment TEXT,
            granted_by TEXT,
            granted_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # ── Device trust ──────────────────────────────────────────────────────────
    # An approved personal device. grant_hash is the sha256 of the opaque
    # device-grant cookie value and is absent until approval.
    "kyber_trusted_devices": """
        CREATE TABLE IF NOT EXISTS kyber_trusted_devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            operator_id TEXT,
            display_name TEXT,
            platform_family TEXT,
            browser_family TEXT,
            approval_state TEXT,
            risk_state TEXT,
            grant_hash TEXT,
            requested_at TIMESTAMPTZ,
            approved_at TIMESTAMPTZ,
            approved_by TEXT,
            expires_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            suspended_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Platform authenticator credentials. Public key + counter only.
    "kyber_webauthn_credentials": """
        CREATE TABLE IF NOT EXISTS kyber_webauthn_credentials (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            device_id TEXT,
            operator_id TEXT,
            credential_id TEXT,
            sign_count BIGINT,
            aaguid TEXT,
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Browser-profile-bound ECDSA P-256 public keys. The private half is
    # non-extractable and never leaves the enrolled browser profile, which is
    # what a synced passkey cannot replicate.
    "kyber_device_proof_keys": """
        CREATE TABLE IF NOT EXISTS kyber_device_proof_keys (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            device_id TEXT,
            operator_id TEXT,
            algorithm TEXT,
            last_verified_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_device_approval_events": """
        CREATE TABLE IF NOT EXISTS kyber_device_approval_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            device_id TEXT,
            operator_id TEXT,
            action TEXT,
            actor_id TEXT,
            from_state TEXT,
            to_state TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # ── Sessions ──────────────────────────────────────────────────────────────
    # Only the sha256 of the opaque session token is stored. presence /
    # authority / idle expiries coexist: presence keeps a low-authority shell
    # open, authority is the hard ceiling, idle slides forward on use.
    "kyber_workforce_sessions": """
        CREATE TABLE IF NOT EXISTS kyber_workforce_sessions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            token_hash TEXT,
            operator_id TEXT,
            google_subject TEXT,
            device_id TEXT,
            status TEXT,
            authentication_strength TEXT,
            environment TEXT,
            presence_expires_at TIMESTAMPTZ,
            authority_expires_at TIMESTAMPTZ,
            idle_expires_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            rotated_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            risk_state TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_step_up_grants": """
        CREATE TABLE IF NOT EXISTS kyber_step_up_grants (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            session_id TEXT,
            operator_id TEXT,
            device_id TEXT,
            capability_id TEXT,
            expires_at TIMESTAMPTZ,
            consumed_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_authentication_events": """
        CREATE TABLE IF NOT EXISTS kyber_authentication_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            event_type TEXT,
            operator_id TEXT,
            google_subject TEXT,
            email TEXT,
            session_id TEXT,
            device_id TEXT,
            environment TEXT,
            outcome TEXT,
            reason TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # ── Tenant access scopes & decisions ──────────────────────────────────────
    # Durable replacement for the previous in-process tenant-entry dictionary.
    # Bound to the session and device that opened it and to exactly one tenant.
    "kyber_access_scopes": """
        CREATE TABLE IF NOT EXISTS kyber_access_scopes (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            operator_id TEXT,
            session_id TEXT,
            device_id TEXT,
            environment TEXT,
            purpose TEXT,
            disclosure_level INTEGER,
            status TEXT,
            entered_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            exited_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            policy_decision_id TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Kyber-specific detail for a governance policy decision. policy_decision_id
    # links back to security_policy_decisions; this is not a parallel ledger.
    "kyber_access_decisions": """
        CREATE TABLE IF NOT EXISTS kyber_access_decisions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            policy_decision_id TEXT,
            operator_id TEXT,
            session_id TEXT,
            device_id TEXT,
            route_id TEXT,
            capability_id TEXT,
            action_class INTEGER,
            environment TEXT,
            scope_id TEXT,
            purpose TEXT,
            requested_disclosure INTEGER,
            granted_disclosure INTEGER,
            allowed BOOLEAN,
            denial_reason TEXT,
            step_up_required BOOLEAN,
            approval_required BOOLEAN,
            expires_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}

# (table, index suffix, JSONB key) — the repository read paths.
_JSONB_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("olympus_workforce_principals", "email", "email"),
    ("olympus_workforce_invitations", "email", "email"),
    ("olympus_role_bindings", "operator", "operator_id"),
    ("olympus_capability_grants", "operator", "operator_id"),
    ("kyber_trusted_devices", "operator", "operator_id"),
    ("kyber_trusted_devices", "grant", "grant_hash"),
    ("kyber_webauthn_credentials", "device", "device_id"),
    ("kyber_webauthn_credentials", "operator", "operator_id"),
    ("kyber_device_proof_keys", "device", "device_id"),
    ("kyber_device_approval_events", "device", "device_id"),
    ("kyber_workforce_sessions", "operator", "operator_id"),
    ("kyber_workforce_sessions", "device", "device_id"),
    ("kyber_step_up_grants", "session", "session_id"),
    ("kyber_authentication_events", "operator", "operator_id"),
    ("kyber_access_scopes", "session", "session_id"),
    ("kyber_access_scopes", "operator", "operator_id"),
    ("kyber_access_scopes", "tenant_key", "tenant_id"),
    ("kyber_access_decisions", "operator", "operator_id"),
    ("kyber_access_decisions", "session", "session_id"),
    ("kyber_access_decisions", "policy", "policy_decision_id"),
)

# Uniqueness that carries security weight. Enforced on the JSONB expression the
# repositories query, and partial where a revoked/expired row must not block a
# legitimate re-registration.
_UNIQUE_INDEXES: tuple[tuple[str, str, str, str], ...] = (
    # One principal per Google subject. This is the identity key.
    (
        "olympus_workforce_principals",
        "ux_olympus_workforce_principals_google_subject",
        "((data->>'google_subject'))",
        "WHERE data->>'google_subject' IS NOT NULL",
    ),
    # An invitation token is single use.
    (
        "olympus_workforce_invitations",
        "ux_olympus_workforce_invitations_token",
        "((data->>'token_hash'))",
        "WHERE data->>'token_hash' IS NOT NULL",
    ),
    # A session token must resolve to at most one session.
    (
        "kyber_workforce_sessions",
        "ux_kyber_workforce_sessions_token",
        "((data->>'token_hash'))",
        "WHERE data->>'token_hash' IS NOT NULL",
    ),
    # A WebAuthn credential id may be registered once. Revoked credentials are
    # excluded so an operator can re-enroll the same authenticator after a wipe.
    (
        "kyber_webauthn_credentials",
        "ux_kyber_webauthn_credentials_credential_id",
        "((data->>'credential_id'))",
        "WHERE data->>'credential_id' IS NOT NULL AND data->>'revoked_at' IS NULL",
    ),
    # A live device grant maps to exactly one device.
    (
        "kyber_trusted_devices",
        "ux_kyber_trusted_devices_grant",
        "((data->>'grant_hash'))",
        "WHERE data->>'grant_hash' IS NOT NULL AND data->>'revoked_at' IS NULL",
    ),
)

# Composite indexes for the authorization hot path: resolving a session's active
# scope for a target tenant, and listing an operator's devices.
_COMPOSITE_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "kyber_access_scopes",
        "ix_kyber_access_scopes_session_tenant",
        "((data->>'session_id'), (data->>'tenant_id'), (data->>'status'))",
    ),
    (
        "kyber_trusted_devices",
        "ix_kyber_trusted_devices_operator_state",
        "((data->>'operator_id'), (data->>'approval_state'))",
    ),
    (
        "kyber_workforce_sessions",
        "ix_kyber_workforce_sessions_operator_status",
        "((data->>'operator_id'), (data->>'status'))",
    ),
)

# Expiry sweeps scan by status + expiry; index the typed columns they use.
_EXPIRY_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("olympus_workforce_invitations", "ix_olympus_workforce_invitations_expiry", "(status, expires_at)"),
    ("kyber_workforce_sessions", "ix_kyber_workforce_sessions_expiry", "(status, authority_expires_at)"),
    ("kyber_workforce_sessions", "ix_kyber_workforce_sessions_idle", "(status, idle_expires_at)"),
    ("kyber_step_up_grants", "ix_kyber_step_up_grants_expiry", "(expires_at)"),
    ("kyber_access_scopes", "ix_kyber_access_scopes_expiry", "(status, expires_at)"),
    ("kyber_trusted_devices", "ix_kyber_trusted_devices_expiry", "(approval_state, expires_at)"),
    ("kyber_authentication_events", "ix_kyber_authentication_events_created", "(created_at)"),
    ("kyber_access_decisions", "ix_kyber_access_decisions_created", "(created_at)"),
)


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)

    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")

    for table, suffix, key in _JSONB_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_{suffix} ON {table} ((data->>'{key}'));"
        )

    for table, name, expression, predicate in _UNIQUE_INDEXES:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} {expression} {predicate};"
        )

    for table, name, expression in _COMPOSITE_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {expression};")

    for table, name, expression in _EXPIRY_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {expression};")


def downgrade() -> None:
    # Dropping the tables removes their indexes with them.
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
