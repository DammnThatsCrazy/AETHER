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
  connect: {
    mutate: vi.fn(),
    isLoading: false,
    error: null as string | null,
    data: null as Record<string, unknown> | null,
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
  useConnectCampaignSource: () => hookState.connect,
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
  hookState.connect.mutate = vi.fn()
  hookState.connect.isLoading = false
  hookState.connect.error = null
  hookState.connect.data = null
  hookState.connect.reset = vi.fn()
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

  it('never re-connects a platform that is already connected', () => {
    hookState.adOptions.data = {
      items: [{ ...META_OPTION, already_connected: true }],
      source_status: 'ok',
    }
    renderFlow()
    expect(screen.getByText('Already connected')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(hookState.connect.mutate).not.toHaveBeenCalled()
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
})
