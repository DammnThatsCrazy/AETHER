import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  GlyphIcon,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Popover,
  StatusIndicator,
  useToast,
} from '@aether/ui';
import { queryCache } from '@aether/ui';
import {
  useWebhooks,
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  type WebhookConfig,
} from '@aether-app/features/account/use-notification-webhooks';

const AVAILABLE_EVENTS = [
  'entity.created',
  'entity.updated',
  'anomaly.detected',
  'suggestion.created',
  'sdk.silence',
] as const;

type TestResult = { success: boolean; status_code?: number; latency_ms?: number; error?: string };

function WebhookRow({
  webhook,
  onDelete,
  onTest,
}: {
  readonly webhook: WebhookConfig;
  readonly onDelete: (id: string) => Promise<void>;
  readonly onTest: (id: string) => Promise<TestResult | null>;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onTest(webhook.id);
      setTestResult(result);
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex items-start justify-between rounded border border-border-default px-3 py-2 text-xs gap-2">
      <div className="flex items-start gap-2 min-w-0">
        <StatusIndicator status={webhook.active ? 'healthy' : 'degraded'} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="font-mono text-text-primary truncate">{webhook.url}</p>
          <div className="flex flex-wrap gap-1 mt-1">
            {webhook.events.map(ev => (
              <Badge key={ev} variant="default" className="text-[10px] px-1">{ev}</Badge>
            ))}
          </div>
          {testResult && (
            <p className={`font-mono mt-1 ${testResult.success ? 'text-healthy' : 'text-danger'}`}>
              {testResult.success
                ? `${testResult.status_code} OK • ${testResult.latency_ms}ms`
                : `failed${testResult.error ? ` — ${testResult.error}` : ''}`}
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button variant="ghost" size="sm" disabled={testing} onClick={() => { void handleTest(); }}>
          {testing ? '…' : 'Test'}
        </Button>
        <Popover
          trigger={
            <Button variant="ghost" size="sm" className="text-danger hover:bg-danger/10">
              <GlyphIcon glyph="[x]" />
            </Button>
          }
          content={
            <div className="space-y-2">
              <p className="text-text-primary text-xs">Delete this endpoint?</p>
              <p className="text-danger text-xs">This cannot be undone.</p>
              <Button
                variant="danger"
                size="sm"
                className="w-full mt-1"
                onClick={() => { void onDelete(webhook.id); }}
              >
                Confirm delete
              </Button>
            </div>
          }
        />
      </div>
    </div>
  );
}

interface AddWebhookModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function AddWebhookModal({ open, onClose, onCreated }: AddWebhookModalProps) {
  const { toast } = useToast();
  const [url, setUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [events, setEvents] = useState<string[]>(['entity.created']);
  const { mutate: create, isLoading } = useCreateWebhook();

  function toggleEvent(ev: string) {
    setEvents(prev => prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev]);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim() || events.length === 0) return;
    const result = await create({ url: url.trim(), events, ...(secret.trim() ? { secret: secret.trim() } : {}) });
    if (result !== null) {
      toast.success('Webhook endpoint added');
      queryCache.invalidate('notification-webhooks');
      onCreated();
      setUrl('');
      setSecret('');
      setEvents(['entity.created']);
    } else {
      toast.error('Failed to add webhook — check the URL and try again');
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">Add webhook endpoint</h2>
      </ModalHeader>
      <form onSubmit={(e) => { void handleSubmit(e); }}>
        <ModalBody className="space-y-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="wh-url" className="text-xs text-text-secondary">Endpoint URL</label>
            <input
              id="wh-url"
              type="url"
              required
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://example.com/webhook"
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="wh-secret" className="text-xs text-text-secondary">
              Signing secret <span className="text-text-muted">(optional)</span>
            </label>
            <input
              id="wh-secret"
              type="password"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              placeholder="whsec_…"
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-text-secondary">Events</span>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_EVENTS.map(ev => (
                <button
                  key={ev}
                  type="button"
                  role="switch"
                  aria-checked={events.includes(ev)}
                  onClick={() => toggleEvent(ev)}
                  className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${
                    events.includes(ev)
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-surface-base border-border-default text-text-muted'
                  }`}
                >
                  {ev}
                </button>
              ))}
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={!url.trim() || events.length === 0 || isLoading}
          >
            {isLoading ? '[···]' : 'Add endpoint'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}

export function WebhooksSection() {
  const { toast } = useToast();
  const { data: webhooks, isLoading, error, refetch } = useWebhooks();
  const { mutate: deleteWebhook } = useDeleteWebhook();
  const { mutate: testWebhook } = useTestWebhook();
  const [addOpen, setAddOpen] = useState(false);

  async function handleDelete(id: string) {
    const result = await deleteWebhook(id);
    if (result !== null) {
      queryCache.invalidate('notification-webhooks');
      refetch();
      toast.success('Webhook removed');
    } else {
      toast.error('Delete failed — please try again');
    }
  }

  async function handleTest(id: string): Promise<TestResult | null> {
    const result = await testWebhook(id);
    if (result === null) {
      toast.error('Test request failed');
      return null;
    }
    return result as TestResult;
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono text-text-muted">Webhook Endpoints</CardTitle>
          <Button variant="primary" size="sm" onClick={() => setAddOpen(true)}>
            Add endpoint
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && <LoadingState lines={2} />}
        {error && (
          <p className="text-xs text-danger font-mono">Failed to load webhooks — check your connection</p>
        )}
        {!isLoading && !error && (webhooks ?? []).length === 0 && (
          <EmptyState
            title="No webhook endpoints"
            description="Add an endpoint to receive event notifications from Aether."
          />
        )}
        {(webhooks ?? []).map(wh => (
          <WebhookRow
            key={wh.id}
            webhook={wh}
            onDelete={handleDelete}
            onTest={handleTest}
          />
        ))}
        <p className="text-[10px] text-text-muted font-mono mt-2">
          Aether signs each delivery with an HMAC-SHA256 signature in the <span className="font-mono">X-Aether-Signature</span> header.
        </p>
      </CardContent>

      <AddWebhookModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={() => {
          setAddOpen(false);
          refetch();
        }}
      />
    </Card>
  );
}
