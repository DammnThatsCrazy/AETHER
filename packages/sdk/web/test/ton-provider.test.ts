// =============================================================================
// Tests: TonProvider — wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TonProvider } from '../src/web3/providers/ton-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestTonProvider extends TonProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeTONProvider = () => ({
  send: vi.fn().mockResolvedValue(undefined),
  listen: vi.fn(),
  account: null,
});

describe('TonProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns tonkeeper for window.tonkeeper', () => {
    const w = makeTONProvider();
    vi.stubGlobal('window', { tonkeeper: w });
    const p = new TestTonProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('tonkeeper');
  });

  it('returns ton_wallet for window.ton', () => {
    const w = makeTONProvider();
    vi.stubGlobal('window', { ton: w });
    const p = new TestTonProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('ton_wallet');
  });

  it('returns tonconnect for window.__tc_bridge (TonConnect/Telegram WebApp)', () => {
    const w = makeTONProvider();
    vi.stubGlobal('window', { __tc_bridge: w });
    const p = new TestTonProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('tonconnect');
  });

  it('tonkeeper takes priority over window.ton', () => {
    const tonkeeper = makeTONProvider();
    const ton = makeTONProvider();
    vi.stubGlobal('window', { tonkeeper, ton });
    const p = new TestTonProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('tonkeeper');
  });

  it('does not init when no TON provider present', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new TestTonProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('TonProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=ton', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new TonProvider(cbs);
    p.connect('EQFakeAddress', { type: 'tonkeeper' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'ton' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new TonProvider(cbs);
    p.connect('EQFakeAddress', { type: 'tonkeeper' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'ton' }));
  });
});
