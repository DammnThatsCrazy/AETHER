import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  canonicalJson,
  ManifestCanonicalizationError,
  verifyManifestSignature,
} from '../src/health/manifest-signature';
import { SDKHealthAgent } from '../src/health/sdk-health-agent';

// Shared with the backend, iOS and Android suites: docs/reference/sdks/manifest-signing.md
const vectors = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../tests/fixtures/sdk/manifest-signing-vectors.json'), 'utf8'),
) as {
  public_key_spki_b64url: string;
  other_public_key_spki_b64url: string;
  canonical: { name: string; input_json: string; canonical: string }[];
  rejected_inputs: { name: string; input_json: string }[];
  manifests: { name: string; valid: boolean; why: string; manifest_json: string }[];
};

describe('manifest canonical JSON (shared vectors)', () => {
  for (const c of vectors.canonical) {
    it(`canonicalizes ${c.name}`, () => {
      expect(canonicalJson(JSON.parse(c.input_json))).toBe(c.canonical);
    });
  }

  for (const r of vectors.rejected_inputs) {
    it(`rejects ${r.name}`, () => {
      expect(() => canonicalJson(JSON.parse(r.input_json))).toThrow(ManifestCanonicalizationError);
    });
  }
});

describe('manifest signature verification (shared vectors)', () => {
  for (const m of vectors.manifests) {
    it(`${m.valid ? 'accepts' : 'rejects'} ${m.name} — ${m.why}`, async () => {
      const manifest = JSON.parse(m.manifest_json) as Record<string, unknown>;
      expect(await verifyManifestSignature(manifest, vectors.public_key_spki_b64url)).toBe(m.valid);
    });
  }

  it('rejects a valid manifest under a different public key', async () => {
    const good = vectors.manifests.find((m) => m.name === 'valid_full_manifest')!;
    const manifest = JSON.parse(good.manifest_json) as Record<string, unknown>;
    expect(await verifyManifestSignature(manifest, vectors.other_public_key_spki_b64url)).toBe(false);
  });

  it('rejects a malformed public key instead of throwing', async () => {
    const good = vectors.manifests.find((m) => m.name === 'valid_full_manifest')!;
    const manifest = JSON.parse(good.manifest_json) as Record<string, unknown>;
    expect(await verifyManifestSignature(manifest, 'not-a-key')).toBe(false);
  });

  it('fails closed when WebCrypto is unavailable', async () => {
    const good = vectors.manifests.find((m) => m.name === 'valid_full_manifest')!;
    const manifest = JSON.parse(good.manifest_json) as Record<string, unknown>;
    vi.stubGlobal('crypto', undefined);
    try {
      expect(await verifyManifestSignature(manifest, vectors.public_key_spki_b64url)).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('SDKHealthAgent manifest verification', () => {
  const originalFetch = globalThis.fetch;
  const fakeQueue = { size: 0 } as unknown as import('../src/core/event-queue').EventQueue;
  const manifestBody = (name: string) =>
    JSON.parse(vectors.manifests.find((m) => m.name === name)!.manifest_json);

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function agentServing(body: unknown, manifestPublicKey?: string) {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ data: body }),
    })) as unknown as typeof fetch;
    return new SDKHealthAgent(
      { endpoint: 'https://api.test', apiKey: 'k', sdkId: 'web_test', manifestPublicKey },
      fakeQueue,
    );
  }

  it('applies a correctly signed manifest', async () => {
    const agent = agentServing(manifestBody('valid_full_manifest'), vectors.public_key_spki_b64url);
    const applied = vi.fn();
    agent.onManifestUpdate(applied);
    expect((await agent.fetchManifest())?.manifest_version).toBe('42');
    expect(applied).toHaveBeenCalledTimes(1);
  });

  it.each(['tampered_endpoint', 'tampered_rollout', 'downgraded_alg', 'missing_signature', 'signed_by_other_key'])(
    'rejects %s and keeps the last known-good config',
    async (name) => {
      const agent = agentServing(manifestBody(name), vectors.public_key_spki_b64url);
      const applied = vi.fn();
      agent.onManifestUpdate(applied);
      vi.spyOn(console, 'warn').mockImplementation(() => {});
      expect(await agent.fetchManifest()).toBeNull();
      expect(applied).not.toHaveBeenCalled();
    },
  );

  it('applies manifests unverified when no public key is configured', async () => {
    const agent = agentServing(manifestBody('tampered_endpoint'));
    const applied = vi.fn();
    agent.onManifestUpdate(applied);
    expect(await agent.fetchManifest()).not.toBeNull();
    expect(applied).toHaveBeenCalledTimes(1);
  });
});
