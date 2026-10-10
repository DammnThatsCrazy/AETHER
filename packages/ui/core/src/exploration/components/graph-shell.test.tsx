import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GraphContextBar } from './graph-context-bar';
import { GraphTimeRail } from './graph-time-rail';
import { GraphWorkspaceFrame } from './graph-workspace-frame';
import { NoesisContextStrip } from './noesis-context-strip';

describe('GraphWorkspaceFrame', () => {
  it('composes named slots and keeps the inspector optional', () => {
    const html = renderToStaticMarkup(
      <GraphWorkspaceFrame
        contextBar={<span>context</span>}
        lensDock={<span>lenses</span>}
        canvas={<span>graph object</span>}
        timeRail={<span>time</span>}
        noesisStrip={<span>noesis</span>}
      />,
    );
    expect(html).toContain('context');
    expect(html).toContain('lenses');
    expect(html).toContain('graph object');
    expect(html).toContain('time');
    expect(html).toContain('noesis');
    expect(html).not.toContain('data-slot="inspector"');
    expect(html).toContain('lg:grid-cols-');
    expect(html).toContain('data-mobile-order="object-first"');
  });

  it('renders the inspector in its desktop drawer slot', () => {
    const html = renderToStaticMarkup(
      <GraphWorkspaceFrame
        contextBar={<span>context</span>}
        lensDock={<span>lenses</span>}
        canvas={<span>canvas</span>}
        inspector={<span>details</span>}
        timeRail={<span>time</span>}
        noesisStrip={<span>noesis</span>}
      />,
    );
    expect(html).toContain('data-slot="inspector"');
    expect(html).toContain('Graph inspector');
  });
});

describe('GraphContextBar', () => {
  it('marks missing context labels as unavailable', () => {
    const html = renderToStaticMarkup(
      <GraphContextBar workspaceLabel="Workspace A" environmentLabel={null} timeLabel="UTC" />,
    );
    expect(html).toContain('Workspace A');
    expect(html).toContain('Unavailable');
    expect(html).toContain('data-availability="unavailable"');
    expect(html).toContain('Environment: Unavailable');
  });

  it('provides a keyboard-accessible search button for the callback form', () => {
    const search = vi.fn();
    const html = renderToStaticMarkup(
      <GraphContextBar workspaceLabel="A" environmentLabel="staging" timeLabel="Live" onSearch={search} />,
    );
    expect(html).toContain('Search graph');
    expect(html).toContain('type="button"');
  });
});

describe('GraphTimeRail', () => {
  it('exposes the canonical temporal vocabulary and controlled history labels', () => {
    const html = renderToStaticMarkup(
      <GraphTimeRail
        temporal={{ mode: 'range', range: { kind: 'instant', start: '2026-01-01T00:00:00Z', endExclusive: '2026-01-02T00:00:00Z' } }}
        historyPosition={2}
        historyCount={4}
        onPrevious={() => undefined}
        onNext={() => undefined}
        onLive={() => undefined}
      />,
    );
    for (const label of ['Live', 'Point', 'Range', 'Compare', 'Diff']) expect(html).toContain(label);
    expect(html).toContain('History 2 of 4');
    expect(html).toContain('2026-01-01T00:00:00Z');
    expect(html).toContain('Previous history point');
    expect(html).toContain('Return to live graph');
  });

  it('honestly labels absent temporal and history data', () => {
    const html = renderToStaticMarkup(<GraphTimeRail historyPosition={0} historyCount={0} />);
    expect(html).toContain('Temporal context unavailable');
    expect(html).toContain('History unavailable');
  });
});

describe('NoesisContextStrip', () => {
  it('uses an explicit controlled expanded state and native keyboard button', () => {
    const html = renderToStaticMarkup(
      <NoesisContextStrip contextChips={['Focused object', '2 evidence refs']} expanded={false} onToggle={() => undefined}>
        <p>details</p>
      </NoesisContextStrip>,
    );
    expect(html).toContain('Focused object');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-controls="noesis-context-details"');
    expect(html).toContain('Show context');
    expect(html).toContain('hidden=""');
  });
});
