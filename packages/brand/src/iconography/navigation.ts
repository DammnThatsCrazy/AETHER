import type { IconDescriptor } from './types';

export interface NavigationDestinationDescriptor extends IconDescriptor {
  readonly product: 'aether' | 'kyber';
  readonly path: string;
}

/**
 * Application-shell destinations discovered from both current sidebars. Detail
 * routes inherit their nearest destination icon; a renderer must still set a
 * text label or tooltip when the navigation is collapsed.
 */
export const navigationDestinations = {
  'aether-users': { product: 'aether', path: '/users', icon: 'users-round', label: 'Users', decorativeByDefault: true, description: 'Customer identities and profiles.' },
  'aether-campaigns': { product: 'aether', path: '/campaigns', icon: 'megaphone', label: 'Campaigns', decorativeByDefault: true, description: 'Campaign intelligence.' },
  'aether-graph': { product: 'aether', path: '/graph', icon: 'network', label: 'Graph', decorativeByDefault: true, description: 'Relationship graph.' },
  'aether-noesis': { product: 'aether', path: '/noesis', icon: 'brain-circuit', label: 'Noesis', decorativeByDefault: true, description: 'Intelligence workspace.' },
  'aether-onboarding': { product: 'aether', path: '/onboarding', icon: 'list-checks', label: 'Onboarding', decorativeByDefault: true, description: 'Implementation onboarding.' },
  'aether-notifications': { product: 'aether', path: '/notifications', icon: 'bell', label: 'Notifications', decorativeByDefault: true, description: 'Notification center.' },
  'aether-settings': { product: 'aether', path: '/settings', icon: 'settings-2', label: 'Settings', decorativeByDefault: true, description: 'Workspace settings.' },
  'aether-billing': { product: 'aether', path: '/billing', icon: 'receipt-text', label: 'Billing', decorativeByDefault: true, description: 'Billing and invoices.' },
  'aether-profile': { product: 'aether', path: '/me', icon: 'circle-user-round', label: 'Profile', decorativeByDefault: true, description: 'Current user profile.' },
  'aether-audit-exports': { product: 'aether', path: '/audit-exports', icon: 'file-check-2', label: 'Audit exports', decorativeByDefault: true, description: 'Audit-ready data exports.' },
  'aether-value-review': { product: 'aether', path: '/value-review', icon: 'chart-no-axes-combined', label: 'Value review', decorativeByDefault: true, description: 'Value measurement review.' },
  'aether-security': { product: 'aether', path: '/security', icon: 'shield-check', label: 'Security', decorativeByDefault: true, description: 'Security controls.' },
  'aether-system-status': { product: 'aether', path: '/system-status', icon: 'activity-square', label: 'System status', decorativeByDefault: true, description: 'System health.' },
  'aether-data-quality': { product: 'aether', path: '/data-quality', icon: 'badge-check', label: 'Data quality', decorativeByDefault: true, description: 'Data quality controls.' },
  'aether-integrations': { product: 'aether', path: '/integrations', icon: 'plug-zap', label: 'Integrations', decorativeByDefault: true, description: 'External provider connections.' },
  'aether-imports': { product: 'aether', path: '/imports', icon: 'file-up', label: 'Imports', decorativeByDefault: true, description: 'Data imports.' },
  'aether-deployments': { product: 'aether', path: '/deployments', icon: 'rocket', label: 'Deployments', decorativeByDefault: true, description: 'Agent deployments.' },
  'aether-payment-rails': { product: 'aether', path: '/payment-rails', icon: 'credit-card', label: 'Payment rails', decorativeByDefault: true, description: 'Payment rail observability.' },
  'aether-ai-efficiency': { product: 'aether', path: '/ai-efficiency', icon: 'gauge', label: 'AI efficiency', decorativeByDefault: true, description: 'AI efficiency analysis.' },
  'aether-activation': { product: 'aether', path: '/activation', icon: 'circle-power', label: 'Activation', decorativeByDefault: true, description: 'Product activation.' },
  'aether-journey': { product: 'aether', path: '/users/:profileId/journey', icon: 'route', label: 'Journey', decorativeByDefault: true, description: 'Customer journey explorer.' },
  'aether-campaign-intelligence': { product: 'aether', path: '/campaign-intelligence', icon: 'radar', label: 'Campaign intelligence', decorativeByDefault: true, description: 'Campaign source and mapping intelligence.' },
  'aether-rewards': { product: 'aether', path: '/rewards', icon: 'award', label: 'Rewards', decorativeByDefault: true, description: 'Reward decisions and approvals.' },
  'aether-delivery': { product: 'aether', path: '/delivery', icon: 'send', label: 'Delivery history', decorativeByDefault: true, description: 'Outcome delivery history.' },
  'aether-stablecoins': { product: 'aether', path: '/stablecoins', icon: 'coins', label: 'Stablecoins', decorativeByDefault: true, description: 'Stablecoin intelligence.' },
  'aether-derivatives': { product: 'aether', path: '/derivatives', icon: 'chart-candlestick', label: 'Derivatives', decorativeByDefault: true, description: 'Derivatives intelligence.' },
  'aether-agent-access': { product: 'aether', path: '/agent-access', icon: 'bot-key', label: 'Agent access', decorativeByDefault: true, description: 'Agent access controls.' },
  'aether-interop': { product: 'aether', path: '/interop', icon: 'waypoints', label: 'Interoperability', decorativeByDefault: true, description: 'Interoperability traffic.' },

  'kyber-mission': { product: 'kyber', path: '/mission', icon: 'crosshair', label: 'Mission', decorativeByDefault: true, description: 'Operator mission control.' },
  'kyber-graph': { product: 'kyber', path: '/kyber-graph', icon: 'git-fork', label: 'Kyber Graph', decorativeByDefault: true, description: 'Operator graph.' },
  'kyber-tenant-mirror': { product: 'kyber', path: '/tenant-mirror', icon: 'panels-top-left', label: 'Tenant Mirror', decorativeByDefault: true, description: 'Tenant mirror view.' },
  'kyber-exceptions': { product: 'kyber', path: '/kyber-exceptions', icon: 'siren', label: 'Exceptions', decorativeByDefault: true, description: 'Operator exceptions.' },
  'kyber-commands': { product: 'kyber', path: '/kyber-commands', icon: 'terminal-square', label: 'Commands', decorativeByDefault: true, description: 'Command receipts.' },
  'kyber-live': { product: 'kyber', path: '/live', icon: 'radio-tower', label: 'Live', decorativeByDefault: true, description: 'Live operational state.' },
  'kyber-command': { product: 'kyber', path: '/command', icon: 'command', label: 'Command', decorativeByDefault: true, description: 'Command center.' },
  'kyber-review': { product: 'kyber', path: '/review', icon: 'clipboard-check', label: 'Review', decorativeByDefault: true, description: 'Review queue.' },
  'kyber-entities': { product: 'kyber', path: '/entities', icon: 'boxes', label: 'Entities', decorativeByDefault: true, description: 'Entity operations.' },
  'kyber-noesis': { product: 'kyber', path: '/noesis', icon: 'sparkles', label: 'Noesis', decorativeByDefault: true, description: 'Operator intelligence.' },
  'kyber-tenants': { product: 'kyber', path: '/tenants', icon: 'building-2', label: 'Tenants', decorativeByDefault: true, description: 'Tenant administration.' },
  'kyber-imports': { product: 'kyber', path: '/imports', icon: 'database-zap', label: 'Import Engine', decorativeByDefault: true, description: 'Import engine operations.' },
  'kyber-implementation': { product: 'kyber', path: '/implementation', icon: 'clipboard-list', label: 'Implementation', decorativeByDefault: true, description: 'Customer implementation.' },
  'kyber-investigations': { product: 'kyber', path: '/investigations', icon: 'search-check', label: 'Investigations', decorativeByDefault: true, description: 'Operational investigations.' },
  'kyber-cis': { product: 'kyber', path: '/cis', icon: 'scan-search', label: 'CIS', decorativeByDefault: true, description: 'Continuous intelligence system.' },
  'kyber-packages': { product: 'kyber', path: '/packages', icon: 'package-check', label: 'Packages', decorativeByDefault: true, description: 'Solution packages.' },
  'kyber-deployment-readiness': { product: 'kyber', path: '/deployment-readiness', icon: 'clipboard-signature', label: 'Deploy ready', decorativeByDefault: true, description: 'Deployment readiness.' },
  'kyber-reliability': { product: 'kyber', path: '/reliability', icon: 'heart-pulse', label: 'Reliability', decorativeByDefault: true, description: 'Reliability operations.' },
  'kyber-journey-health': { product: 'kyber', path: '/journey-health', icon: 'map-pinned', label: 'Journey health', decorativeByDefault: true, description: 'Journey health operations.' },
  'kyber-intelligence-quality': { product: 'kyber', path: '/intelligence-quality', icon: 'circle-gauge', label: 'Intelligence quality', decorativeByDefault: true, description: 'Intelligence quality.' },
  'kyber-suggestions': { product: 'kyber', path: '/intelligence/suggestions', icon: 'lightbulb', label: 'Suggestions', decorativeByDefault: true, description: 'Intelligence suggestions.' },
  'kyber-semantic-ops': { product: 'kyber', path: '/intelligence/semantic-review', icon: 'braces', label: 'Semantic Ops', decorativeByDefault: true, description: 'Semantic review.' },
  'kyber-traffic-intelligence': { product: 'kyber', path: '/measurement/traffic-intelligence', icon: 'traffic-cone', label: 'Traffic Intel', decorativeByDefault: true, description: 'Traffic intelligence.' },
  'kyber-connectors': { product: 'kyber', path: '/connectors', icon: 'cable', label: 'Connectors', decorativeByDefault: true, description: 'Connector health.' },
  'kyber-agent-telemetry': { product: 'kyber', path: '/agent-telemetry', icon: 'cpu', label: 'Agent Telemetry', decorativeByDefault: true, description: 'Agent telemetry.' },
  'kyber-payment-rails': { product: 'kyber', path: '/payment-rails', icon: 'landmark', label: 'Payment Rails', decorativeByDefault: true, description: 'Payment-rail operations.' },
  'kyber-ai-efficiency': { product: 'kyber', path: '/ai-efficiency', icon: 'badge-dollar-sign', label: 'AI Efficiency', decorativeByDefault: true, description: 'AI economic operations.' },
  'kyber-targeting': { product: 'kyber', path: '/targeting', icon: 'focus', label: 'Targeting', decorativeByDefault: true, description: 'Targeting intelligence.' },
  'kyber-dune-feeder': { product: 'kyber', path: '/dune-feeder', icon: 'database-backup', label: 'Dune Feeder', decorativeByDefault: true, description: 'Dune data feed.' },
  'kyber-revops': { product: 'kyber', path: '/revops', icon: 'hand-coins', label: 'RevOps', decorativeByDefault: true, description: 'Revenue operations.' },
  'kyber-sales-readiness': { product: 'kyber', path: '/sales-readiness', icon: 'badge-percent', label: 'Sales Ready', decorativeByDefault: true, description: 'Sales readiness.' },
  'kyber-pricing': { product: 'kyber', path: '/pricing-architecture', icon: 'tags', label: 'Pricing', decorativeByDefault: true, description: 'Pricing architecture.' },
  'kyber-gtm-materials': { product: 'kyber', path: '/gtm-materials', icon: 'folder-kanban', label: 'GTM Materials', decorativeByDefault: true, description: 'Go-to-market materials.' },
  'kyber-personas': { product: 'kyber', path: '/buyer-personas', icon: 'contact-round', label: 'Personas', decorativeByDefault: true, description: 'Buyer personas.' },
  'kyber-roi-calculators': { product: 'kyber', path: '/roi-calculators', icon: 'calculator', label: 'ROI Calcs', decorativeByDefault: true, description: 'ROI calculators.' },
  'kyber-fraud-networks': { product: 'kyber', path: '/fraud-networks', icon: 'fingerprint-pattern', label: 'Fraud Networks', decorativeByDefault: true, description: 'Fraud networks.' },
  'kyber-flow-trace': { product: 'kyber', path: '/fraud-networks/flow-trace', icon: 'workflow', label: 'Flow Trace', decorativeByDefault: true, description: 'Fraud-flow trace.' },
  'kyber-security': { product: 'kyber', path: '/security', icon: 'shield-alert', label: 'Security', decorativeByDefault: true, description: 'Security operations.' },
  'kyber-diagnostics': { product: 'kyber', path: '/diagnostics', icon: 'stethoscope', label: 'Diagnostics', decorativeByDefault: true, description: 'Diagnostic tools.' },
  'kyber-lab': { product: 'kyber', path: '/lab', icon: 'flask-conical', label: 'Lab', decorativeByDefault: true, description: 'Operator laboratory.' },
} as const satisfies Readonly<Record<string, NavigationDestinationDescriptor>>;

export type NavigationDestination = keyof typeof navigationDestinations;

export function navigationDestinationFor(
  product: NavigationDestinationDescriptor['product'],
  path: string,
): NavigationDestinationDescriptor | undefined {
  return Object.values(navigationDestinations).find(destination => destination.product === product && destination.path === path);
}
