import { isLocalMocked, getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import * as fixtures from '@shiki/fixtures';

export function useLabData() {
  const environment = getEnvironment();
  const mode = getRuntimeMode();
  const isMocked = isLocalMocked();

  const fixtureManifest = [
    { name: 'Entities', count: fixtures.getMockEntities().length, get: () => fixtures.getMockEntities() },
    { name: 'Controllers', count: fixtures.getMockControllers().length, get: () => fixtures.getMockControllers() },
    { name: 'Events', count: fixtures.getMockEvents().length, get: () => fixtures.getMockEvents() },
    { name: 'Graph Nodes', count: fixtures.getMockGraphData().nodes.length, get: () => fixtures.getMockGraphData() },
    { name: 'Health', count: 1, get: () => fixtures.getMockSystemHealth() },
    { name: 'Review Batches', count: fixtures.getMockReviewBatches().length, get: () => fixtures.getMockReviewBatches() },
    { name: 'Mission', count: 1, get: () => fixtures.getMockMissionData() },
  ];

  function exportAsJson(name: string, data: unknown) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `shiki-${name}-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return { environment, mode, isMocked, fixtureManifest, exportAsJson };
}
