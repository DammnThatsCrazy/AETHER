#!/usr/bin/env node
// =============================================================================
// Aether SDK — CDN RELEASE LAYOUT VERIFICATION
//
// Validates the staged tree in artifacts/sdk/cdn/ before anything is uploaded.
// Publishing a manifest whose hashes do not match the bytes it points at is
// worse than publishing nothing: every client that trusts the hash rejects the
// bundle and the failure surfaces as a silent install failure in the field.
//
// Run after scripts/release/generate-sdk-cdn-manifest.mjs.
// =============================================================================

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const OUT = join(ROOT, 'artifacts', 'sdk', 'cdn');
const CDN_BASE = 'https://cdn.aether.network';

const pkg = JSON.parse(readFileSync(join(ROOT, 'packages', 'web', 'package.json'), 'utf-8'));
const VERSION = pkg.version;
const MAJOR = VERSION.split('.')[0];

const failures = [];
const notes = [];
const fail = (msg) => failures.push(msg);

const sha256Hex = (buf) => createHash('sha256').update(buf).digest('hex');
const sri384 = (buf) => `sha384-${createHash('sha384').update(buf).digest('base64')}`;

/** Map a manifest URL back to its path inside the staged layout. */
function layoutPathForUrl(url) {
  if (!url.startsWith(`${CDN_BASE}/`)) return null;
  return join(OUT, url.slice(CDN_BASE.length + 1));
}

function readLayoutFile(abs, label) {
  if (!existsSync(abs)) {
    fail(`missing from CDN layout: ${label} (${relative(ROOT, abs)})`);
    return null;
  }
  const { size } = statSync(abs);
  if (size === 0) {
    fail(`empty file in CDN layout: ${label}`);
    return null;
  }
  return readFileSync(abs);
}

// --- 1. Every declared path exists ------------------------------------------
const REQUIRED_LAYOUT = [
  'v1.js',
  `sdk/v${MAJOR}/loader.js`,
  `sdk/v${MAJOR}/loader.mjs`,
  `sdk/v${MAJOR}/aether.umd.js`,
  `sdk/${VERSION}/web/loader.js`,
  `sdk/${VERSION}/web/loader.mjs`,
  `sdk/${VERSION}/web/aether.umd.js`,
  `sdk/${VERSION}/web/aether.esm.js`,
  'sdk/manifests/web/latest.json',
  `sdk/manifests/web/${VERSION}.json`,
];

for (const rel of REQUIRED_LAYOUT) {
  const buf = readLayoutFile(join(OUT, rel), rel);
  if (buf) notes.push(`  ok  ${rel} (${buf.length} bytes)`);
}

if (failures.length > 0) {
  // The manifest checks below would cascade into noise without the tree.
  console.error('CDN layout verification failed:');
  for (const f of failures) console.error(`  - ${f}`);
  console.error('\nRun `node scripts/release/generate-sdk-cdn-manifest.mjs` first.');
  process.exit(1);
}

// --- 2. The three loader placements must be byte-identical -------------------
// They are the same bootstrap served from three URLs; a divergence means one
// path silently serves a different loader than the others.
const loaderJs = readFileSync(join(OUT, 'v1.js'));
for (const rel of [`sdk/v${MAJOR}/loader.js`, `sdk/${VERSION}/web/loader.js`]) {
  if (!readFileSync(join(OUT, rel)).equals(loaderJs)) {
    fail(`${rel} differs from v1.js — the stable and versioned loaders must be identical bytes`);
  }
}
notes.push('  ok  v1.js, major loader, and versioned loader are byte-identical');

// --- 3. No source maps published --------------------------------------------
// Maps ship in the npm tarball; the public CDN origin stays free of them.
const findMaps = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) return findMaps(abs);
    return abs.endsWith('.map') ? [relative(OUT, abs)] : [];
  });
const maps = findMaps(OUT);
if (maps.length > 0) {
  fail(`source maps must not be published to the CDN: ${maps.join(', ')}`);
} else {
  notes.push('  ok  no source maps in the CDN layout');
}

// --- 4. Latest manifest must equal the versioned manifest --------------------
const latestRaw = readFileSync(join(OUT, 'sdk/manifests/web/latest.json'), 'utf-8');
const versionedRaw = readFileSync(join(OUT, `sdk/manifests/web/${VERSION}.json`), 'utf-8');
if (latestRaw !== versionedRaw) {
  fail(`latest.json and ${VERSION}.json differ; they are written as the same document`);
}

let manifest;
try {
  manifest = JSON.parse(latestRaw);
} catch (error) {
  fail(`latest.json is not valid JSON: ${error.message}`);
  console.error('CDN layout verification failed:');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}

// --- 5. Manifest must describe this version and this layout ------------------
if (manifest.latestVersion !== VERSION) {
  fail(`manifest latestVersion ${manifest.latestVersion} != package version ${VERSION}`);
}
if (manifest.major !== Number(MAJOR)) {
  fail(`manifest major ${manifest.major} != package major ${MAJOR} (the CDN major path must track the package)`);
}

const expectedUrls = {
  loaderUrl: `${CDN_BASE}/v1.js`,
  sdkBundleUrl: `${CDN_BASE}/sdk/${VERSION}/web/aether.umd.js`,
};
for (const [field, expected] of Object.entries(expectedUrls)) {
  if (manifest.downloads?.[field] !== expected) {
    fail(`manifest downloads.${field} is ${manifest.downloads?.[field]}, expected ${expected}`);
  }
}

// --- 6. Every URL in the manifest must resolve to a staged file -------------
for (const [field, url] of Object.entries(manifest.downloads ?? {})) {
  if (typeof url !== 'string' || !url.startsWith('http')) continue; // hashes/sizes
  const abs = layoutPathForUrl(url);
  if (!abs) {
    fail(`manifest downloads.${field} (${url}) is outside the CDN base ${CDN_BASE}`);
    continue;
  }
  readLayoutFile(abs, `downloads.${field} -> ${url}`);
}

// --- 7. Hashes must match the bytes they describe ---------------------------
// This is the check that makes publishing safe.
const bundleUrl = manifest.downloads?.sdkBundleUrl;
const loaderUrl = manifest.downloads?.loaderUrl;

if (typeof bundleUrl === 'string' && layoutPathForUrl(bundleUrl)) {
  const buf = readFileSync(layoutPathForUrl(bundleUrl));
  const actual = sha256Hex(buf);

  if (manifest.downloads.sdkBundleHash !== actual) {
    fail(
      `manifest downloads.sdkBundleHash ${manifest.downloads.sdkBundleHash} does not match ` +
        `${relative(ROOT, layoutPathForUrl(bundleUrl))} (${actual})`,
    );
  } else {
    notes.push(`  ok  sdkBundleHash matches aether.umd.js (${actual.slice(0, 16)}…)`);
  }

  if (manifest.downloads.sdkBundleHash?.startsWith('sha256-')) {
    fail(
      'downloads.sdkBundleHash must be bare hex, not SRI-prefixed: aether-loader.ts compares it ' +
        'with `!==` against a bare hex digest, so a prefix breaks every bundle fetch',
    );
  }

  if (manifest.downloads.sdkBundleSize !== buf.length) {
    fail(`manifest sdkBundleSize ${manifest.downloads.sdkBundleSize} != actual ${buf.length}`);
  }

  const expectedSri = sri384(buf);
  if (manifest.integrity?.sri !== expectedSri) {
    fail(`manifest integrity.sri does not match the UMD bundle (expected ${expectedSri})`);
  } else {
    notes.push('  ok  integrity.sri matches the UMD bundle');
  }
}

if (typeof loaderUrl === 'string' && layoutPathForUrl(loaderUrl)) {
  const buf = readFileSync(layoutPathForUrl(loaderUrl));
  const actual = sha256Hex(buf);
  if (manifest.downloads.loaderHash !== actual) {
    fail(`manifest downloads.loaderHash does not match ${loaderUrl} (actual ${actual})`);
  } else {
    notes.push('  ok  loaderHash matches v1.js');
  }
}

// --- 8. The manifest must satisfy the loader's runtime contract --------------
// aether-loader.ts declares SDKManifest and reads these fields directly. A
// manifest that stages cleanly but omits one of them fails in the browser, on
// a customer's page, with no build-time signal — so assert the contract here.
const LOADER_CONTRACT = [
  ['latestVersion', 'string'],
  ['minimumVersion', 'string'],
  ['updateUrgency', 'string'],
  ['checkIntervalMs', 'number'],
  ['generatedAt', 'string'],
  ['downloads.sdkBundleUrl', 'string'],
  ['downloads.sdkBundleHash', 'string'],
  ['downloads.sdkBundleSize', 'number'],
];
const dig = (obj, path) => path.split('.').reduce((acc, key) => acc?.[key], obj);

for (const [path, type] of LOADER_CONTRACT) {
  const value = dig(manifest, path);
  if (value === undefined) {
    fail(`manifest is missing ${path}, which aether-loader.ts reads at runtime`);
  } else if (typeof value !== type) {
    fail(`manifest ${path} is ${typeof value}, aether-loader.ts expects ${type}`);
  }
}

const URGENCY = ['none', 'recommended', 'critical'];
if (!URGENCY.includes(manifest.updateUrgency)) {
  fail(`manifest updateUrgency ${manifest.updateUrgency} is not one of ${URGENCY.join('|')}`);
}
if (typeof manifest.downloads?.sdkBundleHash === 'string' &&
    !/^[0-9a-f]{64}$/.test(manifest.downloads.sdkBundleHash)) {
  fail(
    'manifest downloads.sdkBundleHash is not a bare 64-char hex digest; ' +
      'aether-loader.ts compares it with `!==` and would reject every bundle',
  );
}
if (!failures.some((f) => f.includes('runtime contract') || f.includes('aether-loader.ts reads'))) {
  notes.push('  ok  manifest satisfies the aether-loader.ts SDKManifest contract');
}

// --- Report ------------------------------------------------------------------
for (const note of notes) console.log(note);

if (failures.length > 0) {
  console.error(`\nCDN layout verification failed with ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}

console.log(`\nCDN layout verified for @aether/web v${VERSION}: paths present, manifest hashes match, no maps published.`);
