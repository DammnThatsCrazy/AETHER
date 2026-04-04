import { NavLink } from 'react-router-dom';
import { cn } from '@shiki/lib/utils';

interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly glyph: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/mission', label: 'Mission', glyph: '\u25C8' },
  { path: '/live', label: 'Live', glyph: '\u25C9' },
  { path: '/gouf', label: 'GOUF', glyph: '\u2B22' },
  { path: '/entities', label: 'Entities', glyph: '\u2B21' },
  { path: '/command', label: 'Command', glyph: '\u2318' },
  { path: '/diagnostics', label: 'Diagnostics', glyph: '\u2699' },
  { path: '/review', label: 'Review', glyph: '\u2713' },
  { path: '/lab', label: 'Lab', glyph: '\u2697' },
];

export function Sidebar() {
  return (
    <nav className="flex w-52 flex-col border-r border-border-default bg-surface-sunken" aria-label="Main navigation">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-border-default">
        <span className="font-mono text-lg font-bold text-text-primary tracking-wider">SHIKI</span>
        <span className="text-[10px] text-text-muted font-mono">v0.1</span>
      </div>
      <div className="flex-1 overflow-auto py-2">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-4 py-2 text-xs font-medium transition-colors',
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
        <div className="text-[10px] text-text-muted font-mono">AETHER INTERNAL</div>
      </div>
    </nav>
  );
}
