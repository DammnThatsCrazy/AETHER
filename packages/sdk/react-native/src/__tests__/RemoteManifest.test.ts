import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.mock() is hoisted; capture the native mock via vi.hoisted().
const { nativeFlags } = vi.hoisted(() => ({
  nativeFlags: {
    initialize: vi.fn(),
    isEnabled: vi.fn(),
    getFlag: vi.fn(),
    getValue: vi.fn(),
    getAllFlags: vi.fn(),
    setOverride: vi.fn(),
    clearOverride: vi.fn(),
    refresh: vi.fn(),
    destroy: vi.fn(),
  },
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherFeatureFlags: nativeFlags },
  NativeEventEmitter: class {},
  Platform: { OS: 'ios' },
}));

import {
  applyManifest,
  getManifest,
  getSamplingRate,
  getEndpointOverride,
  fetchAndApplyManifest,
  _resetManifest,
} from '../modules/RemoteManifest';

describe('RemoteManifest (RN JS-side apply)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetManifest();
  });

  it('stores the manifest and pushes flags/features into RNFeatureFlags', () => {
    applyManifest({
      flags: { ff_new_ui: true },
      features: { beta: false },
      endpoints: { ingest: 'https://ingest.eu.aether.io' },
      rollout_percentage: 25,
    });
    expect(nativeFlags.setOverride).toHaveBeenCalledWith('ff_new_ui', true);
    expect(nativeFlags.setOverride).toHaveBeenCalledWith('beta', false);
    expect(getManifest()?.rollout_percentage).toBe(25);
    expect(getSamplingRate()).toBeCloseTo(0.25);
    expect(getEndpointOverride('ingest')).toBe('https://ingest.eu.aether.io');
  });

  it('getSamplingRate defaults to 1 when rollout is unset', () => {
    expect(getSamplingRate()).toBe(1);
  });

  it('ignores non-object input without crashing or applying', () => {
    applyManifest(null);
    applyManifest(undefined);
    expect(nativeFlags.setOverride).not.toHaveBeenCalled();
    expect(getManifest()).toBeNull();
  });

  it('fetchAndApplyManifest unwraps the APIResponse data envelope and applies', async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ data: { flags: { ff_x: true }, rollout_percentage: 50 } }),
    })) as unknown as typeof fetch;

    await fetchAndApplyManifest('https://api.test', 'key');
    expect(nativeFlags.setOverride).toHaveBeenCalledWith('ff_x', true);
    expect(getSamplingRate()).toBeCloseTo(0.5);
  });

  describe('with a verifier (manifestPublicKey configured)', () => {
    const serve = (data: unknown) => {
      globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ data }) })) as unknown as typeof fetch;
    };

    it('applies a manifest the verifier accepts, passing it the unwrapped manifest', async () => {
      const manifest = { flags: { ff_signed: true }, rollout_percentage: 25 };
      serve(manifest);
      const verify = vi.fn(async () => true);
      await fetchAndApplyManifest('https://api.test', 'key', verify);
      expect(verify).toHaveBeenCalledWith(manifest);
      expect(nativeFlags.setOverride).toHaveBeenCalledWith('ff_signed', true);
      expect(getSamplingRate()).toBeCloseTo(0.25);
    });

    it('does not apply a manifest the verifier rejects (fail closed)', async () => {
      serve({ flags: { ff_forged: true }, rollout_percentage: 0 });
      await fetchAndApplyManifest('https://api.test', 'key', async () => false);
      expect(nativeFlags.setOverride).not.toHaveBeenCalled();
      expect(getManifest()).toBeNull();
      expect(getSamplingRate()).toBe(1);
    });

    it('does not apply when the verifier throws', async () => {
      serve({ flags: { ff_x: true } });
      await expect(
        fetchAndApplyManifest('https://api.test', 'key', async () => { throw new Error('native unavailable'); }),
      ).resolves.toBeUndefined();
      expect(nativeFlags.setOverride).not.toHaveBeenCalled();
      expect(getManifest()).toBeNull();
    });

    it('applies unverified when no verifier is configured', async () => {
      serve({ flags: { ff_open: true } });
      await fetchAndApplyManifest('https://api.test', 'key');
      expect(nativeFlags.setOverride).toHaveBeenCalledWith('ff_open', true);
    });
  });

  it('fetchAndApplyManifest is non-fatal on network failure', async () => {
    globalThis.fetch = vi.fn(async () => { throw new Error('network down'); }) as unknown as typeof fetch;
    await expect(fetchAndApplyManifest('https://api.test', 'key')).resolves.toBeUndefined();
    expect(getManifest()).toBeNull();
  });
});
