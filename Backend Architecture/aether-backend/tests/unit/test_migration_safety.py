"""Unit tests for the migration destructive-change gate
(scripts/validate_migration_safety.py).

The gate AST-parses every Alembic revision's upgrade() body and flags
destructive schema operations (drop_column, drop_table, drop_constraint,
rename_table, and an unsafe alter_column) unless the revision declares a
validated MIGRATION_PHASE="contract" / EXPAND_REVISION pair or is explicitly
grandfathered in config/migration_safety_allowlist.yaml.

These tests build synthetic revision files under pytest's tmp_path and feed
them straight to the validator's functions (parse_all_revisions /
validate_revisions) — the real 62-revision graph under
Backend Architecture/aether-backend/alembic/versions is never touched.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_SPEC = importlib.util.spec_from_file_location(
    "validate_migration_safety", ROOT / "scripts" / "validate_migration_safety.py"
)
assert _SPEC and _SPEC.loader
MODULE = importlib.util.module_from_spec(_SPEC)
# Register before exec: the module uses `from __future__ import annotations`
# with dataclasses, whose field-type resolution looks the module up in
# sys.modules by name while it is executing.
sys.modules[_SPEC.name] = MODULE
_SPEC.loader.exec_module(MODULE)


def _write_revision(
    directory: Path,
    filename: str,
    *,
    revision: str,
    down_revision,
    body: str,
    extra: str = "",
) -> Path:
    """Write a synthetic Alembic-shaped revision module for the gate to parse."""
    content = f'''"""Synthetic revision for validator unit tests."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = None
depends_on = None
{extra}

def upgrade() -> None:
{textwrap.indent(body, "    ")}

def downgrade() -> None:
    pass
'''
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# (a) contract-phase must not be the same revision as its expand
# --------------------------------------------------------------------------


def test_contract_phase_rejects_self_referential_expand(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_base.py",
        revision="synt_base",
        down_revision=None,
        body="pass\n",
    )
    _write_revision(
        tmp_path,
        "0002_contract_self.py",
        revision="synt_contract_self",
        down_revision="synt_base",
        body='op.drop_column("widgets", "legacy_flag")\n',
        extra=(
            'MIGRATION_PHASE = "contract"\n'
            'EXPAND_REVISION = "synt_contract_self"\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert len(errors) == 1
    assert "synt_contract_self" in errors[0]
    assert "own revision" in errors[0]


def test_contract_phase_rejects_non_ancestor_expand(tmp_path: Path) -> None:
    """EXPAND_REVISION must be a real ancestor, not merely a real revision id."""
    _write_revision(
        tmp_path,
        "0001_base.py",
        revision="synt_base",
        down_revision=None,
        body="pass\n",
    )
    _write_revision(
        tmp_path,
        "0002_sibling.py",
        revision="synt_sibling",
        down_revision="synt_base",
        body="pass\n",
    )
    _write_revision(
        tmp_path,
        "0003_contract.py",
        revision="synt_contract_bad_expand",
        down_revision="synt_base",
        body='op.drop_table("legacy_widgets")\n',
        extra=(
            'MIGRATION_PHASE = "contract"\n'
            # synt_sibling is a real revision, but not an ancestor of
            # synt_contract_bad_expand (they're siblings off synt_base).
            'EXPAND_REVISION = "synt_sibling"\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert len(errors) == 1
    assert "synt_contract_bad_expand" in errors[0]
    assert "not an ancestor" in errors[0]


# --------------------------------------------------------------------------
# (b) validator flags a synthetic undeclared drop_column, and passes a
#     properly declared contract pair
# --------------------------------------------------------------------------


def test_undeclared_drop_column_is_flagged(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_undeclared.py",
        revision="synt_undeclared_drop",
        down_revision=None,
        body='op.drop_column("widgets", "legacy_flag")\n',
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert len(errors) == 1
    assert "synt_undeclared_drop" in errors[0]
    assert "drop_column" in errors[0]
    assert "undeclared destructive migration" in errors[0]


def test_properly_declared_contract_pair_passes(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_expand.py",
        revision="synt_expand_ok",
        down_revision=None,
        body='op.add_column("widgets", sa.Column("legacy_flag", sa.Boolean()))\n',
    )
    _write_revision(
        tmp_path,
        "0002_contract.py",
        revision="synt_contract_ok",
        down_revision="synt_expand_ok",
        body='op.drop_column("widgets", "legacy_flag")\n',
        extra=(
            'MIGRATION_PHASE = "contract"\n'
            'EXPAND_REVISION = "synt_expand_ok"\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert errors == []


def test_properly_declared_contract_pair_across_merge_point(tmp_path: Path) -> None:
    """EXPAND_REVISION resolution must fan out through tuple down_revisions
    (merge commits), not just single-parent chains."""
    _write_revision(
        tmp_path,
        "0001_left.py",
        revision="synt_left",
        down_revision=None,
        body="pass\n",
    )
    _write_revision(
        tmp_path,
        "0002_right_expand.py",
        revision="synt_right_expand",
        down_revision=None,
        body='op.add_column("widgets", sa.Column("legacy_flag", sa.Boolean()))\n',
    )
    _write_revision(
        tmp_path,
        "0003_merge.py",
        revision="synt_merge",
        down_revision=("synt_left", "synt_right_expand"),
        body="pass\n",
    )
    _write_revision(
        tmp_path,
        "0004_contract.py",
        revision="synt_contract_after_merge",
        down_revision="synt_merge",
        body='op.drop_column("widgets", "legacy_flag")\n',
        extra=(
            'MIGRATION_PHASE = "contract"\n'
            'EXPAND_REVISION = "synt_right_expand"\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert errors == []


# --------------------------------------------------------------------------
# No naive substring matching: destructive ops reached via a local helper
# function called from upgrade() must still be caught.
# --------------------------------------------------------------------------


def test_destructive_op_via_local_helper_is_flagged(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_indirect.py",
        revision="synt_indirect_drop",
        down_revision=None,
        body="_drop_legacy_columns()\n",
        extra=(
            "\n\ndef _drop_legacy_columns() -> None:\n"
            '    op.drop_column("widgets", "legacy_flag")\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert len(errors) == 1
    assert "synt_indirect_drop" in errors[0]
    assert "drop_column" in errors[0]


def test_downgrade_only_drop_is_not_flagged(tmp_path: Path) -> None:
    """Only upgrade() is in scope; a drop in downgrade() (the normal
    "undo the create" pattern) must not trip the gate."""
    directory = tmp_path
    content = '''"""Synthetic revision: create in upgrade, drop in downgrade."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "synt_downgrade_only"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Text(), primary_key=True))


def downgrade() -> None:
    op.drop_table("widgets")
'''
    (directory / "0001_downgrade_only.py").write_text(content, encoding="utf-8")

    infos = MODULE.parse_all_revisions(directory)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert errors == []


# --------------------------------------------------------------------------
# alter_column(nullable=False) heuristic
# --------------------------------------------------------------------------


def test_alter_column_not_nullable_without_default_is_flagged(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_alter.py",
        revision="synt_alter_unsafe",
        down_revision=None,
        body='op.alter_column("widgets", "sku", nullable=False)\n',
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert len(errors) == 1
    assert "synt_alter_unsafe" in errors[0]
    assert "alter_column" in errors[0]


def test_alter_column_not_nullable_with_server_default_is_safe(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_alter_safe.py",
        revision="synt_alter_safe",
        down_revision=None,
        body=(
            'op.alter_column("widgets", "sku", nullable=False, '
            'server_default="unknown")\n'
        ),
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids=set())

    assert errors == []


# --------------------------------------------------------------------------
# Allowlist grandfathering
# --------------------------------------------------------------------------


def test_allowlisted_revision_is_grandfathered(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_grandfathered.py",
        revision="synt_grandfathered_drop",
        down_revision=None,
        body='op.drop_table("legacy_widgets")\n',
    )

    infos = MODULE.parse_all_revisions(tmp_path)
    errors = MODULE.validate_revisions(infos, allowlist_ids={"synt_grandfathered_drop"})

    assert errors == []


def test_allowlist_entry_for_nonexistent_revision_fails() -> None:
    infos: dict = {}
    entries = [{"revision": "does_not_exist", "reason": "made up"}]

    errors = MODULE.validate_allowlist_entries(entries, infos)

    assert len(errors) == 1
    assert "does_not_exist" in errors[0]


def test_allowlist_entry_missing_reason_fails(tmp_path: Path) -> None:
    _write_revision(
        tmp_path,
        "0001_x.py",
        revision="synt_needs_reason",
        down_revision=None,
        body="pass\n",
    )
    infos = MODULE.parse_all_revisions(tmp_path)
    entries = [{"revision": "synt_needs_reason"}]

    errors = MODULE.validate_allowlist_entries(entries, infos)

    assert len(errors) == 1
    assert "missing a 'reason'" in errors[0]


# --------------------------------------------------------------------------
# The real repo graph, exercised through the same code path (defensive —
# guards against someone re-adding a destructive op to upgrade() without a
# gate run; the CLI itself is verified separately, not here).
# --------------------------------------------------------------------------


def test_real_graph_currently_has_no_undeclared_destructive_migrations() -> None:
    exit_code, errors, infos, allowlist_entries = MODULE.run(
        MODULE.DEFAULT_VERSIONS_DIR, MODULE.DEFAULT_ALLOWLIST_PATH
    )

    assert exit_code == 0, errors
    assert errors == []
    assert len(infos) >= 60
    assert allowlist_entries == []
