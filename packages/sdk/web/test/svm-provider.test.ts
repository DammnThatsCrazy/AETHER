// =============================================================================
// Tests: SVMProvider — wallet detection, connect/disconnect
// =============================================================================
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SVMProvider } from '../src/web3/providers/svm-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

// Expose protected detectWalletType
class TestSVMProvider extends SVMProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeSolanaProvider = (flags: Record<string, boolean> = {}) => ({
  ...flags,
  isConnected: false,
  connect: vi.fn().mockResolvedValue({ publicKey: { toString: () => 'FakePublicKey123' } }),
  disconnect: vi.fn().mockResolvedValue(undefined),
  on: vi.fn(),
  off: vi.fn(),
});

describe('SVMProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns phantom when provider has isPhantom', () => {
    const mockProvider = makeSolanaProvider({ isPhantom: true });
    vi.stubGlobal('window', { phantom: { solana: mockProvider } });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('phantom');
  });

  it('returns solflare when provider has isSolflare', () => {
    const mockProvider = makeSolanaProvider({ isSolflare: true });
    vi.stubGlobal('window', { solflare: mockProvider });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('solflare');
  });

  it('returns backpack when provider has isBackpack', () => {
    const mockProvider = makeSolanaProvider({ isBackpack: true });
    vi.stubGlobal('window', { backpack: { solana: mockProvider } });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('backpack');
  });

  it('returns glow when provider has isGlow', () => {
    const mockProvider = makeSolanaProvider({ isGlow: true });
    vi.stubGlobal('window', { glow: mockProvider });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('glow');
  });

  it('returns nightly when provider has isNightly', () => {
    const mockProvider = makeSolanaProvider({ isNightly: true });
    vi.stubGlobal('window', { nightly: { solana: mockProvider } });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('nightly');
  });

  it('returns brave via isBraveWallet flag', () => {
    const mockProvider = makeSolanaProvider({ isBraveWallet: true });
    vi.stubGlobal('window', { braveSolana: mockProvider });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('brave');
  });

  it('returns coin98 via isCoin98 flag', () => {
    const mockProvider = makeSolanaProvider({ isCoin98: true });
    vi.stubGlobal('window', { coin98: { sol: mockProvider } });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('coin98');
  });

  it('returns exodus via isExodus flag', () => {
    const mockProvider = makeSolanaProvider({ isExodus: true });
    vi.stubGlobal('window', { exodus: { solana: mockProvider } });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('exodus');
  });

  it('returns solana for generic provider without known flags', () => {
    const mockProvider = makeSolanaProvider();
    vi.stubGlobal('window', { solana: mockProvider });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('solana');
  });

  it('returns unknown when no provider is set', () => {
    vi.stubGlobal('window', {});
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('unknown');
  });

  it('phantom takes priority over solana fallback', () => {
    const phantom = makeSolanaProvider({ isPhantom: true });
    const solana = makeSolanaProvider();
    vi.stubGlobal('window', { phantom: { solana: phantom }, solana });
    const p = new TestSVMProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('phantom');
  });
});

describe('SVMProvider — connect / disconnect / transaction', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('connect emits onWalletEvent with vm=svm', () => {
    const cbs = makeCallbacks();
    vi.stubGlobal('window', {});
    const p = new SVMProvider(cbs);
    p.connect('FakePublicKey123', { type: 'phantom' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'svm' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    const cbs = makeCallbacks();
    vi.stubGlobal('window', {});
    const p = new SVMProvider(cbs);
    p.connect('FakePublicKey123', { type: 'phantom' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'svm' }));
  });

  it('transaction emits onTransaction with pending status', () => {
    vi.useFakeTimers();
    const cbs = makeCallbacks();
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    const p = new SVMProvider(cbs);
    p.connect('FakeKey', { type: 'phantom' });
    p.transaction('sig123', { vm: 'svm' });
    expect(cbs.onTransaction).toHaveBeenCalledWith(
      'sig123',
      expect.objectContaining({ vm: 'svm', status: 'pending' }),
    );
    vi.unstubAllGlobals();
  });
});
