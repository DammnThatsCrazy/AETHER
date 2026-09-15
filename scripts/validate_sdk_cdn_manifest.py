#!/usr/bin/env python3
"""Validate the SDK CDN release pipeline wiring and, when staged, its output.

The CDN manifest is the contract every installed loader fetches at runtime. Two
failure modes matter and neither is visible in a green build:

  * the pipeline silently stops running (a job renamed, a step dropped), so the
    CDN keeps serving a manifest that no longer matches the package;
  * the manifest advertises a hash in the wrong format, so every client rejects
    the bundle and the install fails silently in a customer's browser.

This gate covers the first statically and re-checks the second when a layout has
been staged locally. Actual hash verification runs in the publish workflow via
scripts/release/verify-cdn-layout.mjs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
NOTES: list[str] = []

GENERATOR = 'scripts/release/generate-sdk-cdn-manifest.mjs'
VERIFIER = 'scripts/release/verify-cdn-layout.mjs'
WORKFLOW = '.github/workflows/publish-sdk.yml'
LAYOUT = ROOT / 'artifacts/sdk/cdn'


def fail(msg: str) -> None:
    ERRORS.append(msg)


def note(msg: str) -> None:
    NOTES.append(msg)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


# --- 1. The pipeline scripts must exist -------------------------------------
for rel in (GENERATOR, VERIFIER):
    if not (ROOT / rel).exists():
        fail(f'{rel} does not exist')

if ERRORS:
    print('SDK CDN manifest validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

pkg_version = json.loads(text('packages/web/package.json'))['version']
major = pkg_version.split('.')[0]

# --- 2. Version must derive from the package, never be hardcoded -------------
generator = text(GENERATOR)
if "readFileSync(join(WEB, 'package.json'" not in generator:
    fail(f'{GENERATOR} does not read the version from packages/web/package.json')
for stale in re.findall(r'\b(\d+\.\d+\.\d+)\b', generator):
    # A literal version in the generator would silently pin the CDN layout.
    fail(f'{GENERATOR} contains hardcoded version literal {stale}; derive it from package.json')

# The major path must track the package major, not a fixed value.
if 'MAJOR' not in generator or 'VERSION.split' not in generator:
    fail(f'{GENERATOR} does not derive the CDN major path from the package version')

# The stable bootstrap URL is part of the public contract.
if 'v1.js' not in generator:
    fail(f'{GENERATOR} does not stage the stable v1.js bootstrap')

# --- 3. Retired CDN major paths must not reappear ----------------------------
for rel in (GENERATOR, VERIFIER):
    body = text(rel)
    for stale in re.findall(r'sdk/v(\d+)/loader', body):
        if stale in {'5', '8'}:
            fail(f'{rel} references the retired sdk/v{stale}/loader path')

# --- 4. The manifest must carry bare-hex hashes for the loader ---------------
# aether-loader.ts compares downloads.sdkBundleHash with `!==` against a bare
# hex digest. An SRI-prefixed value here breaks every bundle fetch.
verifier_src = text(VERIFIER)
if 'integrity?.sri' not in verifier_src:
    fail(f'{VERIFIER} does not verify integrity.sri')
if 'bare' not in text(VERIFIER).lower():
    fail(f'{VERIFIER} does not document/verify the bare-hex requirement for sdkBundleHash')

# --- 5. The publish workflow must actually run the pipeline ------------------
workflow = text(WORKFLOW)
if 'publish-cdn:' not in workflow:
    fail(f'{WORKFLOW} has no publish-cdn job — CDN assets would never be published')
else:
    job = workflow.split('publish-cdn:', 1)[1]
    # Bound the job slice at the next top-level job key.
    next_job = re.search(r'\n  [a-z][a-z0-9-]*:', job)
    if next_job:
        job = job[: next_job.start()]
    for needle, label in (
        (GENERATOR, 'the manifest generator'),
        (VERIFIER, 'the CDN layout verifier'),
        ('verify:artifacts', 'the package artifact verifier'),
    ):
        if needle not in job:
            fail(f'publish-cdn job does not run {label} ({needle})')
    if '!inputs.dry_run' not in job:
        fail('publish-cdn job has no dry_run guard — a dry run would publish')
    if 'cloudfront' not in job.lower():
        fail('publish-cdn job does not invalidate the CDN')

# Short-cache the two mutable paths; long-cache the immutable versioned ones.
if 'max-age=300' not in workflow:
    fail(f'{WORKFLOW} does not give the stable v1.js a short cache policy')
if 'max-age=60' not in workflow:
    fail(f'{WORKFLOW} does not give the manifest a short cache policy')
if 'immutable' not in workflow:
    fail(f'{WORKFLOW} does not give versioned bundles an immutable cache policy')

# --- 6. If a layout is staged, its hashes must verify ------------------------
if LAYOUT.exists() and any(LAYOUT.rglob('*.json')):
    if shutil.which('node') is None:
        note('artifacts/sdk/cdn is staged but node is unavailable; deferred to the publish workflow')
    else:
        result = subprocess.run(
            ['node', VERIFIER], cwd=ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-4:]
            for line in tail:
                fail(f'staged CDN layout failed verification: {line.strip()}')
        else:
            note('staged CDN layout verified: manifest hashes match the staged bytes')
else:
    note('artifacts/sdk/cdn is not staged; hash verification deferred to the publish workflow')

if ERRORS:
    print('SDK CDN manifest validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

for line in NOTES:
    print(f'note: {line}')
print(
    f'SDK CDN manifest validation passed for {pkg_version} (major v{major}): '
    'pipeline wired, version derived from the package, dry-run guarded, cache policy set.'
)
