import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  LoadingState, EmptyState, ScrollArea,
} from '@aether/ui';
import { useWeb3RegistryView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }
function fmtNum(v: unknown): string { return v == null ? '—' : Number(v).toLocaleString(); }

export function Web3Page() {
  const { chains, protocols, tokens, coverage, unclassified, classifyContract } = useWeb3RegistryView();

  const chainList = asList(chains.data);
  const protocolList = asList(protocols.data);
  const tokenList = asList(tokens.data);
  const unclassifiedList = asList(unclassified.data);
  const coverageData = asRecord(coverage.data);

  return (
    <PageWrapper title="Web3 Registry" subtitle="Chains, protocols, tokens, and contract classification">
      {/* Coverage strip */}
      {coverage.isLoading ? <LoadingState lines={1} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {[
            { label: 'Chains', value: chainList.length },
            { label: 'Protocols', value: protocolList.length },
            { label: 'Tokens', value: tokenList.length },
            { label: 'Unclassified', value: unclassifiedList.length },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface-raised border border-border-default rounded px-3 py-2">
              <p className="text-[10px] text-text-muted font-mono">{label}</p>
              <p className="text-xl font-bold font-mono text-text-primary">{value}</p>
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="chains">
        <TabsList>
          <TabsTrigger value="chains">Chains</TabsTrigger>
          <TabsTrigger value="protocols">Protocols</TabsTrigger>
          <TabsTrigger value="tokens">Tokens</TabsTrigger>
          <TabsTrigger value="unclassified">
            Unclassified
            {unclassifiedList.length > 0 && <Badge variant="warning" className="ml-1.5">{unclassifiedList.length}</Badge>}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chains">
          {chains.isLoading ? <LoadingState lines={4} /> : chainList.length === 0 ? (
            <EmptyState title="No chains" description="No chains registered." icon="○" />
          ) : (
            <ScrollArea maxHeight="500px">
              <div className="space-y-1">
                {chainList.map((c, i) => {
                  const chain = asRecord(c);
                  return (
                    <div key={i} className="flex items-center justify-between px-3 py-1.5 rounded hover:bg-surface-raised text-xs font-mono border-b border-border-default last:border-0">
                      <span className="text-text-primary font-bold">{fmt(chain.name ?? chain.chain_id)}</span>
                      <div className="flex items-center gap-2 text-text-muted">
                        <span>{fmt(chain.vm_family)}</span>
                        <span>{fmt(chain.chain_id)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent value="protocols">
          {protocols.isLoading ? <LoadingState lines={4} /> : protocolList.length === 0 ? (
            <EmptyState title="No protocols" description="No protocols registered." icon="○" />
          ) : (
            <ScrollArea maxHeight="500px">
              <div className="space-y-1">
                {protocolList.map((p, i) => {
                  const proto = asRecord(p);
                  return (
                    <div key={i} className="flex items-center justify-between px-3 py-1.5 rounded hover:bg-surface-raised text-xs font-mono border-b border-border-default last:border-0">
                      <span className="text-text-primary font-bold">{fmt(proto.name ?? proto.protocol_id)}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-text-muted">{fmt(proto.family)}</span>
                        <Badge variant="default">{fmt(proto.chain_id)}</Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent value="tokens">
          {tokens.isLoading ? <LoadingState lines={4} /> : tokenList.length === 0 ? (
            <EmptyState title="No tokens" description="No tokens registered." icon="○" />
          ) : (
            <ScrollArea maxHeight="500px">
              <div className="space-y-1">
                {tokenList.map((t, i) => {
                  const token = asRecord(t);
                  return (
                    <div key={i} className="flex items-center justify-between px-3 py-1.5 rounded hover:bg-surface-raised text-xs font-mono border-b border-border-default last:border-0">
                      <span className="text-text-primary font-bold">{fmt(token.symbol)}</span>
                      <div className="flex items-center gap-2 text-text-muted">
                        <span>{fmt(token.name)}</span>
                        <Badge variant="default">{fmt(token.chain_id)}</Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent value="unclassified">
          {unclassified.isLoading ? <LoadingState lines={4} /> : unclassifiedList.length === 0 ? (
            <EmptyState title="All classified" description="No unclassified contracts." icon="✓" />
          ) : (
            <ScrollArea maxHeight="500px">
              <div className="space-y-2">
                {unclassifiedList.map((c, i) => {
                  const contract = asRecord(c);
                  const addr = fmt(contract.address);
                  const chainId = fmt(contract.chain_id);
                  return (
                    <Card key={i}>
                      <CardContent className="flex items-center justify-between py-2">
                        <div className="space-y-0.5">
                          <div className="text-xs font-mono text-text-primary truncate max-w-[300px]">{addr}</div>
                          <div className="text-[10px] text-text-muted font-mono">{chainId}</div>
                        </div>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => classifyContract.mutate({ chainId, address: addr })}
                          disabled={classifyContract.isLoading}
                        >
                          Classify
                        </Button>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
