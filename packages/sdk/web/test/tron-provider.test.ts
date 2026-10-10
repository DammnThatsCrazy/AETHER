// =============================================================================
// Tests: TronProvider — wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TronProvider } from '../src/web3/providers/tron-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestTronProvider extends TronProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeTronWeb = () => ({
  defaultAddress: { base58: 'TFakeAddress123' },
  trx: { getBalance: vi.fn().mockResolvedValue(0) },
});

describe('TronProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  const makeWindow = (extra: Record<string, unknown> = {}) => ({
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    ...extra,
  });

  it('returns tronlink for window.tronLink', () => {
    vi.stubGlobal('window', makeWindow({ tronLink: { tronWeb: makeTronWeb() } }));
    const p = new TestTronProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('tronlink');
  });

  it('returns bitget_tron for window.bitkeep.tronLink', () => {
    const tronWeb = makeTronWeb();
    vi.stubGlobal('window', makeWindow({ bitkeep: { tronLink: { tronWeb } } }));
    const p = new TestTronProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('bitget_tron');
  });

  it('does not throw when no tron provider exists', () => {
    vi.stubGlobal('window', makeWindow());
    const p = new TestTronProvider(makeCallbacks());
    expect(() => p.init()).not.toThrow();
    expect(p.testDetectWalletType()).toBe('tronlink'); // default
  });
});

describe('TronProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=tvm', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new TronProvider(cbs);
    p.connect('TFakeAddress123', { type: 'tronlink' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'tvm' }));
  });
});
