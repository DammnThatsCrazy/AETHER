#!/usr/bin/env node
// =============================================================================
// Aether SDK — @aether/web PACKAGE ARTIFACT VERIFICATION
//
// Guards the boundary between "the build ran" and "the package is publishable".
// A published tarball whose package.json points at files the build never emitted
// is broken for every consumer, and npm will not tell you. This script fails the
// release instead.
//
// Invoked by: `npm run verify:artifacts` and `prepack`.
//
// NOTE: `npm pack` is invoked with --ignore-scripts. Without it, prepack ->
// verify:artifacts -> npm pack -> prepack would recurse forever.
// =============================================================================

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const PKG_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(PKG_ROOT, 'package.json'), 'utf-8'));

const failures = [];
const notes = [];

/** Every artifact the package contract promises. */
const REQUIRED_FILES = [
  'dist/aether.cjs.js',
  'dist/aether.esm.js',
  'dist/aether.umd.js',
  'dist/loader.js',
  'dist/loader.mjs',
  'dist/index.d.ts',
  'dist/react.js',
  'dist/react.d.ts',
  'dist/health/index.js',
  'dist/health/index.d.ts',
];

/** Gzip budgets in KB. Ratchet down as the bundles shrink; never up to pass. */
const SIZE_BUDGETS = [
  { file: 'dist/loader.js', maxKb: 5 },
  { file: 'dist/aether.umd.js', maxKb: 80 },
  { file: 'dist/aether.esm.js', maxKb: 80 },
  { file: 'dist/react.js', maxKb: 10 },
];

/** Content markers that prove a bundle is the thing it claims to be. */
const CONTENT_MARKERS = [
  { file: 'dist/aether.umd.js', marker: 'Aether', what: 'UMD global `Aether`' },
  { file: 'dist/loader.js', marker: 'AetherLoader', what: 'loader global `AetherLoader`' },
];

const abs = (rel) => join(PKG_ROOT, rel);
const kb = (bytes) => bytes / 1024;

function checkExistsAndNonEmpty() {
  for (const rel of REQUIRED_FILES) {
    const path = abs(rel);
    if (!existsSync(path)) {
      failures.push(`missing artifact: ${rel} (expected at ${path})`);
      continue;
    }
    const { size } = statSync(path);
    if (size === 0) {
      failures.push(`empty artifact: ${rel}`);
      continue;
    }
    notes.push(`  ok  ${rel} (${size} bytes)`);
  }
}

function checkContentMarkers() {
  for (const { file, marker, what } of CONTENT_MARKERS) {
    const path = abs(file);
    if (!existsSync(path)) continue; // already reported by checkExistsAndNonEmpty
    if (!readFileSync(path, 'utf-8').includes(marker)) {
      failures.push(`${file} does not contain ${what} (looked for ${JSON.stringify(marker)})`);
    }
  }
}

/**
 * Walk every path-valued field in package.json and confirm it resolves.
 * A dangling `exports` target is invisible until a consumer imports it.
 */
function checkPackageEntryPoints() {
  const declared = new Map();
  for (const field of ['main', 'module', 'types']) {
    if (typeof pkg[field] === 'string') declared.set(`"${field}"`, pkg[field]);
  }

  const walkExports = (node, trail) => {
    if (typeof node === 'string') {
      declared.set(trail, node);
      return;
    }
    if (node && typeof node === 'object') {
      for (const [key, value] of Object.entries(node)) walkExports(value, `${trail}.${key}`);
    }
  };
  walkExports(pkg.exports ?? {}, '"exports"');

  for (const [label, rel] of declared) {
    if (!rel.startsWith('./')) {
      failures.push(`${label} must be a relative ./ path, got ${rel}`);
      continue;
    }
    if (!existsSync(abs(rel))) failures.push(`${label} points at a missing file: ${rel}`);
  }
  notes.push(`  ok  package.json entry points (${declared.size} declared paths resolve)`);
}

/**
 * Confirm the tarball npm would actually build contains the runtime outputs.
 * `files: ["dist", "src"]` plus ignore rules can silently drop artifacts.
 */
function checkPackManifest() {
  let raw;
  try {
    raw = execFileSync(
      'npm',
      ['pack', '--dry-run', '--json', '--ignore-scripts'],
      { cwd: PKG_ROOT, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] },
    );
  } catch (error) {
    failures.push(`\`npm pack --dry-run --json\` failed: ${error.message}`);
    return;
  }

  let manifest;
  try {
    manifest = JSON.parse(raw);
  } catch {
    failures.push('could not parse `npm pack --dry-run --json` output as JSON');
    return;
  }

  const packed = new Set((manifest[0]?.files ?? []).map((f) => f.path));
  if (packed.size === 0) {
    failures.push('`npm pack --dry-run` reported an empty file list');
    return;
  }

  for (const rel of REQUIRED_FILES) {
    if (!packed.has(rel)) failures.push(`npm tarball omits ${rel} — check the "files" field and .gitignore/.npmignore`);
  }
  notes.push(`  ok  npm tarball contains all ${REQUIRED_FILES.length} required artifacts (${packed.size} files packed)`);
}

function checkSizeBudgets() {
  for (const { file, maxKb } of SIZE_BUDGETS) {
    const path = abs(file);
    if (!existsSync(path)) continue; // already reported
    const gzipped = kb(gzipSync(readFileSync(path), { level: 9 }).length);
    if (gzipped > maxKb) {
      failures.push(`${file} is ${gzipped.toFixed(1)} KB gzipped, over the ${maxKb} KB budget`);
    } else {
      notes.push(`  ok  ${file} ${gzipped.toFixed(1)} KB gzipped (budget ${maxKb} KB)`);
    }
  }
}

checkExistsAndNonEmpty();
checkContentMarkers();
checkPackageEntryPoints();
checkPackManifest();
checkSizeBudgets();

console.log(`@aether/web v${pkg.version} — package artifact verification`);
for (const note of notes) console.log(note);

if (failures.length > 0) {
  console.error(`\nFAILED: ${failures.length} artifact problem(s):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  console.error('\nRun `npm run build` first, then re-run `npm run verify:artifacts`.');
  process.exit(1);
}

console.log(`\nOK: all ${REQUIRED_FILES.length} required artifacts present and within budget.`);
