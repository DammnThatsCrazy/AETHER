// =============================================================================
// Aether SDK — INTERNET COMPUTER (ICP) PROVIDER
// Plug wallet (window.ic.plug), NFID, Stoic detection.
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface PlugWallet {
  isConnected(): Promise<boolean>;
  requestConnect(opts?: { whitelist?: string[]; host?: string }): Promise<boolean>;
  getPrincipal(): Promise<{ toString(): string }>;
  accountId?: string;
  agent?: unknown;
}

interface NFIDWallet {
  requestConnect(opts?: { derivationOrigin?: string }): Promise<{ getPrincipal(): { toString(): string } }>;
  isAuthenticated?: boolean;
}

declare global {
  interface Window {
    ic?: {
      plug?: PlugWallet;
      nfid?: NFIDWallet;
      stoic?: unknown;
    };
  }
}

export class ICPProvider extends BaseVMProvider {
  readonly vm: VMType = 'icp';
  readonly defaultChainId: string = 'icp:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined' || !window.ic) return;
    const ic = window.ic;
    if (ic.plug) {
      this.walletType = 'plug';
      this.setupPlug(ic.plug);
    } else if (ic.nfid) {
      this.walletType = 'nfid';
      this.setupNFID(ic.nfid);
    }
  }

  destroy(): void {
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined' || !window.ic) return 'icp';
    if (window.ic.plug) return 'plug';
    if (window.ic.nfid) return 'nfid';
    return 'icp';
  }

  protected async monitorTransaction(txId: string): Promise<void> {
    // ICP uses block heights rather than tx hashes for tracking.
    // Ship the ID to backend for monitoring via the IC management canister.
    this.callbacks.onTransaction(txId, {
      txHash: txId, chainId: 'icp:mainnet', vm: 'icp', status: 'pending',
    });
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupPlug(plug: PlugWallet): Promise<void> {
    try {
      const connected = await plug.isConnected();
      if (connected) {
        const principal = await plug.getPrincipal();
        const address = plug.accountId ?? principal.toString();
        this.connect(address, { type: 'plug', chainId: 'icp:mainnet' });
      }
    } catch { /* not connected */ }
  }

  private async setupNFID(nfid: NFIDWallet): Promise<void> {
    try {
      if (nfid.isAuthenticated) {
        const identity = await nfid.requestConnect();
        const principal = identity?.getPrincipal?.()?.toString();
        if (principal) {
          this.connect(principal, { type: 'nfid', chainId: 'icp:mainnet' });
        }
      }
    } catch { /* not authenticated */ }
  }
}
