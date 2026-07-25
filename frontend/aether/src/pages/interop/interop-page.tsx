import { useNavigate } from 'react-router-dom';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState,
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import {
  useInteropMessages, useInteropPaths, useInteropProviders,
} from '@aether-app/features/interop';
import {
  NotEnabledOrError, Stat, asRecord, asList, fmt, messageStatusVariant,
} from '@aether-app/components/domain-intelligence';

function implementationStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'provider_live') return 'success';
  if (status === 'credential_gated') return 'warning';
  return 'default';
}

export function InteropPage() {
  const navigate = useNavigate();
  const providers = useInteropProviders();
  const messages = useInteropMessages();
  const paths = useInteropPaths();

  if (providers.isLoading && !providers.data) return <LoadingState lines={6} className="p-8" />;
  if (providers.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={providers.error} domainLabel="Interoperability Intelligence" onRetry={providers.refetch} />
      </div>
    );
  }

  const providerRows = asList(asRecord(providers.data).items).map(asRecord);
  const messageRows = asList(asRecord(messages.data).items).map(asRecord);
  const pathRows = asList(asRecord(paths.data).items).map(asRecord);
  const inFlight = messageRows.filter(m => !['settled', 'delivered', 'executed', 'cancelled', 'refunded'].includes(String(m.status)));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Interoperability Intelligence</h1>
        <p className="text-sm text-text-secondary mt-1">
          Observation-only view of cross-chain message lifecycles, paths, and provider
          adapters. Aether never relays, retries, or recovers messages.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Providers" value={providerRows.length} />
        <Stat label="Messages observed" value={messageRows.length} />
        <Stat label="In flight" value={inFlight.length} />
        <Stat label="Paths" value={pathRows.length} />
      </div>

      <Tabs defaultValue="messages">
        <TabsList>
          <TabsTrigger value="messages">Messages</TabsTrigger>
          <TabsTrigger value="paths">Paths</TabsTrigger>
          <TabsTrigger value="providers">Providers</TabsTrigger>
        </TabsList>

        <TabsContent value="messages">
          <Card>
            <CardHeader><CardTitle>Cross-chain messages</CardTitle></CardHeader>
            <CardContent>
              {messageRows.length === 0 ? (
                <EmptyState title="No messages observed" description="Messages appear once provider scanning is enabled." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'key', header: 'Correlation', render: r => <span className="font-mono">{String(r.correlation_key ?? '').slice(0, 22)}…</span> },
                    { key: 'provider', header: 'Provider', render: r => fmt(r.provider_kind) },
                    { key: 'path', header: 'Path', render: r => <span className="font-mono">{fmt(r.path_id)}</span> },
                    {
                      key: 'status', header: 'Status',
                      render: r => <Badge variant={messageStatusVariant(String(r.status))}>{fmt(r.status)}</Badge>,
                    },
                    { key: 'observed', header: 'First observed', render: r => fmt(r.source_observed_at) },
                  ]}
                  data={messageRows}
                  keyExtractor={r => String(r.interop_message_id)}
                  onRowClick={r => navigate(`/interoperability/messages/${String(r.interop_message_id)}`)}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="paths">
          <Card>
            <CardHeader><CardTitle>Paths</CardTitle></CardHeader>
            <CardContent>
              {pathRows.length === 0 ? (
                <EmptyState title="No paths registered" />
              ) : (
                <DataTable
                  columns={[
                    { key: 'id', header: 'Path', render: r => <span className="font-mono">{fmt(r.path_id)}</span> },
                    { key: 'src', header: 'Source', render: r => fmt(r.source_network_id) },
                    { key: 'dst', header: 'Destination', render: r => fmt(r.destination_network_id) },
                    { key: 'provider', header: 'Provider', render: r => fmt(r.provider_id) },
                  ]}
                  data={pathRows}
                  keyExtractor={r => String(r.path_id)}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="providers">
          <Card>
            <CardHeader><CardTitle>Provider adapters</CardTitle></CardHeader>
            <CardContent>
              {providerRows.length === 0 ? (
                <EmptyState title="No provider adapters registered" />
              ) : (
                <DataTable
                  columns={[
                    { key: 'id', header: 'Provider', render: r => <span className="font-mono">{fmt(r.provider_id)}</span> },
                    { key: 'kind', header: 'Kind', render: r => fmt(r.provider_kind) },
                    {
                      key: 'impl', header: 'Implementation status',
                      render: r => (
                        <Badge variant={implementationStatusVariant(String(r.implementation_status))}>
                          {fmt(r.implementation_status)}
                        </Badge>
                      ),
                    },
                    { key: 'exec', header: 'Execution by Aether', render: () => <Badge variant="success">never</Badge> },
                  ]}
                  data={providerRows}
                  keyExtractor={r => String(r.provider_id)}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
