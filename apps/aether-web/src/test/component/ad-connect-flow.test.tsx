import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdConnectFlow } from '@aether-app/features/campaigns/ad-connect-flow'

// The component consumes the WS-2 advertising hooks directly; fully stub the
// hook module so no real API client or query cache is loaded in this test.
const hookState = vi.hoisted(() => ({
  adOptions: {
    data: null as Record<string, unknown> | null,
    isLoading: false,
    error: null as string | null,
    refetch: vi.fn(),
  },
  overview: {
    data: null as { items: Record<string, unknown>[] } | null,
    isLoading: false,
    error: null as string | null,
    refetch: vi.fn(),
  },
  connect: {
    mutate: vi.fn(),
    isLoading: false,
    error: null as string | null,
    data: null as Record<string, unknown> | null,
    reset: vi.fn(),
  },
  reconnect: {
    mutate: vi.fn(),
    isLoading: false,
    error: null as string | null,
    data: null as Record<string, unknown> | null,
    reset: vi.fn(),
  },
  sync: {
    mutate: vi.fn(),
    isLoading: false,
    error: null as string | null,
    reset: vi.fn(),
  },
  setAccount: {
    mutate: vi.fn(),
    isLoading: false,
    error: null as string | null,
    data: null as Record<string, unknown> | null,
    reset: vi.fn(),
  },
}))

vi.mock('@aether-app/features/campaigns/use-campaign-sources', () => ({
  useCampaignSourceAdOptions: () => hookState.adOptions,
  useCampaignSources: () => hookState.overview,
  useConnectCampaignSource: () => hookState.connect,
  useReconnectCampaignSource: () => hookState.reconnect,
  useSyncCampaignSource: () => hookState.sync,
  useSetCampaignSourceAccount: () => hookState.setAccount,
}))

/** Single-account, manual-selection option (the truthful WS-2 wire shape). */
const META_OPTION = {
  family: 'meta_ads',
  display_name: 'Meta Ads',
  category: 'advertising_campaigns',
  account_field: 'ad_account_id',
  account_discovery: false,
  already_connected: false,
  credential_fields: [
    { name: 'ad_account_id', type: 'string', secret: false, required: true },
    { name: 'access_token', type: 'secret', secret: true, required: true },
  ],
}

function defaultState() {
  hookState.adOptions.data = null
  hookState.adOptions.isLoading = false
  hookState.adOptions.error = null
  hookState.adOptions.refetch = vi.fn()
  // Default: an empty overview (no source row for any family).
  hookState.overview.data = { items: [] }
  hookState.overview.isLoading = false
  hookState.overview.error = null
  hookState.overview.refetch = vi.fn()
  hookState.connect.mutate = vi.fn()
  hookState.connect.isLoading = false
  hookState.connect.error = null
  hookState.connect.data = null
  hookState.connect.reset = vi.fn()
  hookState.reconnect.mutate = vi.fn()
  hookState.reconnect.isLoading = false
  hookState.reconnect.error = null
  hookState.reconnect.data = null
  hookState.reconnect.reset = vi.fn()
  hookState.sync.mutate = vi.fn()
  hookState.sync.isLoading = false
  hookState.sync.error = null
  hookState.sync.reset = vi.fn()
  hookState.setAccount.mutate = vi.fn()
  hookState.setAccount.isLoading = false
  hookState.setAccount.error = null
  hookState.setAccount.data = null
  hookState.setAccount.reset = vi.fn()
}

function renderFlow(platform = 'meta_ads', onDone = vi.fn(), onCancel = vi.fn()) {
  const utils = render(
    <AdConnectFlow platform={platform} onDone={onDone} onCancel={onCancel} />,
  )
  return { ...utils, onDone, onCancel }
}

function healthyActiveRow(overrides: Record<string, unknown> = {}) {
  return {
    connector_id: 'conn-1',
    platform: 'meta_ads',
    connector_type: 'meta_ads',
    name: 'Meta Ads',
    status: 'active',
    enabled: true,
    is_ad_platform: true,
    account_field: 'ad_account_id',
    account_id: 'act_987',
    secret_configured: true,
    missing_secrets: [],
    secrets_total: 1,
    health_status: 'healthy',
    health_message: null,
    error_count: 0,
    ...overrides,
  }
}

describe('AdConnectFlow', () => {
  beforeEach(() => {
    defaultState()
  })

  it('renders a loading state while ad options are loading', () => {
    hookState.adOptions.isLoading = true
    renderFlow()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByText('Connect Meta Ads')).not.toBeInTheDocument()
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument()
  })

  it('renders an ErrorState (never a form) when the options read fails', () => {
    hookState.adOptions.error = 'ad options service offline'
    renderFlow()
    expect(screen.getByText('Could not load connect options')).toBeInTheDocument()
    expect(screen.getByText('ad options service offline')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(document.querySelector('[data-connect-form]')).toBeNull()
    expect(screen.queryByText('Connect Meta Ads')).not.toBeInTheDocument()
  })

  it('renders an EmptyState when no option exists for the requested platform', () => {
    hookState.adOptions.data = { items: [META_OPTION], source_status: 'ok' }
    renderFlow('unknown_ads')
    expect(screen.getByText('Unknown Ads is not available to connect')).toBeInTheDocument()
    expect(screen.queryByText('Connect Meta Ads')).not.toBeInTheDocument()
  })

  // The behavior change: "already connected" is now decided from the source
  // overview (healthy active row → manage card, no reconnect) rather than from
  // the option's active-only flag alone.
  it('never offers connect or reconnect on a healthy active source', () => {
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: true }],
      source_status: 'ok',
    }
    hookState.overview.data = { items: [healthyActiveRow()] }
    renderFlow()
    expect(screen.getByText('Already connected')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reconnect' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(hookState.connect.mutate).not.toHaveBeenCalled()
    expect(hookState.reconnect.mutate).not.toHaveBeenCalled()
    expect(document.querySelector('[data-provider-family="meta_ads"]')).not.toBeNull()
  })

  it('connects a manual account + credential in the config and calls onDone once', async () => {
    const user = userEvent.setup()
    hookState.adOptions.data = { items: [META_OPTION], source_status: 'ok' }
    hookState.connect.mutate.mockResolvedValue({
      already_connected: false,
      platform: 'meta_ads',
      source: { connector_id: 'conn-1', platform: 'meta_ads', account_id: 'act_987' },
    })
    const { onDone } = renderFlow()

    expect(screen.getByText('Connect Meta Ads')).toBeInTheDocument()
    // Single manual account field with honest no-discovery helper text.
    expect(document.querySelector('[data-account-picker]')).not.toBeNull()
    expect(document.querySelector('[data-connect-form="meta_ads"]')).not.toBeNull()
    expect(
      screen.getByText('Account selection is manual — this platform has no account discovery.'),
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText('Access Token'), 'tok-123')
    await user.type(screen.getByLabelText('Ad Account ID'), 'act_987')
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(hookState.connect.mutate).toHaveBeenCalledTimes(1)
    expect(hookState.connect.mutate).toHaveBeenCalledWith({
      platform: 'meta_ads',
      name: 'Meta Ads',
      config: { access_token: 'tok-123', ad_account_id: 'act_987' },
    })
    // No fabricated Connected/Ready text is ever rendered by this flow.
    expect(screen.queryByText(/Connected|Ready/i)).not.toBeInTheDocument()
  })

  it('surfaces the backend connect error verbatim and never calls onDone', async () => {
    const user = userEvent.setup()
    hookState.adOptions.data = { items: [META_OPTION], source_status: 'ok' }
    hookState.connect.mutate.mockImplementation(async () => {
      hookState.connect.error = 'Incomplete meta_ads credential set'
      return null
    })
    const utils = renderFlow()
    const onDone = utils.onDone

    await user.type(screen.getByLabelText('Access Token'), 'tok-123')
    await user.type(screen.getByLabelText('Ad Account ID'), 'act_987')
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    // Re-render reads the mutation's updated error state, as a real hook would.
    utils.rerender(
      <AdConnectFlow platform="meta_ads" onDone={onDone} onCancel={vi.fn()} />,
    )
    expect(await screen.findByText('Incomplete meta_ads credential set')).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
    expect(screen.queryByText(/Connected|Ready/i)).not.toBeInTheDocument()
  })

  // ── Reconnect (health-aware re-credential) ───────────────────────────────

  it('renders a Reconnect form for a degraded source and posts the new credential', async () => {
    const user = userEvent.setup()
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: true }],
      source_status: 'ok',
    }
    hookState.overview.data = {
      items: [healthyActiveRow({ connector_id: 'conn-deg', account_id: 'act_deg', health_status: 'degraded', error_count: 3 })],
    }
    hookState.reconnect.mutate.mockResolvedValue({
      reconnected: true,
      connector_id: 'conn-deg',
      platform: 'meta_ads',
      status: 'active',
      source: healthyActiveRow({ connector_id: 'conn-deg', health_status: 'unknown', error_count: 0 }),
    })
    renderFlow()

    expect(screen.getByText('Reconnect Meta Ads')).toBeInTheDocument()
    // Same single-account MANUAL form + data markers are reused.
    expect(document.querySelector('[data-credential-field="access_token"]')).not.toBeNull()
    expect(document.querySelector('[data-account-picker]')).not.toBeNull()
    expect(document.querySelector('[data-connect-form="meta_ads"]')).not.toBeNull()
    expect(
      screen.getByText('Account selection is manual — this platform has no account discovery.'),
    ).toBeInTheDocument()

    // Account identifier is prefilled from the current source (not a rotation).
    const accountInput = screen.getByLabelText('Ad Account ID') as HTMLInputElement
    expect(accountInput.value).toBe('act_deg')

    await user.type(screen.getByLabelText('Access Token'), 'tok-new')
    await user.click(screen.getByRole('button', { name: 'Reconnect' }))

    await waitFor(() => expect(hookState.reconnect.mutate).toHaveBeenCalledTimes(1))
    expect(hookState.reconnect.mutate).toHaveBeenCalledWith({
      connectorId: 'conn-deg',
      secretConfig: { access_token: 'tok-new', ad_account_id: 'act_deg' },
    })
    expect(hookState.connect.mutate).not.toHaveBeenCalled()
  })

  it('offers Reconnect for a disabled row (re-credential, not re-activation)', async () => {
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: false }],
      source_status: 'ok',
    }
    hookState.overview.data = {
      items: [healthyActiveRow({ connector_id: 'conn-dis', enabled: false, status: 'disabled', health_status: 'unknown' })],
    }
    renderFlow()
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument()
    expect(screen.queryByText('Already connected')).not.toBeInTheDocument()
  })

  it('surfaces the backend reconnect error verbatim and never claims success', async () => {
    const user = userEvent.setup()
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: true }],
      source_status: 'ok',
    }
    hookState.overview.data = {
      items: [healthyActiveRow({ connector_id: 'conn-deg', account_id: 'act_deg', health_status: 'error' })],
    }
    hookState.reconnect.mutate.mockImplementation(async () => {
      hookState.reconnect.error = 'Campaign source conn-deg is active and healthy'
      return null
    })
    const utils = renderFlow()
    const onDone = utils.onDone

    await user.type(screen.getByLabelText('Access Token'), 'tok-new')
    await user.click(screen.getByRole('button', { name: 'Reconnect' }))

    utils.rerender(
      <AdConnectFlow platform="meta_ads" onDone={onDone} onCancel={vi.fn()} />,
    )
    expect(
      await screen.findByText('Campaign source conn-deg is active and healthy'),
    ).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
    expect(hookState.reconnect.data).toBeNull()
    expect(screen.queryByText(/Connected|Ready/i)).not.toBeInTheDocument()
  })

  it('shows the honest post-reconnect state (never Ready) and offers Sync now', async () => {
    const user = userEvent.setup()
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: true }],
      source_status: 'ok',
    }
    hookState.overview.data = {
      items: [healthyActiveRow({ connector_id: 'conn-deg', account_id: 'act_deg', health_status: 'degraded' })],
    }
    hookState.reconnect.mutate.mockImplementation(async () => {
      hookState.reconnect.data = {
        reconnected: true,
        connector_id: 'conn-deg',
        platform: 'meta_ads',
        status: 'active',
        source: healthyActiveRow({ connector_id: 'conn-deg', health_status: 'unknown', error_count: 0 }),
      }
      return hookState.reconnect.data
    })
    const utils = renderFlow()
    const onDone = utils.onDone

    await user.type(screen.getByLabelText('Access Token'), 'tok-new')
    await user.click(screen.getByRole('button', { name: 'Reconnect' }))

    utils.rerender(
      <AdConnectFlow platform="meta_ads" onDone={onDone} onCancel={vi.fn()} />,
    )
    // Honest copy: exactly what happened, and no evidence of a healthy sync.
    expect(
      await screen.findByText('Re-credential saved — the next sync will use it.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Connected|Ready/i)).not.toBeInTheDocument()
    // The sync (not the swap) is what exercises the credential.
    const syncButton = screen.getByRole('button', { name: 'Sync now' })
    await user.click(syncButton)
    await waitFor(() => expect(hookState.sync.mutate).toHaveBeenCalledWith('conn-deg'))
    expect(onDone).not.toHaveBeenCalled()
  })
})
