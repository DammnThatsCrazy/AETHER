import { NavLink } from 'react-router-dom';
import { cn } from '@kyber/lib/utils';

interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly glyph: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/mission',         label: 'Mission',         glyph: '◈' },
  { path: '/live',            label: 'Live',            glyph: '◉' },
  { path: '/command',         label: 'Command',         glyph: '⌘' },
  { path: '/review',          label: 'Review',          glyph: '✓' },
  { path: '/entities',        label: 'Entities',        glyph: '⬡' },
  { path: '/noesis',          label: 'Noesis',          glyph: '⬢' },
  { path: '/tenants',         label: 'Tenants',         glyph: '⊞' },
  { path: '/implementation', label: 'Implementation', glyph: '◫' },
  { path: '/investigations',  label: 'Investigations',  glyph: '⚒' },
  { path: '/cis',             label: 'CIS',             glyph: '◎' },
  { path: '/packages',        label: 'Packages',        glyph: '▣' },
  { path: '/deployment-readiness', label: 'Deploy Ready', glyph: '▤' },
  { path: '/reliability',     label: 'Reliability',     glyph: '◐' },
  { path: '/journey-health',  label: 'Journey Health',  glyph: '↔' },
  { path: '/intelligence-quality', label: 'Intel Quality', glyph: '◉' },
  { path: '/intelligence/suggestions', label: 'Suggestions',   glyph: '◈' },
  { path: '/connectors', label: 'Connectors', glyph: '⇄' },
  { path: '/dune-feeder', label: 'Dune Feeder', glyph: '⬡' },
  { path: '/revops',          label: 'RevOps',          glyph: '₿' },
  { path: '/sales-readiness', label: 'Sales Ready', glyph: '$' },
  { path: '/pricing-architecture', label: 'Pricing', glyph: '≋' },
  { path: '/gtm-materials', label: 'GTM Materials', glyph: '▥' },
  { path: '/buyer-personas', label: 'Personas', glyph: '◌' },
  { path: '/roi-calculators', label: 'ROI Calcs', glyph: '%' },
  { path: '/security',        label: 'Security',        glyph: '⛨' },
  { path: '/diagnostics',     label: 'Diagnostics',     glyph: '⚙' },
  { path: '/lab',             label: 'Lab',             glyph: '⚗' },
];

export function Sidebar() {
  return (
    <nav className="flex w-52 flex-col border-r border-border-default bg-surface-sunken" aria-label="Main navigation">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-border-default">
        <span className="font-mono text-lg font-bold text-text-primary tracking-wider">KYBER</span>
        <span className="text-[10px] text-text-muted font-mono">v0.1</span>
      </div>
      <div className="flex-1 overflow-auto py-2">
        {NAV_ITEMS.map(item => (
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
      </div>
    </nav>
  );
}
