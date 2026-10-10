import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import {
  EvidenceReferences,
  sanitizeSnippet,
  truncateSnippet,
  type EvidenceRef,
} from '@aether-app/features/model-selection/EvidenceReferences';

describe('EvidenceReferences', () => {
  it('renders a row per reference with referenceId and source', () => {
    const evidence: EvidenceRef[] = [
      { referenceId: 'rec-1', source: 'accounts' },
      { referenceId: 'rec-2', source: 'transactions', snippet: 'updated balance' },
    ];

    render(<EvidenceReferences evidence={evidence} />);

    expect(screen.getByText('Evidence references (2)')).toBeInTheDocument();
    expect(screen.getByText('rec-1')).toBeInTheDocument();
    expect(screen.getByText('accounts')).toBeInTheDocument();
    expect(screen.getByText('rec-2')).toBeInTheDocument();
    expect(screen.getByText('transactions')).toBeInTheDocument();
    expect(screen.getByText('updated balance')).toBeInTheDocument();
  }, 15_000);

  it('truncates a long snippet to 160 characters with an ellipsis', () => {
    const longSnippet = 'x'.repeat(200);
    const evidence: EvidenceRef[] = [
      { referenceId: 'rec-1', source: 'accounts', snippet: longSnippet },
    ];

    render(<EvidenceReferences evidence={evidence} />);

    const rendered = screen.getByText(`${'x'.repeat(160)}…`);
    expect(rendered).toBeInTheDocument();
    expect(rendered.textContent).toHaveLength(161);
  }, 15_000);

  it('renders nothing when evidence is empty', () => {
    const { container } = render(<EvidenceReferences evidence={[]} />);
    expect(container).toBeEmptyDOMElement();
  }, 15_000);

  it('redacts credential-like patterns in snippets', () => {
    const evidence: EvidenceRef[] = [
      {
        referenceId: 'rec-1',
        source: 'ledger',
        snippet: 'api key sk-abc12345 rotated; AKIAIOSFODNN7EXAMPLE and Bearer abc.def.ghi',
      },
    ];

    render(<EvidenceReferences evidence={evidence} />);

    expect(screen.queryByText(/sk-abc12345/)).not.toBeInTheDocument();
    expect(screen.queryByText(/AKIAIOSFODNN7EXAMPLE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Bearer abc\.def\.ghi/)).not.toBeInTheDocument();
    expect(screen.getByText(/\[redacted\]/)).toBeInTheDocument();
  }, 15_000);

  it('strips control characters during sanitization', () => {
    expect(sanitizeSnippet('line1\x00\x1Fline2')).toBe('line1  line2');
  }, 15_000);

  it('toggles the collapsible list via the summary', async () => {
    const user = userEvent.setup();
    const evidence: EvidenceRef[] = [
      { referenceId: 'rec-1', source: 'accounts' },
    ];

    const { container } = render(<EvidenceReferences evidence={evidence} />);

    const details = container.querySelector('details');
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false);

    const summary = screen.getByText('Evidence references (1)');
    await user.click(summary);
    expect(details!.open).toBe(true);

    await user.click(summary);
    expect(details!.open).toBe(false);
  }, 15_000);
});

describe('sanitizeSnippet', () => {
  it('redacts sk- keys, AKIA keys, and Bearer tokens and preserves plain text', () => {
    const result = sanitizeSnippet(
      'key sk-live-abc was leaked; AKIAIOSFODNN7EXAMPLE; Bearer abc.def_ghi~+; keep me',
    );
    expect(result).not.toContain('sk-live-abc');
    expect(result).not.toContain('AKIAIOSFODNN7EXAMPLE');
    expect(result).not.toContain('Bearer abc.def_ghi~+');
    expect(result).toContain('[redacted]');
    expect(result).toContain('keep me');
  }, 15_000);
});

describe('truncateSnippet', () => {
  it('returns short snippets unchanged and truncates long ones with an ellipsis', () => {
    expect(truncateSnippet('short')).toBe('short');
    expect(truncateSnippet('a'.repeat(160))).toBe('a'.repeat(160));
    expect(truncateSnippet('b'.repeat(161))).toBe(`${'b'.repeat(160)}…`);
  }, 15_000);
});
