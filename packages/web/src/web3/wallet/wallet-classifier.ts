// =============================================================================
// AETHER SDK — WALLET CLASSIFIER
// Hot/cold/smart/exchange/protocol/multisig wallet classification
// =============================================================================

import type { VMType, WalletClassification } from '../../types';
import { isExchangeAddress, isProtocolAddress } from './wallet-labels';

/** Provider metadata for classification */
export interface ProviderMeta {
  walletType?: string;
  isHardware?: boolean;
  isLedger?: boolean;
  isTrezor?: boolean;
  isGridPlus?: boolean;
  isKeystone?: boolean;
  isSafe?: boolean;
  isSmartAccount?: boolean;
  isMultisig?: boolean;
  is4337?: boolean;
  rdns?: string;
}

// Known hardware wallet RDNS identifiers (EIP-6963)
let HARDWARE_RDNS = new Set([
  'com.ledger', 'io.metamask.flask', 'com.gridplus',
  'com.keystonehq', 'io.trezor',
]);

// Known smart wallet RDNS identifiers
let SMART_WALLET_RDNS = new Set([
  'global.safe', 'com.ambire', 'com.sequence',
  'network.zerodev', 'com.biconomy',
]);

// ---------------------------------------------------------------------------
// OTA Remote Data Support
// ---------------------------------------------------------------------------

interface ClassificationRules {
  hardwareRdns?: string[];
  smartWalletRdns?: string[];
  hardwareWalletTypes?: string[];
  multisigWalletTypes?: string[];
}

/**
 * Inject remote classification rules from OTA update.
 * Updates the RDNS sets and wallet type patterns used for classification.
 * Pass null to revert to bundled defaults.
 */
export function setRemoteData(remote: ClassificationRules | null): void {
  if (remote) {
    if (remote.hardwareRdns) HARDWARE_RDNS = new Set(remote.hardwareRdns);
    if (remote.smartWalletRdns) SMART_WALLET_RDNS = new Set(remote.smartWalletRdns);
  } else {
    // Revert to defaults
    HARDWARE_RDNS = new Set(['com.ledger', 'io.metamask.flask', 'com.gridplus', 'com.keystonehq', 'io.trezor']);
    SMART_WALLET_RDNS = new Set(['global.safe', 'com.ambire', 'com.sequence', 'network.zerodev', 'com.biconomy']);
  }
}

/**
 * Classify a wallet based on provider metadata and on-chain data
 */
export function classifyWallet(
  address: string,
  vm: VMType,
  chainId: number | string,
  providerMeta?: ProviderMeta,
): WalletClassification {
  // 1. Check against known exchange addresses
  if (isExchangeAddress(chainId, address)) {
    return 'exchange';
  }

  // 2. Check against known protocol addresses
  if (isProtocolAddress(chainId, address)) {
    return 'protocol';
  }

  // 3. Check provider metadata for hardware wallets
  if (providerMeta) {
    if (providerMeta.isHardware || providerMeta.isLedger || providerMeta.isTrezor ||
        providerMeta.isGridPlus || providerMeta.isKeystone) {
      return 'cold';
    }

    // Check RDNS for hardware wallet apps
    if (providerMeta.rdns && HARDWARE_RDNS.has(providerMeta.rdns)) {
      return 'cold';
    }

    // Check for smart wallets / account abstraction
    if (providerMeta.isSafe || providerMeta.isMultisig) {
      return 'multisig';
    }

    if (providerMeta.isSmartAccount || providerMeta.is4337) {
      return 'smart';
    }

    if (providerMeta.rdns && SMART_WALLET_RDNS.has(providerMeta.rdns)) {
      return 'smart';
    }
  }

  // 4. Check wallet type string for known hardware patterns
  const walletType = providerMeta?.walletType?.toLowerCase() ?? '';
  if (['ledger', 'trezor', 'gridplus', 'keystone', 'lattice', 'coldcard'].includes(walletType)) {
    return 'cold';
  }

  if (['safe', 'gnosis_safe', 'squads'].includes(walletType)) {
    return 'multisig';
  }

  // 5. Default: hot wallet (browser extension, mobile, web)
  return 'hot';
}

/**
 * Check if a contract address is a smart wallet (ERC-4337 or Safe)
 * by checking if it has contract code deployed
 */
export async function isSmartWallet(
  provider: { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> },
  address: string,
): Promise<boolean> {
  try {
    const code = await provider.request({
      method: 'eth_getCode',
      params: [address, 'latest'],
    });
    // EOA accounts have code "0x", smart wallets have deployed code
    return typeof code === 'string' && code !== '0x' && code.length > 2;
  } catch {
    return false;
  }
}

/**
 * Determine classification display label
 */
export function getClassificationLabel(classification: WalletClassification): string {
  const labels: Record<WalletClassification, string> = {
    hot: 'Hot Wallet',
    cold: 'Hardware Wallet',
    smart: 'Smart Account',
    exchange: 'Exchange',
    protocol: 'Protocol',
    multisig: 'Multisig',
  };
  return labels[classification];
}

/**
 * Get security score based on wallet classification (0-100)
 */
export function getSecurityScore(classification: WalletClassification): number {
  const scores: Record<WalletClassification, number> = {
    cold: 95,
    multisig: 90,
    smart: 80,
    hot: 60,
    exchange: 50,
    protocol: 70,
  };
  return scores[classification];
}
