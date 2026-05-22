// =============================================================================
// Tests: BitcoinProvider — wallet detection, address type, connect
// =============================================================================
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BitcoinProvider } from '../src/web3/providers/bitcoin-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestBTCProvider extends BitcoinProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeBTCProvider = () => ({
  requestAccounts: vi.fn().mockResolvedValue(['bc1qfakeaddress']),
  getAccounts: vi.fn().mockResolvedValue(['bc1qfakeaddress']),
  on: vi.fn(),
  removeListener: vi.fn(),
});

describe('BitcoinProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns unisat when window.unisat is present', () => {
    vi.stubGlobal('window', { unisat: makeBTCProvider() });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('unisat');
  });

  it('returns xverse when window.xverse.bitcoin is present', () => {
    vi.stubGlobal('window', { xverse: { bitcoin: makeBTCProvider() } });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('xverse');
  });

  it('returns leather when window.LeatherProvider is present', () => {
    vi.stubGlobal('window', { LeatherProvider: makeBTCProvider() });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('leather');
  });

  it('returns okx when window.okxwallet.bitcoin is present', () => {
    vi.stubGlobal('window', { okxwallet: { bitcoin: makeBTCProvider() } });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('okx');
  });

  it('returns bitget when window.bitkeep.bitcoin is present', () => {
    vi.stubGlobal('window', { bitkeep: { bitcoin: makeBTCProvider() } });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('bitget');
  });

  it('returns bitcoin as fallback when no known wallet', () => {
    vi.stubGlobal('window', {});
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('bitcoin');
  });

  it('unisat takes priority over xverse when both present', () => {
    vi.stubGlobal('window', {
      unisat: makeBTCProvider(),
      xverse: { bitcoin: makeBTCProvider() },
    });
    const p = new TestBTCProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('unisat');
  });
});

describe('BitcoinProvider — connect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=bitcoin', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new BitcoinProvider(cbs);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    p.connect('bc1qfakeaddress', { type: 'unisat' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'bitcoin' }));
  });

  it('preserves Bitcoin address casing (not lowercased)', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new BitcoinProvider(cbs);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    p.connect('bc1qABCDEF', { type: 'unisat' });
    // Bitcoin addresses must not be lowercased
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ address: 'bc1qABCDEF' }));
  });

  it('connect includes addressType in event payload', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new BitcoinProvider(cbs);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    p.connect('bc1qfakeaddress', { type: 'unisat' });
    // The second call (the override) should have addressType
    const calls = cbs.onWalletEvent.mock.calls;
    const connectCalls = calls.filter((c) => c[0] === 'connect');
    const hasAddressType = connectCalls.some((c) => (c[1] as Record<string, unknown>).addressType !== undefined);
    expect(hasAddressType).toBe(true);
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new BitcoinProvider(cbs);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    p.connect('bc1qfakeaddress', { type: 'unisat' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'bitcoin' }));
  });
});
