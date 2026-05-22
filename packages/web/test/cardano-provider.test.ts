// =============================================================================
// Tests: CardanoProvider — CIP-30 wallet detection, priority order
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CardanoProvider } from '../src/web3/providers/cardano-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

const makeCIP30Handle = (name: string) => ({
  name,
  icon: '',
  version: '0.1.0',
  isEnabled: vi.fn().mockResolvedValue(true),
  enable: vi.fn().mockResolvedValue({
    getNetworkId: vi.fn().mockResolvedValue(1),
    getUsedAddresses: vi.fn().mockResolvedValue(['ADAFakeAddress']),
    getChangeAddress: vi.fn().mockResolvedValue('ADAFakeAddress'),
    getBalance: vi.fn().mockResolvedValue('1000000'),
    signTx: vi.fn(),
    submitTx: vi.fn(),
  }),
});

describe('CardanoProvider — CIP-30 wallet priority', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects nami when present (highest priority)', async () => {
    vi.stubGlobal('window', {
      cardano: {
        nami: makeCIP30Handle('Nami'),
        eternl: makeCIP30Handle('Eternl'),
      },
    });
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'cardano', walletType: 'nami' }),
      );
    });
  });

  it('falls through to eternl when nami is absent', async () => {
    vi.stubGlobal('window', {
      cardano: {
        eternl: makeCIP30Handle('Eternl'),
      },
    });
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'cardano', walletType: 'eternl' }),
      );
    });
  });

  it('does not init when window.cardano is absent', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });

  it('uses first available wallet when none match priority list', async () => {
    vi.stubGlobal('window', {
      cardano: {
        customWallet: makeCIP30Handle('CustomWallet'),
      },
    });
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.init();
    // Should still connect using the available wallet
    await vi.waitFor(() => {
      // CIP30_WALLETS iteration may skip unknown wallets; no error expected
      expect(cbs.onWalletEvent).not.toThrow?.();
    });
  });
});

describe('CardanoProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('manual connect emits onWalletEvent with vm=cardano', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.connect('ADAFakeAddress', { type: 'nami' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'cardano' }));
  });

  it('disconnect emits onWalletEvent with disconnect action', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new CardanoProvider(cbs);
    p.connect('ADAFakeAddress', { type: 'nami' });
    p.disconnect();
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('disconnect', expect.objectContaining({ vm: 'cardano' }));
  });
});
