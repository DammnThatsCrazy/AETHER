import type { IconDescriptor } from './types';

export type EntityFallback = 'avatar-or-initials' | 'semantic-icon' | 'provider-mark-or-icon';

export interface EntityIdentityDescriptor extends IconDescriptor {
  readonly fallback: EntityFallback;
  readonly shape: 'circle' | 'square' | 'hexagon' | 'rounded-square';
  readonly aliases: readonly string[];
}

/** Canonical graph and Profile360 identity mapping. Provider identity is an optional overlay, never the entity's base icon. */
export const entityIdentities = {
  person: { icon: 'user-round', label: 'Person', decorativeByDefault: true, description: 'A human identity.', fallback: 'avatar-or-initials', shape: 'circle', aliases: ['user', 'human', 'profile'] },
  organization: { icon: 'building-2', label: 'Organization', decorativeByDefault: true, description: 'A company, tenant, or other organization.', fallback: 'avatar-or-initials', shape: 'rounded-square', aliases: ['org', 'tenant', 'business', 'brand', 'governance_org'] },
  agent: { icon: 'bot', label: 'Agent', decorativeByDefault: true, description: 'A software or AI agent.', fallback: 'semantic-icon', shape: 'hexagon', aliases: ['agent_economic_identity', 'agent_profile360'] },
  wallet: { icon: 'wallet-cards', label: 'Wallet', decorativeByDefault: true, description: 'A blockchain wallet.', fallback: 'semantic-icon', shape: 'hexagon', aliases: [] },
  device: { icon: 'smartphone', label: 'Device', decorativeByDefault: true, description: 'A client device.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: [] },
  contract: { icon: 'file-code-2', label: 'Contract', decorativeByDefault: true, description: 'A smart or legal contract.', fallback: 'semantic-icon', shape: 'hexagon', aliases: [] },
  campaign: { icon: 'megaphone', label: 'Campaign', decorativeByDefault: true, description: 'A marketing campaign.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['ad_campaign'] },
  cluster: { icon: 'share-2', label: 'Cluster', decorativeByDefault: true, description: 'A resolved identity or graph cluster.', fallback: 'semantic-icon', shape: 'hexagon', aliases: ['tier_group'] },
  account: { icon: 'landmark', label: 'Account', decorativeByDefault: true, description: 'A financial or trading account.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['plaid_account', 'trading_account', 'trading_subaccount', 'collateral_account'] },
  identity: { icon: 'badge-check', label: 'Identity', decorativeByDefault: true, description: 'A verified or linked identity.', fallback: 'semantic-icon', shape: 'circle', aliases: ['social_profile', 'credit_profile'] },
  unresolved: { icon: 'circle-help', label: 'Unresolved entity', decorativeByDefault: true, description: 'An entity that is not resolved yet.', fallback: 'semantic-icon', shape: 'circle', aliases: ['unknown'] },
  data_source: { icon: 'database', label: 'Data source', decorativeByDefault: true, description: 'A source system or ingestion record.', fallback: 'provider-mark-or-icon', shape: 'rounded-square', aliases: ['connector_checkpoint', 'source'] },
  credential: { icon: 'key-round', label: 'Credential', decorativeByDefault: true, description: 'A credential reference, never the secret itself.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['venue_credential_reference'] },
  transaction: { icon: 'arrow-left-right', label: 'Transaction', decorativeByDefault: true, description: 'A transaction or settlement.', fallback: 'semantic-icon', shape: 'hexagon', aliases: ['payment', 'payment_intent', 'settlement_event', 'funding_payment', 'trading_fee'] },
  message_event: { icon: 'messages-square', label: 'Message or event', decorativeByDefault: true, description: 'An event, message, or operational receipt.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['event', 'session', 'resource', 'approval', 'execution_decision'] },
  application: { icon: 'app-window', label: 'Application', decorativeByDefault: true, description: 'An application or service.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['service'] },
  commerce: { icon: 'shopping-bag', label: 'Commerce entity', decorativeByDefault: true, description: 'An invoice, subscription, plan, marketplace, or commerce entity.', fallback: 'semantic-icon', shape: 'rounded-square', aliases: ['invoice', 'subscription', 'plan', 'marketplace', 'economic_resource'] },
  chain: { icon: 'blocks', label: 'Blockchain network', decorativeByDefault: true, description: 'A chain, token, protocol, exchange, or yield platform.', fallback: 'semantic-icon', shape: 'hexagon', aliases: ['chain', 'token', 'protocol', 'exchange', 'yield_platform', 'dex', 'staking_platform'] },
  media: { icon: 'newspaper', label: 'Media entity', decorativeByDefault: true, description: 'A media entity or content source.', fallback: 'provider-mark-or-icon', shape: 'rounded-square', aliases: ['media_entity'] },
  trading: { icon: 'chart-candlestick', label: 'Trading entity', decorativeByDefault: true, description: 'A venue, instrument, order, position, or risk policy.', fallback: 'semantic-icon', shape: 'hexagon', aliases: ['trading_venue', 'venue_deployment', 'derivative_instrument', 'derivative_market', 'market_index', 'trading_vault', 'derivatives_order', 'derivatives_fill', 'derivatives_position', 'position_epoch', 'margin_snapshot', 'liquidation_event', 'price_observation', 'risk_policy', 'trading_strategy', 'strategy_version', 'reconciliation_variance'] },
} as const satisfies Readonly<Record<string, EntityIdentityDescriptor>>;

export type EntityIdentity = keyof typeof entityIdentities;

function normalizeEntityType(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

export function resolveEntityIdentity(entityType: string | null | undefined): EntityIdentityDescriptor {
  const normalized = entityType ? normalizeEntityType(entityType) : '';
  for (const identity of Object.values(entityIdentities)) {
    const aliases: readonly string[] = identity.aliases;
    if (normalized === identity.label.toLowerCase().replace(/[\s-]+/g, '_') || aliases.includes(normalized)) return identity;
  }
  return entityIdentities.unresolved;
}
