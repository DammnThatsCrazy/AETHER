import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ChannelTypeIcon } from './channel-type-icon';

describe('ChannelTypeIcon', () => {
  it('uses the central neutral provider fallback rather than feature-local third-party SVG geometry', () => {
    const { container } = render(<ChannelTypeIcon type="slack" />);

    expect(container.querySelector('[data-provider="slack"]')).not.toBeNull();
    expect(container.querySelector('[data-provider-mark="fallback"]')).not.toBeNull();
    expect(container.querySelector('svg')).toBeNull();
    expect(container).toHaveTextContent('S');
  });

  it('keeps a generic webhook neutral and decorative when its text label is adjacent', () => {
    const { container } = render(<ChannelTypeIcon type="webhook" />);

    expect(container.querySelector('[data-provider="webhook"]')).not.toBeNull();
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
    expect(container).toHaveTextContent('W');
  });
});
