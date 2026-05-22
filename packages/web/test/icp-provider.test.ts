// =============================================================================
// Tests: ICPProvider — Plug and NFID wallet detection
// =============================================================================
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ICPProvider } from '../src/web3/providers/icp-provider';

const makeCallbacks = () => ({
  onWalletEvent: vi.fn(),
  onTransaction: vi.fn(),
});

class TestICPProvider extends ICPProvider {
  testDetectWalletType() { return this.detectWalletType(); }
}

const makePlug = () => ({
  isConnected: vi.fn().mockResolvedValue(true),
  getPrincipal: vi.fn().mockResolvedValue({ toText: () => 'fake-principal-id' }),
  requestConnect: vi.fn().mockResolvedValue(true),
  agent: {},
});

const makeNFID = () => ({
  requestConnect: vi.fn().mockResolvedValue({ principal: { toText: () => 'fake-nfid-principal' } }),
});

describe('ICPProvider.detectWalletType', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('returns plug when window.ic.plug is present', () => {
    vi.stubGlobal('window', { ic: { plug: makePlug() } });
    const p = new TestICPProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('plug');
  });

  it('returns nfid when window.ic.nfid is present (no plug)', () => {
    vi.stubGlobal('window', { ic: { nfid: makeNFID() } });
    const p = new TestICPProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('nfid');
  });

  it('returns icp when window.ic has no known wallet', () => {
    vi.stubGlobal('window', { ic: {} });
    const p = new TestICPProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('icp');
  });

  it('returns icp when window.ic is absent', () => {
    vi.stubGlobal('window', {});
    const p = new TestICPProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('icp');
  });

  it('plug takes priority over nfid when both present', () => {
    vi.stubGlobal('window', { ic: { plug: makePlug(), nfid: makeNFID() } });
    const p = new TestICPProvider(makeCallbacks());
    expect(p.testDetectWalletType()).toBe('plug');
  });
});

describe('ICPProvider — init', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects via Plug when isConnected returns true', async () => {
    vi.stubGlobal('window', { ic: { plug: makePlug() } });
    const cbs = makeCallbacks();
    const p = new ICPProvider(cbs);
    p.init();
    await vi.waitFor(() => {
      expect(cbs.onWalletEvent).toHaveBeenCalledWith(
        'connect',
        expect.objectContaining({ vm: 'icp', walletType: 'plug' }),
      );
    });
  });

  it('does not auto-connect Plug when isConnected returns false', async () => {
    const plug = makePlug();
    plug.isConnected = vi.fn().mockResolvedValue(false);
    vi.stubGlobal('window', { ic: { plug } });
    const cbs = makeCallbacks();
    const p = new ICPProvider(cbs);
    p.init();
    // Give async time to settle
    await new Promise((r) => setTimeout(r, 50));
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });

  it('does not init when no IC wallet present', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new ICPProvider(cbs);
    p.init();
    expect(cbs.onWalletEvent).not.toHaveBeenCalled();
  });
});

describe('ICPProvider — connect/disconnect/transaction', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connect emits onWalletEvent with vm=icp', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new ICPProvider(cbs);
    p.connect('fake-principal-id', { type: 'plug' });
    expect(cbs.onWalletEvent).toHaveBeenCalledWith('connect', expect.objectContaining({ vm: 'icp' }));
  });

  it('transaction ships block index to backend immediately (no polling)', () => {
    vi.stubGlobal('window', {});
    const cbs = makeCallbacks();
    const p = new ICPProvider(cbs);
    p.connect('fake-principal-id', { type: 'plug' });
    p.transaction('1234567', { vm: 'icp' });
    // ICP uses block heights — monitorTransaction emits immediately (no polling)
    expect(cbs.onTransaction).toHaveBeenCalledWith(
      '1234567',
      expect.objectContaining({ vm: 'icp', status: 'pending' }),
    );
  });
});
