// =============================================================================
// Tests: MoveProvider (SUI) — wallet detection, connect/disconnect
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MoveProvider } from '../src/web3/providers/move-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestMoveProvider extends MoveProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeSuiWallet = () => ({
  name: 'SUI Wallet',
  connect: vi.fn().mockResolvedValue({ accounts: [{ address: '0xSUIADDRESS' }] }),
  on: vi.fn(),
  off: vi.fn(),
});

describe('MoveProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns sui_wallet for window.suiWallet with no name', () => {
    const w = { ...makeSuiWallet(), name: undefined };
    vi.stubGlobal('window', { suiWallet: w });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('sui_wallet');
  });

  it('returns ethos for window.ethosWallet', () => {
    const w = makeSuiWallet();
    vi.stubGlobal('window', { ethosWallet: w });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('ethos');
  });

  it('returns martian for window.martian.sui', () => {
    const w = makeSuiWallet();
    vi.stubGlobal('window', { martian: { sui: w } });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('martian');
  });

  it('returns surf for window.surfWallet', () => {
    const w = makeSuiWallet();
    vi.stubGlobal('window', { surfWallet: w });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('surf');
  });

  it('returns suiet for window.suiet', () => {
    const w = makeSuiWallet();
    vi.stubGlobal('window', { suiet: w });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('suiet');
  });

  it('returns nightly_sui for window.nightly.sui', () => {
    const w = makeSuiWallet();
    vi.stubGlobal('window', { nightly: { sui: w } });
    const p = new TestMoveProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('nightly_sui');
  });

  it('does not init when window is undefined', () => {
    const cbs = makeCallbacks();
    const p = new TestMoveProvider(cbs);
    // window is not defined — init should silently return
    vi.stubGlobal('window', undefined);
    expect(() => p.init()).not.toThrow();
  });
});

describe('MoveProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=movevm', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new MoveProvider(cbs);
    p.connect('0xSUIADDRESS', { type: 'sui_wallet' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'movevm' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new MoveProvider(cbs);
    p.connect('0xSUIADDRESS', { type: 'sui_wallet' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'movevm' }));
  });
});
