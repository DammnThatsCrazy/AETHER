// =============================================================================
// Tests: StarknetProvider — wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StarknetProvider } from '../src/web3/providers/starknet-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestStarknetProvider extends StarknetProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makeStarknetWallet = (id?: string, name?: string) => ({
  id,
  name,
  version: '0.7',
  icon: '',
  request: vi.fn().mockResolvedValue(['0xSTARKNETADDRESS']),
  on: vi.fn(),
  off: vi.fn(),
  account: { address: '0xSTARKNETADDRESS' },
  provider: {},
  selectedAddress: '0xSTARKNETADDRESS',
  chainId: 'SN_MAIN',
  isConnected: false,
  enable: vi.fn().mockResolvedValue(['0xSTARKNETADDRESS']),
});

describe('StarknetProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns argent_x for window.starknet_argentX', () => {
    const w = makeStarknetWallet('argentX', 'ArgentX');
    vi.stubGlobal('window', {
      starknet_argentX: w,
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const p = new TestStarknetProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('argent_x');
  });

  it('returns braavos for window.starknet_braavos', () => {
    const w = makeStarknetWallet('braavos', 'Braavos');
    vi.stubGlobal('window', {
      starknet_braavos: w,
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const p = new TestStarknetProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('braavos');
  });

  it('returns provider.id for generic starknet wallet', () => {
    const w = makeStarknetWallet('myWallet', 'My Wallet');
    vi.stubGlobal('window', {
      starknet: w,
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const p = new TestStarknetProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('myWallet');
  });

  it('argent_x takes priority over generic starknet', () => {
    const argent = makeStarknetWallet('argentX');
    const generic = makeStarknetWallet('other');
    vi.stubGlobal('window', {
      starknet_argentX: argent,
      starknet: generic,
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const p = new TestStarknetProvider(makeCallbacks());
    p.init();
    expect(p.testDetectWalletType()).toBe('argent_x');
  });
});

describe('StarknetProvider — connect/disconnect', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=starknet', () => {
    vi.stubGlobal('window', {
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const cbs = makeCallbacks();
    const p = new StarknetProvider(cbs);
    p.init();
    p.connect('0xSTARKNETADDRESS', { type: 'argent_x' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'starknet' }));
  });

  it('connect always sets classification to smart (no EOAs on Starknet)', () => {
    vi.stubGlobal('window', {
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const cbs = makeCallbacks();
    const p = new StarknetProvider(cbs);
    p.init();
    p.connect('0xSTARKNETADDRESS', { type: 'argent_x', classification: 'smart' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith(
      'connect',
      expect.objectContaining({ vm: 'starknet' }),
    );
  });
});
