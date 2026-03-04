// =============================================================================
// AETHER SDK — WALLET LABELS DATABASE
// Known addresses: CEX hot/cold wallets, protocol treasuries, whales
// =============================================================================

import type { AddressLabel, VMType } from '../../types';

interface LabelEntry {
  name: string;
  category: AddressLabel['category'];
  subcategory?: string;
  confidence: number;
}

// ---------------------------------------------------------------------------
// OTA Remote Data Support
// ---------------------------------------------------------------------------

/** Remote label data injected via OTA updates */
let remoteLabelData: Record<string, LabelEntry> | null = null;

/**
 * Inject remote wallet label data from OTA update.
 * When set, lookups use remote data instead of bundled defaults.
 * Pass null to revert to bundled defaults.
 */
export function setRemoteData(remote: Record<string, LabelEntry> | null): void {
  remoteLabelData = remote;
}

/** Get the active labels database (remote if available, otherwise bundled) */
function getActiveLabels(): Record<string, LabelEntry> {
  return remoteLabelData ?? ETH_LABELS;
}

// Known Ethereum mainnet labels (chainId: 1)
const ETH_LABELS: Record<string, LabelEntry> = {
  // Binance
  '0x28c6c06298d514db089934071355e5743bf21d60': { name: 'Binance 14', category: 'cex', subcategory: 'binance', confidence: 1.0 },
  '0x21a31ee1afc51d94c2efccaa2092ad1028285549': { name: 'Binance 7', category: 'cex', subcategory: 'binance', confidence: 1.0 },
  '0xdfd5293d8e347dfe59e90efd55b2956a1343963d': { name: 'Binance 8', category: 'cex', subcategory: 'binance', confidence: 1.0 },
  '0x56eddb7aa87536c09ccc2793473599fd21a8b17f': { name: 'Binance 16', category: 'cex', subcategory: 'binance', confidence: 1.0 },
  '0xf977814e90da44bfa03b6295a0616a897441acec': { name: 'Binance 8 (BSC)', category: 'cex', subcategory: 'binance', confidence: 1.0 },
  // Coinbase
  '0x71660c4005ba85c37ccec55d0c4493e66fe775d3': { name: 'Coinbase 1', category: 'cex', subcategory: 'coinbase', confidence: 1.0 },
  '0x503828976d22510aad0201ac7ec88293211d23da': { name: 'Coinbase 2', category: 'cex', subcategory: 'coinbase', confidence: 1.0 },
  '0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43': { name: 'Coinbase 10', category: 'cex', subcategory: 'coinbase', confidence: 1.0 },
  // Kraken
  '0x2910543af39aba0cd09dbb2d50200b3e800a63d2': { name: 'Kraken 13', category: 'cex', subcategory: 'kraken', confidence: 1.0 },
  '0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0': { name: 'Kraken 4', category: 'cex', subcategory: 'kraken', confidence: 1.0 },
  // OKX
  '0x6cc5f688a315f3dc28a7781717a9a798a59fda7b': { name: 'OKX 7', category: 'cex', subcategory: 'okx', confidence: 1.0 },
  '0x236f233dBf78341d7B38e30e6F2A3CbA0faf7Cee': { name: 'OKX', category: 'cex', subcategory: 'okx', confidence: 0.9 },
  // Bybit
  '0xf89d7b9c864f589bbf53a82105107622b35eaa40': { name: 'Bybit', category: 'cex', subcategory: 'bybit', confidence: 1.0 },
  // KuCoin
  '0xd6216fc19db775df9774a6e33526131da7d19a2c': { name: 'KuCoin', category: 'cex', subcategory: 'kucoin', confidence: 1.0 },
  // Gate.io
  '0x0d0707963952f2fba59dd06f2b425ace40b492fe': { name: 'Gate.io 1', category: 'cex', subcategory: 'gate', confidence: 1.0 },
  // Huobi / HTX
  '0xab5c66752a9e8167967685f1450532fb96d5d24f': { name: 'Huobi 1', category: 'cex', subcategory: 'huobi', confidence: 1.0 },
  // Gemini
  '0xd24400ae8bfebb18ca49be86258a3c749cf46853': { name: 'Gemini 4', category: 'cex', subcategory: 'gemini', confidence: 1.0 },
  // Bitfinex
  '0x876eabf441b2ee5b5b0554fd502a8e0600950cfa': { name: 'Bitfinex 5', category: 'cex', subcategory: 'bitfinex', confidence: 1.0 },
  // Protocol treasuries
  '0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e': { name: 'Yearn Finance', category: 'protocol', confidence: 1.0 },
  '0x40d73df4f99bae688ce3c23a01022224fe16c7b2': { name: 'Gnosis Safe: Deployer', category: 'protocol', confidence: 1.0 },
  // Bridge contracts
  '0x3ee18b2214aff97000d974cf647e7c347e8fa585': { name: 'Wormhole: Portal', category: 'bridge', confidence: 1.0 },
  '0x99c9fc46f92e8a1c0dec1b1747d010903e884be1': { name: 'Optimism: Gateway', category: 'bridge', confidence: 1.0 },
  '0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a': { name: 'Arbitrum: Bridge', category: 'bridge', confidence: 1.0 },
  '0x3154cf16ccdb4c6d922629664174b904d80f2c35': { name: 'Base: Bridge', category: 'bridge', confidence: 1.0 },
  // DAO treasuries
  '0x0bef27feb58e857046d630b2c03dfb7bae567494': { name: 'Uniswap: Timelock', category: 'dao', confidence: 1.0 },
  '0x10a19e7ee7d7f8a52822f6817de8ea18204f2e4f': { name: 'Lido: Treasury', category: 'dao', confidence: 1.0 },
};

/** Get label for an address on a specific chain */
export function getAddressLabel(chainId: number | string, address: string, _vm?: VMType): AddressLabel | null {
  const addr = address.toLowerCase();
  const chainStr = String(chainId);
  const labels = getActiveLabels();

  // Currently we have labels for Ethereum mainnet
  if (chainStr === '1' || chainStr === '56') {
    const label = labels[addr];
    if (label) {
      return {
        address: addr, name: label.name, category: label.category,
        subcategory: label.subcategory, confidence: label.confidence,
        chainId, vm: 'evm',
      };
    }
  }

  return null;
}

/** Check if an address is a known exchange wallet */
export function isExchangeAddress(chainId: number | string, address: string): boolean {
  const label = getAddressLabel(chainId, address);
  return label?.category === 'cex';
}

/** Check if an address is a known protocol/contract */
export function isProtocolAddress(chainId: number | string, address: string): boolean {
  const label = getAddressLabel(chainId, address);
  return label?.category === 'protocol' || label?.category === 'bridge' || label?.category === 'dao';
}

/** Get exchange name for a known exchange address */
export function getExchangeName(chainId: number | string, address: string): string | null {
  const label = getAddressLabel(chainId, address);
  if (label?.category === 'cex') return label.subcategory ?? label.name;
  return null;
}

/** Get all known labels for a chain */
export function getAllLabelsForChain(_chainId: number | string): AddressLabel[] {
  const labels = getActiveLabels();
  return Object.entries(labels).map(([addr, label]) => ({
    address: addr, name: label.name, category: label.category,
    subcategory: label.subcategory, confidence: label.confidence,
    chainId: 1, vm: 'evm' as VMType,
  }));
}
