// =============================================================================
// Tests: AlgorandProvider — ARC-0027 and AlgoSigner wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AlgorandProvider } from '../src/web3/providers/algorand-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestAlgorandProvider extends AlgorandProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeARC0027Provider = (name = 'pera') => ({
  name,
  enable: vi.fn().mockResolvedValue({ accounts: ['FAKEALGOADDRESS'] }),
  on: vi.fn(),
});

describe('AlgorandProvider — init via ARC-0027 (window.algorand)', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects via window.algorand and uses provider name as wallet type', async () => {
    vi.stubGlobal('window', {
      algorand: makeARC0027Provider('kibisis'),
    });
    const cbs = makeCallbacks();
    const p = new AlgorandProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'algorand', walletType: 'kibisis' }),
      );
    });
  });

  it('detects algorand as fallback when provider has no name', async () => {
    vi.stubGlobal('window', {
      algorand: makeARC0027Provider(undefined as unknown as string),
    });
    const cbs = makeCallbacks();
    const p = new AlgorandProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'algorand' }),
      );
    });
  });
});

describe('AlgorandProvider — init via AlgoSigner fallback', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects via AlgoSigner when window.algorand absent', async () => {
    vi.stubGlobal('window', {
      AlgoSigner: {
        accounts: vi.fn().mockResolvedValue([{ address: 'FAKEALGOADDRESS' }]),
        sign: vi.fn(),
      },
    });
    const cbs = makeCallbacks();
    const p = new AlgorandProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'algorand', walletType: 'algosigner' }),
      );
    });
  });
});

describe('AlgorandProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns algosigner when only AlgoSigner present', () => {
    vi.stubGlobal('window', { AlgoSigner: {} });
    const p = new TestAlgorandProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('algosigner');
  });

  it('returns algorand as fallback when neither provider present', () => {
    vi.stubGlobal('window', {});
    const p = new TestAlgorandProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('algorand');
  });
});

describe('AlgorandProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('manual connect emits onWalletEvent with vm=algorand', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new AlgorandProvider(cbs);
    p.connect('FAKEALGOADDRESS', { type: 'pera' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'algorand' }));
  });

  it('transaction emits onTransaction with pending status', () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    const cbs = makeCallbacks();
    const p = new AlgorandProvider(cbs);
    p.connect('FAKEALGOADDRESS', { type: 'pera' });
    p.transaction('TXID123', { vm: 'algorand' });
    expect(cbs.onTransaction).toHaveBeenCalledWith(
      'TXID123',
      expect.objectContaining({ vm: 'algorand', status: 'pending' }),
    );
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
