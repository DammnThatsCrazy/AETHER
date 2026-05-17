import { NavLink } from 'react-router-dom';
import { cn } from '@kyber/lib/utils';

interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly glyph: string;
}

interface NavGroup {
  readonly label: string;
  readonly items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Operations',
    items: [
      { path: '/mission', label: 'Mission', glyph: '\u25C8' },
      { path: '/live', label: 'Live', glyph: '\u25C9' },
      { path: '/command', label: 'Command', glyph: '\u2318' },
      { path: '/agent', label: 'Agent', glyph: '\u25B6' },
      { path: '/review', label: 'Review', glyph: '\u2713' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { path: '/entities', label: 'Entities', glyph: '\u2B21' },
      { path: '/noesis', label: 'Noesis', glyph: '\u2B22' },
      { path: '/population', label: 'Population', glyph: '\u25A6' },
      { path: '/resolution', label: 'Resolution', glyph: '\u2299' },
    ],
  },
  {
    label: 'Compliance',
    items: [
      { path: '/fraud', label: 'Fraud', glyph: '\u26A0' },
      { path: '/consent', label: 'Consent', glyph: '\u25A1' },
      { path: '/rewards', label: 'Rewards', glyph: '\u25C6' },
    ],
  },
  {
    label: 'Infrastructure',
    items: [
      { path: '/web3', label: 'Web3', glyph: '\u29C9' },
      { path: '/lake', label: 'Lake', glyph: '\u25BD' },
      { path: '/diagnostics', label: 'Diagnostics', glyph: '\u2699' },
      { path: '/admin', label: 'Admin', glyph: '\u2302' },
      { path: '/lab', label: 'Lab', glyph: '\u2697' },
    ],
  },
];

export function Sidebar() {
  return (
    <nav className="flex w-52 flex-col border-r border-border-default bg-surface-sunken" aria-label="Main navigation">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-border-default">
        <span className="font-mono text-lg font-bold text-text-primary tracking-wider">KYBER</span>
        <span className="text-[10px] text-text-muted font-mono">v0.1</span>
      </div>
      <div className="flex-1 overflow-auto py-2">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <div className="px-4 pt-3 pb-1 text-[9px] font-mono font-bold tracking-widest text-text-muted uppercase">
              {group.label}
            </div>
            {group.items.map(item => (
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
        ))}
      </div>
      <div className="border-t border-border-default px-4 py-3">
        <div className="text-[10px] text-text-muted font-mono">Aether Internal</div>
      </div>
    </nav>
  );
}
