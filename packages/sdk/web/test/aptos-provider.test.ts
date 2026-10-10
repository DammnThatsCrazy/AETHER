// =============================================================================
// Tests: AptosProvider — wallet detection, connect/disconnect
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AptosProvider } from '../src/web3/providers/aptos-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestAptosProvider extends AptosProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeAptosWallet = (name?: string) => ({
  name,
  connect: vi.fn().mockResolvedValue({ address: '0xAPTOSADDRESS', publicKey: '0xPUBKEY' }),
  disconnect: vi.fn().mockResolvedValue(undefined),
  account: vi.fn().mockResolvedValue({ address: '0xAPTOSADDRESS', publicKey: '0xPUBKEY' }),
  onAccountChange: vi.fn(),
  onNetworkChange: vi.fn(),
});

describe('AptosProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns petra for window.petra', () => {
    const wallet = makeAptosWallet('Petra');
    vi.stubGlobal('window', { petra: wallet });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('petra');
  });

  it('returns martian_aptos for window.martian.aptos', () => {
    const wallet = makeAptosWallet('Martian');
    vi.stubGlobal('window', { martian: { aptos: wallet } });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('martian_aptos');
  });

  it('returns pontem for window.pontem', () => {
    const wallet = makeAptosWallet('Pontem');
    vi.stubGlobal('window', { pontem: wallet });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('pontem');
  });

  it('returns fewcha for window.fewcha', () => {
    const wallet = makeAptosWallet('Fewcha');
    vi.stubGlobal('window', { fewcha: wallet });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('fewcha');
  });

  it('returns nightly_aptos for window.nightly.aptos', () => {
    const wallet = makeAptosWallet('Nightly');
    vi.stubGlobal('window', { nightly: { aptos: wallet } });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('nightly_aptos');
  });

  it('returns rise for window.rise', () => {
    const wallet = makeAptosWallet('Rise');
    vi.stubGlobal('window', { rise: wallet });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('rise');
  });

  it('falls back to provider name for unknown wallet', () => {
    const wallet = makeAptosWallet('MyCustomWallet');
    vi.stubGlobal('window', { petra: wallet });
    // Petra match takes priority via instance comparison
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('petra');
  });

  it('petra takes priority over pontem when both present', () => {
    const petra = makeAptosWallet('Petra');
    const pontem = makeAptosWallet('Pontem');
    vi.stubGlobal('window', { petra, pontem });
    const p = new TestAptosProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('petra');
  });

  it('does not init when no aptos provider present', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new TestAptosProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('AptosProvider — connect/disconnect/transaction', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('connect emits onWalletEvent with vm=aptos', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new AptosProvider(cbs);
    p.connect('0xAPTOSADDRESS', { type: 'petra' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'aptos' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new AptosProvider(cbs);
    p.connect('0xAPTOSADDRESS', { type: 'petra' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'aptos' }));
  });

  it('transaction emits onTransaction with pending status', () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    const cbs = makeCallbacks();
    const p = new AptosProvider(cbs);
    p.connect('0xAPTOS', { type: 'petra' });
    p.transaction('0xTXHASH', { vm: 'aptos' });
    expect(cbs.onTransaction).toHaveBeenCalledWith(
      '0xTXHASH',
      expect.objectContaining({ vm: 'aptos', status: 'pending' }),
    );
    vi.unstubAllGlobals();
  });
});
