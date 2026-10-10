// =============================================================================
// Tests: EVMProvider — wallet type detection, connect/disconnect, transactions
// =============================================================================
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EVMProvider } from '../src/web3/providers/evm-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

// Access private detectWalletType via any-cast
function detectType(
  provider: EVMProvider,
  flags: Record<string, boolean | unknown>,
): string {
  return (provider as unknown as { detectWalletType(p: unknown): string }).detectWalletType(flags);
}

describe('EVMProvider.detectWalletType', () => {
  let provider: EVMProvider;

  beforeEach(() => {
    provider = new EVMProvider(makeCallbacks(), {});
  });

  it('returns safe for isSafe (highest priority)', () => {
    expect(detectType(provider, { isSafe: true, isMetaMask: true })).toBe('safe');
  });

  it('returns rabby for isRabby', () => {
    expect(detectType(provider, { isRabby: true })).toBe('rabby');
  });

  it('returns coinbase for isCoinbaseWallet', () => {
    expect(detectType(provider, { isCoinbaseWallet: true })).toBe('coinbase');
  });

  it('returns brave for isBraveWallet', () => {
    expect(detectType(provider, { isBraveWallet: true })).toBe('brave');
  });

  it('returns rainbow for isRainbow', () => {
    expect(detectType(provider, { isRainbow: true })).toBe('rainbow');
  });

  it('returns trust for isTrust', () => {
    expect(detectType(provider, { isTrust: true })).toBe('trust');
  });

  it('returns frame for isFrame', () => {
    expect(detectType(provider, { isFrame: true })).toBe('frame');
  });

  it('returns zerion for isZerion', () => {
    expect(detectType(provider, { isZerion: true })).toBe('zerion');
  });

  it('returns okx for isOKExWallet', () => {
    expect(detectType(provider, { isOKExWallet: true })).toBe('okx');
  });

  it('returns ledger for isLedgerConnect', () => {
    expect(detectType(provider, { isLedgerConnect: true })).toBe('ledger');
  });

  it('returns taho for isTaho', () => {
    expect(detectType(provider, { isTaho: true })).toBe('taho');
  });

  it('returns uniswap_wallet for isUniswapWallet', () => {
    expect(detectType(provider, { isUniswapWallet: true })).toBe('uniswap_wallet');
  });

  it('returns ronin for isRoninWallet', () => {
    expect(detectType(provider, { isRoninWallet: true })).toBe('ronin');
  });

  it('returns bitget for isBitgetWallet', () => {
    expect(detectType(provider, { isBitgetWallet: true })).toBe('bitget');
  });

  it('returns bybit for isBybitWallet', () => {
    expect(detectType(provider, { isBybitWallet: true })).toBe('bybit');
  });

  it('returns exodus for isExodus', () => {
    expect(detectType(provider, { isExodus: true })).toBe('exodus');
  });

  it('returns coin98 for isCoin98', () => {
    expect(detectType(provider, { isCoin98: true })).toBe('coin98');
  });

  it('returns token_pocket for isTokenPocket', () => {
    expect(detectType(provider, { isTokenPocket: true })).toBe('token_pocket');
  });

  it('returns metamask for isMetaMask (lowest branded priority)', () => {
    expect(detectType(provider, { isMetaMask: true })).toBe('metamask');
  });

  it('returns injected when no known flags are set', () => {
    expect(detectType(provider, {})).toBe('injected');
  });

  it('prefers safe over metamask when both flags are set', () => {
    expect(detectType(provider, { isSafe: true, isMetaMask: true })).toBe('safe');
  });

  it('prefers rabby over metamask (rabby sets isMetaMask for compat)', () => {
    expect(detectType(provider, { isRabby: true, isMetaMask: true })).toBe('rabby');
  });
});

describe('EVMProvider — classifyProvider', () => {
  it('classifies safe wallet as multisig', () => {
    const classify = (EVMProvider.prototype as unknown as {
      classifyProvider(type: string): string;
    }).classifyProvider.bind({});
    expect(classify('safe')).toBe('multisig');
  });

  it('classifies ledger as cold', () => {
    const classify = (EVMProvider.prototype as unknown as {
      classifyProvider(type: string): string;
    }).classifyProvider.bind({});
    expect(classify('ledger')).toBe('cold');
  });

  it('classifies metamask as hot', () => {
    const classify = (EVMProvider.prototype as unknown as {
      classifyProvider(type: string): string;
    }).classifyProvider.bind({});
    expect(classify('metamask')).toBe('hot');
  });
});

describe('EVMProvider — connect / disconnect / transaction', () => {
  let cbs: ReturnType<typeof makeCallbacks>;

  beforeEach(() => {
    cbs = makeCallbacks();
    // Suppress any setTimeout-based monitoring
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('connect fires onWalletEvent with correct vm', () => {
    const p = new EVMProvider(cbs, {});
    p.connect('0xABCDEF', { type: 'metamask', chainId: 1 });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith(
      'connect',
      expect.objectContaining({ vm: 'evm', address: '0xabcdef' }),
    );
  });

  it('disconnect fires onWalletEvent with disconnect action', () => {
    const p = new EVMProvider(cbs, {});
    p.connect('0x1234', { type: 'metamask', chainId: 1 });
    p.disconnect('0x1234');
    expect(cbs.onWalletEvent).toHaveBeenCalledWith(
      'disconnect',
      expect.objectContaining({ vm: 'evm' }),
    );
  });

  it('transaction fires onTransaction with pending status', () => {
    const p = new EVMProvider(cbs, {});
    p.connect('0x1234', { type: 'metamask', chainId: 1 });
    // Mock fetch to prevent real network calls
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    p.transaction('0xdeadbeef', { vm: 'evm' });
    expect(cbs.onTransaction).toHaveBeenCalledWith(
      '0xdeadbeef',
      expect.objectContaining({ vm: 'evm' }),
    );
    vi.unstubAllGlobals();
  });
});
