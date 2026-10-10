import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ExplorationBreadcrumbs } from './breadcrumbs';
import { SavedViewChrome } from './saved-view-chrome';

describe('ExplorationBreadcrumbs', () => {
  it('renders each crumb', () => {
    const html = renderToStaticMarkup(
      <ExplorationBreadcrumbs crumbs={[{ label: 'Graph' }, { label: 'cluster · c1' }]} />,
    );
    expect(html).toContain('Graph');
    expect(html).toContain('cluster · c1');
  });

  it('renders nothing for an empty trail', () => {
    expect(renderToStaticMarkup(<ExplorationBreadcrumbs crumbs={[]} />)).toBe('');
  });
});

describe('SavedViewChrome', () => {
  it('says saved views are unavailable when the surface does not support them', () => {
    const html = renderToStaticMarkup(<SavedViewChrome views={[]} supportsSavedViews={false} />);
    expect(html).toContain('not available');
  });

  it('renders a save control when supported', () => {
    const html = renderToStaticMarkup(
      <SavedViewChrome views={[]} supportsSavedViews onSave={() => undefined} />,
    );
    expect(html).toContain('Save view');
  });
});
