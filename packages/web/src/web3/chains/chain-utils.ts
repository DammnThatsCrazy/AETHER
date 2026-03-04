// =============================================================================
// AETHER SDK — CHAIN UTILITIES
// Address validation, normalization, and VM detection
// =============================================================================

import type { VMType } from '../../types';

// ---------------------------------------------------------------------------
// Address validation per VM
// ---------------------------------------------------------------------------

const EVM_ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;
const SOLANA_ADDRESS_REGEX = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const BITCOIN_LEGACY_REGEX = /^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$/;
const BITCOIN_SEGWIT_REGEX = /^(bc1|tb1)[a-zA-HJ-NP-Z0-9]{25,87}$/;
const BITCOIN_TAPROOT_REGEX = /^(bc1p|tb1p)[a-zA-HJ-NP-Z0-9]{58}$/;
const SUI_ADDRESS_REGEX = /^0x[0-9a-fA-F]{64}$/;
const NEAR_ADDRESS_REGEX = /^[a-z0-9._-]{2,64}(\.near|\.testnet)$|^[0-9a-f]{64}$/;
const TRON_ADDRESS_REGEX = /^T[1-9A-HJ-NP-Za-km-z]{33}$/;
const COSMOS_ADDRESS_REGEX = /^(sei1|cosmos1)[a-z0-9]{38,58}$/;

/** Validate an address for a specific VM */
export function validateAddress(address: string, vm: VMType): boolean {
  switch (vm) {
    case 'evm': return EVM_ADDRESS_REGEX.test(address);
    case 'svm': return SOLANA_ADDRESS_REGEX.test(address);
    case 'bitcoin':
      return BITCOIN_LEGACY_REGEX.test(address)
        || BITCOIN_SEGWIT_REGEX.test(address)
        || BITCOIN_TAPROOT_REGEX.test(address);
    case 'movevm': return SUI_ADDRESS_REGEX.test(address);
    case 'near': return NEAR_ADDRESS_REGEX.test(address);
    case 'tvm': return TRON_ADDRESS_REGEX.test(address);
    case 'cosmos': return COSMOS_ADDRESS_REGEX.test(address);
    default: return false;
  }
}

/** Normalize address format per VM conventions */
export function normalizeAddress(address: string, vm: VMType): string {
  switch (vm) {
    case 'evm': return address.toLowerCase();
    case 'svm': return address; // Base58 is case-sensitive
    case 'bitcoin': return address; // Case-sensitive for Bech32
    case 'movevm': return address.toLowerCase();
    case 'near': return address.toLowerCase();
    case 'tvm': return address; // Base58 is case-sensitive
    case 'cosmos': return address.toLowerCase();
    default: return address;
  }
}

/** Auto-detect VM from address format */
export function detectVMFromAddress(address: string): VMType | undefined {
  if (EVM_ADDRESS_REGEX.test(address)) return 'evm';
  if (SUI_ADDRESS_REGEX.test(address)) return 'movevm'; // Check before Solana (both are hex-ish)
  if (TRON_ADDRESS_REGEX.test(address)) return 'tvm';
  if (NEAR_ADDRESS_REGEX.test(address)) return 'near';
  if (COSMOS_ADDRESS_REGEX.test(address)) return 'cosmos';
  if (BITCOIN_LEGACY_REGEX.test(address) || BITCOIN_SEGWIT_REGEX.test(address) || BITCOIN_TAPROOT_REGEX.test(address)) return 'bitcoin';
  if (SOLANA_ADDRESS_REGEX.test(address)) return 'svm';
  return undefined;
}

/** Get native token info for a VM/chain */
export function getNativeToken(vm: VMType, _chainId?: number | string): { symbol: string; name: string; decimals: number } {
  switch (vm) {
    case 'evm': return { symbol: 'ETH', name: 'Ether', decimals: 18 };
    case 'svm': return { symbol: 'SOL', name: 'Solana', decimals: 9 };
    case 'bitcoin': return { symbol: 'BTC', name: 'Bitcoin', decimals: 8 };
    case 'movevm': return { symbol: 'SUI', name: 'SUI', decimals: 9 };
    case 'near': return { symbol: 'NEAR', name: 'NEAR', decimals: 24 };
    case 'tvm': return { symbol: 'TRX', name: 'TRON', decimals: 6 };
    case 'cosmos': return { symbol: 'ATOM', name: 'Cosmos', decimals: 6 };
    default: return { symbol: 'UNKNOWN', name: 'Unknown', decimals: 18 };
  }
}

/** Get Bitcoin address type */
export function getBitcoinAddressType(address: string): 'legacy' | 'segwit' | 'native_segwit' | 'taproot' | 'unknown' {
  if (BITCOIN_TAPROOT_REGEX.test(address)) return 'taproot';
  if (BITCOIN_SEGWIT_REGEX.test(address)) return 'native_segwit';
  if (/^3[a-km-zA-HJ-NP-Z1-9]{25,34}$/.test(address)) return 'segwit';
  if (BITCOIN_LEGACY_REGEX.test(address)) return 'legacy';
  return 'unknown';
}

/** Truncate address for display (0x1234...abcd) */
export function truncateAddress(address: string, startChars = 6, endChars = 4): string {
  if (address.length <= startChars + endChars) return address;
  return `${address.slice(0, startChars)}...${address.slice(-endChars)}`;
}

/** Check if two addresses are the same (normalized comparison) */
export function addressesEqual(a: string, b: string, vm: VMType): boolean {
  return normalizeAddress(a, vm) === normalizeAddress(b, vm);
}
