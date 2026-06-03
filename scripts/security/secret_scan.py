#!/usr/bin/env python3
"""Dependency-free secret scanner for tracked files.

Scans git-tracked text files for high-confidence secret patterns (private keys,
cloud keys, provider tokens, and assignments of long literals to secret-named
variables). Example templates, tests, docs, and generated artifacts are
excluded. This is a readiness/hygiene aid, not a substitute for a dedicated
scanner (gitleaks / detect-secrets) in CI.

Usage:
  python scripts/security/secret_scan.py            # report (exit 1 on findings)
  python scripts/security/secret_scan.py --advisory # always exit 0

See docs/SECRET-SCANNING.md.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Paths where secret-looking strings are expected/allowed (examples, tests, docs).
ALLOW_SUBSTRINGS = (
    ".example", "/test", "test_", "_test", "/tests/", "/docs/", "/_generated/",
    "mockServiceWorker.js", "package-lock.json", ".md", "generate_secrets.py",
    "secret_scan.py", "/mocks/",
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stripe_live_key", re.compile(r"\bsk_live_[0-9a-zA-Z]{16,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("generic_secret_assignment", re.compile(
        r"(?i)(secret|password|api[_-]?key|token|private[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9/+=_\-]{24,}['\"]")),
]


def tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT)
    files: list[Path] = []
    for line in out.stdout.splitlines():
        if not line or any(s in line for s in ALLOW_SUBSTRINGS):
            continue
        p = ROOT / line
        try:
            if p.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def scan() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "placeholder" in line.lower() or "change-me" in line.lower() or "example" in line.lower():
                continue
            for name, pat in PATTERNS:
                if pat.search(line):
                    findings.append((str(path.relative_to(ROOT)), i, name))
                    break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--advisory", action="store_true", help="Always exit 0.")
    args = parser.parse_args()
    findings = scan()
    if findings:
        print(f"secret_scan: {len(findings)} potential secret(s) found:")
        for f, line, name in findings:
            print(f"  - {f}:{line} [{name}]")
        return 0 if args.advisory else 1
    print("secret_scan: no high-confidence secrets found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
