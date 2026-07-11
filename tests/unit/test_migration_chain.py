"""Migration-graph integrity: exactly one head, always.

Multiple heads make ``alembic upgrade head`` fail outright — and because
deploys only run migrations via the opt-in ``RUN_MIGRATIONS=1`` entrypoint,
a forked graph can sit unnoticed until a staging deploy hard-fails at the
readiness gate. This test makes the fork visible at PR time instead.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_migration_head():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"Migration graph has {len(heads)} heads {heads} — 'alembic upgrade "
        "head' will fail. Add a merge migration (tuple down_revision, see "
        "20260714_merge_heads.py) instead of leaving a fork."
    )


def test_every_revision_reachable_from_head():
    sd = _script_directory()
    (head,) = sd.get_heads()
    reachable = {rev.revision for rev in sd.walk_revisions(base="base", head=head)}
    all_revisions = {rev.revision for rev in sd.walk_revisions()}
    orphaned = all_revisions - reachable
    assert not orphaned, (
        f"Revisions not reachable from head {head}: {sorted(orphaned)} — "
        "they will never be applied by 'alembic upgrade head'."
    )
