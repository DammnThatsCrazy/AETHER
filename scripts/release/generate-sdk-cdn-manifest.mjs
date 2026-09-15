#!/usr/bin/env node
// =============================================================================
// Aether SDK — CDN RELEASE LAYOUT + MANIFEST GENERATOR
//
// Stages the exact tree that gets synced to the SDK CDN bucket and emits the
// version manifests the CDN auto-loader reads at runtime.
//
// Inputs:  packages/web/dist/ (run `npm run build --workspace=packages/web`)
// Outputs: artifacts/sdk/cdn/... (gitignored; synced to the bucket by CI)
//
// TWO HASH FORMATS, ON PURPOSE — do not "simplify" these into one:
//
//   downloads.*Hash  bare lowercase hex SHA-256. aether-loader.ts computes
//                    exactly this (`_sha256` hex-encodes the digest) and
//                    compares with `!==`. A `sha256-` prefix here breaks every
//                    bundle fetch in the field.
//   integrity.sri    `sha384-<base64>` Subresource Integrity, for a
//                    `<script integrity="...">` attribute in HTML.
//
// Version authority is packages/web/package.json. The major-version CDN path is
// derived from it, never hand-written, so a version bump cannot leave the CDN
// layout behind.
// =============================================================================

import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const WEB = join(ROOT, 'packages', 'web');
const DIST = join(WEB, 'dist');
const OUT = join(ROOT, 'artifacts', 'sdk', 'cdn');

const pkg = JSON.parse(readFileSync(join(WEB, 'package.json'), 'utf-8'));
const VERSION = pkg.version;
const MAJOR = VERSION.split('.')[0];

/** CDN base for the URLs recorded in the manifest. */
const CDN_BASE = 'https://cdn.aether.network';

/**
 * Minimum supported SDK version, read from the ingestion compatibility bands so
 * the manifest cannot advertise a floor the backend does not honour.
 */
function readMinimumSupportedVersion() {
  const source = readFileSync(
    join(ROOT, 'services', 'backend', 'services', 'ingestion', 'sdk_version_tiers.py'),
    'utf-8',
  );
  // The `supported` band is the first block whose id is "supported".
  const band = source.match(/id="supported"[\s\S]*?min_version="([^"]+)"/);
  if (!band) {
    throw new Error('could not read the `supported` band min_version from sdk_version_tiers.py');
  }
  return band[1];
}

/** Contract schema version, from its canonical shared source. */
function readContractSchemaVersion() {
  const source = readFileSync(join(ROOT, 'packages', 'shared', 'schema-version.ts'), 'utf-8');
  const match = source.match(/CONTRACT_SCHEMA_VERSION = '([^']+)'/);
  if (!match) throw new Error('could not read CONTRACT_SCHEMA_VERSION from packages/shared/schema-version.ts');
  return match[1];
}

const sha256Hex = (buf) => createHash('sha256').update(buf).digest('hex');
const sri384 = (buf) => `sha384-${createHash('sha384').update(buf).digest('base64')}`;

/** Build outputs are not committed; a missing one means "build first". */
function readArtifact(rel) {
  const path = join(DIST, rel);
  try {
    const buf = readFileSync(path);
    if (buf.length === 0) throw new Error('file is empty');
    return buf;
  } catch (error) {
    throw new Error(
      `cannot read ${rel} from packages/web/dist (${error.message}). ` +
        'Run `npm run build --workspace=packages/web` first.',
    );
  }
}

function write(rel, contents) {
  const path = join(OUT, rel);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, contents);
}

// --- 1. Read the build outputs ----------------------------------------------
const loaderJs = readArtifact('loader.js');
const loaderMjs = readArtifact('loader.mjs');
const umd = readArtifact('aether.umd.js');
const esm = readArtifact('aether.esm.js');

const loaderSha = sha256Hex(loaderJs);
const umdSha = sha256Hex(umd);

// --- 2. Stage the CDN tree ---------------------------------------------------
// Rebuilt from scratch so a removed artifact cannot linger from a prior run.
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

// Stable bootstrap — the one URL quickstarts paste. Short-cached by CI.
write('v1.js', loaderJs);

// Major-version loader — what a pinned-but-tracked install uses.
write(`sdk/v${MAJOR}/loader.js`, loaderJs);
write(`sdk/v${MAJOR}/loader.mjs`, loaderMjs);
write(`sdk/v${MAJOR}/aether.umd.js`, umd);

// Version-pinned bundles — immutable, long-cached.
write(`sdk/${VERSION}/web/loader.js`, loaderJs);
write(`sdk/${VERSION}/web/loader.mjs`, loaderMjs);
write(`sdk/${VERSION}/web/aether.umd.js`, umd);
write(`sdk/${VERSION}/web/aether.esm.js`, esm);

// Source maps are deliberately NOT published to the CDN: they ship in the npm
// tarball for local debugging and stay off the public origin.

// --- 3. Emit the manifests ---------------------------------------------------
const manifest = {
  platform: 'web',
  latestVersion: VERSION,
  minimumVersion: readMinimumSupportedVersion(),
  major: Number(MAJOR),
  generatedAt: new Date().toISOString(),
  updateUrgency: 'none',
  checkIntervalMs: 3600000,
  downloads: {
    loaderUrl: `${CDN_BASE}/v1.js`,
    // Bare hex SHA-256 — matched byte-for-byte by aether-loader.ts `_sha256`.
    loaderHash: loaderSha,
    sdkBundleUrl: `${CDN_BASE}/sdk/${VERSION}/web/aether.umd.js`,
    sdkBundleHash: umdSha,
    sdkBundleSize: umd.length,
  },
  integrity: {
    sri: sri384(umd),
  },
  compatibility: {
    served: true,
    tier: 'supported',
    contractSchemaVersion: readContractSchemaVersion(),
  },
};

const manifestJson = `${JSON.stringify(manifest, null, 2)}\n`;
write('sdk/manifests/web/latest.json', manifestJson);
write(`sdk/manifests/web/${VERSION}.json`, manifestJson);

console.log(`Staged CDN layout for @aether/web v${VERSION} (major v${MAJOR})`);
console.log(`  ${CDN_BASE}/v1.js`);
console.log(`  ${CDN_BASE}/sdk/v${MAJOR}/loader.js`);
console.log(`  ${manifest.downloads.sdkBundleUrl}`);
console.log(`  ${CDN_BASE}/sdk/manifests/web/latest.json`);
console.log(`  minimumVersion=${manifest.minimumVersion} contractSchema=${manifest.compatibility.contractSchemaVersion}`);
