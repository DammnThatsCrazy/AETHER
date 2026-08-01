"""Guard: no module may pass structured fields as logger keyword arguments.

``shared.logger.logger.get_logger`` returns a stdlib :class:`logging.Logger`.
Stdlib loggers accept only ``exc_info``/``extra``/``stack_info``/``stacklevel``
as keyword arguments, so a call like::

    logger.info("custom_campaign_created", tenant_id=tenant_id)

raises ``TypeError: Logger._log() got an unexpected keyword argument`` at the
moment it executes. That is not a logging inconvenience — in
``services/economic/routes.py`` these calls sat inside request handlers, and in
``services/campaign/registry.py`` one sat *after* the database write, so the
write landed and the request then failed.

Sixteen such calls existed across three modules. They survived because
``Backend Architecture/aether-backend/tests/`` was executed by no gate.

``log_event(logger, level, message, **fields)`` is the supported way to attach
structured data.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# The only keywords a stdlib Logger method accepts.
_STDLIB_LOG_KWARGS = frozenset({"exc_info", "extra", "stack_info", "stacklevel"})

_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _iter_source_files():
    for path in BACKEND_ROOT.rglob("*.py"):
        parts = path.parts
        if "__pycache__" in parts or "tests" in parts:
            continue
        yield path


def _bad_log_calls(path: Path) -> list[tuple[int, str, list[str]]]:
    """Return (lineno, method, offending_kwargs) for stdlib-invalid log calls."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
            continue
        # Only `logger.<level>(...)` — an attribute call on some other object may
        # legitimately be a structlog-style logger with a different contract.
        if not isinstance(func.value, ast.Name) or func.value.id != "logger":
            continue
        offending = [
            kw.arg
            for kw in node.keywords
            if kw.arg is not None and kw.arg not in _STDLIB_LOG_KWARGS
        ]
        if offending:
            found.append((node.lineno, func.attr, offending))
    return found


def test_no_module_passes_structured_fields_as_logger_kwargs() -> None:
    violations: list[str] = []
    for path in _iter_source_files():
        for lineno, method, kwargs in _bad_log_calls(path):
            rel = path.relative_to(BACKEND_ROOT)
            violations.append(f"{rel}:{lineno} logger.{method}(..., {', '.join(kwargs)}=...)")

    assert not violations, (
        "These logger calls raise TypeError when executed — a stdlib Logger does "
        "not accept arbitrary keyword arguments. Use "
        "log_event(logger, level, message, **fields) instead:\n  "
        + "\n  ".join(sorted(violations))
    )


def test_guard_detects_a_known_bad_call(tmp_path: Path) -> None:
    """The guard must actually fire — a scanner that never matches is not a gate."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.info('evt', tenant_id='t1')\n"
        "logger.warning('ok', exc_info=True)\n",
        encoding="utf-8",
    )
    found = _bad_log_calls(sample)
    assert found == [(3, "info", ["tenant_id"])], found


def test_stdlib_logger_really_rejects_those_kwargs() -> None:
    """Pin the premise itself, so the guard cannot outlive the reason for it.

    The level matters. ``Logger.info`` consults ``isEnabledFor`` *before*
    delegating to ``_log``, so a logger left at the default WARNING level
    discards the call — and the bad keyword argument with it — without raising.
    That is precisely what makes this defect class dangerous: it is invisible
    until the level is enabled, and ``get_logger`` enables INFO and attaches a
    handler, so every one of these calls raises in a real process.
    """
    import logging

    logger = logging.getLogger("aether.test.logger_call_shape")

    # Another suite in this tree calls logging.disable(), which suppresses every
    # logger process-wide regardless of its own level. Restore the precondition
    # explicitly rather than inheriting whatever ran first — this assertion is
    # about the stdlib contract, not about test ordering.
    previous_disable = logging.root.manager.disable
    previous_level = logger.level
    logging.disable(logging.NOTSET)
    logger.setLevel(logging.INFO)
    try:
        assert logger.isEnabledFor(logging.INFO), (
            "premise requires an enabled level; a disabled logger silently drops "
            "the offending keyword argument instead of raising"
        )

        try:
            logger.info("evt", tenant_id="t1")
        except TypeError as exc:
            assert "unexpected keyword argument" in str(exc)
        else:  # pragma: no cover — would mean the stdlib contract changed
            raise AssertionError(
                "stdlib Logger accepted an arbitrary keyword argument; the guard "
                "in this module is now based on a false premise and should be "
                "revisited"
            )
    finally:
        logging.disable(previous_disable)
        logger.setLevel(previous_level)
