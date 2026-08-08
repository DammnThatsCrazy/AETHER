"""Fast offline guard against a fresh-DB DDL-literal bug class.

Several Alembic revisions build DDL with an f-string that carries a JSONB
default, e.g.::

    op.execute(f'''
        CREATE TABLE IF NOT EXISTS {table} (
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
    ''')

Inside an f-string the doubled braces are correct — Python collapses ``{{}}``
to the literal ``{}`` the moment the string is evaluated, so Postgres receives
``DEFAULT '{}'::jsonb`` (a valid empty JSON object). The trap is copying that
exact ``'{{}}'`` text into a **plain** (non-f, never ``.format()``-ed) string:
there is nothing to collapse the braces, so the literal ``'{{}}'`` reaches
Postgres and ``alembic upgrade head`` fails on a genuinely fresh database with::

    invalid input syntax for type json ... Expected string or "}", but found "{"

That failure is invisible to the in-memory ``AETHER_ENV=local`` path (which
never runs Alembic) and only surfaces when a real Postgres is provisioned — as
happened once in ``20260808_provider_evidence.py`` and was caught by the
production-equivalent CI lane. This test turns that whole class into a fast,
always-on offline check so the next occurrence fails in the regular python
suite instead of only in the slow, non-blocking real-stack lane.

Detection is precise rather than a substring grep: it is AST-based, and it
relies on the fact that a genuine f-string chunk can never carry ``{{`` in its
evaluated value (the parser has already turned ``{{`` into ``{``). So any
``ast.Constant`` *string* whose value still contains ``{{`` must be a plain
string literal — the bug — unless that constant is the immediate receiver of a
``.format()`` call, where doubled braces are the legitimate escape.
"""

from __future__ import annotations

import ast
from pathlib import Path

VERSIONS_DIR = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions"
)


def _format_receiver_constants(tree: ast.Module) -> set[int]:
    """id()s of string Constants used directly as ``"...".format(...)``.

    A plain string that is a ``.format()`` template legitimately contains
    ``{{`` (the escape for a literal brace in the output), so it must not be
    flagged.
    """
    receivers: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)
        ):
            receivers.add(id(node.func.value))
    return receivers


def plain_string_double_brace_literals(source: str) -> list[tuple[int, str]]:
    """Return ``(lineno, snippet)`` for every plain-string ``{{`` literal.

    An f-string chunk never reaches the AST with ``{{`` in its value (it is
    already collapsed to ``{``), so a surviving ``{{`` in an ``ast.Constant``
    string is necessarily a plain (non-f) literal — the fresh-DB bug — unless
    that constant is a ``.format()`` template.
    """
    tree = ast.parse(source)
    format_receivers = _format_receiver_constants(tree)
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "{{" in node.value
            and id(node) not in format_receivers
        ):
            snippet = node.value.strip().splitlines()[0][:80] if node.value.strip() else ""
            findings.append((node.lineno, snippet))
    return findings


def test_no_plain_string_double_brace_ddl_in_real_migrations() -> None:
    """No revision under alembic/versions carries a plain-string ``{{`` literal.

    Guards against re-introducing the ``DEFAULT '{{}}'::jsonb``-in-a-plain-string
    fresh-DB failure. If this trips, change the offending ``'{{}}'`` to ``'{}'``
    in the plain string (or make the string an f-string if it interpolates).
    """
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        found = plain_string_double_brace_literals(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.name] = found

    assert not offenders, (
        "plain-string doubled-brace DDL literal(s) found — these fail "
        "`alembic upgrade head` on a fresh Postgres with invalid-JSON; replace "
        "'{{}}' with '{}' (or make the string an f-string): "
        + "; ".join(
            f"{name} at line(s) {[ln for ln, _ in hits]}"
            for name, hits in offenders.items()
        )
    )


def test_detector_flags_plain_string_double_brace() -> None:
    """The exact shape of the original bug is detected."""
    source = (
        "_DDL = \"\"\"\n"
        "    CREATE TABLE IF NOT EXISTS t (\n"
        "        data JSONB NOT NULL DEFAULT '{{}}'::jsonb\n"
        "    )\n"
        "\"\"\"\n"
    )
    findings = plain_string_double_brace_literals(source)
    assert len(findings) == 1


def test_detector_ignores_fstring_double_brace() -> None:
    """The legitimate f-string idiom (`f\"...'{{}}'::jsonb...\"`) is not flagged."""
    source = (
        "table = 't'\n"
        "sql = f\"CREATE TABLE {table} (data JSONB DEFAULT '{{}}'::jsonb)\"\n"
    )
    assert plain_string_double_brace_literals(source) == []


def test_detector_ignores_format_template_double_brace() -> None:
    """A `.format()` template's doubled braces are the legitimate escape."""
    source = "sql = \"CREATE TABLE {0} (data JSONB DEFAULT '{{}}'::jsonb)\".format('t')\n"
    assert plain_string_double_brace_literals(source) == []
