import { useState } from 'react';
import { Badge, Button, Input, Modal, ModalBody, ModalFooter, ModalHeader } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

interface ConnectorInfo {
  readonly connector_type: string;
  readonly label: string;
  readonly description: string;
  readonly requires_secret: boolean;
  readonly enabled: boolean;
  readonly secret_configured: boolean;
  readonly sync_status: string;
}

interface Props {
  readonly connector: ConnectorInfo;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

type Step = 'configure' | 'testing' | 'done' | 'error' | 'sync' | 'syncing' | 'synced';

type ConnectorConfigureResult = {
  readonly connector_type?: unknown;
  readonly enabled?: unknown;
};

type ConnectorTestResult = {
  readonly connector_type?: unknown;
  readonly ok?: unknown;
  readonly status?: unknown;
  readonly detail?: unknown;
};

type SyncRun = {
  readonly status?: string;
  readonly mode?: string;
  readonly records_received?: number;
  readonly campaigns_created?: number;
  readonly facts_written?: number;
  readonly safe_error_code?: string | null;
  readonly safe_error_detail?: string | null;
};

// Historical backfill windows (§12.3). `days: null` = provider maximum.
const BACKFILL_OPTIONS: ReadonlyArray<{ label: string; days: number | null }> = [
  { label: 'No history (incremental only)', days: 0 },
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'Last 180 days', days: 180 },
  { label: 'Last year', days: 365 },
  { label: 'Provider maximum', days: null },
];

function computeSince(days: number | null): string | undefined {
  if (days === 0) return undefined; // no history → incremental from cursor
  const span = days === null ? 3650 : days; // provider maximum ≈ 10 years
  return new Date(Date.now() - span * 24 * 60 * 60 * 1000).toISOString();
}

export function connectorSavePostcondition(
  result: unknown,
  connectorType: string,
  enabled: boolean,
): string | null {
  if (!result || typeof result !== 'object') return 'The server did not return the saved connector configuration.';
  const saved = result as ConnectorConfigureResult;
  if (saved.connector_type !== connectorType) return 'The saved configuration was returned for a different connector.';
  if (saved.enabled !== enabled) return 'The saved connector state does not match the requested enabled state.';
  return null;
}

export function connectorTestPostcondition(result: unknown, connectorType: string): string | null {
  if (!result || typeof result !== 'object') return 'The server did not return a connection-test result.';
  const tested = result as ConnectorTestResult;
  if (tested.connector_type !== connectorType) return 'The connection test was returned for a different connector.';
  if (tested.ok !== true) {
    const detail = typeof tested.detail === 'string' && tested.detail.trim()
      ? tested.detail
      : String(tested.status ?? 'connection test did not pass');
    return detail;
  }
  return null;
}

export function ConnectorConfigModal({ connector, onClose, onSaved }: Props) {
  const [secret, setSecret] = useState('');
  const [name, setName] = useState(connector.label);
  const [enabled, setEnabled] = useState(connector.enabled);
  const [step, setStep] = useState<Step>('configure');
  const [errorMsg, setErrorMsg] = useState('');
  const [testResult, setTestResult] = useState<'ok' | 'fail' | null>(null);
  const [backfillIdx, setBackfillIdx] = useState(2); // default: Last 30 days
  const [syncRun, setSyncRun] = useState<SyncRun | null>(null);

  async function handleSave() {
    setStep('testing');
    setErrorMsg('');
    try {
      const body: Record<string, unknown> = { name, enabled, config: {} };
      if (secret.trim()) body['credential'] = secret.trim();

      const saved = await api.connectors.configure(connector.connector_type, body);
      const saveFailure = connectorSavePostcondition(saved, connector.connector_type, enabled);
      if (saveFailure) throw new Error(saveFailure);

      if (enabled) {
        try {
          const tested = await api.connectors.test(connector.connector_type);
          const testFailure = connectorTestPostcondition(tested, connector.connector_type);
          if (testFailure) {
            setErrorMsg(testFailure);
            setTestResult('fail');
            setStep('done');
            return;
          }
          setTestResult('ok');
          // Credential valid + enabled → offer initial synchronization from the product.
          setStep('sync');
          return;
        } catch (e) {
          setErrorMsg(e instanceof Error ? e.message : 'Connection test failed');
          setTestResult('fail');
        }
      }
      setStep('done');
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Save failed');
      setStep('error');
    }
  }

  async function handleStartSync() {
    setStep('syncing');
    setErrorMsg('');
    try {
      const since = computeSince(BACKFILL_OPTIONS[backfillIdx]?.days ?? 0);
      await api.connectors.sync(connector.connector_type, since ? { since } : undefined);
      const runs = await api.connectors.syncRuns(connector.connector_type, 1) as { items?: SyncRun[] };
      setSyncRun((runs?.items ?? [])[0] ?? null);
      setStep('synced');
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Sync failed to start');
      setStep('error');
    }
  }

  return (
    <Modal open onClose={onClose}>
      <ModalHeader>
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-sm">{connector.label}</span>
          {connector.enabled
            ? <Badge variant="success">enabled</Badge>
            : <Badge variant="default">disabled</Badge>}
        </div>
        <p className="text-xs text-text-muted mt-1">{connector.description}</p>
      </ModalHeader>

      <ModalBody className="space-y-4">
        {step === 'configure' && (
          <>
            <Input
              label="Display name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={connector.label}
            />

            {connector.requires_secret && (
              <Input
                label={connector.secret_configured ? 'Update credential (leave blank to keep existing)' : 'Credential / API key'}
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={connector.secret_configured ? '••••••••' : 'Paste your API key or token'}
                autoComplete="new-password"
              />
            )}

            {connector.requires_secret && !connector.secret_configured && !secret && (
              <p className="text-xs text-status-warning">
                A credential is required to enable this connector. Secrets are encrypted at rest and never logged.
              </p>
            )}

            <label className="flex items-center gap-2 cursor-pointer select-none text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="rounded"
              />
              Enable connector
            </label>
          </>
        )}

        {step === 'testing' && (
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <span className="animate-spin">⟳</span>
            Saving and verifying connection…
          </div>
        )}

        {step === 'sync' && (
          <div className="space-y-3">
            <p className="text-sm text-status-success font-medium">Connection verified.</p>
            <div>
              <label className="block text-xs text-text-muted mb-1">Historical backfill window</label>
              <select
                className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm"
                value={backfillIdx}
                onChange={(e) => setBackfillIdx(Number(e.target.value))}
              >
                {BACKFILL_OPTIONS.map((o, i) => (
                  <option key={o.label} value={i}>{o.label}</option>
                ))}
              </select>
              <p className="text-xs text-text-muted mt-1">
                Choose how far back to import. Providers may cap the available window.
              </p>
            </div>
          </div>
        )}

        {step === 'syncing' && (
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <span className="animate-spin">⟳</span>
            Starting synchronization…
          </div>
        )}

        {step === 'synced' && (
          <div className="space-y-1">
            <p className="text-sm text-status-success font-medium">Synchronization started.</p>
            {syncRun && (
              <div className="text-xs text-text-muted space-y-0.5">
                <div>Status: <span className="font-mono">{syncRun.status ?? 'running'}</span> ({syncRun.mode ?? 'sync'})</div>
                <div>Records received: {syncRun.records_received ?? 0}</div>
                <div>Campaigns imported: {syncRun.campaigns_created ?? 0}</div>
                {syncRun.safe_error_code && (
                  <p className="text-status-warning">
                    Issue: {syncRun.safe_error_code} — {syncRun.safe_error_detail ?? 'see connector health for remediation'}
                  </p>
                )}
              </div>
            )}
            <p className="text-xs text-text-muted">Track progress under this connector’s sync history.</p>
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-1">
            <p className="text-sm text-status-success font-medium">Connector saved.</p>
            {testResult === 'fail' && (
              <p className="text-xs text-status-warning">
                Saved, but the connection test failed: {errorMsg || 'check the credential and try again'}.
              </p>
            )}
          </div>
        )}

        {step === 'error' && (
          <p className="text-sm text-status-danger">{errorMsg}</p>
        )}
      </ModalBody>

      <ModalFooter>
        {step === 'sync' ? (
          <>
            <Button variant="secondary" size="sm" onClick={onSaved}>Skip for now</Button>
            <Button size="sm" onClick={() => { void handleStartSync(); }}>Start initial sync</Button>
          </>
        ) : step === 'synced' || step === 'done' ? (
          <Button variant="secondary" size="sm" onClick={onSaved}>Close</Button>
        ) : step === 'error' ? (
          <Button variant="secondary" size="sm" onClick={onClose}>Close</Button>
        ) : (
          <>
            <Button variant="secondary" size="sm" onClick={onClose} disabled={step === 'testing' || step === 'syncing'}>Cancel</Button>
            <Button
              size="sm"
              onClick={() => { void handleSave(); }}
              disabled={step === 'testing' || step === 'syncing' || (connector.requires_secret && !connector.secret_configured && !secret.trim())}
            >
              {step === 'testing' ? 'Saving…' : 'Save'}
            </Button>
          </>
        )}
      </ModalFooter>
    </Modal>
  );
}
