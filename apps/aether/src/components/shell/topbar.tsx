import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { LiveIndicator } from '../ui/live-indicator';

interface TopbarProps {
  onToggleSidebar?: () => void;
  onOpenCommand?: () => void;
  sidebarCollapsed?: boolean;
}

export function Topbar({ onToggleSidebar, onOpenCommand }: TopbarProps) {
  const [notifOpen, setNotifOpen] = useState(false);
  const notifCount = 4;

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        onOpenCommand?.();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onOpenCommand]);

  return (
    <header className="h-topbar flex-shrink-0 flex items-center justify-between gap-3 px-4 border-b border-border-default bg-surface-sidebar z-sticky">
      {/* Left */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="font-mono text-text-muted hover:text-text-primary transition-colors p-1 rounded"
          aria-label="Toggle sidebar"
        >
          ☰
        </button>

        {/* Workspace breadcrumb */}
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-text-muted">Olympus</span>
          <span className="text-text-muted opacity-40">/</span>
          <span className="text-text-secondary">Production</span>
        </div>

        <LiveIndicator className="hidden sm:inline-flex" />
      </div>

      {/* Center - Search */}
      <button
        onClick={onOpenCommand}
        className={cn(
          'flex items-center gap-2 px-3 py-1.5 rounded bg-surface-raised border border-border-default',
          'text-text-muted text-xs font-sans hover:border-border-hover transition-colors',
          'min-w-[200px] max-w-[360px] flex-1',
        )}
        aria-label="Open command palette"
      >
        <span className="font-mono opacity-60">/</span>
        <span>Search entities, events, graphs…</span>
        <kbd className="kbd ml-auto hidden sm:block">⌘K</kbd>
      </button>

      {/* Right */}
      <div className="flex items-center gap-1.5">
        {/* Status */}
        <TopbarIconBtn label="System healthy" title="System status">
          <span className="w-2 h-2 rounded-pill bg-verdant" />
        </TopbarIconBtn>

        {/* Notifications */}
        <div className="relative">
          <TopbarIconBtn
            label={`${notifCount} notifications`}
            onClick={() => setNotifOpen(v => !v)}
          >
            <span className="font-mono text-sm">✉</span>
            {notifCount > 0 && (
              <span className="absolute -top-0.5 -right-1 min-w-[14px] h-[14px] flex items-center justify-center bg-ember text-stone-white font-mono text-2xs rounded-pill px-0.5">
                {notifCount > 9 ? '9+' : notifCount}
              </span>
            )}
          </TopbarIconBtn>
          {notifOpen && <NotificationPanel onClose={() => setNotifOpen(false)} />}
        </div>

        {/* User */}
        <button className="flex items-center gap-2 px-2 py-1 rounded hover:bg-surface-overlay transition-colors">
          <div className="w-6 h-6 rounded-full bg-signal/20 border border-signal/30 flex items-center justify-center">
            <span className="font-mono text-2xs text-steel">OP</span>
          </div>
          <span className="text-xs text-text-secondary hidden md:block">Operator</span>
        </button>
      </div>
    </header>
  );
}

function TopbarIconBtn({
  children,
  label,
  title,
  onClick,
}: {
  children: React.ReactNode;
  label?: string;
  title?: string;
  onClick?: () => void;
}) {
  return (
    <button
      className="relative flex items-center justify-center w-8 h-8 rounded hover:bg-surface-overlay text-text-muted hover:text-text-primary transition-colors"
      aria-label={label}
      title={title ?? label}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

const NOTIFS = [
  { id: '1', sev: 'P0', msg: 'Cluster CL-28x flagged: coordinated device activity', time: '2m ago' },
  { id: '2', sev: 'P1', msg: 'Entity usr_9k2f risk score exceeded threshold (87)', time: '14m ago' },
  { id: '3', sev: 'P1', msg: 'Graph mutation rate spike: 3.2× baseline (5min)', time: '32m ago' },
  { id: '4', sev: 'P2', msg: 'Investigation INV-0041 requires governance review', time: '1h ago' },
];

const SEV_STYLE = {
  P0:   'text-ember',
  P1:   'text-amber',
  P2:   'text-signal',
  INFO: 'text-text-muted',
} as Record<string, string>;

function NotificationPanel({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute top-10 right-0 w-80 panel shadow-popover z-overlay animate-fade-in"
    >
      <div className="panel-header">
        <span className="panel-title">Notifications</span>
        <button
          onClick={() => { navigate('/alerts'); onClose(); }}
          className="text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          View all
        </button>
      </div>
      <div className="divide-y divide-border-subtle">
        {NOTIFS.map(n => (
          <div key={n.id} className="px-3 py-2.5 hover:bg-surface-overlay cursor-pointer transition-colors">
            <div className="flex items-start gap-2">
              <span className={cn('font-mono text-2xs mt-0.5 font-medium', SEV_STYLE[n.sev])}>{n.sev}</span>
              <p className="text-xs text-text-primary leading-relaxed flex-1">{n.msg}</p>
            </div>
            <p className="text-2xs text-text-muted mt-1 font-mono">{n.time}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
