// =============================================================================
// AETHER SDK — UNIFIED CROSS-VM CHAIN REGISTRY
// Merges EVM, Solana, Bitcoin, SUI, NEAR, TRON, Cosmos into a single registry
// =============================================================================

import type { VMType, ChainInfo } from '../../types';
import { EVM_CHAINS } from './evm-chains';

// ---------------------------------------------------------------------------
// Solana clusters
// ---------------------------------------------------------------------------

export const SVM_CLUSTERS: Record<string, ChainInfo> = {
  'mainnet-beta': {
    vm: 'svm', chainId: 'mainnet-beta', name: 'Solana', shortName: 'SOL',
    nativeCurrency: { name: 'Solana', symbol: 'SOL', decimals: 9 },
    rpcUrl: 'https://api.mainnet-beta.solana.com',
    explorerUrl: 'https://solscan.io', isTestnet: false,
  },
  devnet: {
    vm: 'svm', chainId: 'devnet', name: 'Solana Devnet', shortName: 'SOL-DEV',
    nativeCurrency: { name: 'Solana', symbol: 'SOL', decimals: 9 },
    rpcUrl: 'https://api.devnet.solana.com',
    explorerUrl: 'https://solscan.io?cluster=devnet', isTestnet: true,
  },
  testnet: {
    vm: 'svm', chainId: 'testnet', name: 'Solana Testnet', shortName: 'SOL-TEST',
    nativeCurrency: { name: 'Solana', symbol: 'SOL', decimals: 9 },
    rpcUrl: 'https://api.testnet.solana.com',
    explorerUrl: 'https://solscan.io?cluster=testnet', isTestnet: true,
  },
};

// ---------------------------------------------------------------------------
// Bitcoin networks
// ---------------------------------------------------------------------------

export const BTC_NETWORKS: Record<string, ChainInfo> = {
  mainnet: {
    vm: 'bitcoin', chainId: 'mainnet', name: 'Bitcoin', shortName: 'BTC',
    nativeCurrency: { name: 'Bitcoin', symbol: 'BTC', decimals: 8 },
    rpcUrl: 'https://blockstream.info/api',
    explorerUrl: 'https://mempool.space', isTestnet: false,
  },
  testnet: {
    vm: 'bitcoin', chainId: 'testnet', name: 'Bitcoin Testnet', shortName: 'tBTC',
    nativeCurrency: { name: 'Bitcoin', symbol: 'tBTC', decimals: 8 },
    rpcUrl: 'https://blockstream.info/testnet/api',
    explorerUrl: 'https://mempool.space/testnet', isTestnet: true,
  },
  signet: {
    vm: 'bitcoin', chainId: 'signet', name: 'Bitcoin Signet', shortName: 'sBTC',
    nativeCurrency: { name: 'Bitcoin', symbol: 'sBTC', decimals: 8 },
    rpcUrl: 'https://blockstream.info/signet/api',
    explorerUrl: 'https://mempool.space/signet', isTestnet: true,
  },
};

// ---------------------------------------------------------------------------
// SUI networks (Move VM)
// ---------------------------------------------------------------------------

export const SUI_NETWORKS: Record<string, ChainInfo> = {
  mainnet: {
    vm: 'movevm', chainId: 'sui:mainnet', name: 'SUI', shortName: 'SUI',
    nativeCurrency: { name: 'SUI', symbol: 'SUI', decimals: 9 },
    rpcUrl: 'https://fullnode.mainnet.sui.io',
    explorerUrl: 'https://suiscan.xyz/mainnet', isTestnet: false,
  },
  testnet: {
    vm: 'movevm', chainId: 'sui:testnet', name: 'SUI Testnet', shortName: 'SUI-TEST',
    nativeCurrency: { name: 'SUI', symbol: 'SUI', decimals: 9 },
    rpcUrl: 'https://fullnode.testnet.sui.io',
    explorerUrl: 'https://suiscan.xyz/testnet', isTestnet: true,
  },
  devnet: {
    vm: 'movevm', chainId: 'sui:devnet', name: 'SUI Devnet', shortName: 'SUI-DEV',
    nativeCurrency: { name: 'SUI', symbol: 'SUI', decimals: 9 },
    rpcUrl: 'https://fullnode.devnet.sui.io',
    explorerUrl: 'https://suiscan.xyz/devnet', isTestnet: true,
  },
};

// ---------------------------------------------------------------------------
// NEAR networks
// ---------------------------------------------------------------------------

export const NEAR_NETWORKS: Record<string, ChainInfo> = {
  mainnet: {
    vm: 'near', chainId: 'near:mainnet', name: 'NEAR Protocol', shortName: 'NEAR',
    nativeCurrency: { name: 'NEAR', symbol: 'NEAR', decimals: 24 },
    rpcUrl: 'https://rpc.mainnet.near.org',
    explorerUrl: 'https://nearblocks.io', isTestnet: false,
  },
  testnet: {
    vm: 'near', chainId: 'near:testnet', name: 'NEAR Testnet', shortName: 'NEAR-TEST',
    nativeCurrency: { name: 'NEAR', symbol: 'NEAR', decimals: 24 },
    rpcUrl: 'https://rpc.testnet.near.org',
    explorerUrl: 'https://testnet.nearblocks.io', isTestnet: true,
  },
};

// ---------------------------------------------------------------------------
// TRON networks (TVM)
// ---------------------------------------------------------------------------

export const TRON_NETWORKS: Record<string, ChainInfo> = {
  mainnet: {
    vm: 'tvm', chainId: 'tron:mainnet', name: 'TRON', shortName: 'TRX',
    nativeCurrency: { name: 'TRON', symbol: 'TRX', decimals: 6 },
    rpcUrl: 'https://api.trongrid.io',
    explorerUrl: 'https://tronscan.org', isTestnet: false,
  },
  shasta: {
    vm: 'tvm', chainId: 'tron:shasta', name: 'TRON Shasta', shortName: 'TRX-TEST',
    nativeCurrency: { name: 'TRON', symbol: 'TRX', decimals: 6 },
    rpcUrl: 'https://api.shasta.trongrid.io',
    explorerUrl: 'https://shasta.tronscan.org', isTestnet: true,
  },
  nile: {
    vm: 'tvm', chainId: 'tron:nile', name: 'TRON Nile', shortName: 'TRX-NILE',
    nativeCurrency: { name: 'TRON', symbol: 'TRX', decimals: 6 },
    rpcUrl: 'https://nile.trongrid.io',
    explorerUrl: 'https://nile.tronscan.org', isTestnet: true,
  },
};

// ---------------------------------------------------------------------------
// Cosmos / SEI networks
// ---------------------------------------------------------------------------

export const COSMOS_NETWORKS: Record<string, ChainInfo> = {
  'sei-pacific-1': {
    vm: 'cosmos', chainId: 'sei-pacific-1', name: 'SEI', shortName: 'SEI',
    nativeCurrency: { name: 'SEI', symbol: 'SEI', decimals: 6 },
    rpcUrl: 'https://sei-rpc.polkachu.com',
    explorerUrl: 'https://www.seiscan.app', isTestnet: false,
  },
  'cosmoshub-4': {
    vm: 'cosmos', chainId: 'cosmoshub-4', name: 'Cosmos Hub', shortName: 'ATOM',
    nativeCurrency: { name: 'Cosmos', symbol: 'ATOM', decimals: 6 },
    rpcUrl: 'https://cosmos-rpc.polkachu.com',
    explorerUrl: 'https://www.mintscan.io/cosmos', isTestnet: false,
  },
};

// ---------------------------------------------------------------------------
// OTA Remote Data Support
// ---------------------------------------------------------------------------

/** Remote chain data injected via OTA updates (overlays bundled defaults) */
let remoteChainData: ChainInfo[] | null = null;

/**
 * Inject remote chain data from OTA update.
 * When set, getAllChains() returns the remote data instead of bundled defaults.
 * Pass null to revert to bundled defaults.
 */
export function setRemoteData(remote: ChainInfo[] | null): void {
  remoteChainData = remote;
}

/** Get the current data module version info for cache comparison */
export function getDataVersion(): string | null {
  return remoteChainData ? 'remote' : null;
}

// ---------------------------------------------------------------------------
// Unified registry
// ---------------------------------------------------------------------------

/** Get all chains across all VMs */
export function getAllChains(): ChainInfo[] {
  // If remote data is available (from OTA update), use it
  if (remoteChainData) return remoteChainData;

  // Otherwise, use bundled defaults
  const evmChains: ChainInfo[] = Object.values(EVM_CHAINS).map((c) => ({
    vm: 'evm' as VMType,
    chainId: c.chainId,
    name: c.name,
    shortName: c.shortName,
    nativeCurrency: c.nativeCurrency,
    rpcUrl: c.rpcUrl,
    explorerUrl: c.explorerUrl,
    isTestnet: c.isTestnet,
    isL2: c.isL2,
  }));

  return [
    ...evmChains,
    ...Object.values(SVM_CLUSTERS),
    ...Object.values(BTC_NETWORKS),
    ...Object.values(SUI_NETWORKS),
    ...Object.values(NEAR_NETWORKS),
    ...Object.values(TRON_NETWORKS),
    ...Object.values(COSMOS_NETWORKS),
  ];
}

/** Get chains filtered by VM type */
export function getChainsByVM(vm: VMType): ChainInfo[] {
  return getAllChains().filter((c) => c.vm === vm);
}

/** Get a specific chain by VM and chainId */
export function getChain(vm: VMType, chainId: number | string): ChainInfo | undefined {
  return getAllChains().find((c) => c.vm === vm && String(c.chainId) === String(chainId));
}

/** Get mainnet chains only */
export function getMainnetChains(): ChainInfo[] {
  return getAllChains().filter((c) => !c.isTestnet);
}

/** Get explorer transaction URL for any chain */
export function getExplorerTxUrl(vm: VMType, chainId: number | string, txHash: string): string | undefined {
  const chain = getChain(vm, chainId);
  if (!chain?.explorerUrl) return undefined;

  switch (vm) {
    case 'evm': return `${chain.explorerUrl}/tx/${txHash}`;
    case 'svm': return `${chain.explorerUrl}/tx/${txHash}`;
    case 'bitcoin': return `${chain.explorerUrl}/tx/${txHash}`;
    case 'movevm': return `${chain.explorerUrl}/txblock/${txHash}`;
    case 'near': return `${chain.explorerUrl}/txns/${txHash}`;
    case 'tvm': return `${chain.explorerUrl}/#/transaction/${txHash}`;
    case 'cosmos': return `${chain.explorerUrl}/tx/${txHash}`;
    default: return undefined;
  }
}

/** Get explorer address URL for any chain */
export function getExplorerAddressUrl(vm: VMType, chainId: number | string, address: string): string | undefined {
  const chain = getChain(vm, chainId);
  if (!chain?.explorerUrl) return undefined;

  switch (vm) {
    case 'evm': return `${chain.explorerUrl}/address/${address}`;
    case 'svm': return `${chain.explorerUrl}/account/${address}`;
    case 'bitcoin': return `${chain.explorerUrl}/address/${address}`;
    case 'movevm': return `${chain.explorerUrl}/account/${address}`;
    case 'near': return `${chain.explorerUrl}/address/${address}`;
    case 'tvm': return `${chain.explorerUrl}/#/address/${address}`;
    case 'cosmos': return `${chain.explorerUrl}/account/${address}`;
    default: return undefined;
  }
}
