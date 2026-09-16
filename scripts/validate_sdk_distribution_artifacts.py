#!/usr/bin/env python3
"""Validate that @aether/web's declared distribution surface is buildable and self-consistent.

This is a *wiring* gate, not an artifact gate. It answers: "if we ran the build,
would it emit everything package.json promises, and would the verifier catch it
if it did not?" That question is answerable without building, which matters
because `make ci-check` runs on a fresh checkout where dist/ holds only the
committed .d.ts declarations.

Actual artifact existence is checked by `npm run verify:artifacts`
(packages/web/scripts/verify-web-sdk-package.mjs) in the SDK release workflow,
where the build has genuinely run.

When dist/ *has* been built locally, this gate re-checks the runtime artifacts
too, so a partial build fails here rather than at publish time.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
NOTES: list[str] = []

WEB = 'packages/web'
VERIFIER = f'{WEB}/scripts/verify-web-sdk-package.mjs'


def fail(msg: str) -> None:
    ERRORS.append(msg)


def note(msg: str) -> None:
    NOTES.append(msg)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def rollup_outputs(config: str) -> set[str]:
    """Collect every `file: 'dist/...'` output a rollup config declares."""
    return set(re.findall(r"""file:\s*['"](dist/[^'"]+)['"]""", text(config)))


pkg = json.loads(text(f'{WEB}/package.json'))
scripts = pkg.get('scripts', {})

# --- 1. The build must actually invoke both rollup configs -------------------
# The loader config shipped orphaned for a long time: it existed and declared
# dist/loader.js, but no script ever ran it, so the loader 404'd from the CDN.
build_script = scripts.get('build', '')
if 'rollup.config.mjs' not in build_script:
    fail(f'{WEB}/package.json build script does not run rollup.config.mjs')
if 'rollup.loader.mjs' not in build_script:
    fail(
        f'{WEB}/package.json build script does not run rollup.loader.mjs — '
        'the CDN loader bundle would never be emitted'
    )
if not re.search(r'\btsc\b.*--emitDeclarationOnly', build_script):
    fail(f'{WEB}/package.json build script does not emit type declarations')

# --- 2. The verification scripts must exist and be wired --------------------
if 'verify:artifacts' not in scripts:
    fail(f'{WEB}/package.json is missing the verify:artifacts script')
elif not (ROOT / VERIFIER).exists():
    fail(f'{VERIFIER} does not exist but verify:artifacts references it')

prepack = scripts.get('prepack', '')
if not prepack:
    fail(f'{WEB}/package.json is missing prepack — bad packages would publish unchecked')
else:
    if 'build' not in prepack:
        fail('prepack does not run the build')
    if 'verify:artifacts' not in prepack:
        fail('prepack does not run verify:artifacts')

# --- 3. Rollup must declare the full artifact set ---------------------------
MAIN_OUTPUTS = {
    'dist/aether.cjs.js',
    'dist/aether.esm.js',
    'dist/aether.umd.js',
    'dist/health/index.js',
    'dist/react.js',
}
LOADER_OUTPUTS = {'dist/loader.js', 'dist/loader.mjs'}

main_declared = rollup_outputs(f'{WEB}/rollup.config.mjs')
loader_declared = rollup_outputs(f'{WEB}/rollup.loader.mjs')

for missing in sorted(MAIN_OUTPUTS - main_declared):
    fail(f'{WEB}/rollup.config.mjs does not declare output {missing}')
for missing in sorted(LOADER_OUTPUTS - loader_declared):
    fail(f'{WEB}/rollup.loader.mjs does not declare output {missing}')

# The UMD bundle is the CDN artifact; it must expose the `Aether` global.
if "name: 'Aether'" not in text(f'{WEB}/rollup.config.mjs'):
    fail(f'{WEB}/rollup.config.mjs does not expose the UMD global `Aether`')

# The loader banner must advertise the stable URL, not a stale major path.
loader_banner = text(f'{WEB}/rollup.loader.mjs')
if 'https://cdn.aether.network/v1.js' not in loader_banner:
    fail(f'{WEB}/rollup.loader.mjs banner does not reference the stable https://cdn.aether.network/v1.js')

# --- 4. package.json entry points must be covered by declared outputs -------
def path_targets(node, trail):
    """Every path-valued string in a package.json entry-point structure."""
    if isinstance(node, str):
        yield trail, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from path_targets(value, f'{trail}.{key}')


entry_points: list[tuple[str, str]] = []
for field in ('main', 'module', 'types'):
    if isinstance(pkg.get(field), str):
        entry_points.append((field, pkg[field]))
if isinstance(pkg.get('exports'), dict):
    entry_points.extend(path_targets(pkg['exports'], 'exports'))

declared_all = main_declared | loader_declared
runtime_targets: set[str] = set()
for label, rel in entry_points:
    if not rel.startswith('./'):
        fail(f'package.json {label} must be a relative ./ path, got {rel}')
        continue
    target = rel[2:]
    if target.endswith(('.js', '.mjs')):
        runtime_targets.add(target)
        if target not in declared_all:
            fail(
                f'package.json {label} -> {target} is not emitted by any rollup config '
                '(consumers would import a missing file)'
            )

# --- 5. The verifier must guard exactly the declared runtime surface --------
# Keep REQUIRED_FILES and the entry-point map from drifting apart: a new export
# that the verifier does not know about is an unguarded publish surface.
verifier_src = text(VERIFIER)
match = re.search(r'const REQUIRED_FILES = \[(.*?)\];', verifier_src, re.DOTALL)
if not match:
    fail(f'{VERIFIER} has no parseable REQUIRED_FILES list')
else:
    required = set(re.findall(r"""['"]([^'"]+)['"]""", match.group(1)))
    unguarded = runtime_targets - required
    if unguarded:
        fail(
            f'{VERIFIER} REQUIRED_FILES does not guard package.json entry point(s): '
            f'{", ".join(sorted(unguarded))}'
        )

# --- 6. No stale CDN major paths left in SDK source or CICD -------------------------
# The CICD tree (manifest_publisher.py, sdk_release.py) is the legacy distribution
# layer. It must not hold a stale sdk/v5/loader.js path any more than the web
# package does — both sides publish to the same canonical origin.
cicd_python = [
    'cicd/aether-cicd/stages/sdk/manifest_publisher.py',
    'cicd/aether-cicd/stages/sdk/sdk_release.py',
    'cicd/aether-cicd/README.md',
]
for rel in [f'{WEB}/src/loader/aether-loader.ts', f'{WEB}/rollup.loader.mjs', f'{WEB}/README.md'] + cicd_python:
    body = text(rel)
    for stale in re.findall(r'sdk/v(\d+)/loader\.(?:js|mjs)', body):
        if stale == '5':
            fail(f'{rel} still references the retired sdk/v5/loader path')

# --- 7. If dist was built, the runtime artifacts must all be there ----------
# dist/ always exists (committed .d.ts declarations live there), so the build
# signal is the primary JS bundle rather than the directory itself.
dist = ROOT / WEB / 'dist'
if (dist / 'aether.esm.js').exists():
    for rel in sorted(MAIN_OUTPUTS | LOADER_OUTPUTS):
        target = dist / rel[len('dist/'):]
        if not target.exists():
            fail(f'built tree is incomplete: {WEB}/{rel} is missing — run `npm run build`')
        elif target.stat().st_size == 0:
            fail(f'built tree has an empty artifact: {WEB}/{rel}')
    note('dist/ is built; runtime artifacts verified present')
else:
    note('dist/ is not built (fresh checkout); artifact existence deferred to `npm run verify:artifacts`')

if ERRORS:
    print('SDK distribution artifact validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

for line in NOTES:
    print(f'note: {line}')
print(
    'SDK distribution artifact validation passed: build wiring emits every declared '
    'artifact, package entry points resolve, and the verifier guards the full runtime surface.'
)
