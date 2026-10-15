// =============================================================================
// Tests: CosmosProvider — wallet detection, multi-chain support
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CosmosProvider } from '../src/web3/providers/cosmos-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestCosmosProvider extends CosmosProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeKeplr = () => ({
  enable: vi.fn().mockResolvedValue(undefined),
  getKey: vi.fn().mockResolvedValue({ bech32Address: 'cosmos1fake', name: 'test', algo: 'secp256k1', pubKey: new Uint8Array() }),
  experimentalSuggestChain: vi.fn(),
});

describe('CosmosProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns keplr for window.keplr', () => {
    vi.stubGlobal('window', { keplr: makeKeplr() });
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('keplr');
  });

  it('returns leap for window.leap', () => {
    vi.stubGlobal('window', { leap: makeKeplr() });
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('leap');
  });

  it('returns cosmostation for window.cosmostation', () => {
    vi.stubGlobal('window', { cosmostation: { providers: { keplr: makeKeplr() } } });
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('cosmostation');
  });

  it('returns station for window.station', () => {
    vi.stubGlobal('window', { station: makeKeplr() });
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('station');
  });

  it('returns cosmos as fallback when no wallet detected', () => {
    vi.stubGlobal('window', {});
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('cosmos');
  });

  it('keplr takes priority over leap when both present', () => {
    vi.stubGlobal('window', {
      keplr: makeKeplr(), leap: makeKeplr(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    });
    const p = new TestCosmosProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('keplr');
  });
});

describe('CosmosProvider — multi-chain config', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('accepts custom supportedChains in config', async () => {
    const keplr = makeKeplr();
    const addEventListener = vi.fn();
    vi.stubGlobal('window', { keplr, addEventListener, removeEventListener: vi.fn() });
    const cbs = makeCallbacks();
    const p = new CosmosProvider(cbs, {
      supportedChains: ['cosmoshub-4', 'osmosis-1'],
    });
    p.init();
    // Wait until the full async chain completes (addEventListener called last in setupProvider)
    await vi.waitFor(() => expect(addEventListener).toHaveBeenCalledWith('keplr_keystorechange', expect.any(Function)));
    expect(keplr.enable).toHaveBeenCalledWith(['cosmoshub-4', 'osmosis-1']);
  });

  it('uses default chains when no config provided', async () => {
    const keplr = makeKeplr();
    const addEventListener = vi.fn();
    vi.stubGlobal('window', { keplr, addEventListener, removeEventListener: vi.fn() });
    const cbs = makeCallbacks();
    const p = new CosmosProvider(cbs);
    p.init();
    // Wait until the full async chain completes (addEventListener called last in setupProvider)
    await vi.waitFor(() => expect(addEventListener).toHaveBeenCalledWith('keplr_keystorechange', expect.any(Function)));
    const enabledChains = keplr.enable.mock.calls[0][0] as string[];
    expect(Array.isArray(enabledChains)).toBe(true);
    expect(enabledChains.length).toBeGreaterThan(0);
  });
});

describe('CosmosProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=cosmos', () => {
    vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn() });
    const cbs = makeCallbacks();
    const p = new CosmosProvider(cbs);
    p.connect('cosmos1fake', { type: 'keplr' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'cosmos' }));
  });
});
