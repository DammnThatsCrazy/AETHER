import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { RedirectPreservingQuery } from '@aether-app/app/router';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}{location.hash}</output>;
}

describe('Aether route compatibility', () => {
  it('redirects legacy /graph to /explore without dropping query or hash state', () => {
    render(
      <MemoryRouter initialEntries={['/graph?entity=user-1#focus']}>
        <Routes>
          <Route path="/graph" element={<RedirectPreservingQuery to="/explore" />} />
          <Route path="/explore" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=user-1#focus');
  });
});
