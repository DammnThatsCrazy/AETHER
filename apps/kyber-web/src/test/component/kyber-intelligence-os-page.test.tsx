import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { KyberIntelligenceOSPage } from '@kyber/pages/intelligence-os';

describe('Kyber Intelligence Operating System route', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it('renders the populated graph and a successful empty command state', async () => {
    const user = userEvent.setup();

    render(<KyberIntelligenceOSPage />);

    expect(screen.getByRole('region', { name: 'Living graph workspace' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Select Human Maya Chen/ })).toBeInTheDocument();
    expect(screen.getByText('Why did Maya’s journey accelerate?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Evidence mode' }));
    expect(screen.getByText('Evidence supporting this claim')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Open command palette' }));
    const search = screen.getByPlaceholderText('Search entities, actions, investigations…');
    await user.type(search, 'not-in-the-graph');

    expect(screen.getByText('No context found in the current graph.')).toBeInTheDocument();
  });
});
