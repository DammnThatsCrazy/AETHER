// =============================================================================
// AETHER SDK — BITCOIN TRACKER
// UTXO tracking, inscription/ordinal detection, fee analytics
// =============================================================================

import type { GasAnalytics, WhaleAlert } from '../../types';

export interface BTCTrackerCallbacks {
  onGasAnalytics: (gas: GasAnalytics) => void;
  onWhaleAlert: (alert: WhaleAlert) => void;
  onInscriptionDetected: (data: Record<string, unknown>) => void;
  onUTXOUpdate: (data: Record<string, unknown>) => void;
}

export interface BTCTrackerConfig {
  whaleThresholdBTC?: number;
  network?: 'mainnet' | 'testnet' | 'signet';
}

export class BTCTracker {
  private callbacks: BTCTrackerCallbacks;
  private config: Required<BTCTrackerConfig>;

  constructor(callbacks: BTCTrackerCallbacks, config?: BTCTrackerConfig) {
    this.callbacks = callbacks;
    this.config = {
      whaleThresholdBTC: config?.whaleThresholdBTC ?? 10,
      network: config?.network ?? 'mainnet',
    };
  }

  /** Process a confirmed Bitcoin transaction */
  processTransaction(tx: {
    txid: string; fee: number; size: number; weight: number;
    vin: { prevout?: { value: number; scriptpubkey_address?: string } }[];
    vout: { value: number; scriptpubkey_address?: string; scriptpubkey_type?: string }[];
  }): void {
    // Fee analytics (sat/vB)
    const feeRate = tx.fee / (tx.weight / 4);
    this.callbacks.onGasAnalytics({
      gasCostNative: (tx.fee / 1e8).toFixed(8),
      chainId: this.config.network, vm: 'bitcoin',
      gasUsed: String(tx.weight), gasPrice: feeRate.toFixed(1),
    });

    // Total value transferred
    const totalValue = tx.vout.reduce((sum, out) => sum + out.value, 0);
    const valueBTC = totalValue / 1e8;

    // Whale detection
    if (valueBTC >= this.config.whaleThresholdBTC) {
      const fromAddress = tx.vin[0]?.prevout?.scriptpubkey_address ?? 'unknown';
      const toAddress = tx.vout[0]?.scriptpubkey_address ?? 'unknown';
      this.callbacks.onWhaleAlert({
        txHash: tx.txid, value: String(totalValue),
        from: fromAddress, to: toAddress,
        chainId: this.config.network, vm: 'bitcoin',
        threshold: String(this.config.whaleThresholdBTC),
      });
    }

    // Inscription detection (OP_RETURN or witness data patterns)
    for (const out of tx.vout) {
      if (out.scriptpubkey_type === 'op_return') {
        this.callbacks.onInscriptionDetected({
          txid: tx.txid, type: 'op_return', vm: 'bitcoin',
          chainId: this.config.network,
        });
      }
    }
  }

  /** Fetch UTXOs for an address */
  async getUTXOs(address: string): Promise<{ txid: string; vout: number; value: number; status: { confirmed: boolean } }[]> {
    try {
      const baseUrl = this.getApiUrl();
      const response = await fetch(`${baseUrl}/address/${address}/utxo`);
      const utxos = await response.json();
      this.callbacks.onUTXOUpdate({
        address, utxoCount: utxos.length, vm: 'bitcoin',
        totalValue: utxos.reduce((sum: number, u: { value: number }) => sum + u.value, 0),
        chainId: this.config.network,
      });
      return utxos;
    } catch { return []; }
  }

  /** Get address balance */
  async getBalance(address: string): Promise<{ confirmed: number; unconfirmed: number }> {
    try {
      const baseUrl = this.getApiUrl();
      const response = await fetch(`${baseUrl}/address/${address}`);
      const data = await response.json();
      return {
        confirmed: data.chain_stats?.funded_txo_sum - data.chain_stats?.spent_txo_sum ?? 0,
        unconfirmed: data.mempool_stats?.funded_txo_sum - data.mempool_stats?.spent_txo_sum ?? 0,
      };
    } catch { return { confirmed: 0, unconfirmed: 0 }; }
  }

  /** Detect address type from scriptpubkey */
  detectAddressType(address: string): 'legacy' | 'segwit' | 'native_segwit' | 'taproot' | 'unknown' {
    if (address.startsWith('bc1p') || address.startsWith('tb1p')) return 'taproot';
    if (address.startsWith('bc1') || address.startsWith('tb1')) return 'native_segwit';
    if (address.startsWith('3') || address.startsWith('2')) return 'segwit';
    if (address.startsWith('1') || address.startsWith('m') || address.startsWith('n')) return 'legacy';
    return 'unknown';
  }

  destroy(): void { /* no timers */ }

  private getApiUrl(): string {
    const map: Record<string, string> = {
      mainnet: 'https://mempool.space/api',
      testnet: 'https://mempool.space/testnet/api',
      signet: 'https://mempool.space/signet/api',
    };
    return map[this.config.network] ?? map.mainnet;
  }
}
