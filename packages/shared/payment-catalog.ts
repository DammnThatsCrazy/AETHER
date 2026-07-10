import type { CardActivityBasis } from './card-linked-payments';

export type PaymentCatalogEntityType = 'card_program' | 'issuer' | 'payment_network' | 'chain' | 'currency';
export type PaymentCatalogSource = 'paymentscan' | 'tenant' | 'issuer_api' | 'provider_webhook' | 'manual_seed';

export interface PaymentCatalogEntity {
  id: string;
  source: PaymentCatalogSource;
  entity_type: PaymentCatalogEntityType;
  display_name: string;
  slug: string;
  aliases: string[];
  status: 'active' | 'deprecated' | 'unknown';
  source_url?: string;
  first_seen_at: string;
  last_seen_at: string;
  metadata?: Record<string, unknown>;
}

const seenAt = '2026-07-10T00:00:00.000Z';
const paymentscanUrl = 'https://paymentscan.xyz/';

function entity(entity_type: PaymentCatalogEntityType, display_name: string, slug: string, aliases: string[] = [], metadata?: Record<string, unknown>): PaymentCatalogEntity {
  return { id: `${entity_type}:${slug}`, source: 'paymentscan', entity_type, display_name, slug, aliases, status: 'active', source_url: paymentscanUrl, first_seen_at: seenAt, last_seen_at: seenAt, metadata };
}

export const paymentscanCardPrograms = [
  entity('card_program', 'RedotPay', 'redotpay', ['Red.Pay', 'Redot Pay']),
  entity('card_program', 'KAST', 'kast'),
  entity('card_program', 'EtherFi', 'etherfi', ['ether.fi']),
  entity('card_program', 'Plasma One', 'plasma_one'),
  entity('card_program', 'Karta', 'karta'),
  entity('card_program', 'Tria', 'tria'),
  entity('card_program', 'Gnosis', 'gnosis', ['Gnosis Pay']),
  entity('card_program', 'Cypher', 'cypher'),
  entity('card_program', 'Kolo', 'kolo'),
  entity('card_program', 'Ready', 'ready'),
  entity('card_program', 'BFinance', 'bfinance'),
  entity('card_program', 'MetaMask', 'metamask', ['MetaMask Card']),
  entity('card_program', 'Holyheld', 'holyheld'),
  entity('card_program', 'Bitget Wallet', 'bitget_wallet'),
  entity('card_program', 'Avici', 'avici'),
  entity('card_program', 'SafePal', 'safepal'),
  entity('card_program', 'Solayer', 'solayer'),
  entity('card_program', 'Avalanche Card', 'avalanche_card'),
  entity('card_program', 'Exa', 'exa'),
  entity('card_program', 'Tuyo', 'tuyo'),
  entity('card_program', 'Solflare', 'solflare'),
  entity('card_program', 'Phantom Cash', 'phantom_cash'),
  entity('card_program', 'Hyperbeat', 'hyperbeat'),
] as const satisfies readonly PaymentCatalogEntity[];

export const paymentscanIssuers = [
  entity('issuer', 'Rain', 'rain'),
  entity('issuer', 'Wirex', 'wirex'),
  entity('issuer', 'Bridge', 'bridge'),
  entity('issuer', 'UR', 'ur'),
  entity('issuer', 'Kulipa', 'kulipa'),
  entity('issuer', 'Immersve', 'immersve'),
] as const satisfies readonly PaymentCatalogEntity[];

export const paymentNetworkCatalog = [
  entity('payment_network', 'Visa', 'visa'),
  entity('payment_network', 'Mastercard', 'mastercard', ['MasterCard']),
  entity('payment_network', 'Unknown', 'unknown'),
] as const satisfies readonly PaymentCatalogEntity[];

export const cardLinkedChainCatalog = ['Ethereum', 'TRON', 'BSC', 'Optimism', 'Solana', 'Arbitrum', 'Base', 'Other', 'Unknown']
  .map((name) => entity('chain', name, name.toLowerCase().replace(/ /g, '_')));

export const cardLinkedCurrencyCatalog = ['USDC', 'USDT', 'EURe', 'GBPe', 'USD24', 'liquidUSD', 'Other', 'Unknown']
  .map((name) => entity('currency', name, name.toLowerCase().replace(/ /g, '_')));

export const paymentScanCatalogSeed = [
  ...paymentscanCardPrograms,
  ...paymentscanIssuers,
  ...paymentNetworkCatalog,
  ...cardLinkedChainCatalog,
  ...cardLinkedCurrencyCatalog,
] as const satisfies readonly PaymentCatalogEntity[];

export const paymentCatalogAliasToSlug: Record<string, string> = Object.fromEntries(
  paymentScanCatalogSeed.flatMap((item) => [[item.display_name.toLowerCase(), item.slug], [item.slug.toLowerCase(), item.slug], ...item.aliases.map((alias) => [alias.toLowerCase(), item.slug] as const)]),
);

export function resolvePaymentCatalogSlug(value: string): string | undefined {
  return paymentCatalogAliasToSlug[value.trim().toLowerCase()];
}

export interface PaymentScanBenchmarkObservation {
  catalog_entity_id: string;
  metric_name: string;
  metric_window: string;
  basis: CardActivityBasis | 'benchmark_only';
  confidence: 'weak' | 'probable';
  source: 'paymentscan';
  observed_at: string;
  value?: string;
}
