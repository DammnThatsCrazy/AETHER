import { NavLink } from 'react-router-dom';
import { cn } from '@kyber/lib/utils';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';
import {
  KyberLockup,
  NavigationIcon,
  resolveDestinationAvailability,
  useBuildInfo,
  useCapabilities,
  type NavigationIconProps,
  type CapabilityRequirement,
} from '@aether/ui';

type EnvFlag = Parameters<typeof isFeatureEnabled>[0];
type NavigationDestination = NavigationIconProps['destination'];

interface NavItem {
  readonly path: string;
  readonly label: string;
  /** Shared semantic taxonomy; visual geometry lives only in @aether/ui. */
  readonly destination: NavigationDestination;
  /** Backend capability this destination requires (domain excluded / flag off → hidden). */
  readonly requirement?: CapabilityRequirement;
  /** Frontend-only feature flag (no backend capability mapping). */
  readonly envFlag?: EnvFlag;
}

export const KYBER_NAV_ITEMS: readonly NavItem[] = [
  { path: '/mission',         label: 'Mission',         destination: 'kyber-mission' },
  // Kyber's own operating plane. Deliberately carries no `requirement`:
  // CapabilityRequirement expresses `{ domain }` or `{ flag }`, and the real
  // gate on all four is a backend capability string plus — for the tenant
  // surfaces — an active, purpose-bound access scope that is per tenant and
  // therefore unknowable at nav time. Inventing a domain to hide the entry
  // would be a guess dressed as a permission; each page renders its own
  // forbidden state from what the backend actually returns instead. Routing is
  // not a grant.
  { path: '/kyber-graph',     label: 'Kyber Graph',     destination: 'kyber-graph' },
  { path: '/tenant-mirror',   label: 'Tenant Mirror',   destination: 'kyber-tenant-mirror' },
  { path: '/kyber-exceptions', label: 'Exceptions',     destination: 'kyber-exceptions' },
  { path: '/kyber-commands',  label: 'Commands',        destination: 'kyber-commands' },
  { path: '/rights-operations', label: 'Rights Ops',    destination: 'kyber-security' },
  { path: '/live',            label: 'Live',            destination: 'kyber-live' },
  { path: '/command',         label: 'Command',         destination: 'kyber-command' },
  { path: '/review',          label: 'Review',          destination: 'kyber-review' },
  { path: '/entities',        label: 'Entities',        destination: 'kyber-entities' },
  { path: '/noesis',          label: 'Noesis',          destination: 'kyber-noesis' },
  { path: '/tenants',         label: 'Tenants',         destination: 'kyber-tenants' },
  { path: '/imports',         label: 'Import Engine',   destination: 'kyber-imports' },
  { path: '/implementation', label: 'Implementation',   destination: 'kyber-implementation' },
  { path: '/investigations',  label: 'Investigations',  destination: 'kyber-investigations' },
  { path: '/cis',             label: 'CIS',             destination: 'kyber-cis' },
  { path: '/packages',        label: 'Packages',        destination: 'kyber-packages' },
  { path: '/deployment-readiness', label: 'Deploy Ready', destination: 'kyber-deployment-readiness' },
  { path: '/reliability',     label: 'Reliability',     destination: 'kyber-reliability' },
  { path: '/journey-health',  label: 'Journey Health',  destination: 'kyber-journey-health' },
  { path: '/intelligence-quality', label: 'Intel Quality', destination: 'kyber-intelligence-quality' },
  { path: '/intelligence/suggestions', label: 'Suggestions', destination: 'kyber-suggestions', requirement: { flag: 'suggestions_enabled' } },
  { path: '/intelligence/semantic-review', label: 'Semantic Ops', destination: 'kyber-semantic-ops' },
  { path: '/measurement/traffic-intelligence', label: 'Traffic Intel', destination: 'kyber-traffic-intelligence' },
  { path: '/connectors', label: 'Connectors', destination: 'kyber-connectors', requirement: { flag: 'connectors_enabled' } },
  { path: '/agent-telemetry', label: 'Agent Telemetry', destination: 'kyber-agent-telemetry', envFlag: 'enableExternalAgentTelemetry' },
  { path: '/payment-rails', label: 'Payment Rails', destination: 'kyber-payment-rails', requirement: { domain: 'payments' }, envFlag: 'enablePaymentRails' },
  { path: '/ai-efficiency', label: 'AI Efficiency', destination: 'kyber-ai-efficiency', requirement: { domain: 'economic' }, envFlag: 'enableAiEfficiency' },
  { path: '/targeting', label: 'Targeting', destination: 'kyber-targeting', envFlag: 'enableTargetingIntelligence' },
  // Provider Runtime reuses the 'kyber-connectors' icon taxonomy — adding a brand
  // destination for it would touch packages/brand (out of scope). Frontend-only
  // flag mirrors the backend KYBER_PROVIDER_RUNTIME_UI_ENABLED; the admin
  // provider-connections routes it reads mount when EITHER that flag OR
  // KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED is set.
  { path: '/provider-connections', label: 'Provider Runtime', destination: 'kyber-connectors', envFlag: 'enableProviderRuntime' },
  // Model-runtime control-plane admin surfaces (ADR-008 D8/D9). Frontend-only
  // flag mirrors the Aether harness surface (enableModelHarness, default OFF);
  // the backend /v1/model-runtime/* endpoints are the real grant gate. Icon
  // taxonomy reuses existing kyber destinations — adding brand destinations
  // would touch packages/brand (out of scope), same as Provider Runtime.
  { path: '/model-runtime/registry', label: 'Model Registry', destination: 'kyber-packages', envFlag: 'enableModelHarness' },
  { path: '/model-runtime/health', label: 'Model Health', destination: 'kyber-reliability', envFlag: 'enableModelHarness' },
  { path: '/model-runtime/entitlements', label: 'Model Entitlements', destination: 'kyber-tenants', envFlag: 'enableModelHarness' },
  { path: '/model-runtime/usage', label: 'Model Usage', destination: 'kyber-ai-efficiency', envFlag: 'enableModelHarness' },
  { path: '/model-runtime/traces', label: 'Model Traces', destination: 'kyber-flow-trace', envFlag: 'enableModelHarness' },
  { path: '/dune-feeder', label: 'Dune Feeder', destination: 'kyber-dune-feeder' },
  { path: '/revops',          label: 'RevOps',          destination: 'kyber-revops' },
  { path: '/sales-readiness', label: 'Sales Ready',     destination: 'kyber-sales-readiness' },
  { path: '/pricing-architecture', label: 'Pricing',    destination: 'kyber-pricing' },
  { path: '/gtm-materials', label: 'GTM Materials',     destination: 'kyber-gtm-materials' },
  { path: '/buyer-personas', label: 'Personas',         destination: 'kyber-personas' },
  { path: '/roi-calculators', label: 'ROI Calcs',       destination: 'kyber-roi-calculators' },
  { path: '/fraud-networks',  label: 'Fraud Networks',  destination: 'kyber-fraud-networks' },
  { path: '/fraud-networks/flow-trace', label: 'Flow Trace', destination: 'kyber-flow-trace' },
  { path: '/security',        label: 'Security',        destination: 'kyber-security' },
  { path: '/diagnostics',     label: 'Diagnostics',     destination: 'kyber-diagnostics' },
  { path: '/lab',             label: 'Lab',             destination: 'kyber-lab' },
];

export function Sidebar() {
  const { capabilities } = useCapabilities();
  const build = useBuildInfo();

  const items = KYBER_NAV_ITEMS.filter(item => {
    // Frontend-only flags gate first (no backend capability signal for these).
    if (item.envFlag && !isFeatureEnabled(item.envFlag)) return false;
    // Then the backend capability contract: hide excluded domains / off flags.
    return resolveDestinationAvailability(capabilities, item.requirement) === 'available';
  });

  return (
    <nav className="flex w-52 flex-col border-r border-border-default bg-surface-sunken" aria-label="Main navigation">
      <div className="flex min-w-0 items-center gap-2 px-4 py-3 border-b border-border-default">
        <KyberLockup variant="responsive" size={24} className="min-w-0 flex-1" />
        <span className="text-[10px] text-text-muted font-mono">v{build?.version ?? 'dev'}</span>
      </div>
      <div className="flex-1 overflow-auto py-2">
        {items.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-4 py-1.5 text-xs font-medium transition-colors',
                isActive
                  ? 'text-accent bg-accent/10 border-r-2 border-accent'
                  : 'text-text-secondary hover:text-text-primary hover:bg-surface-raised',
              )
            }
          >
            <NavigationIcon destination={item.destination} decorative size="sm" className="w-5 text-center" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </div>
      <div className="border-t border-border-default px-4 py-3">
        <div className="text-[10px] text-text-muted font-mono">Aether Internal</div>
        {build ? (
          <div className="text-[9px] text-text-muted font-mono mt-1">
            {build.gitSha.slice(0, 7)} · {build.profile}
          </div>
        ) : null}
      </div>
    </nav>
  );
}
