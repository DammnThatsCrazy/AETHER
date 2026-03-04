// =============================================================================
// AETHER SDK — SOLANA (SVM) TRACKER
// SPL token tracking, program interaction detection, compute unit analytics
// =============================================================================

import type { TokenBalance, GasAnalytics, DeFiCategory } from '../../types';

export interface SVMTrackerCallbacks {
  onTokenBalance: (balance: TokenBalance) => void;
  onGasAnalytics: (gas: GasAnalytics) => void;
  onDeFiInteraction: (data: Record<string, unknown>) => void;
  onProgramInteraction: (data: Record<string, unknown>) => void;
}

// Well-known Solana program IDs
const KNOWN_PROGRAMS: Record<string, { name: string; category?: DeFiCategory }> = {
  'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4': { name: 'Jupiter V6', category: 'router' },
  'JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB': { name: 'Jupiter V4', category: 'router' },
  '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8': { name: 'Raydium V4', category: 'dex' },
  'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK': { name: 'Raydium CLMM', category: 'dex' },
  'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc': { name: 'Orca Whirlpool', category: 'dex' },
  '9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP': { name: 'Orca V2', category: 'dex' },
  'MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD': { name: 'Marinade Finance', category: 'staking' },
  'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn': { name: 'Jito SOL', category: 'staking' },
  'MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA': { name: 'Marginfi', category: 'lending' },
  'So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo': { name: 'Solend', category: 'lending' },
  'DRiFTspy4YnosPodXHtUFh2MCTxD3HE95RjCnmeBJEzg': { name: 'Drift Protocol', category: 'perpetuals' },
  'ZETAxsqBRek56DhiGXrn75yj2NHU3aYUnxvHXpkf3aD': { name: 'Zeta Markets', category: 'options' },
  'M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K': { name: 'Magic Eden V2', category: 'nft_marketplace' },
  'TSWAPaqyCSx2KABk68Shruf4rp7CxcNi8hAsbdwmHbN': { name: 'Tensor', category: 'nft_marketplace' },
  'worm2ZoG2kUd4vFXhvjh93UUH596ayRfgQ2MgjNMTth': { name: 'Wormhole', category: 'bridge' },
  'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA': { name: 'SPL Token Program' },
  'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL': { name: 'Associated Token Program' },
  '11111111111111111111111111111111': { name: 'System Program' },
  'Stake11111111111111111111111111111111111111': { name: 'Stake Program', category: 'staking' },
  'Vote111111111111111111111111111111111111111': { name: 'Vote Program', category: 'governance' },
};

export class SVMTracker {
  private callbacks: SVMTrackerCallbacks;
  private cluster: string = 'mainnet-beta';

  constructor(callbacks: SVMTrackerCallbacks, cluster?: string) {
    this.callbacks = callbacks;
    if (cluster) this.cluster = cluster;
  }

  /** Identify a Solana program by its public key */
  identifyProgram(programId: string): { name: string; category?: DeFiCategory } {
    return KNOWN_PROGRAMS[programId] ?? { name: 'Unknown Program' };
  }

  /** Process a confirmed Solana transaction */
  processTransaction(tx: {
    signature: string;
    programIds?: string[];
    computeUnitsConsumed?: number;
    fee?: number;
    preBalances?: number[];
    postBalances?: number[];
    accountKeys?: string[];
  }): void {
    // Compute unit analytics (Solana's gas equivalent)
    this.callbacks.onGasAnalytics({
      gasCostNative: ((tx.fee ?? 0) / 1e9).toFixed(9),
      chainId: this.cluster, vm: 'svm',
      computeUnits: tx.computeUnitsConsumed,
      priorityFee: tx.fee ? String(tx.fee) : undefined,
    });

    // Program interaction detection
    if (tx.programIds) {
      for (const programId of tx.programIds) {
        const program = this.identifyProgram(programId);
        this.callbacks.onProgramInteraction({
          signature: tx.signature, programId, programName: program.name,
          category: program.category, vm: 'svm', chainId: this.cluster,
        });

        if (program.category) {
          this.callbacks.onDeFiInteraction({
            txHash: tx.signature, protocol: program.name,
            category: program.category, vm: 'svm', chainId: this.cluster,
          });
        }
      }
    }
  }

  /** Query SPL token accounts for an owner */
  async getTokenAccounts(ownerAddress: string): Promise<TokenBalance[]> {
    try {
      const response = await fetch(this.getRpcUrl(), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0', id: 1, method: 'getTokenAccountsByOwner',
          params: [ownerAddress, { programId: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' },
            { encoding: 'jsonParsed' }],
        }),
      });
      const result = await response.json();
      const accounts = result?.result?.value ?? [];
      const balances: TokenBalance[] = accounts.map((account: {
        account: { data: { parsed: { info: { mint: string; tokenAmount: { uiAmountString: string; decimals: number; amount: string } } } } };
      }) => {
        const info = account.account.data.parsed.info;
        return {
          symbol: '', name: '', contractAddress: info.mint,
          balance: info.tokenAmount.amount, decimals: info.tokenAmount.decimals,
          vm: 'svm' as const, chainId: this.cluster, standard: 'spl' as const,
        };
      });
      balances.forEach((b) => this.callbacks.onTokenBalance(b));
      return balances;
    } catch { return []; }
  }

  /** Get SOL balance */
  async getSOLBalance(address: string): Promise<TokenBalance | null> {
    try {
      const response = await fetch(this.getRpcUrl(), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'getBalance', params: [address] }),
      });
      const result = await response.json();
      const lamports = result?.result?.value ?? 0;
      const balance: TokenBalance = {
        symbol: 'SOL', name: 'Solana', contractAddress: 'native',
        balance: String(lamports), decimals: 9,
        vm: 'svm', chainId: this.cluster, standard: 'native',
      };
      this.callbacks.onTokenBalance(balance);
      return balance;
    } catch { return null; }
  }

  destroy(): void {
    // No timers to clean up
  }

  private getRpcUrl(): string {
    const map: Record<string, string> = {
      'mainnet-beta': 'https://api.mainnet-beta.solana.com',
      devnet: 'https://api.devnet.solana.com',
      testnet: 'https://api.testnet.solana.com',
    };
    return map[this.cluster] ?? map['mainnet-beta'];
  }
}
