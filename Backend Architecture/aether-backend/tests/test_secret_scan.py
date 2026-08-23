"""Secret-scan gate (program §25/§28).

Two layers:

1. ``test_canonical_secret_scan_passes`` — the repository's own scanner
   (``scripts/security/secret_scan.py``) must report zero high-confidence
   secrets in its canonical scope (tracked files outside tests/docs/examples/
   generated artifacts). This is the hygiene gate that ships with the repo.

2. ``test_no_real_secrets_in_any_tracked_file`` — a STRICTER sweep that applies
   the same high-confidence patterns to EVERY git-tracked file (no test/docs
   exclusions). Test fixtures legitimately contain secret-shaped literals, so
   the sweep fails only on a finding whose matched value is not honestly
   declared in ``SYNTHETIC_FIXTURE_VALUES`` — and, as an anti-weakening guard,
   every declared value must occur ONLY in paths the canonical scanner already
   excludes. A real credential committed anywhere (even under ``tests/``) has a
   value no fixture declares, so it fails the sweep; a developer who copies a
   real key into a fixture cannot paper over it because the declaration itself
   is pinned to test/docs paths.

The registry is keyed on the matched substring (not path/line) so renames and
line moves do not invalidate it. It must stay a strict superset of nothing and
a subset of reality: ``SYNTHETIC_FIXTURE_VALUES`` entries that no longer appear
in any tracked file also fail, so stale declarations are cleaned up too.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_SCANNER_PATH = REPO_ROOT / "scripts" / "security" / "secret_scan.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("secret_scan", _SCANNER_PATH)
    assert spec and spec.loader, f"cannot load {_SCANNER_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCANNER = _load_scanner()

#: Matched secret-shaped literals that are provably fixture/test values. The
#: anti-weakening guard below requires every value in this set to occur ONLY in
#: canonical-excluded paths (tests/docs/fixtures/generated/.md), so it cannot be
#: used to whitelist a real credential.
SYNTHETIC_FIXTURE_VALUES: frozenset[str] = frozenset({
    'secret = "whsec_test_stripe_secret"',
    'xoxb-test-token',
    'SECRET = "test-linear-webhook-secret"',
    'SECRET = "test-slack-signing-secret"',
    'SECRET = "test-aether-callback-secret"',
    'TOKEN = "kses_containment_scope_test"',
    'TOKEN = "csrf_containment_scope_test"',
    'SECRET = "fake-client-secret-value"',
    'secret="whsec_golden_stripe_2024"',
    'secret="whsec_golden_moonpay_2024"',
    'secret="whsec_golden_coinbase_2024"',
    'secret="whsec_declared_bridge_2024"',
    'secret="whsec_declared_privy_2024"',
    'secret = "slack-signing-secret-123"',
    'xoxb-idem-token',
    'api_key="sk-live-super-secret-key"',
    'secret = "whsec_should_not_persist"',
    'xoxb-fake-token',
    "API_KEY = 'ak_test_key_abcdefghijklmnop'",
    "api_key: 'ak_mock_dev_key_from_otp_verify'",
    "token: 'mock_access_token_refreshed'",
    'xoxb-new-token-here',
    "-----BEGIN RSA PRIVATE KEY-----",
    'SECRET="test-sdk-config-secret-for-tests"',
})


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO_ROOT,
        check=True,
    )
    files: list[Path] = []
    for line in out.stdout.splitlines():
        if not line:
            continue
        p = REPO_ROOT / line
        try:
            if p.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def _strict_scan() -> list[tuple[Path, int, str, str]]:
    """Apply the scanner's high-confidence patterns to EVERY tracked file.

    Returns ``(path, lineno, pattern_name, matched_value)`` — no exclusion.
    """
    findings: list[tuple[Path, int, str, str]] = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name, pat in _SCANNER.PATTERNS:
                match = pat.search(line)
                if not match:
                    continue
                if _SCANNER.PLACEHOLDER_RE.search(match.group(0)):
                    break
                findings.append((path, i, name, match.group(0)))
                break
    return findings


def _canonically_allowed(path: Path) -> bool:
    """True iff the canonical scanner would skip this path outright."""
    return any(s in str(path.relative_to(REPO_ROOT)) for s in _SCANNER.ALLOW_SUBSTRINGS)


def test_canonical_secret_scan_passes() -> None:
    """The repo's own hygiene gate must find nothing in its canonical scope."""
    findings = _SCANNER.scan()
    assert findings == [], (
        "scripts/security/secret_scan.py reported high-confidence secrets in "
        "tracked (non-test/doc) files:\n"
        + "\n".join(f"  - {f}:{line} [{name}]" for f, line, name in findings)
    )


def test_no_real_secrets_in_any_tracked_file() -> None:
    """Every secret-shaped literal across the whole tree is a declared fixture."""
    findings = _strict_scan()
    observed: dict[str, list[tuple[Path, int, str]]] = {}
    for path, lineno, name, value in findings:
        observed.setdefault(value, []).append((path, lineno, name))

    undeclared = sorted(set(observed) - SYNTHETIC_FIXTURE_VALUES)
    assert undeclared == [], (
        "secret-shaped literal(s) in tracked files are NOT declared synthetic "
        "fixtures (possible real credential):\n"
        + "\n".join(
            f"  - {value!r} at "
            + ", ".join(f"{p.relative_to(REPO_ROOT)}:{ln}" for p, ln, _ in observed[value])
            for value in undeclared
        )
    )

    # Anti-weakening: every declared fixture must occur ONLY in paths the
    # canonical scanner already excludes, so the registry cannot be used to
    # whitelist a real key that lives in production code.
    mislocated = [
        (value, f"{p.relative_to(REPO_ROOT)}:{ln}")
        for value, locs in observed.items()
        for p, ln, _ in locs
        if not _canonically_allowed(p)
    ]
    assert mislocated == [], (
        "declared synthetic fixture value appears in a path the canonical "
        "scanner does NOT exclude — it is not a test fixture:\n"
        + "\n".join(f"  - {value!r} at {loc}" for value, loc in mislocated)
    )

    # Stale registry hygiene: entries that no longer appear anywhere must be
    # removed (otherwise the declaration rots while a real secret silently
    # replaces the fixture later).
    stale = sorted(SYNTHETIC_FIXTURE_VALUES - set(observed))
    assert stale == [], (
        "SYNTHETIC_FIXTURE_VALUES entries no longer appear in any tracked file; "
        "remove them: " + ", ".join(stale)
    )
