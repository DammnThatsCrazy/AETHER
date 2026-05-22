// =============================================================================
// Tests: SubstrateProvider — injectedWeb3 wallet detection, priority order
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SubstrateProvider } from '../src/web3/providers/substrate-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

const makeInjectedExtension = () => ({
  enable: vi.fn().mockResolvedValue({
    accounts: {
      get: vi.fn().mockResolvedValue([{ address: '5FakePolkadotAddress', name: 'Test Account', type: 'sr25519' }]),
      subscribe: vi.fn().mockReturnValue(() => {}),
    },
    signer: {},
  }),
  version: '0.44.1',
});

describe('SubstrateProvider — wallet priority order', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects subwallet-js first when multiple wallets present', async () => {
    vi.stubGlobal('window', {
      injectedWeb3: {
        'subwallet-js': makeInjectedExtension(),
        'talisman': makeInjectedExtension(),
        'polkadot-js': makeInjectedExtension(),
      },
    });
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'substrate', walletType: 'subwallet-js' }),
      );
    });
  });

  it('connects talisman when subwallet-js absent', async () => {
    vi.stubGlobal('window', {
      injectedWeb3: {
        'talisman': makeInjectedExtension(),
        'polkadot-js': makeInjectedExtension(),
      },
    });
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'substrate', walletType: 'talisman' }),
      );
    });
  });

  it('connects polkadot-js when higher-priority wallets absent', async () => {
    vi.stubGlobal('window', {
      injectedWeb3: {
        'polkadot-js': makeInjectedExtension(),
      },
    });
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'substrate', walletType: 'polkadot-js' }),
      );
    });
  });

  it('falls back to first available wallet when none in priority list', async () => {
    vi.stubGlobal('window', {
      injectedWeb3: {
        'unknown-wallet': makeInjectedExtension(),
      },
    });
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'substrate', walletType: 'unknown-wallet' }),
      );
    });
  });

  it('does not init when window.injectedWeb3 is absent', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('SubstrateProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('manual connect emits onWalletEvent with vm=substrate', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new SubstrateProvider(cbs);
    p.connect('5FakeAddress', { type: 'polkadot-js' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'substrate' }));
  });
});
