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
  useCampaignSources,
  useConnectCampaignSource,
  useReconnectCampaignSource,
  useSetCampaignSourceAccount,
  useSyncCampaignSource,
  type CampaignSourceRecord,
  type ConnectCampaignSourceInput,
} from '@aether-app/features/campaigns/use-campaign-sources'

/**
 * AdConnectFlow — honest, self-contained advertising CampaignSource connect /
 * re-credential flow.
 *
 * Reads the tenant's /v1/campaign-sources/ad-options (useCampaignSourceAdOptions)
 * for the credential shape of the requested ad ``platform`` family, and
 * /v1/campaign-sources/overview (useCampaignSources) for the family's actual
 * source rows, then branches on real source state:
 *
 * * no source row for the family → first-connect path (unchanged);
 * * an ACTIVE row that is NOT degraded/failed/stale (and has no missing
 *   secrets) → the honest "Already connected" manage card — reconnect is never
 *   offered on a healthy row;
 * * an ACTIVE-but-degraded/failed/stale row, a row with missing secrets, or a
 *   DISABLED row → a "Reconnect" form that posts the new single-account
 *   credential set to POST /v1/campaign-sources/{connector_id}/reconnect,
 *   replacing the stored config IN PLACE on the same connector.
 *
 * Advertising accounts are SINGLE-account and MANUAL: there is no account
 * discovery, so the one account identifier (the option's ``account_field``
 * config key) is collected as a plain manual input and sent in the config.
 * Nothing is ever dressed as Connected/Ready/healthy — a credential swap is not
 * evidence of a healthy sync, so the reconnect post-state says exactly that and
 * offers "Sync now" (the sync, not the swap, exercises the credential).
 * Mutation errors are shown verbatim.
 */
export interface AdConnectFlowProps {
  /** The advertising platform family to connect (matches the ad-option ``family``). */
  readonly platform: string
  readonly onDone?: () => void
  readonly onCancel?: () => void
}

/** health_status literals that mean the stored credential is (or may be) broken. */
const RECONNECT_HEALTH = new Set(['degraded', 'error', 'failed', 'stale', 'lagging'])

/** Whether a source row genuinely needs re-credentialing (never true on healthy). */
function sourceNeedsReconnect(source: CampaignSourceRecord): boolean {
  if (!source) return false
  // A disabled row cannot sync; the operator re-credentials then enables.
  if (source.enabled === false) return true
  // Degraded/failed/stale/error health is the degraded-source signal.
  if (source.health_status && RECONNECT_HEALTH.has(source.health_status)) return true
  // Missing secrets means the stored set cannot authenticate at all.
  if (source.secret_configured === false) return true
  return false
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
  const overview = useCampaignSources()
  const connect = useConnectCampaignSource()
  const reconnect = useReconnectCampaignSource()
  const sync = useSyncCampaignSource()
  const setAccount = useSetCampaignSourceAccount()

  const option = (adOptions.data?.items ?? []).find(o => o.family === platform) ?? null

  const [draft, setDraft] = useState<Record<string, string>>({})
  const [reconnectDraft, setReconnectDraft] = useState<Record<string, string>>({})
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

  // ── Source-state classification (overview is authoritative for row state) ──
  // Wait for the overview before deciding first-connect vs reconnect vs manage,
  // so a disabled/degraded row is never mislabeled as a fresh connect.
  if (overview.isLoading && overview.data === null && option.already_connected !== true) {
    return <LoadingState lines={3} />
  }

  const overviewItems = overview.data?.items ?? []
  const familyRows = overviewItems.filter(
    s => (s.platform ?? s.connector_type ?? '') === platform,
  )
  // One active row per family is enforced upstream; prefer it as "the source".
  const activeRow = familyRows.find(s => s.enabled === true) ?? null
  const currentSource = activeRow ?? familyRows[0] ?? null
  const reconnectTargetId = currentSource?.connector_id ?? null
  const needsReconnect = currentSource !== null && sourceNeedsReconnect(currentSource)

  // When the overview is unavailable we fall back to the option's own
  // active-only signal (the pre-reconnect gating), never guessing reconnect.
  const overviewMissing = overview.data === null
  const alreadyConnected = needsReconnect
    ? false
    : currentSource !== null || (overviewMissing && option.already_connected === true)

  const inputId = (name: string): string => `adc-${platform}-${name}`
  const inputClass = 'w-full bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-border-focus'
  const labelClass = 'block text-[10px] uppercase tracking-wide text-text-muted mb-1'

  const accountField = option.account_field && option.account_field.length > 0
    ? option.account_field
    : null
  const credentialFields = option.credential_fields ?? []
  // The account identifier is collected once as the manual account picker below,
  // never double-rendered as a generic credential field.
  const credentialInputs = accountField
    ? credentialFields.filter(f => f.name !== accountField)
    : credentialFields

  // ── First-connect path (no source row yet) ────────────────────────────────
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

  // ── Reconnect path (a degraded / failed / stale / disabled row) ──────────
  // The reconnect form reuses the SAME single-account manual credential form:
  // the operator re-enters the credential fields, and the account identifier is
  // prefilled from the current source (re-credentialing is a credential swap,
  // not an account rotation). Submitting replaces the stored config on the same
  // connector_id via the reconnect mutation.
  const reconnectAccountId = accountDraft.trim() !== ''
    ? accountDraft.trim()
    : (currentSource?.account_id ? String(currentSource.account_id) : '')
  const reconnectCredentialComplete = credentialInputs.every(f => {
    if (f.required === false) return true
    return (reconnectDraft[f.name] ?? '').trim() !== ''
  })
  const reconnectAccountComplete = accountField === null || reconnectAccountId !== ''
  const canReconnect = reconnectCredentialComplete && reconnectAccountComplete

  async function submitReconnect(): Promise<void> {
    if (reconnectTargetId === null || reconnect.isLoading) return
    const config: Record<string, string> = {}
    for (const f of credentialInputs) {
      config[f.name] = (reconnectDraft[f.name] ?? '').trim()
    }
    if (accountField !== null) config[accountField] = reconnectAccountId

    // Credentials never linger once the reconnect request has fired.
    setReconnectDraft({})
    const result = await reconnect.mutate({
      connectorId: reconnectTargetId,
      secretConfig: config,
    })
    if (result === null) return // error is surfaced verbatim by reconnect.error
    // No finish()/onDone here: the honest post-state is shown inline and a
    // "Sync now" action is offered (the sync, not the swap, exercises the
    // credential).
  }

  async function syncNow(): Promise<void> {
    if (reconnectTargetId === null || sync.isLoading) return
    await sync.mutate(reconnectTargetId)
  }

  // ── Honest post-reconnect state ───────────────────────────────────────────
  // A stored credential swap is not evidence of a healthy sync, so this is NOT a
  // Connected/Ready card — it says exactly what happened and offers to sync.
  if (reconnect.data !== null) {
    return (
      <Card data-ad-connect-flow data-provider-family={platform} className="max-w-xl">
        <CardHeader>
          <CardTitle>{displayName}</CardTitle>
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-text-primary">
            Re-credential saved — the next sync will use it.
          </p>
          <p className="text-xs text-text-secondary">
            The stored credential set on {reconnectTargetId ?? 'this source'} was replaced and its
            health/error state was reset. A credential swap is not evidence of a healthy sync.
          </p>
          <div className="flex items-center gap-2 pt-1">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => void syncNow()}
              disabled={sync.isLoading}
            >
              {sync.isLoading ? '[···]' : 'Sync now'}
            </Button>
          </div>
          {sync.error && (
            <p className="text-xs font-mono text-danger break-words">{sync.error}</p>
          )}
        </CardContent>
      </Card>
    )
  }

  // Account sub-step from a connect that returned an account-less source — kept
  // reachable above the manage/reconnect cards so a just-created source is never
  // masked by the overview's refreshed row.
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

  // Manage card for a healthy (or never-degraded) active source: reconnect is
  // NEVER offered on a healthy row.
  if (alreadyConnected) {
    return (
      <Card data-ad-connect-flow data-provider-family={platform} className="max-w-xl">
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

  if (needsReconnect) {
    return (
      <Card data-ad-connect-flow data-provider-family={platform} className="max-w-xl">
        <CardHeader>
          <CardTitle>Reconnect {displayName}</CardTitle>
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          )}
        </CardHeader>
        <CardContent>
          <form
            id={`reconnect-${platform}`}
            aria-label={`Reconnect ${displayName}`}
            className="space-y-3"
            onSubmit={e => { e.preventDefault(); void submitReconnect() }}
          >
            <p className="text-xs text-text-secondary">
              This source’s stored credential set will be replaced on the same connector. Its
              health state is reset until the next sync — a credential swap is not evidence of a
              healthy sync.
            </p>
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
                  value={reconnectDraft[f.name] ?? ''}
                  onChange={e => setReconnectDraft(prev => ({ ...prev, [f.name]: e.target.value }))}
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
                  value={reconnectAccountId}
                  onChange={e => setAccountDraft(e.target.value)}
                  placeholder={humanizeField(accountField)}
                />
                <p className="text-[10px] text-text-muted mt-1">
                  Account selection is manual — this platform has no account discovery.
                </p>
              </div>
            )}

            {reconnect.error && (
              <p className="text-xs font-mono text-danger break-words">{reconnect.error}</p>
            )}

            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!canReconnect || reconnect.isLoading}
            >
              {reconnect.isLoading ? '[···]' : 'Reconnect'}
            </Button>
          </form>
        </CardContent>
      </Card>
    )
  }

  // ── Option present and not already connected: gather a complete config ──
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
