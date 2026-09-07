import { useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui'
import {
  useCampaignSourceAdOptions,
  useConnectCampaignSource,
  useSetCampaignSourceAccount,
  type CampaignSourceRecord,
  type ConnectCampaignSourceInput,
} from '@aether-app/features/campaigns/use-campaign-sources'

/**
 * AdConnectFlow — honest, self-contained advertising CampaignSource connect.
 *
 * Reads the tenant's /v1/campaign-sources/ad-options (useCampaignSourceAdOptions)
 * and drives /v1/campaign-sources/connect for the requested ad ``platform``
 * family. Advertising accounts are SINGLE-account and MANUAL: there is no
 * account discovery, so the one account identifier (the option's ``account_field``
 * config key) is collected as a plain manual input and sent in the connect
 * config. Nothing is ever dressed as Connected/Ready — every transition is
 * driven by the backend response, and mutation errors are shown verbatim.
 */
export interface AdConnectFlowProps {
  /** The advertising platform family to connect (matches the ad-option ``family``). */
  readonly platform: string
  readonly onDone?: () => void
  readonly onCancel?: () => void
}

/** Turn a config key into a readable label: customer_id → "Customer ID". */
function humanizeField(key: string): string {
  return key
    .split('_')
    .filter(Boolean)
    .map(part => (part === 'id' ? 'ID' : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(' ')
}

export function AdConnectFlow({ platform, onDone, onCancel }: AdConnectFlowProps) {
  const adOptions = useCampaignSourceAdOptions()
  const connect = useConnectCampaignSource()
  const setAccount = useSetCampaignSourceAccount()

  const option = (adOptions.data?.items ?? []).find(o => o.family === platform) ?? null

  const [draft, setDraft] = useState<Record<string, string>>({})
  const [accountDraft, setAccountDraft] = useState('')
  const [pendingAccount, setPendingAccount] = useState<CampaignSourceRecord | null>(null)

  const displayName = option?.display_name && option.display_name.length > 0
    ? option.display_name
    : humanizeField(platform)

  if (adOptions.isLoading && !option) {
    return <LoadingState lines={3} />
  }

  if (adOptions.error && !option) {
    return (
      <ErrorState
        title="Could not load connect options"
        message={String(adOptions.error)}
        onRetry={adOptions.refetch}
      />
    )
  }

  if (!option) {
    return (
      <EmptyState
        title={`${displayName} is not available to connect`}
        description={`There is no advertising connect option for “${platform}” in this workspace, so nothing is presented to fill in.`}
        action={onCancel ? (
          <Button type="button" variant="secondary" size="sm" onClick={onCancel}>Go back</Button>
        ) : undefined}
      />
    )
  }

  if (option.already_connected) {
    return (
      <Card data-ad-connect-flow className="max-w-xl">
        <CardHeader>
          <CardTitle>{displayName}</CardTitle>
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          )}
        </CardHeader>
        <CardContent>
          <EmptyState
            title="Already connected"
            description={`${displayName} already has an active campaign source — connecting again would not change its credentials. Manage or sync the existing source from the sources list on this page.`}
          />
        </CardContent>
      </Card>
    )
  }

  // ── Option present and not already connected: gather a complete config ──
  const accountField = option.account_field && option.account_field.length > 0
    ? option.account_field
    : null
  const credentialFields = option.credential_fields ?? []
  // The account identifier is collected once as the manual account picker below,
  // never double-rendered as a generic credential field.
  const credentialInputs = accountField
    ? credentialFields.filter(f => f.name !== accountField)
    : credentialFields

  const inputId = (name: string): string => `adc-${platform}-${name}`

  const credentialComplete = credentialInputs.every(f => {
    if (f.required === false) return true
    return (draft[f.name] ?? '').trim() !== ''
  })
  const accountComplete = accountField === null || accountDraft.trim() !== ''
  const canConnect = credentialComplete && accountComplete

  function finish(): void {
    setDraft({})
    setAccountDraft('')
    setPendingAccount(null)
    onDone?.()
  }

  async function submit(): Promise<void> {
    if (option === null || connect.isLoading) return
    const config: Record<string, string> = {}
    for (const f of credentialInputs) {
      config[f.name] = (draft[f.name] ?? '').trim()
    }
    if (accountField !== null) config[accountField] = accountDraft.trim()

    const payload: ConnectCampaignSourceInput = {
      platform: option.family,
      name: displayName,
      config,
    }

    // Credentials never linger once the connect request has fired.
    setDraft({})
    const result = await connect.mutate(payload)
    if (result === null) return // error is surfaced verbatim by connect.error

    const source = result.source ?? null
    // Honest account gate: only require the account sub-step when the backend
    // response actually reports an account-less source for a family whose option
    // carries an account field. A connect that already bound the account is done.
    if (source !== null && accountField !== null && !source.account_id) {
      setPendingAccount(source)
      return
    }
    finish()
  }

  async function submitAccount(): Promise<void> {
    const sourceId = pendingAccount?.connector_id
    if (!sourceId || setAccount.isLoading) return
    const result = await setAccount.mutate({ connectorId: sourceId, accountId: accountDraft.trim() })
    if (result === null) return
    finish()
  }

  const inputClass = 'w-full bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-border-focus'
  const labelClass = 'block text-[10px] uppercase tracking-wide text-text-muted mb-1'

  if (pendingAccount !== null) {
    const pendingSourceId = pendingAccount.connector_id ?? ''
    return (
      <Card data-ad-connect-flow className="max-w-xl">
        <CardHeader>
          <CardTitle>Set {displayName} account</CardTitle>
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-text-secondary">
            The connect response reported a source for {pendingSourceId} without a bound
            account. Set the single account it is bound to manually.
          </p>
          <form
            id={`connect-${platform}-account`}
            aria-label={`Set ${displayName} account`}
            className="space-y-3"
            onSubmit={e => { e.preventDefault(); void submitAccount() }}
          >
            {accountField !== null && (
              <div>
                <label htmlFor={inputId('account')} className={labelClass}>
                  {humanizeField(accountField)}
                </label>
                <input
                  id={inputId('account')}
                  type="text"
                  autoComplete="off"
                  required
                  data-account-picker
                  data-connect-form={platform}
                  className={inputClass}
                  value={accountDraft}
                  onChange={e => setAccountDraft(e.target.value)}
                  placeholder="account identifier"
                />
                <p className="text-[10px] text-text-muted mt-1">
                  Account selection is manual — this platform has no account discovery.
                </p>
              </div>
            )}
            {setAccount.error && (
              <p className="text-xs font-mono text-danger break-words">{setAccount.error}</p>
            )}
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!accountComplete || setAccount.isLoading}
            >
              {setAccount.isLoading ? '[···]' : 'Set account'}
            </Button>
          </form>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card data-ad-connect-flow className="max-w-xl">
      <CardHeader>
        <CardTitle>Connect {displayName}</CardTitle>
        {onCancel && (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        )}
      </CardHeader>
      <CardContent>
        <form
          id={`connect-${platform}`}
          aria-label={`Connect ${displayName}`}
          className="space-y-3"
          onSubmit={e => { e.preventDefault(); void submit() }}
        >
          {credentialInputs.map(f => (
            <div key={f.name}>
              <label htmlFor={inputId(f.name)} className={labelClass}>
                {humanizeField(f.name)}
              </label>
              <input
                id={inputId(f.name)}
                type={f.secret !== false ? 'password' : 'text'}
                autoComplete="off"
                required={f.required !== false}
                data-credential-field={f.name}
                data-connect-form={platform}
                className={inputClass}
                value={draft[f.name] ?? ''}
                onChange={e => setDraft(prev => ({ ...prev, [f.name]: e.target.value }))}
                placeholder={f.secret !== false ? '••••••••' : humanizeField(f.name)}
              />
            </div>
          ))}

          {accountField !== null && (
            <div>
              <label htmlFor={inputId('account')} className={labelClass}>
                {humanizeField(accountField)}
              </label>
              <input
                id={inputId('account')}
                type="text"
                autoComplete="off"
                required
                data-account-picker
                data-connect-form={platform}
                className={inputClass}
                value={accountDraft}
                onChange={e => setAccountDraft(e.target.value)}
                placeholder={humanizeField(accountField)}
              />
              <p className="text-[10px] text-text-muted mt-1">
                Account selection is manual — this platform has no account discovery.
              </p>
            </div>
          )}

          {connect.error && (
            <p className="text-xs font-mono text-danger break-words">{connect.error}</p>
          )}

          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={!canConnect || connect.isLoading}
          >
            {connect.isLoading ? '[···]' : 'Connect'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
