import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ExperienceFrameSlots,
  experienceFrameSchema,
  slotStateVariant,
} from '@aether-app/features/experience-frame';

const serverFrame = {
  surfaceId: 'account360',
  tenantId: 'tenant-1',
  subject: { kind: 'account', id: 'acct-1' },
  state: 'partial',
  generatedAt: '2026-11-07T10:00:00Z',
  asOf: null,
  ownsCanonicalTruth: false,
  warnings: ['one slot unavailable'],
  degradation: { level: 'partial' },
  slots: [
    {
      id: 'overview', requirement: 'required', state: 'available',
      evidenceRefs: [{ id: 'e1' }, { id: 'e2' }],
      policyDisposition: { state: 'allowed' },
      content: { secret: 'must not be rendered' },
    },
    {
      id: 'billing', requirement: 'optional', state: 'unknown',
      reasonCodes: ['provider_timeout'], limitations: ['billing provider did not answer'],
      policyDisposition: { state: 'unknown' },
    },
    { id: 'contacts', requirement: 'optional', state: 'missing' },
    { id: 'novel', requirement: 'optional', state: 'future_state' },
  ],
};

describe('ExperienceFrameSlots', () => {
  it('shows every slot state exactly as the server sent it', () => {
    const frame = experienceFrameSchema.parse(serverFrame);
    render(<ExperienceFrameSlots frame={frame} />);
    const list = screen.getByRole('list', { name: 'account360 slots' });
    const row = (id: string) => within(list).getByText(id).closest('li') as HTMLElement;
    expect(within(row('overview')).getByText('available')).toBeTruthy();
    expect(within(row('billing')).getByText('unknown')).toBeTruthy();
    expect(within(row('contacts')).getByText('missing')).toBeTruthy();
    expect(within(row('novel')).getByText('future_state')).toBeTruthy();
    expect(screen.getByText(/frame state:/).parentElement?.textContent).toContain('partial');
  });

  it('keeps partial and unknown slots visibly different from available ones', () => {
    expect(slotStateVariant('available')).toBe('success');
    expect(slotStateVariant('unknown')).not.toBe('success');
    expect(slotStateVariant('degraded')).not.toBe('success');
    expect(slotStateVariant('missing')).not.toBe('success');
    expect(slotStateVariant('future_state')).toBe('default');
  });

  it('shows reasons, limitations, evidence counts, and policy, never slot content', () => {
    const frame = experienceFrameSchema.parse(serverFrame);
    const { container } = render(<ExperienceFrameSlots frame={frame} />);
    expect(screen.getByText('reason: provider_timeout')).toBeTruthy();
    expect(screen.getByText('limitation: billing provider did not answer')).toBeTruthy();
    expect(screen.getByText('evidence refs: 2')).toBeTruthy();
    expect(screen.getByText('warning: one slot unavailable')).toBeTruthy();
    expect(container.textContent).not.toContain('must not be rendered');
  });

  it('rejects a frame that claims to own canonical truth', () => {
    expect(() => experienceFrameSchema.parse({ ...serverFrame, ownsCanonicalTruth: true })).toThrow();
  });
});
