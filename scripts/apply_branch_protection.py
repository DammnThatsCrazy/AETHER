#!/usr/bin/env python3
"""
Apply required branch protection rules to origin/main via the GitHub CLI.

Usage:
    python scripts/apply_branch_protection.py [--repo OWNER/REPO] [--dry-run]

Requirements:
    - `gh` CLI installed and authenticated
    - Caller must have admin access to the repository
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def run_gh(args: list[str], *, dry_run: bool) -> dict:
    cmd = ["gh", *args]
    print(f"  {'[DRY RUN] ' if dry_run else ''}{' '.join(cmd)}")
    if dry_run:
        return {}
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply branch protection to origin/main")
    parser.add_argument("--repo", default="DammnThatsCrazy/AETHER", help="owner/repo")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    required_status_checks = [
        "validate",           # aggregate gate in repo-health.yml
        "repo-consistency",   # repo-consistency.yml
    ]

    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": required_status_checks,
        },
        "enforce_admins": False,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
        },
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
    }

    print(f"\nApplying branch protection to {args.repo} / main")
    print(f"Required status checks: {required_status_checks}\n")

    run_gh(
        [
            "api",
            f"repos/{args.repo}/branches/main/protection",
            "--method", "PUT",
            "--input", "-",
        ],
        dry_run=args.dry_run,
    ) if not args.dry_run else None

    if not args.dry_run:
        # Use subprocess directly so we can pipe JSON
        import io
        payload_str = json.dumps(payload)
        cmd = [
            "gh", "api",
            f"repos/{args.repo}/branches/main/protection",
            "--method", "PUT",
            "--input", "-",
        ]
        print(f"  {' '.join(cmd)}")
        result = subprocess.run(cmd, input=payload_str, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        print("  Branch protection applied successfully.")
    else:
        print(f"  Would PUT: {json.dumps(payload, indent=2)}")

    print("\nRequired GitHub ruleset (for manual verification):")
    print("  Branch: main")
    print("  Required status checks (must pass before merge):")
    for check in required_status_checks:
        print(f"    - {check}")
    print("  Require branches to be up to date: YES")
    print("  Require conversation resolution: YES")
    print("  Allow force pushes: NO")
    print("  Allow deletions: NO")
    print("  Required approving reviews: 1")


if __name__ == "__main__":
    main()
