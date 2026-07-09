import { Badge } from '@aether/ui';
import type { AgentDeploymentStatus, ExternalPlatform } from '@aether/shared';

export const OBSERVABILITY_COPY =
  'Aether observes deployments — it does not publish, host, or execute agents.';

const STATUS_VARIANTS: Record<AgentDeploymentStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  active: 'success',
  paused: 'warning',
  error: 'danger',
  revoked: 'danger',
  archived: 'default',
};

export function DeploymentStatusBadge({ status }: { readonly status: AgentDeploymentStatus }) {
  return <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>{status}</Badge>;
}

const PLATFORM_LABELS: Record<ExternalPlatform, string> = {
  web_widget: 'Web Widget',
  mobile_app: 'Mobile App',
  discord_bot: 'Discord Bot',
  telegram_bot: 'Telegram Bot',
  slack_app: 'Slack App',
  shopify_app: 'Shopify App',
  salesforce_app: 'Salesforce App',
  custom_marketplace: 'Custom Marketplace',
  wallet_app: 'Wallet App',
  browser_extension: 'Browser Extension',
  mcp_server: 'MCP Server',
  backend_worker: 'Backend Worker',
  api_agent: 'API Agent',
  unknown: 'Unknown',
};

export function platformLabel(platform: ExternalPlatform): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

export function PlatformBadge({ platform }: { readonly platform: ExternalPlatform }) {
  return <Badge variant="info">{platformLabel(platform)}</Badge>;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
