import { useState, useCallback } from 'react';
import { PageWrapper } from '@shiki/components/layout';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Tabs, TabsList, TabsTrigger, TabsContent, EmptyState, ScrollArea, Select, Input, TerminalSeparator } from '@shiki/components/system';
import { getRuntimeMode, getEnvironment } from '@shiki/lib/env';
import { getMockEvents } from '@shiki/fixtures/events';
import { getMockEntities } from '@shiki/fixtures/entities';
import { getMockGraphData } from '@shiki/fixtures/graph';
import { getMockControllers } from '@shiki/fixtures/controllers';
import { getMockReviewBatches } from '@shiki/fixtures/review';
import { getMockHealthData } from '@shiki/fixtures/health';
import { getMockMissionData } from '@shiki/fixtures/mission';
import { createReplayController } from '@shiki/lib/replay';
import type { LiveEvent } from '@shiki/types';

// Scenario definitions
const SCENARIOS = [
  { id: 'default', name: 'Default State', description: 'Standard operational baseline with mixed entity states' },
  { id: 'p0-incident', name: 'P0 Incident', description: 'Simulates active P0 customer event stream failure' },
  { id: 'agent-stuck', name: 'Agent Stuck Loops', description: 'Multiple agents in retry/stuck state' },
  { id: 'graph-anomaly', name: 'Graph Anomaly Burst', description: 'Cluster of suspicious graph mutations' },
  { id: 'review-backlog', name: 'Review Backlog', description: 'Large pending review queue with mixed classes' },
  { id: 'healthy-all', name: 'All Healthy', description: 'Clean system state, no anomalies or issues' },
] as const;

function JsonViewer({ data, label }: { readonly data: unknown; readonly label: string }) {
  const [collapsed, setCollapsed] = useState(true);
  const json = JSON.stringify(data, null, 2);
  const lines = json.split('\n');
  const preview = lines.slice(0, 5).join('\n') + (lines.length > 5 ? '\n  ...' : '');

  return (
    <div className="border border-border-default rounded bg-surface-sunken">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full text-left px-3 py-2 text-xs font-mono text-text-secondary hover:text-text-primary flex items-center justify-between"
      >
        <span>{label}</span>
        <span className="text-text-muted">{collapsed ? '\u25B6' : '\u25BC'} {lines.length} lines</span>
      </button>
      <ScrollArea maxHeight="300px">
        <pre className="px-3 pb-3 text-[11px] font-mono text-text-primary whitespace-pre overflow-x-auto">
          {collapsed ? preview : json}
        </pre>
      </ScrollArea>
    </div>
  );
}

function ScenarioFixtures() {
  const [activeScenario, setActiveScenario] = useState('default');

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select
          label="Active Scenario"
          options={SCENARIOS.map(s => ({ value: s.id, label: s.name }))}
          value={activeScenario}
          onChange={setActiveScenario}
        />
        <div className="text-xs text-text-muted mt-5">
          {SCENARIOS.find(s => s.id === activeScenario)?.description}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader><CardTitle>Entities ({getMockEntities().length})</CardTitle></CardHeader>
          <CardContent>
            <JsonViewer data={getMockEntities().slice(0, 3)} label="entities (first 3)" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Controllers ({getMockControllers().length})</CardTitle></CardHeader>
          <CardContent>
            <JsonViewer data={getMockControllers().slice(0, 3)} label="controllers (first 3)" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Events ({getMockEvents().length})</CardTitle></CardHeader>
          <CardContent>
            <JsonViewer data={getMockEvents().slice(0, 3)} label="events (first 3)" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Graph</CardTitle></CardHeader>
          <CardContent>
            {(() => {
              const g = getMockGraphData();
              return <JsonViewer data={{ nodeCount: g.nodes.length, edgeCount: g.edges.length, clusterCount: g.clusters.length, sample: g.nodes.slice(0, 2) }} label="graph summary" />;
            })()}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ReplayPanel() {
  const [events] = useState(() => getMockEvents());
  const [replayLog, setReplayLog] = useState<LiveEvent[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);

  const [controller] = useState(() =>
    createReplayController(events, (event) => {
      setReplayLog(prev => [event, ...prev].slice(0, 100));
    }),
  );

  const handlePlay = useCallback(() => {
    controller.play();
    setIsPlaying(true);
  }, [controller]);

  const handlePause = useCallback(() => {
    controller.pause();
    setIsPlaying(false);
  }, [controller]);

  const handleStop = useCallback(() => {
    controller.stop();
    setIsPlaying(false);
    setReplayLog([]);
  }, [controller]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant={isPlaying ? 'danger' : 'primary'} size="sm" onClick={isPlaying ? handlePause : handlePlay}>
          {isPlaying ? '\u23F8 Pause' : '\u25B6 Play'}
        </Button>
        <Button variant="secondary" size="sm" onClick={handleStop}>{'\u23F9'} Stop</Button>
        <Select
          label="Speed"
          options={[
            { value: '0.5', label: '0.5x' },
            { value: '1', label: '1x' },
            { value: '2', label: '2x' },
            { value: '5', label: '5x' },
          ]}
          value="1"
          onChange={(v) => controller.setSpeed(Number(v))}
        />
        <Badge variant={isPlaying ? 'success' : 'default'}>{isPlaying ? 'REPLAYING' : 'STOPPED'}</Badge>
        <span className="text-xs text-text-muted">{replayLog.length} events replayed</span>
      </div>
      <ScrollArea maxHeight="400px">
        {replayLog.length === 0 ? (
          <EmptyState title="No replay events" description="Press Play to start replaying event history" icon={'\u23EF'} />
        ) : (
          <div className="space-y-1">
            {replayLog.map(e => (
              <div key={e.id} className="flex items-center gap-2 text-[11px] font-mono py-1 px-2 hover:bg-surface-raised rounded">
                <span className="text-text-muted w-20 shrink-0">{new Date(e.timestamp).toLocaleTimeString()}</span>
                <Badge variant={e.severity === 'P0' ? 'danger' : e.severity === 'P1' ? 'warning' : 'default'} className="w-8 text-center">{e.severity}</Badge>
                <Badge>{e.type}</Badge>
                <span className="text-text-primary truncate">{e.title}</span>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

function ApiInspector() {
  const [activeEndpoint, setActiveEndpoint] = useState('dashboard-summary');

  const endpoints: Record<string, { method: string; path: string; description: string; sampleResponse: unknown }> = {
    'dashboard-summary': {
      method: 'GET',
      path: '/v1/analytics/dashboard/summary',
      description: 'Aggregated KPIs for the dashboard',
      sampleResponse: { sessionsLast24h: 14200, eventsLast24h: 2100000, uniqueUsersLast24h: 3847, topEvents: [{ name: 'page_view', count: 890000 }, { name: 'click', count: 412000 }] },
    },
    'events-query': {
      method: 'POST',
      path: '/v1/analytics/events/query',
      description: 'Query events with filters and pagination',
      sampleResponse: { data: getMockEvents().slice(0, 2), total: getMockEvents().length, offset: 0, limit: 50, hasMore: true },
    },
    'entity-detail': {
      method: 'GET',
      path: '/v1/identity/entities/:id',
      description: 'Full entity details with scores',
      sampleResponse: getMockEntities()[0],
    },
    'graph-neighborhood': {
      method: 'GET',
      path: '/v1/intelligence/graph/neighborhood/:id',
      description: 'Graph neighborhood for an entity',
      sampleResponse: getMockGraphData(),
    },
    'health-check': {
      method: 'GET',
      path: '/v1/diagnostics/health',
      description: 'System health and dependency status',
      sampleResponse: getMockHealthData(),
    },
    'review-batches': {
      method: 'GET',
      path: '/v1/analytics/review/batches',
      description: 'Pending review batches',
      sampleResponse: getMockReviewBatches().slice(0, 2),
    },
  };

  const ep = endpoints[activeEndpoint];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select
          label="Endpoint"
          options={Object.entries(endpoints).map(([k, v]) => ({ value: k, label: `${v.method} ${v.path}` }))}
          value={activeEndpoint}
          onChange={setActiveEndpoint}
        />
      </div>
      {ep && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge variant={ep.method === 'GET' ? 'success' : 'info'}>{ep.method}</Badge>
            <code className="text-xs font-mono text-text-primary">{ep.path}</code>
          </div>
          <div className="text-xs text-text-secondary">{ep.description}</div>
          <TerminalSeparator label="Response Shape" />
          <JsonViewer data={ep.sampleResponse} label="response" />
        </div>
      )}
    </div>
  );
}

function GraphQLInspector() {
  const queries = [
    { name: 'DashboardSummary', query: `query DashboardSummary($timeRange: TimeRange!) {\n  dashboard {\n    sessionsCount(timeRange: $timeRange)\n    eventsCount(timeRange: $timeRange)\n    uniqueUsers(timeRange: $timeRange)\n    topEvents(limit: 10) {\n      name\n      count\n    }\n  }\n}` },
    { name: 'EntityNeighborhood', query: `query EntityNeighborhood($id: ID!, $depth: Int = 2) {\n  entity(id: $id) {\n    id\n    type\n    trustScore\n    riskScore\n    neighborhood(depth: $depth) {\n      nodes { id type label trustScore riskScore }\n      edges { id source target type weight }\n    }\n  }\n}` },
    { name: 'LiveAlerts', query: `query LiveAlerts($severity: [Severity!], $limit: Int = 50) {\n  alerts(severity: $severity, limit: $limit) {\n    id\n    title\n    severity\n    timestamp\n    controller\n    entityId\n    traceId\n  }\n}` },
  ];

  return (
    <div className="space-y-4">
      {queries.map(q => (
        <Card key={q.name}>
          <CardHeader><CardTitle>{q.name}</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-[11px] font-mono text-accent bg-surface-sunken p-3 rounded overflow-x-auto whitespace-pre">{q.query}</pre>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function DataTransformInspector() {
  const rawEvent = getMockEvents()[0];
  if (!rawEvent) return <EmptyState title="No events" />;

  const normalized = {
    ...rawEvent,
    _normalized: true,
    _timestamp: new Date(rawEvent.timestamp).getTime(),
    _severityLevel: { P0: 0, P1: 1, P2: 2, P3: 3, info: 4 }[rawEvent.severity],
  };

  const graphApplied = {
    nodeId: rawEvent.entityId ?? 'N/A',
    edgeCreated: rawEvent.type === 'graph-mutation',
    overlayUpdate: rawEvent.type === 'anomaly' ? 'risk' : 'none',
    clusterAffected: rawEvent.metadata?.['clusterId'] ?? null,
  };

  return (
    <div className="space-y-4">
      <div className="text-xs text-text-secondary">Inspect how a single event transforms through the pipeline</div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <Badge variant="warning" className="mb-2">RAW</Badge>
          <JsonViewer data={rawEvent} label="raw event" />
        </div>
        <div>
          <Badge variant="info" className="mb-2">NORMALIZED</Badge>
          <JsonViewer data={normalized} label="normalized event" />
        </div>
        <div>
          <Badge variant="success" className="mb-2">GRAPH-APPLIED</Badge>
          <JsonViewer data={graphApplied} label="graph effects" />
        </div>
      </div>
    </div>
  );
}

function ExportPanel() {
  const handleExport = useCallback((type: string) => {
    let data: unknown;
    switch (type) {
      case 'entities': data = getMockEntities(); break;
      case 'events': data = getMockEvents(); break;
      case 'graph': data = getMockGraphData(); break;
      case 'controllers': data = getMockControllers(); break;
      case 'health': data = getMockHealthData(); break;
      case 'review': data = getMockReviewBatches(); break;
      case 'mission': data = getMockMissionData(); break;
      default: return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `shiki-fixture-${type}-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const types = ['entities', 'events', 'graph', 'controllers', 'health', 'review', 'mission'];

  return (
    <div className="space-y-4">
      <div className="text-xs text-text-secondary">Export fixture data as JSON for local development and testing</div>
      <div className="grid grid-cols-4 gap-2">
        {types.map(t => (
          <Button key={t} variant="secondary" size="sm" onClick={() => handleExport(t)}>
            {'\u2913'} {t}
          </Button>
        ))}
      </div>
    </div>
  );
}

export function LabPage() {
  const mode = getRuntimeMode();
  const environment = getEnvironment();

  return (
    <PageWrapper
      title="Lab"
      subtitle="Data inspection, replay, and simulation tools"
      actions={
        <div className="flex items-center gap-2">
          <Badge variant={mode === 'mocked' ? 'warning' : 'info'}>{mode.toUpperCase()}</Badge>
          <Badge>{environment}</Badge>
        </div>
      }
    >
      <Tabs defaultValue="scenarios">
        <TabsList>
          <TabsTrigger value="scenarios">Scenario Fixtures</TabsTrigger>
          <TabsTrigger value="replay">Replay</TabsTrigger>
          <TabsTrigger value="rest">REST Inspector</TabsTrigger>
          <TabsTrigger value="graphql">GraphQL Inspector</TabsTrigger>
          <TabsTrigger value="transforms">Data Transforms</TabsTrigger>
          <TabsTrigger value="export">Export</TabsTrigger>
        </TabsList>
        <TabsContent value="scenarios"><ScenarioFixtures /></TabsContent>
        <TabsContent value="replay"><ReplayPanel /></TabsContent>
        <TabsContent value="rest"><ApiInspector /></TabsContent>
        <TabsContent value="graphql"><GraphQLInspector /></TabsContent>
        <TabsContent value="transforms"><DataTransformInspector /></TabsContent>
        <TabsContent value="export"><ExportPanel /></TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
