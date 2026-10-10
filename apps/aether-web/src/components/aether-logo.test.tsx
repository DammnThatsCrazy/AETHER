import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AetherLogo } from './aether-logo';

describe('AetherLogo', () => {
  it('delegates the standard lockup to the canonical compact composition', () => {
    render(<AetherLogo size={28} />);

    expect(screen.getByRole('img', { name: 'Aether' })).toHaveAttribute('data-variant', 'compact');
    expect(screen.getByRole('img', { name: 'Aether' })).toHaveClass('aether-product-lockup');
  });

  it('preserves the mark-only compatibility option', () => {
    render(<AetherLogo size={28} showWordmark={false} />);

    expect(screen.getByRole('img', { name: 'Aether' })).toHaveAttribute('data-variant', 'mark');
  });
});
