#!/usr/bin/env python3
"""Temporal integrity static gates.

Four checks, each with a committed SHRINK-ONLY allowlist under
``scripts/allowlists/`` (seeded with today's offenders):

1. Python naive-datetime ban — ``datetime.utcnow()`` / ``datetime.now()``
   without a timezone / ``.replace(tzinfo=...)`` outside the temporal kernel.
2. Frontend ad-hoc formatting ban — ``toLocaleString``-family /
   ``Intl.DateTimeFormat`` / ``getHours()``/``getDay()`` outside
   ``frontend/shared/src/time/``.
3. ClickHouse bare ``DateTime`` ban — canonical instants use
   ``DateTime64(3, 'UTC')``.
4. Single Alembic head.

Shrink-only semantics: a NEW offending file fails CI, and an allowlist entry
that no longer offends ALSO fails (remove it — the debt only shrinks).

Usage:
  python scripts/validate_temporal_integrity.py             # validate (CI gate)
  python scripts/validate_temporal_integrity.py --seed      # (re)write allowlists from current state
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
ALLOWLIST_DIR = ROOT / "scripts" / "allowlists"

PY_ALLOWLIST = ALLOWLIST_DIR / "temporal_naive_datetime.json"
FE_ALLOWLIST = ALLOWLIST_DIR / "temporal_frontend_formatting.json"
CH_ALLOWLIST = ALLOWLIST_DIR / "temporal_clickhouse_naive.json"

# The temporal kernel and its tests are the sanctioned homes.
_PY_EXEMPT = ("shared/temporal/",)
_FE_EXEMPT = ("frontend/shared/src/time/",)

_PY_PATTERNS = (
    re.compile(r"datetime\.utcnow\s*\("),
    re.compile(r"(?<![\w.])datetime\.now\s*\(\s*\)"),  # now() with NO tz argument
    re.compile(r"\.replace\s*\(\s*tzinfo\s*="),
)
_FE_PATTERNS = (
    re.compile(r"\.toLocaleString\s*\("),
    re.compile(r"\.toLocaleDateString\s*\("),
    re.compile(r"\.toLocaleTimeString\s*\("),
    re.compile(r"Intl\.DateTimeFormat\s*\("),
    re.compile(r"Intl\.RelativeTimeFormat\s*\("),
    re.compile(r"\.getHours\s*\(\)"),
    re.compile(r"\.getDay\s*\(\)"),
)
_CH_BARE_DATETIME = re.compile(r"(?<!\w)DateTime(?!64)\s*[\(,\s]")


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _scan(paths: list[Path], patterns: tuple[re.Pattern, ...], exempt: tuple[str, ...]) -> set[str]:
    offenders: set[str] = set()
    for path in paths:
        rel = _rel(path)
        if any(marker in rel for marker in exempt):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(p.search(text) for p in patterns):
            offenders.add(rel)
    return offenders


def scan_python() -> set[str]:
    paths: list[Path] = []
    for base in (BACKEND / "services", BACKEND / "shared", BACKEND / "middleware",
                 BACKEND / "repositories", BACKEND / "config"):
        paths.extend(base.rglob("*.py"))
    return _scan(paths, _PY_PATTERNS, _PY_EXEMPT)


def scan_frontend() -> set[str]:
    paths: list[Path] = []
    for app in ("aether", "kyber", "shared"):
        base = ROOT / "frontend" / app / "src"
        if base.exists():
            paths.extend(
                p for p in base.rglob("*.ts*")
                if ".test." not in p.name and not p.name.endswith(".d.ts")
            )
    return _scan(paths, _FE_PATTERNS, _FE_EXEMPT)


def scan_clickhouse() -> set[str]:
    paths: list[Path] = []
    paths.extend((ROOT / "deploy" / "clickhouse").rglob("*.sql"))
    lake_schemas = ROOT / "Data Lake Architecture"
    if lake_schemas.exists():
        paths.extend(lake_schemas.rglob("schemas/*.py"))
    return _scan(paths, (_CH_BARE_DATETIME,), ())


def alembic_heads() -> list[str]:
    revs: dict[str, object] = {}
    for f in (BACKEND / "alembic" / "versions").glob("*.py"):
        rev = down = None
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    name = getattr(t, "id", None)
                    if name == "revision" and isinstance(node.value, ast.Constant):
                        rev = node.value.value
                    if name == "down_revision":
                        if isinstance(node.value, ast.Constant):
                            down = node.value.value
                        elif isinstance(node.value, (ast.Tuple, ast.List)):
                            down = tuple(e.value for e in node.value.elts)
        if rev:
            revs[rev] = down
    downs: set[str] = set()
    for v in revs.values():
        if isinstance(v, tuple):
            downs.update(v)
        elif v:
            downs.add(v)  # type: ignore[arg-type]
    return [r for r in revs if r not in downs]


def _load(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def _diff(name: str, actual: set[str], allowlist: set[str], errors: list[str]) -> None:
    new = actual - allowlist
    stale = allowlist - actual
    for f in sorted(new):
        errors.append(f"{name}: NEW offender (fix it or justify): {f}")
    for f in sorted(stale):
        errors.append(f"{name}: allowlist entry is clean — REMOVE it (shrink-only): {f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="rewrite allowlists from current state")
    args = parser.parse_args()

    py = scan_python()
    fe = scan_frontend()
    ch = scan_clickhouse()

    if args.seed:
        ALLOWLIST_DIR.mkdir(parents=True, exist_ok=True)
        PY_ALLOWLIST.write_text(json.dumps(sorted(py), indent=2) + "\n")
        FE_ALLOWLIST.write_text(json.dumps(sorted(fe), indent=2) + "\n")
        CH_ALLOWLIST.write_text(json.dumps(sorted(ch), indent=2) + "\n")
        print(f"seeded allowlists: py={len(py)} frontend={len(fe)} clickhouse={len(ch)}")
        return 0

    errors: list[str] = []
    _diff("naive-datetime", py, _load(PY_ALLOWLIST), errors)
    _diff("frontend-formatting", fe, _load(FE_ALLOWLIST), errors)
    _diff("clickhouse-bare-datetime", ch, _load(CH_ALLOWLIST), errors)

    heads = alembic_heads()
    if len(heads) != 1:
        errors.append(f"alembic: expected exactly one head, found {heads}")

    if errors:
        print("TEMPORAL INTEGRITY VIOLATIONS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "New date/time logic must use shared/temporal (Python) or "
            "frontend/shared/src/time (TS); ClickHouse instants use DateTime64(3,'UTC').",
            file=sys.stderr,
        )
        return 1

    print(
        f"temporal integrity OK: naive-py debt={len(py)}, frontend debt={len(fe)}, "
        f"clickhouse debt={len(ch)}, alembic head={heads[0]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
