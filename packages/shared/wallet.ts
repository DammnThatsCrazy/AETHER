// =============================================================================
// Aether SDK — Shared Wallet / VM Contract
// Used by wallet, transaction, and onchain-action event families.
// See docs/source-of-truth/ENTITY_MODEL.md §Wallet.
// =============================================================================

/** Virtual machine family — matches backend VMType enum. */
export type VMType =
  | 'evm'
  | 'svm'
  | 'bitcoin'
  | 'movevm'
  | 'near'
  | 'tvm'
  | 'cosmos';

export const VM_TYPES: readonly VMType[] = [
  'evm', 'svm', 'bitcoin', 'movevm', 'near', 'tvm', 'cosmos',
] as const;

/** Wallet security classification (computed server-side; SDK may leave undefined). */
export type WalletClassification =
  | 'hot'
  | 'cold'
  | 'smart'
  | 'exchange'
  | 'protocol'
  | 'multisig';

/** Transaction lifecycle status. */
export type TxStatus = 'pending' | 'confirmed' | 'failed';

/** Canonical wallet identity emitted by SDK wallet.connect calls. */
export interface WalletInfo {
  address: string;
  vm: VMType;
  chainId?: number | string;
  walletType?: string;
  ens?: string;
  connectedAt?: string;
  isPrimary?: boolean;
  classification?: WalletClassification;
}

/** Options accepted by SDK transaction() helpers. */
export interface TransactionOptions {
  vm?: VMType;
  chainId?: number | string;
  from?: string;
  to?: string;
  value?: string;
  gasUsed?: string;
  status?: TxStatus;
  type?: 'transfer' | 'swap' | 'stake' | 'bridge' | 'contract_call' | 'mint' | 'burn';
  protocol?: string;
  [key: string]: unknown;
}
