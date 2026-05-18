import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '@aether/ui';
import { useState } from 'react';

interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

interface NavItem {
  to: string;
  label: string;
  glyph: string;
  badge?: number | string;
  badgeVariant?: 'amber' | 'ember' | 'signal';
  exact?: boolean;
}

const NAV: NavSection[] = [
  {
    id: 'intelligence',
    label: 'Intelligence',
    items: [
      { to: '/feed',          label: 'Feed',          glyph: '◉',  badge: 12, badgeVariant: 'amber' },
      { to: '/graph',         label: 'Graph',         glyph: '⬡' },
      { to: '/investigations',label: 'Investigations', glyph: '⬥', badge: 3, badgeVariant: 'ember' },
      { to: '/alerts',        label: 'Alerts',        glyph: '△',  badge: 7, badgeVariant: 'amber' },
    ],
  },
  {
    id: 'entities',
    label: 'Entities',
    items: [
      { to: '/entities',  label: 'Entities',  glyph: '⬡' },
      { to: '/journeys',  label: 'Journeys',  glyph: '↝' },
      { to: '/clusters',  label: 'Clusters',  glyph: '◈' },
      { to: '/devices',   label: 'Devices',   glyph: '⊡' },
      { to: '/wallets',   label: 'Wallets',   glyph: '⟐' },
      { to: '/agents',    label: 'Agents',    glyph: '⚙' },
    ],
  },
  {
    id: 'geo-econ',
    label: 'Spatial',
    items: [
      { to: '/geo',       label: 'Geographic', glyph: '◎' },
      { to: '/economic',  label: 'Economic',   glyph: '≈' },
      { to: '/web3',      label: 'Web3',       glyph: '⟨⟩' },
    ],
  },
  {
    id: 'governance',
    label: 'Governance',
    items: [
      { to: '/governance',  label: 'Governance',  glyph: '◧' },
      { to: '/audit',       label: 'Audit',       glyph: '✓' },
      { to: '/policies',    label: 'Policies',    glyph: '≡' },
    ],
  },
  {
    id: 'ops',
    label: 'Operations',
    items: [
      { to: '/monitoring',  label: 'Monitoring',   glyph: '⊙' },
      { to: '/reports',     label: 'Reports',      glyph: '⊟' },
      { to: '/developer',   label: 'Developer',    glyph: '⌘' },
      { to: '/settings',    label: 'Settings',     glyph: '⚙' },
    ],
  },
];

const BADGE_STYLES = {
  amber:  'bg-amber/15 text-amber   border-amber/30',
  ember:  'bg-ember/15 text-ember   border-ember/30',
  signal: 'bg-signal/15 text-signal border-signal/30',
};

interface SidebarProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function Sidebar({ collapsed = false }: SidebarProps) {
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const location = useLocation();

  const toggleSection = (id: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <nav
      className={cn(
        'flex flex-col h-full bg-surface-sidebar border-r border-border-default overflow-hidden transition-[width] duration-medium ease-out',
        collapsed ? 'w-sidebar-sm' : 'w-sidebar',
      )}
      aria-label="Main navigation"
    >
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-[18px] py-4 border-b border-border-default flex-shrink-0">
        <AetherLogo size={24} />
        {!collapsed && (
          <>
            <span className="font-sans font-semibold text-sm tracking-wide text-stone-bone">AETHER</span>
            <span className="font-mono text-2xs text-text-muted ml-auto">v8.8</span>
          </>
        )}
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto py-2">
        {NAV.map(section => {
          const isCollapsed = collapsedSections.has(section.id);
          const hasActive = section.items.some(i => location.pathname.startsWith(i.to));

          return (
            <div key={section.id} className="mb-1">
              {!collapsed && (
                <button
                  onClick={() => toggleSection(section.id)}
                  className="w-full flex items-center justify-between px-[18px] py-1 text-2xs font-medium tracking-eyebrow uppercase text-text-muted hover:text-text-secondary transition-colors"
                >
                  <span>{section.label}</span>
                  <span className="font-mono opacity-50">{isCollapsed ? '▸' : '▾'}</span>
                </button>
              )}
              {(!isCollapsed || hasActive) && (
                <div>
                  {section.items.map(item => (
                    <SidebarItem key={item.to} item={item} collapsed={collapsed} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="border-t border-border-default px-[18px] py-3 flex-shrink-0">
        {!collapsed && (
          <>
            <p className="text-2xs font-medium tracking-eyebrow uppercase text-text-muted">Workspace</p>
            <p className="font-mono text-2xs text-text-muted mt-1">Olympus · Production</p>
          </>
        )}
      </div>
    </nav>
  );
}

function SidebarItem({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 px-[18px] py-[7px] text-sm font-medium',
          'transition-colors duration-fast ease-out',
          'border-r-2',
          isActive
            ? 'text-steel bg-signal/5 border-r-signal'
            : 'text-text-secondary hover:text-text-primary hover:bg-surface-overlay border-r-transparent',
        )
      }
      title={collapsed ? item.label : undefined}
    >
      <span className="font-mono text-sm w-5 text-center flex-shrink-0 opacity-80">{item.glyph}</span>
      {!collapsed && (
        <>
          <span className="flex-1">{item.label}</span>
          {item.badge != null && (
            <span className={cn(
              'font-mono text-2xs border rounded-pill px-1.5 py-px',
              BADGE_STYLES[item.badgeVariant ?? 'signal'],
            )}>
              {item.badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

function AetherLogo({ size = 24 }: { size?: number }) {
  const s = size;
  return (
    <svg width={s} height={Math.round(s * 1.16)} viewBox="0 0 200 232" fill="none" aria-hidden="true" className="flex-shrink-0">
      <path d="M20.8 177.2L89.2 146.8Q100 142 110.8 146.8L179.2 177.2Q190 182 179.2 186.8L110.8 217.2Q100 222 89.2 217.2L20.8 186.8Q10 182 20.8 177.2Z" fill="#6b9a7c"/>
      <path d="M20.8 145.2L89.2 114.8Q100 110 110.8 114.8L179.2 145.2Q190 150 179.2 154.8L110.8 185.2Q100 190 89.2 185.2L20.8 154.8Q10 150 20.8 145.2Z" fill="#a87575"/>
      <path d="M20.8 113.2L89.2 82.8Q100 78 110.8 82.8L179.2 113.2Q190 118 179.2 122.8L110.8 153.2Q100 158 89.2 153.2L20.8 122.8Q10 118 20.8 113.2Z" fill="#c9975a"/>
      <path d="M20.8 81.2L89.2 50.8Q100 46 110.8 50.8L179.2 81.2Q190 86 179.2 90.8L110.8 121.2Q100 126 89.2 121.2L20.8 90.8Q10 86 20.8 81.2Z" fill="#5a85a8"/>
      <path d="M20.8 49.2L89.2 18.8Q100 14 110.8 18.8L179.2 49.2Q190 54 179.2 58.8L110.8 89.2Q100 94 89.2 89.2L20.8 58.8Q10 54 20.8 49.2Z" fill="#3a6896"/>
    </svg>
  );
}
