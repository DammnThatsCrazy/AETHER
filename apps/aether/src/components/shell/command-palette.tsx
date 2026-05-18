import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';

interface Command {
  id: string;
  label: string;
  description?: string;
  shortcut?: string;
  glyph?: string;
  category: string;
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const COMMANDS: Command[] = [
    { id: 'feed',         label: 'Intelligence Feed',       glyph: '◉', category: 'Navigate', action: () => navigate('/feed') },
    { id: 'graph',        label: 'Graph Workspace',         glyph: '⬡', category: 'Navigate', action: () => navigate('/graph') },
    { id: 'entities',     label: 'Entity Intelligence',     glyph: '⬡', category: 'Navigate', action: () => navigate('/entities') },
    { id: 'investigations',label: 'Investigations',         glyph: '⬥', category: 'Navigate', action: () => navigate('/investigations') },
    { id: 'governance',   label: 'Governance Dashboard',    glyph: '◧', category: 'Navigate', action: () => navigate('/governance') },
    { id: 'alerts',       label: 'Alert Center',            glyph: '△', category: 'Navigate', action: () => navigate('/alerts') },
    { id: 'monitoring',   label: 'Monitoring',              glyph: '⊙', category: 'Navigate', action: () => navigate('/monitoring') },
    { id: 'developer',    label: 'Developer Console',       glyph: '⌘', category: 'Navigate', action: () => navigate('/developer') },
    { id: 'journeys',     label: 'Journey Intelligence',    glyph: '↝', category: 'Navigate', action: () => navigate('/journeys') },
    { id: 'clusters',     label: 'Cluster Intelligence',    glyph: '◈', category: 'Navigate', action: () => navigate('/clusters') },
    { id: 'wallets',      label: 'Wallet Intelligence',     glyph: '⟐', category: 'Navigate', action: () => navigate('/wallets') },
    { id: 'devices',      label: 'Device Intelligence',     glyph: '⊡', category: 'Navigate', action: () => navigate('/devices') },
    { id: 'agents',       label: 'Agent Intelligence',      glyph: '⚙', category: 'Navigate', action: () => navigate('/agents') },
    { id: 'geo',          label: 'Geographic Intelligence', glyph: '◎', category: 'Navigate', action: () => navigate('/geo') },
    { id: 'web3',         label: 'Web3 Intelligence',       glyph: '⟨⟩',category: 'Navigate', action: () => navigate('/web3') },
    { id: 'economic',     label: 'Economic Intelligence',   glyph: '≈', category: 'Navigate', action: () => navigate('/economic') },
    { id: 'audit',        label: 'Audit Center',            glyph: '✓', category: 'Governance', action: () => navigate('/audit') },
    { id: 'policies',     label: 'Policy Management',       glyph: '≡', category: 'Governance', action: () => navigate('/policies') },
    { id: 'reports',      label: 'Reports',                 glyph: '⊟', category: 'Operations', action: () => navigate('/reports') },
    { id: 'settings',     label: 'Settings',                glyph: '⚙', category: 'Operations', action: () => navigate('/settings') },
    { id: 'new-inv',      label: 'New Investigation',       glyph: '+', category: 'Actions',  description: 'Create investigation', action: () => navigate('/investigations/new') },
    { id: 'new-alert',    label: 'New Alert Rule',          glyph: '+', category: 'Actions',  description: 'Configure alert', action: () => navigate('/alerts/rules/new') },
    { id: 'api-console',  label: 'API Console',             glyph: '⌘', category: 'Developer', action: () => navigate('/developer/api-console') },
    { id: 'sdk',          label: 'SDK Downloads',           glyph: '↓', category: 'Developer', action: () => navigate('/developer/sdk') },
  ];

  const filtered = query.trim()
    ? COMMANDS.filter(c =>
        c.label.toLowerCase().includes(query.toLowerCase()) ||
        c.description?.toLowerCase().includes(query.toLowerCase()) ||
        c.category.toLowerCase().includes(query.toLowerCase()),
      )
    : COMMANDS;

  const grouped = filtered.reduce<Record<string, Command[]>>((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [] as Command[];
    (acc[cmd.category] as Command[]).push(cmd);
    return acc;
  }, {});

  const flatList = Object.values(grouped).flat();

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelected(v => Math.min(v + 1, flatList.length - 1)); }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSelected(v => Math.max(v - 1, 0)); }
      if (e.key === 'Enter') {
        e.preventDefault();
        flatList[selected]?.action();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, selected, flatList, onClose]);

  if (!open) return null;

  let globalIdx = 0;

  return (
    <div className="fixed inset-0 z-cmd flex items-start justify-center pt-[18vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-deep-stone/70 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-xl panel shadow-modal animate-fade-in">
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-default">
          <span className="font-mono text-text-muted text-sm">⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => { setQuery(e.target.value); setSelected(0); }}
            placeholder="Search or type a command…"
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none font-sans"
          />
          <kbd className="kbd">esc</kbd>
        </div>

        {/* Results */}
        <div className="max-h-80 overflow-y-auto py-1">
          {Object.entries(grouped).map(([category, cmds]) => (
            <div key={category}>
              <p className="label-eyebrow px-4 pt-2 pb-1">{category}</p>
              {cmds.map(cmd => {
                const idx = globalIdx++;
                const isSelected = idx === selected;
                return (
                  <button
                    key={cmd.id}
                    onMouseEnter={() => setSelected(idx)}
                    onClick={() => { cmd.action(); onClose(); }}
                    className={cn(
                      'w-full flex items-center gap-3 px-4 py-2 text-left transition-colors',
                      isSelected ? 'bg-signal/10' : 'hover:bg-surface-overlay',
                    )}
                  >
                    <span className="font-mono text-sm w-4 text-center text-text-muted flex-shrink-0">{cmd.glyph}</span>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-text-primary">{cmd.label}</span>
                      {cmd.description && (
                        <span className="text-xs text-text-muted ml-2">{cmd.description}</span>
                      )}
                    </div>
                    {cmd.shortcut && <kbd className="kbd">{cmd.shortcut}</kbd>}
                  </button>
                );
              })}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="text-center text-sm text-text-muted py-8">No results for "{query}"</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-border-subtle">
          <span className="text-2xs text-text-muted font-mono flex items-center gap-1"><kbd className="kbd">↑↓</kbd> navigate</span>
          <span className="text-2xs text-text-muted font-mono flex items-center gap-1"><kbd className="kbd">↵</kbd> select</span>
          <span className="text-2xs text-text-muted font-mono flex items-center gap-1"><kbd className="kbd">esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
