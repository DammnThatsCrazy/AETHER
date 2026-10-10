import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ModelRegistryView, MODEL_STATUS_CLASS } from '@aether-app/features/model-selection/ModelRegistryView';
import type { ModelRegistryModel } from '@aether-app/features/model-selection/types';

// C13-F owns types.ts. ModelRegistryView only imports the type (erased at
// runtime), so this suite depends on the contract shape, not the file.

const MODELS: ModelRegistryModel[] = [
  {
    modelId: 'anthropic/claude-sonnet-4',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['text'],
    inputCostPerMTok: 3,
    outputCostPerMTok: 15,
  },
  {
    modelId: 'anthropic/claude-haiku-4',
    provider: 'anthropic',
    status: 'stable',
    capabilities: ['text', 'tool'],
    inputCostPerMTok: 0.8,
    outputCostPerMTok: 4,
  },
  {
    modelId: 'openai/gpt-4o',
    provider: 'openai',
    status: 'beta',
    capabilities: ['text', 'image'],
    inputCostPerMTok: 2.5,
    outputCostPerMTok: 10,
  },
  {
    modelId: 'openai/text-davinci',
    provider: 'openai',
    status: 'deprecated',
    capabilities: ['text'],
    inputCostPerMTok: 2,
    outputCostPerMTok: 6,
  },
  {
    modelId: 'cohere/command-r',
    provider: 'cohere',
    status: 'experimental',
    capabilities: ['text', 'tool'],
    inputCostPerMTok: 1,
    outputCostPerMTok: 4,
  },
];

const ALL_STATUSES: ModelRegistryModel['status'][] = [
  'recommended',
  'stable',
  'beta',
  'deprecated',
  'experimental',
];

/** Per-spec color encoding for each status badge (green/blue/amber/gray/purple). */
const STATUS_COLOR_CLASS: Record<ModelRegistryModel['status'], string> = {
  recommended: 'bg-emerald-100',
  stable: 'bg-blue-100',
  beta: 'bg-amber-100',
  deprecated: 'bg-gray-200',
  experimental: 'bg-purple-100',
};

describe('ModelRegistryView (tenant model registry read-only view)', () => {
  it('renders each model row with provider, status, capabilities, and cost', () => {
    render(<ModelRegistryView models={MODELS} />);

    const row = screen.getByTestId('model-row-anthropic/claude-sonnet-4');
    expect(within(row).getByText('anthropic/claude-sonnet-4')).toBeInTheDocument();
    expect(within(row).getByText('anthropic')).toBeInTheDocument();
    expect(within(row).getByText('recommended')).toBeInTheDocument();
    expect(within(row).getByText('text')).toBeInTheDocument();
    expect(within(row).getByText('$3.00/MTok')).toBeInTheDocument();
    expect(within(row).getByText('$15.00/MTok')).toBeInTheDocument();

    const gptRow = screen.getByTestId('model-row-openai/gpt-4o');
    expect(within(gptRow).getByText('openai/gpt-4o')).toBeInTheDocument();
    expect(within(gptRow).getByText('openai')).toBeInTheDocument();
    expect(within(gptRow).getByText('beta')).toBeInTheDocument();
    expect(within(gptRow).getByText('image')).toBeInTheDocument();
    expect(within(gptRow).getByText('$2.50/MTok')).toBeInTheDocument();
    expect(within(gptRow).getByText('$10.00/MTok')).toBeInTheDocument();
  }, 15_000);

  it('groups models by provider with one header per provider', () => {
    render(<ModelRegistryView models={MODELS} />);

    const anthropicGroup = screen.getByTestId('provider-group-anthropic');
    expect(within(anthropicGroup).getByRole('heading', { name: 'anthropic' })).toBeInTheDocument();
    expect(
      within(anthropicGroup).getByTestId('model-row-anthropic/claude-sonnet-4'),
    ).toBeInTheDocument();
    expect(
      within(anthropicGroup).getByTestId('model-row-anthropic/claude-haiku-4'),
    ).toBeInTheDocument();
    expect(within(anthropicGroup).queryByTestId('model-row-openai/gpt-4o')).toBeNull();

    const openaiGroup = screen.getByTestId('provider-group-openai');
    expect(within(openaiGroup).getByRole('heading', { name: 'openai' })).toBeInTheDocument();
    expect(within(openaiGroup).getByTestId('model-row-openai/gpt-4o')).toBeInTheDocument();
    expect(within(openaiGroup).getByTestId('model-row-openai/text-davinci')).toBeInTheDocument();

    const cohereGroup = screen.getByTestId('provider-group-cohere');
    expect(within(cohereGroup).getByRole('heading', { name: 'cohere' })).toBeInTheDocument();
    expect(within(cohereGroup).getByTestId('model-row-cohere/command-r')).toBeInTheDocument();

    // Exactly one header per provider.
    expect(screen.getAllByRole('heading')).toHaveLength(3);
  }, 15_000);

  it('renders an empty state when no models are registered', () => {
    render(<ModelRegistryView models={[]} />);

    expect(screen.getByText('No models registered')).toBeInTheDocument();
    expect(screen.getByTestId('model-registry-empty')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByTestId('model-registry')).toBeNull();
  }, 15_000);

  it('applies the correct badge classes for each status', () => {
    render(<ModelRegistryView models={MODELS} />);

    for (const status of ALL_STATUSES) {
      const badge = screen.getByTestId(`status-badge--${status}`);
      expect(badge).toHaveClass('status-badge');
      expect(badge).toHaveClass(`status-badge--${status}`);
      expect(badge).toHaveClass(STATUS_COLOR_CLASS[status]);
      // The semantic mapping is what the component uses for the badge.
      expect(badge.className).toContain(MODEL_STATUS_CLASS[status]);
    }

    // Each status maps to a distinct color encoding (green/blue/amber/gray/purple).
    const colorEncodings = ALL_STATUSES.map((status) => STATUS_COLOR_CLASS[status]);
    expect(new Set(colorEncodings).size).toBe(ALL_STATUSES.length);
  }, 15_000);

  it('never renders secret-like strings (no credentials in the registry view)', () => {
    const { container } = render(<ModelRegistryView models={MODELS} />);

    const rendered = container.textContent ?? '';
    expect(rendered).not.toMatch(/sk-/);
    expect(rendered).not.toMatch(/AKIA/);
    expect(rendered).not.toMatch(/Bearer/);
    expect(screen.queryByText(/sk-|AKIA|Bearer/)).toBeNull();
  }, 15_000);
});
