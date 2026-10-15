// =============================================================================
// Tests: StellarProvider — Freighter, xBull, Rabet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StellarProvider } from '../src/web3/providers/stellar-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestStellarProvider extends StellarProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

describe('StellarProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns freighter for window.freighter', () => {
    vi.stubGlobal('window', {
      freighter: {
        isConnected: vi.fn().mockResolvedValue(true),
        getPublicKey: vi.fn().mockResolvedValue('GFAKESTELLARADDRESS'),
        signTransaction: vi.fn(),
      },
    });
    const p = new TestStellarProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('freighter');
  });

  it('returns xbull for window.xBullSDK', () => {
    vi.stubGlobal('window', {
      xBullSDK: {
        connect: vi.fn().mockResolvedValue(undefined),
        getPublicKey: vi.fn().mockResolvedValue('GFAKESTELLARADDRESS'),
      },
    });
    const p = new TestStellarProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('xbull');
  });

  it('returns rabet for window.rabet', () => {
    vi.stubGlobal('window', {
      rabet: {
        connect: vi.fn().mockResolvedValue({ publicKey: 'GFAKESTELLARADDRESS', network: 'MAINNET' }),
      },
    });
    const p = new TestStellarProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('rabet');
  });

  it('returns stellar as fallback when no wallet present', () => {
    vi.stubGlobal('window', {});
    const p = new TestStellarProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('stellar');
  });

  it('freighter takes priority over xbull when both present', () => {
    vi.stubGlobal('window', {
      freighter: { isConnected: vi.fn(), getPublicKey: vi.fn() },
      xBullSDK: { connect: vi.fn(), getPublicKey: vi.fn() },
    });
    const p = new TestStellarProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('freighter');
  });
});

describe('StellarProvider — init', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('inits with freighter and connects when isConnected returns true', async () => {
    vi.stubGlobal('window', {
      freighter: {
        isConnected: vi.fn().mockResolvedValue(true),
        getPublicKey: vi.fn().mockResolvedValue('GFAKESTELLARADDRESS'),
        getNetwork: vi.fn().mockResolvedValue('MAINNET'),
      },
    });
    const cbs = makeCallbacks();
    const p = new StellarProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'stellar', walletType: 'freighter' }),
      );
    });
  });

  it('inits with rabet and connects when rabet.connect resolves', async () => {
    vi.stubGlobal('window', {
      rabet: {
        connect: vi.fn().mockResolvedValue({ publicKey: 'GFAKESTELLARADDRESS', network: 'MAINNET' }),
      },
    });
    const cbs = makeCallbacks();
    const p = new StellarProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'stellar', walletType: 'rabet' }),
      );
    });
  });

  it('does not init when no Stellar wallet present', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new StellarProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('StellarProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=stellar', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new StellarProvider(cbs);
    p.connect('GFAKESTELLARADDRESS', { type: 'freighter' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'stellar' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new StellarProvider(cbs);
    p.connect('GFAKESTELLARADDRESS', { type: 'freighter' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'stellar' }));
  });
});
