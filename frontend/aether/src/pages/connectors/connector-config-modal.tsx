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

type Step = 'configure' | 'testing' | 'done' | 'error';

export function ConnectorConfigModal({ connector, onClose, onSaved }: Props) {
  const [secret, setSecret] = useState('');
  const [name, setName] = useState(connector.label);
  const [enabled, setEnabled] = useState(connector.enabled);
  const [step, setStep] = useState<Step>('configure');
  const [errorMsg, setErrorMsg] = useState('');
  const [testResult, setTestResult] = useState<'ok' | 'fail' | null>(null);

  async function handleSave() {
    setStep('testing');
    setErrorMsg('');
    try {
      const body: Record<string, unknown> = {
        name,
        enabled,
        config: {},
      };
      if (secret.trim()) body['secret'] = secret.trim();

      await api.connectors.configure(connector.connector_type, body);

      if (enabled) {
        try {
          await api.connectors.test(connector.connector_type);
          setTestResult('ok');
        } catch {
          setTestResult('fail');
        }
      }

      setStep('done');
      onSaved();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Save failed');
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

        {step === 'done' && (
          <div className="space-y-1">
            <p className="text-sm text-status-success font-medium">Connector saved.</p>
            {testResult === 'ok' && <p className="text-xs text-text-muted">Connection test passed.</p>}
            {testResult === 'fail' && (
              <p className="text-xs text-status-warning">
                Saved, but the connection test failed. Check your credential and try again from the connectors list.
              </p>
            )}
          </div>
        )}

        {step === 'error' && (
          <p className="text-sm text-status-danger">{errorMsg}</p>
        )}
      </ModalBody>

      <ModalFooter>
        {step === 'done' || step === 'error' ? (
          <Button variant="secondary" size="sm" onClick={onClose}>Close</Button>
        ) : (
          <>
            <Button variant="secondary" size="sm" onClick={onClose} disabled={step === 'testing'}>Cancel</Button>
            <Button
              size="sm"
              onClick={() => { void handleSave(); }}
              disabled={step === 'testing' || (connector.requires_secret && !connector.secret_configured && !secret.trim())}
            >
              {step === 'testing' ? 'Saving…' : 'Save'}
            </Button>
          </>
        )}
      </ModalFooter>
    </Modal>
  );
}
