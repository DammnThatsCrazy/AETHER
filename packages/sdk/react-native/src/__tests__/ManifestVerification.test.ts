// Manifest signature verification (§2.9) on React Native. Hermes has no WebCrypto,
// so the JS manifest path delegates to the native ES256 verifier shared with the
// iOS and Android SDKs (docs/reference/sdks/manifest-signing.md). The bridge must
// fail closed whenever that verifier is unavailable or errors.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { nativeMethods } = vi.hoisted(() => ({
  nativeMethods: {
    initialize: vi.fn(),
    verifyManifest: vi.fn(),
  } as Record<string, unknown>,
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherNative: nativeMethods },
  NativeEventEmitter: class {
    addListener = vi.fn(() => ({ remove: vi.fn() }));
  },
  Platform: { OS: 'ios', Version: '17.0' },
  Dimensions: { get: vi.fn(() => ({ width: 390, height: 844 })) },
}));

import Aether from '../bridge';

const manifest = { manifest_version: '42', signature_alg: 'ecdsa-p256-sha256', signature: 'sig' };

describe('Aether RN bridge — manifest signature verification', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nativeMethods.verifyManifest = vi.fn();
  });

  it('advertises the capability', () => {
    expect(Aether.capabilities.manifestSignatureVerification).toBe(true);
  });

  it('forwards manifestPublicKey to the native initializer', () => {
    Aether.init({ apiKey: 'k', manifestPublicKey: 'PUBKEY' });
    expect(nativeMethods.initialize).toHaveBeenCalledWith(expect.objectContaining({ manifestPublicKey: 'PUBKEY' }));
  });

  it('sends the manifest as JSON text with the key to the native verifier', async () => {
    (nativeMethods.verifyManifest as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    expect(await Aether.verifyManifest(manifest, 'PUBKEY')).toBe(true);
    expect(nativeMethods.verifyManifest).toHaveBeenCalledWith(JSON.stringify(manifest), 'PUBKEY');
  });

  it('returns false when the native verifier rejects the manifest', async () => {
    (nativeMethods.verifyManifest as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    expect(await Aether.verifyManifest(manifest, 'PUBKEY')).toBe(false);
  });

  it('fails closed when the native verifier throws', async () => {
    (nativeMethods.verifyManifest as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    expect(await Aether.verifyManifest(manifest, 'PUBKEY')).toBe(false);
  });

  it('fails closed when the native module has no verifyManifest (older native build)', async () => {
    delete nativeMethods.verifyManifest;
    expect(await Aether.verifyManifest(manifest, 'PUBKEY')).toBe(false);
  });

  it('only accepts a literal true from native, never a truthy value', async () => {
    (nativeMethods.verifyManifest as ReturnType<typeof vi.fn>).mockResolvedValue('yes');
    expect(await Aether.verifyManifest(manifest, 'PUBKEY')).toBe(false);
  });
});
