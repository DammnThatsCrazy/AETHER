import { NavLink } from 'react-router-dom';
import { cn } from '@kyber/lib/utils';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';
import {
  resolveDestinationAvailability,
  useBuildInfo,
  useCapabilities,
  type CapabilityRequirement,
} from '@aether/ui';

type EnvFlag = Parameters<typeof isFeatureEnabled>[0];

interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly glyph: string;
  /** Backend capability this destination requires (domain excluded / flag off → hidden). */
  readonly requirement?: CapabilityRequirement;
  /** Frontend-only feature flag (no backend capability mapping). */
  readonly envFlag?: EnvFlag;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/mission',         label: 'Mission',         glyph: '◈' },
  { path: '/live',            label: 'Live',            glyph: '◉' },
  { path: '/command',         label: 'Command',         glyph: '⌘' },
  { path: '/review',          label: 'Review',          glyph: '✓' },
  { path: '/entities',        label: 'Entities',        glyph: '⬡' },
  { path: '/noesis',          label: 'Noesis',          glyph: '⬢' },
  { path: '/tenants',         label: 'Tenants',         glyph: '⊞' },
  { path: '/imports',         label: 'Import Engine',   glyph: '⇪' },
  { path: '/implementation', label: 'Implementation', glyph: '◫' },
  { path: '/investigations',  label: 'Investigations',  glyph: '⚒' },
  { path: '/cis',             label: 'CIS',             glyph: '◎' },
  { path: '/packages',        label: 'Packages',        glyph: '▣' },
  { path: '/deployment-readiness', label: 'Deploy Ready', glyph: '▤' },
  { path: '/reliability',     label: 'Reliability',     glyph: '◐' },
  { path: '/journey-health',  label: 'Journey Health',  glyph: '↔' },
  { path: '/intelligence-quality', label: 'Intel Quality', glyph: '◉' },
  { path: '/intelligence/suggestions', label: 'Suggestions', glyph: '◈', requirement: { flag: 'suggestions_enabled' } },
  { path: '/connectors', label: 'Connectors', glyph: '⇄', requirement: { flag: 'connectors_enabled' } },
  { path: '/agent-telemetry', label: 'Agent Telemetry', glyph: '⌁', envFlag: 'enableExternalAgentTelemetry' },
  { path: '/payment-rails', label: 'Payment Rails', glyph: '¤', requirement: { domain: 'payments' }, envFlag: 'enablePaymentRails' },
  { path: '/ai-efficiency', label: 'AI Efficiency', glyph: '∴', requirement: { domain: 'economic' }, envFlag: 'enableAiEfficiency' },
  { path: '/targeting', label: 'Targeting', glyph: '⊙', envFlag: 'enableTargetingIntelligence' },
  { path: '/dune-feeder', label: 'Dune Feeder', glyph: '⬡' },
  { path: '/revops',          label: 'RevOps',          glyph: '₿' },
  { path: '/sales-readiness', label: 'Sales Ready', glyph: '$' },
  { path: '/pricing-architecture', label: 'Pricing', glyph: '≋' },
  { path: '/gtm-materials', label: 'GTM Materials', glyph: '▥' },
  { path: '/buyer-personas', label: 'Personas', glyph: '◌' },
  { path: '/roi-calculators', label: 'ROI Calcs', glyph: '%' },
  { path: '/fraud-networks',  label: 'Fraud Networks',  glyph: '⬡' },
  { path: '/fraud-networks/flow-trace', label: 'Flow Trace', glyph: '→' },
  { path: '/security',        label: 'Security',        glyph: '⛨' },
  { path: '/diagnostics',     label: 'Diagnostics',     glyph: '⚙' },
  { path: '/lab',             label: 'Lab',             glyph: '⚗' },
];

export function Sidebar() {
  const { capabilities } = useCapabilities();
  const build = useBuildInfo();

  const items = NAV_ITEMS.filter(item => {
    // Frontend-only flags gate first (no backend capability signal for these).
    if (item.envFlag && !isFeatureEnabled(item.envFlag)) return false;
    // Then the backend capability contract: hide excluded domains / off flags.
    return resolveDestinationAvailability(capabilities, item.requirement) === 'available';
  });

  return (
    <nav className="flex w-52 flex-col border-r border-border-default bg-surface-sunken" aria-label="Main navigation">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-border-default">
        <span className="font-mono text-lg font-bold text-text-primary tracking-wider">KYBER</span>
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
            <span className="font-mono text-sm w-5 text-center">{item.glyph}</span>
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
