import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, Select } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, any>;

export function AuditExportsPage() {
  const [types, setTypes] = useState<AnyRecord[]>([]);
  const [history, setHistory] = useState<AnyRecord[]>([]);
  const [selected, setSelected] = useState('recommendation_audit');
  const [format, setFormat] = useState('json');
  const [includeEvidence, setIncludeEvidence] = useState(true);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [download, setDownload] = useState<AnyRecord | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const options = useMemo(() => types.map(t => ({ value: t.export_type as string, label: t.label as string })), [types]);

  useEffect(() => { api.intelligence.auditExportTypes().then((raw: unknown) => { const d = raw as AnyRecord; setTypes(d.items ?? []); if (d.items?.[0]?.export_type) setSelected(d.items[0].export_type); }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false)); }, []);

  async function createExport() {
    setCreating(true); setError(null); setDownload(null);
    try {
      const created = await api.intelligence.createAuditExport({ export_type: selected, time_window: { start: `${today}T00:00:00Z`, end: `${today}T23:59:59Z` }, include_evidence: includeEvidence, include_dispatch_receipts: true, include_confidence_deltas: true, format });
      setHistory(h => [created as AnyRecord, ...h]);
      const payload = await api.intelligence.downloadAuditExport((created as AnyRecord).export_id);
      setDownload(payload as AnyRecord);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setCreating(false); }
  }

  return <main className="p-6 space-y-4"><div><h1 className="text-xl font-mono font-bold">Audit Exports</h1><p className="text-sm text-text-secondary">Tenant-scoped exports for recommendations, decisions, actions, dispatches, outcomes, playbooks, governance, and value evidence.</p></div>
    {loading ? <LoadingState lines={5} /> : error ? <EmptyState title="Audit export error" description={error} /> : <>
      <Card><CardHeader><CardTitle>Create export</CardTitle></CardHeader><CardContent className="space-y-3"><Select label="Export type" value={selected} options={options} onChange={setSelected} /><Select label="Format" value={format} options={[{value:'json',label:'JSON'},{value:'csv',label:'CSV'},{value:'pdf_summary',label:'PDF summary placeholder'}]} onChange={setFormat} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeEvidence} onChange={e => setIncludeEvidence(e.target.checked)} /> Include evidence references</label><Button onClick={() => void createExport()} disabled={creating}>{creating ? 'Generating…' : 'Generate export'}</Button></CardContent></Card>
      <Card><CardHeader><CardTitle>Export types</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-2">{types.map(t => <div key={t.export_type} className="rounded border border-border-default p-3"><div className="font-medium">{t.label}</div><p className="text-xs text-text-secondary">{t.description}</p><div className="mt-2 flex gap-1">{(t.supported_formats ?? []).map((f: string) => <Badge key={f}>{f}</Badge>)}</div></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Export history</CardTitle></CardHeader><CardContent>{history.length === 0 ? <EmptyState title="No exports yet" description="Generated exports appear here with status and download metadata." /> : <div className="space-y-2">{history.map(item => <div key={item.export_id} className="flex items-center justify-between rounded border border-border-default p-2 text-sm"><span>{item.export_type}</span><Badge variant="success">{item.status}</Badge><button className="text-accent" onClick={() => void api.intelligence.downloadAuditExport(item.export_id).then((d: unknown) => setDownload(d as AnyRecord))}>Download</button></div>)}</div>}</CardContent></Card>
      {download && <Card><CardHeader><CardTitle>Download payload/status</CardTitle></CardHeader><CardContent><div className="text-xs font-mono text-text-muted">integrity_hash: {download.integrity_hash}</div><pre className="mt-2 max-h-72 overflow-auto rounded bg-surface-sunken p-3 text-xs">{JSON.stringify(download.payload, null, 2)}</pre></CardContent></Card>}
    </>}
  </main>;
}
