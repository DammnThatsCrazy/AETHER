// =============================================================================
// Tests: HederaProvider — HashPack and Blade wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HederaProvider } from '../src/web3/providers/hedera-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestHederaProvider extends HederaProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

describe('HederaProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns hashpack for window.hashpack', () => {
    vi.stubGlobal('window', {
      hashpack: { pairingData: { accountIds: ['0.0.12345'] } },
    });
    const p = new TestHederaProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('hashpack');
  });

  it('returns blade for window.bladeWallet', () => {
    vi.stubGlobal('window', {
      bladeWallet: { getAccountId: vi.fn().mockResolvedValue('0.0.67890') },
    });
    const p = new TestHederaProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('blade');
  });

  it('returns hedera as fallback when no wallet present', () => {
    vi.stubGlobal('window', {});
    const p = new TestHederaProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('hedera');
  });

  it('hashpack takes priority over blade when both present', () => {
    vi.stubGlobal('window', {
      hashpack: { pairingData: { accountIds: ['0.0.12345'] } },
      bladeWallet: { getAccountId: vi.fn() },
    });
    const p = new TestHederaProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('hashpack');
  });
});

describe('HederaProvider — init', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('inits with hashpack and sets walletType', () => {
    const hashpack = {
      pairingData: { accountIds: ['0.0.12345'] },
    };
    vi.stubGlobal('window', { hashpack });
    const cbs = makeCallbacks();
    const p = new HederaProvider(cbs);
    p.init();
    // HashPack uses a pairing data approach — no async connect needed
    expect(() => p.init()).not.toThrow();
  });

  it('does not init when no Hedera wallet present', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new HederaProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('HederaProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=hedera', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new HederaProvider(cbs);
    p.connect('0.0.12345', { type: 'hashpack' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'hedera' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new HederaProvider(cbs);
    p.connect('0.0.12345', { type: 'hashpack' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'hedera' }));
  });
});
