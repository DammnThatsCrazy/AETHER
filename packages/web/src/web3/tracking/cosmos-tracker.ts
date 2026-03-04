// =============================================================================
// AETHER SDK — COSMOS / SEI TRACKER
// IBC transfers, staking, governance tracking
// =============================================================================

import type { TokenBalance, GasAnalytics, DeFiCategory } from '../../types';

export interface CosmosTrackerCallbacks {
  onTokenBalance: (balance: TokenBalance) => void;
  onGasAnalytics: (gas: GasAnalytics) => void;
  onDeFiInteraction: (data: Record<string, unknown>) => void;
  onIBCTransfer: (data: Record<string, unknown>) => void;
  onGovernanceAction: (data: Record<string, unknown>) => void;
}

type CosmosMsgType =
  | '/cosmos.bank.v1beta1.MsgSend'
  | '/cosmos.staking.v1beta1.MsgDelegate'
  | '/cosmos.staking.v1beta1.MsgUndelegate'
  | '/cosmos.staking.v1beta1.MsgBeginRedelegate'
  | '/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward'
  | '/cosmos.gov.v1beta1.MsgVote'
  | '/cosmos.gov.v1.MsgVote'
  | '/ibc.applications.transfer.v1.MsgTransfer';

const MSG_CATEGORIES: Partial<Record<CosmosMsgType, { action: string; category?: DeFiCategory }>> = {
  '/cosmos.staking.v1beta1.MsgDelegate': { action: 'delegate', category: 'staking' },
  '/cosmos.staking.v1beta1.MsgUndelegate': { action: 'undelegate', category: 'staking' },
  '/cosmos.staking.v1beta1.MsgBeginRedelegate': { action: 'redelegate', category: 'staking' },
  '/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward': { action: 'claim_rewards', category: 'staking' },
  '/cosmos.gov.v1beta1.MsgVote': { action: 'vote', category: 'governance' },
  '/cosmos.gov.v1.MsgVote': { action: 'vote', category: 'governance' },
  '/ibc.applications.transfer.v1.MsgTransfer': { action: 'ibc_transfer', category: 'bridge' },
};

export class CosmosTracker {
  private callbacks: CosmosTrackerCallbacks;
  private chainId: string = 'sei-pacific-1';

  constructor(callbacks: CosmosTrackerCallbacks, chainId?: string) {
    this.callbacks = callbacks;
    if (chainId) this.chainId = chainId;
  }

  /** Process a Cosmos/SEI transaction */
  processTransaction(tx: {
    txhash: string;
    messages: { '@type': string; [key: string]: unknown }[];
    gasUsed?: string;
    gasWanted?: string;
    fee?: { amount: { denom: string; amount: string }[] };
  }): void {
    // Gas analytics
    if (tx.fee?.amount?.[0]) {
      this.callbacks.onGasAnalytics({
        gasCostNative: (Number(tx.fee.amount[0].amount) / 1e6).toFixed(6),
        chainId: this.chainId, vm: 'cosmos',
        gasUsed: tx.gasUsed, gasPrice: tx.gasWanted,
      });
    }

    // Message type detection
    for (const msg of tx.messages) {
      const msgType = msg['@type'] as CosmosMsgType;
      const info = MSG_CATEGORIES[msgType];

      if (info?.category) {
        this.callbacks.onDeFiInteraction({
          txHash: tx.txhash, action: info.action,
          category: info.category, vm: 'cosmos', chainId: this.chainId,
          msgType, ...msg,
        });
      }

      // IBC transfer detection
      if (msgType === '/ibc.applications.transfer.v1.MsgTransfer') {
        this.callbacks.onIBCTransfer({
          txHash: tx.txhash, sourceChannel: msg.sourceChannel,
          sourcePort: msg.sourcePort, token: msg.token,
          sender: msg.sender, receiver: msg.receiver,
          vm: 'cosmos', chainId: this.chainId,
        });
      }

      // Governance
      if (msgType.includes('MsgVote')) {
        this.callbacks.onGovernanceAction({
          txHash: tx.txhash, action: 'vote',
          proposalId: msg.proposalId ?? msg.proposal_id,
          option: msg.option, voter: msg.voter,
          vm: 'cosmos', chainId: this.chainId,
        });
      }
    }
  }

  /** Get native token balance */
  async getBalance(address: string): Promise<TokenBalance | null> {
    try {
      const denom = this.chainId.startsWith('sei') ? 'usei' : 'uatom';
      const symbol = this.chainId.startsWith('sei') ? 'SEI' : 'ATOM';
      const response = await fetch(`${this.getRestUrl()}/cosmos/bank/v1beta1/balances/${address}`);
      const data = await response.json();
      const coin = data?.balances?.find((b: { denom: string }) => b.denom === denom);
      const balance: TokenBalance = {
        symbol, name: symbol, contractAddress: denom,
        balance: coin?.amount ?? '0', decimals: 6,
        vm: 'cosmos', chainId: this.chainId, standard: 'native',
      };
      this.callbacks.onTokenBalance(balance);
      return balance;
    } catch { return null; }
  }

  /** Get staking delegations */
  async getDelegations(address: string): Promise<{ validator: string; amount: string }[]> {
    try {
      const response = await fetch(`${this.getRestUrl()}/cosmos/staking/v1beta1/delegations/${address}`);
      const data = await response.json();
      return (data?.delegation_responses ?? []).map((d: { delegation: { validator_address: string }; balance: { amount: string } }) => ({
        validator: d.delegation.validator_address,
        amount: d.balance.amount,
      }));
    } catch { return []; }
  }

  private getRestUrl(): string {
    const map: Record<string, string> = {
      'sei-pacific-1': 'https://sei-api.polkachu.com',
      'cosmoshub-4': 'https://cosmos-rest.publicnode.com',
    };
    return map[this.chainId] ?? map['cosmoshub-4'];
  }

  destroy(): void { /* no timers */ }
}
