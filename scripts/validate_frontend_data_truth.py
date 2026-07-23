#!/usr/bin/env python3
"""Validate frontend data-truth guardrails for Aether and Kyber."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOTS = [ROOT / "frontend/aether/src", ROOT / "frontend/kyber/src"]
PUBLIC_WORKERS = [ROOT / "frontend/aether/public/mockServiceWorker.js", ROOT / "frontend/kyber/public/mockServiceWorker.js"]
TEST_PARTS = {"test", "tests", "test-support", "__tests__", "stories"}
BANNED = [
    "msw/browser",
    "setupWorker",
    "local-mocked",
    "MockModeBanner",
    "tenant_demo_001",
    "tenant_kyber_mock",
    "alex@acme.io",
    "ak_mock",
    "mock_access_token",
]
IMPORT_RE = re.compile(r"from\s+['\"]([^'\"]*(?:mocks|fixtures)[^'\"]*)['\"]|import\s*\(\s*['\"]([^'\"]*(?:mocks|fixtures)[^'\"]*)['\"]")

def is_test_path(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return any(part in TEST_PARTS or part.endswith('.test.ts') or part.endswith('.test.tsx') for part in rel.parts)

def scan() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for worker in PUBLIC_WORKERS:
        if worker.exists():
            findings.append({"path": str(worker.relative_to(ROOT)), "line": 1, "reason": "public mockServiceWorker.js is prohibited"})
    for root in RUNTIME_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".jsx"} or is_test_path(path):
                continue
            rel_parts = set(path.relative_to(ROOT).parts)
            isolated_fixture_or_mock_file = "fixtures" in rel_parts or "mocks" in rel_parts
            text = path.read_text(encoding="utf-8", errors="ignore")
            for idx, line in enumerate(text.splitlines(), 1):
                if not isolated_fixture_or_mock_file:
                    for token in BANNED:
                        if token in line and token != "mockServiceWorker":
                            findings.append({"path": str(path.relative_to(ROOT)), "line": idx, "reason": f"banned runtime token: {token}"})
                    if IMPORT_RE.search(line):
                        findings.append({"path": str(path.relative_to(ROOT)), "line": idx, "reason": "runtime import from mocks/fixtures"})
    return findings

def bundle_scan() -> list[dict[str, object]]:
    dist_roots = [ROOT / "frontend/aether/dist", ROOT / "frontend/kyber/dist"]
    tokens = ["mockServiceWorker", "tenant_demo_001", "tenant_kyber_mock", "alex@acme.io", "mock_access_token"]
    findings: list[dict[str, object]] = []
    for root in dist_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".js", ".html", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in tokens:
                if token in text:
                    findings.append({"path": str(path.relative_to(ROOT)), "line": 1, "reason": f"banned production bundle token: {token}"})
    return findings

def main() -> int:
    findings = scan() + bundle_scan()
    report = {"status": "pass" if not findings else "fail", "findings": findings}
    print(json.dumps(report, indent=2))
    return 1 if findings else 0

if __name__ == "__main__":
    raise SystemExit(main())
