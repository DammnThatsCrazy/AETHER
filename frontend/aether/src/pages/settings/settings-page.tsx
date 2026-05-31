import { useState } from 'react';
import {
  Button,
  Card,
  CardContent,
  DataTable,
  EmptyState,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Popover,
  Skeleton,
  StatusIndicator,
  TerminalSeparator,
  Tooltip,
  Badge,
  useToast,
} from '@aether/ui';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@aether-app/features/account';
import type { ApiKey } from '@aether-app/features/account';
import { queryCache } from '@aether/ui';

function formatRelative(iso: string | null): string {
  if (!iso) return 'never';
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3600000);
  if (h < 1) return 'just now';
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function LastUsedCell({ lastUsed }: { lastUsed: string | null }) {
  if (!lastUsed) {
    return (
      <span className="flex items-center gap-1 text-xs">
        <StatusIndicator status="degraded" />
        <span className="text-text-muted italic">never</span>
      </span>
    );
  }
  const diffH = (Date.now() - new Date(lastUsed).getTime()) / 3600000;
  const status = diffH < 24 ? 'healthy' : diffH < 168 ? 'degraded' : 'unknown';
  return (
    <span className="flex items-center gap-1 text-xs">
      <StatusIndicator status={status} />
      <span className="text-text-secondary">{formatRelative(lastUsed)}</span>
    </span>
  );
}

function RevokePopover({ apiKey, onRevoke }: { apiKey: ApiKey; onRevoke: () => void }) {
  return (
    <Popover
      trigger={
        <Button variant="ghost" size="sm" className="text-danger hover:bg-danger/10">
          Revoke
        </Button>
      }
      content={
        <div className="space-y-2">
          <p className="text-text-primary text-xs">Revoke <span className="font-mono">{apiKey.name}</span>?</p>
          <p className="text-danger text-xs">This cannot be undone.</p>
          <Button variant="danger" size="sm" className="w-full mt-1" onClick={onRevoke}>
            Confirm revoke
          </Button>
        </div>
      }
    />
  );
}

interface NewKeyModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (key: string) => void;
}

const ALL_PERMISSIONS = ['read', 'write', 'ingest', 'analytics'] as const;
type Permission = typeof ALL_PERMISSIONS[number];

function NewKeyModal({ open, onClose, onCreated }: NewKeyModalProps) {
  const [name, setName] = useState('');
  const [permissions, setPermissions] = useState<Permission[]>(['read']);
  const { mutate, isLoading } = useCreateApiKey();

  function togglePermission(perm: Permission) {
    setPermissions(prev =>
      prev.includes(perm) ? prev.filter(p => p !== perm) : [...prev, perm]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const result = await mutate({ name: name.trim(), permissions });
    if (result) {
      onCreated((result as { api_key?: string; key?: string }).api_key ?? (result as { key: string }).key);
      setName('');
      setPermissions(['read']);
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">New API key</h2>
      </ModalHeader>
      <form onSubmit={(e) => { void handleSubmit(e); }}>
        <ModalBody className="space-y-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="key-name" className="text-xs text-text-secondary">Key name</label>
            <input
              id="key-name"
              type="text"
              required
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Production, iOS App"
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-text-secondary">Permissions</span>
            <div className="flex flex-wrap gap-2">
              {ALL_PERMISSIONS.map(perm => (
                <button
                  key={perm}
                  type="button"
                  role="switch"
                  aria-checked={permissions.includes(perm)}
                  onClick={() => togglePermission(perm)}
                  className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${
                    permissions.includes(perm)
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-surface-base border-border-default text-text-muted'
                  }`}
                >
                  {perm}
                </button>
              ))}
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" type="submit" disabled={!name.trim() || permissions.length === 0 || isLoading}>
            {isLoading ? '[···]' : 'Create key'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}

interface KeyRevealModalProps {
  open: boolean;
  apiKey: string;
  onClose: () => void;
}

function KeyRevealModal({ open, apiKey, onClose }: KeyRevealModalProps) {
  const { toast } = useToast();
  const [saved, setSaved] = useState(false);

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(apiKey);
      toast.success('Copied');
    } catch {
      toast.info('Copy unavailable — select and copy the key manually');
    }
  }

  return (
    <Modal open={open} onClose={saved ? onClose : () => {}}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">Your new API key</h2>
      </ModalHeader>
      <ModalBody className="space-y-3">
        <div className="flex items-start gap-1.5">
          <GlyphIcon glyph="[!]" className="text-warning text-xs mt-px shrink-0" />
          <p className="text-warning text-xs font-mono">Store this key — it will not be shown again</p>
        </div>
        <div className="bg-surface-overlay border border-accent/40 rounded p-3 relative">
          <p className="text-accent font-mono text-xs select-all break-all pr-7">{apiKey}</p>
          <button
            onClick={() => { void copyKey(); }}
            className="absolute top-2 right-2 text-accent hover:text-accent-hover"
            aria-label="Copy API key"
          >
            <GlyphIcon glyph="[cp]" className="text-xs" />
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={saved}
            onChange={e => setSaved(e.target.checked)}
            className="accent-accent"
          />
          I&apos;ve saved this key
        </label>
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" size="sm" disabled={!saved} onClick={onClose}>
          Done
        </Button>
      </ModalFooter>
    </Modal>
  );
}

export function SettingsPage() {
  const { toast } = useToast();
  const { data: keys, isLoading, error, refetch } = useApiKeys();
  const { mutate: revoke } = useRevokeApiKey();
  const [newKeyOpen, setNewKeyOpen] = useState(false);
  const [revealKey, setRevealKey] = useState<string | null>(null);

  async function handleRevoke(id: string, name: string) {
    const result = await revoke(id);
    if (result !== null) {
      queryCache.invalidate('api-keys');
      refetch();
      toast.success(`${name} revoked`);
    } else {
      toast.error('Revoke failed — please try again');
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <span className="text-sm font-mono text-text-muted">API Keys</span>
        <Button variant="primary" size="sm" onClick={() => setNewKeyOpen(true)}>
          New key
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      )}

      {error && (
        <ErrorState
          message="Failed to load API keys"
          onRetry={refetch}
        />
      )}

      {!isLoading && !error && keys && keys.length === 0 && (
        <EmptyState
          title="No API keys yet"
          description="Create your first key to start using the SDK."
          action={
            <Button variant="primary" size="sm" onClick={() => setNewKeyOpen(true)}>
              Create your first key
            </Button>
          }
        />
      )}

      {!isLoading && !error && keys && keys.length > 0 && (
        <DataTable
          columns={[
            {
              key: 'name',
              header: 'Name',
              render: (row: ApiKey) => <span className="text-sm text-text-primary">{row.name}</span>,
            },
            {
              key: 'tier',
              header: 'Tier',
              render: (row: ApiKey) => <Badge variant="default" size="sm">{row.tier}</Badge>,
            },
            {
              key: 'permissions',
              header: 'Permissions',
              render: (row: ApiKey) => (
                <span className="font-mono text-xs text-text-secondary">
                  {row.permissions.join(', ') || '—'}
                </span>
              ),
            },
            {
              key: 'last_used_at',
              header: 'Last used',
              render: (row: ApiKey) => <LastUsedCell lastUsed={row.last_used_at} />,
            },
            {
              key: 'actions',
              header: '',
              render: (row: ApiKey) => (
                <RevokePopover
                  apiKey={row}
                  onRevoke={() => { void handleRevoke(row.id, row.name); }}
                />
              ),
            },
          ]}
          data={keys}
          keyExtractor={(row: ApiKey) => row.id}
        />
      )}

      {!isLoading && !error && keys && keys.length > 0 && (
        <p className="text-xs font-mono text-text-muted mt-3 text-right">
          1–{keys.length} of {keys.length} key{keys.length !== 1 ? 's' : ''}
        </p>
      )}

      <NewKeyModal
        open={newKeyOpen}
        onClose={() => setNewKeyOpen(false)}
        onCreated={(key) => {
          setNewKeyOpen(false);
          setRevealKey(key);
          queryCache.invalidate('api-keys');
          refetch();
        }}
      />

      {revealKey && (
        <KeyRevealModal
          open
          apiKey={revealKey}
          onClose={() => setRevealKey(null)}
        />
      )}
    </div>
  );
}
