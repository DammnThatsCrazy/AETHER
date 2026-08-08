import type { ProviderCategory } from './categories';
import type { ProviderAsset, ProviderId, ProviderVisualIdentity, ResolvedProviderIdentity } from './types';

const FALLBACK_REASON = 'No reviewed local provider mark is available in this repository.';

function initials(label: string): string {
  const tokens = label.match(/[A-Za-z0-9]+/g) ?? [];
  const derived = tokens.slice(0, 2).map(token => token[0] ?? '').join('').toUpperCase();
  return derived || '?';
}

function fallbackMark(label: string): ProviderAsset {
  return {
    kind: 'fallback',
    opticalScale: 1,
    fallbackInitials: initials(label),
    reason: FALLBACK_REASON,
  };
}

function provider(
  id: string,
  label: string,
  category: ProviderCategory,
  aliases: readonly string[] = [],
  attributionRequired = true,
): ProviderVisualIdentity {
  const fallbackInitials = initials(label);
  return {
    id,
    label,
    category,
    mark: fallbackMark(label),
    preferredBackground: 'either',
    fallbackInitials,
    attributionRequired,
    trademarkGuidance: attributionRequired
      ? 'Use only an approved local mark. Until one is reviewed and added, render the neutral initials fallback with the provider name.'
      : 'Generic integration type; render the neutral initials fallback and the supplied label.',
    aliases,
  };
}

/**
 * Repository-discovered provider identities. This is intentionally metadata,
 * not a logo pack: none of the third-party marks below are fabricated or loaded
 * remotely. The shared renderer may show a mark only after a reviewed local
 * asset is attached to this registry; otherwise it renders `fallbackInitials`.
 */
export const providerRegistry = {
  // Auth and identity providers used by web, mobile, and payment flows.
  privy: provider('privy', 'Privy', 'identity'),
  google: provider('google', 'Google', 'identity', ['google_auth']),
  google_analytics: provider('google_analytics', 'Google Analytics', 'analytics', ['ga4', 'google_ga4']),
  apple: provider('apple', 'Apple', 'identity', ['apple_sign_in']),
  microsoft: provider('microsoft', 'Microsoft', 'identity', ['azure_ad']),
  auth0: provider('auth0', 'Auth0', 'authentication'),
  okta: provider('okta', 'Okta', 'authentication'),
  clerk: provider('clerk', 'Clerk', 'authentication'),
  magic: provider('magic', 'Magic', 'authentication'),
  walletconnect: provider('walletconnect', 'WalletConnect', 'identity'),

  // Payment rails, card programmes, issuers, and networks.
  stripe: provider('stripe', 'Stripe', 'payments', ['stripe_onramp']),
  coinbase: provider('coinbase', 'Coinbase', 'payments', ['coinbase_exchange']),
  moonpay: provider('moonpay', 'MoonPay', 'payments'),
  bridge: provider('bridge', 'Bridge', 'payments'),
  apple_pay: provider('apple_pay', 'Apple Pay', 'payments'),
  google_pay: provider('google_pay', 'Google Pay', 'payments'),
  paypal: provider('paypal', 'PayPal', 'payments'),
  square: provider('square', 'Square', 'payments'),
  adyen: provider('adyen', 'Adyen', 'payments'),
  visa: provider('visa', 'Visa', 'payments'),
  mastercard: provider('mastercard', 'Mastercard', 'payments', ['master_card']),
  rain: provider('rain', 'Rain', 'payments'),
  wirex: provider('wirex', 'Wirex', 'payments'),
  ur: provider('ur', 'UR', 'payments'),
  kulipa: provider('kulipa', 'Kulipa', 'payments'),
  immersve: provider('immersve', 'Immersve', 'payments'),
  redotpay: provider('redotpay', 'RedotPay', 'payments', ['red_pay', 'redot_pay']),
  kast: provider('kast', 'KAST', 'payments'),
  etherfi: provider('etherfi', 'EtherFi', 'payments', ['ether_fi']),
  plasma_one: provider('plasma_one', 'Plasma One', 'payments'),
  karta: provider('karta', 'Karta', 'payments'),
  tria: provider('tria', 'Tria', 'payments'),
  gnosis: provider('gnosis', 'Gnosis', 'payments', ['gnosis_pay']),
  cypher: provider('cypher', 'Cypher', 'payments'),
  kolo: provider('kolo', 'Kolo', 'payments'),
  ready: provider('ready', 'Ready', 'payments'),
  bfinance: provider('bfinance', 'BFinance', 'payments'),
  metamask: provider('metamask', 'MetaMask', 'identity', ['metamask_card']),
  holyheld: provider('holyheld', 'Holyheld', 'payments'),
  bitget_wallet: provider('bitget_wallet', 'Bitget Wallet', 'identity'),
  avici: provider('avici', 'Avici', 'payments'),
  safepal: provider('safepal', 'SafePal', 'identity'),
  solayer: provider('solayer', 'Solayer', 'payments'),
  avalanche_card: provider('avalanche_card', 'Avalanche Card', 'payments'),
  exa: provider('exa', 'Exa', 'payments'),
  tuyo: provider('tuyo', 'Tuyo', 'payments'),
  solflare: provider('solflare', 'Solflare', 'identity'),
  phantom_cash: provider('phantom_cash', 'Phantom Cash', 'payments'),
  hyperbeat: provider('hyperbeat', 'Hyperbeat', 'payments'),

  // Customer-data, CRM, commerce, and analytics connectors.
  shopify: provider('shopify', 'Shopify', 'commerce'),
  hubspot: provider('hubspot', 'HubSpot', 'commerce'),
  salesforce: provider('salesforce', 'Salesforce', 'commerce'),
  segment: provider('segment', 'Segment', 'analytics'),
  posthog: provider('posthog', 'PostHog', 'analytics'),
  amplitude: provider('amplitude', 'Amplitude', 'analytics'),
  mixpanel: provider('mixpanel', 'Mixpanel', 'analytics'),
  plaid: provider('plaid', 'Plaid', 'identity'),
  braze: provider('braze', 'Braze', 'communications'),
  customerio: provider('customerio', 'Customer.io', 'communications', ['customer_io']),
  iterable: provider('iterable', 'Iterable', 'communications'),
  klaviyo: provider('klaviyo', 'Klaviyo', 'communications'),
  mailchimp: provider('mailchimp', 'Mailchimp', 'communications'),
  postmark: provider('postmark', 'Postmark', 'communications'),
  sendgrid: provider('sendgrid', 'SendGrid', 'communications'),
  intercom: provider('intercom', 'Intercom', 'communications'),
  zendesk: provider('zendesk', 'Zendesk', 'communications'),

  // Collaboration and delivery adapters.
  slack: provider('slack', 'Slack', 'communications'),
  discord: provider('discord', 'Discord', 'communications'),
  telegram: provider('telegram', 'Telegram', 'communications', ['telegram_bot']),
  webhook: provider('webhook', 'Webhook', 'delivery', ['generic_webhook'], false),
  outbound_activation: provider('outbound_activation', 'Outbound activation', 'delivery', [], false),
  agent_assist: provider('agent_assist', 'Agent Assist', 'intelligence', [], false),
  jira: provider('jira', 'Jira', 'productivity'),
  linear: provider('linear', 'Linear', 'productivity'),
  github: provider('github', 'GitHub', 'productivity', ['github_api']),
  gitlab: provider('gitlab', 'GitLab', 'productivity'),
  notion: provider('notion', 'Notion', 'productivity'),
  asana: provider('asana', 'Asana', 'productivity'),

  // Advertising, social, and public intelligence sources.
  meta_ads: provider('meta_ads', 'Meta Ads', 'advertising', ['facebook_ads']),
  google_ads: provider('google_ads', 'Google Ads', 'advertising'),
  tiktok_ads: provider('tiktok_ads', 'TikTok Ads', 'advertising'),
  microsoft_ads: provider('microsoft_ads', 'Microsoft Ads', 'advertising'),
  linkedin_ads: provider('linkedin_ads', 'LinkedIn Ads', 'advertising'),
  x_ads: provider('x_ads', 'X Ads', 'advertising', ['twitter_ads']),
  x: provider('x', 'X', 'social', ['twitter', 'twitter_x']),
  reddit: provider('reddit', 'Reddit', 'social'),
  farcaster_neynar: provider('farcaster_neynar', 'Neynar', 'social', ['farcaster', 'neynar']),
  lens_protocol: provider('lens_protocol', 'Lens Protocol', 'social'),

  // Existing Olympus provider-source catalog (backend identifiers preserved).
  dune: provider('dune', 'Dune', 'blockchain', ['dune_api', 'dune_datashare', 'dune_sim']),
  defi_llama: provider('defi_llama', 'DeFi Llama', 'market-data'),
  coingecko: provider('coingecko', 'CoinGecko', 'market-data'),
  coinmarketcap: provider('coinmarketcap', 'CoinMarketCap', 'market-data'),
  etherscan: provider('etherscan', 'Etherscan', 'blockchain'),
  the_graph: provider('the_graph', 'The Graph', 'blockchain'),
  flipside_crypto: provider('flipside_crypto', 'Flipside Crypto', 'blockchain'),
  covalent_goldrush: provider('covalent_goldrush', 'Covalent GoldRush', 'blockchain'),
  alchemy: provider('alchemy', 'Alchemy', 'blockchain'),
  moralis: provider('moralis', 'Moralis', 'blockchain'),
  transpose: provider('transpose', 'Transpose', 'blockchain'),
  solscan: provider('solscan', 'Solscan', 'blockchain'),
  binance_public: provider('binance_public', 'Binance', 'market-data', ['binance']),
  kraken: provider('kraken', 'Kraken', 'market-data'),
  okx: provider('okx', 'OKX', 'market-data'),
  bybit: provider('bybit', 'Bybit', 'market-data'),
  ccxt: provider('ccxt', 'CCXT', 'market-data'),
  polymarket_gamma: provider('polymarket_gamma', 'Polymarket', 'market-data', ['polymarket', 'polymarket_clob']),
  kalshi: provider('kalshi', 'Kalshi', 'market-data'),
  metaculus: provider('metaculus', 'Metaculus', 'market-data'),
  manifold_markets: provider('manifold_markets', 'Manifold Markets', 'market-data'),
  ens_public: provider('ens_public', 'ENS', 'blockchain', ['ens']),
  snapshot: provider('snapshot', 'Snapshot', 'blockchain'),
  uniswap_subgraph: provider('uniswap_subgraph', 'Uniswap', 'blockchain', ['uniswap']),
  aave_subgraph: provider('aave_subgraph', 'Aave', 'blockchain', ['aave']),
  chainlink_price_feeds: provider('chainlink_price_feeds', 'Chainlink', 'blockchain', ['chainlink']),
  opensea: provider('opensea', 'OpenSea', 'blockchain'),
  reservoir: provider('reservoir', 'Reservoir', 'blockchain'),
  token_terminal: provider('token_terminal', 'Token Terminal', 'market-data'),

  // Runtime and interop providers represented in backend service modules.
  openai: provider('openai', 'OpenAI', 'intelligence'),
  anthropic: provider('anthropic', 'Anthropic', 'intelligence'),
  aws: provider('aws', 'AWS', 'infrastructure'),
  gcp: provider('gcp', 'Google Cloud', 'infrastructure', ['google_cloud']),
  azure: provider('azure', 'Azure', 'infrastructure'),
  cloudflare: provider('cloudflare', 'Cloudflare', 'infrastructure'),
  vercel: provider('vercel', 'Vercel', 'infrastructure'),
  snowflake: provider('snowflake', 'Snowflake', 'infrastructure'),
  bigquery: provider('bigquery', 'BigQuery', 'infrastructure'),
  redshift: provider('redshift', 'Amazon Redshift', 'infrastructure'),
  postgres: provider('postgres', 'PostgreSQL', 'infrastructure', ['postgresql']),
  mongodb: provider('mongodb', 'MongoDB', 'infrastructure'),
  kafka: provider('kafka', 'Apache Kafka', 'infrastructure'),
  wormhole: provider('wormhole', 'Wormhole', 'blockchain'),
  axelar: provider('axelar', 'Axelar', 'blockchain'),
  hyperlane: provider('hyperlane', 'Hyperlane', 'blockchain'),
  chainlink_ccip: provider('chainlink_ccip', 'Chainlink CCIP', 'blockchain'),
} as const satisfies Readonly<Record<string, ProviderVisualIdentity>>;

export type KnownProviderId = keyof typeof providerRegistry;

function normalizeProviderKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

const providerAliases = Object.fromEntries(
  Object.values(providerRegistry).flatMap(identity => [
    [normalizeProviderKey(identity.id), identity.id],
    ...identity.aliases.map(alias => [normalizeProviderKey(alias), identity.id] as const),
  ]),
) as Readonly<Record<string, KnownProviderId>>;

function unknownProviderIdentity(requestedId: string | null): ProviderVisualIdentity {
  const label = requestedId && requestedId.trim() ? requestedId.trim() : 'Unknown provider';
  return {
    id: requestedId ?? 'unknown',
    label,
    category: 'other',
    mark: fallbackMark(label),
    preferredBackground: 'either',
    fallbackInitials: initials(label),
    attributionRequired: false,
    trademarkGuidance: 'Unknown provider: render a neutral fallback and preserve the server-supplied label.',
    aliases: [],
  };
}

/** Resolve backend IDs, human labels, and aliases without guessing an unknown brand. */
export function resolveProvider(providerId: string | null | undefined): ResolvedProviderIdentity {
  const requestedId = providerId?.trim() || null;
  const normalized = requestedId ? normalizeProviderKey(requestedId) : '';
  const resolvedId = normalized ? providerAliases[normalized] : undefined;
  if (resolvedId) {
    return { identity: providerRegistry[resolvedId], known: true, requestedId };
  }
  return { identity: unknownProviderIdentity(requestedId), known: false, requestedId };
}

export function isKnownProviderId(providerId: string): providerId is KnownProviderId {
  return Boolean(providerAliases[normalizeProviderKey(providerId)]);
}

export function providerFallbackInitials(providerId: ProviderId | null | undefined): string {
  return resolveProvider(providerId).identity.fallbackInitials;
}
