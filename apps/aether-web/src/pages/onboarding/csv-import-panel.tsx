import { useRef, useState, type DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eyebrow, InlineNotice, LinkButton, Panel, PrimaryButton, Spinner, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { analyzeImport, cancelImport, createImport, uploadImportFile, type SchemaProfileRecord } from '@aether-app/features/imports';

type Phase = 'idle' | 'uploading' | 'ready' | 'error';

/** Column inferred-type → design mapping chip (identifier / profile / value / event / custom). */
function columnKind(inferred: string, name: string): { readonly label: string; readonly tone: Tone } {
  const n = name.toLowerCase();
  if (/mail/.test(n)) return { label: 'identifier · email', tone: 'blue' };
  if (/phone|mobile|tel/.test(n)) return { label: 'identifier · phone', tone: 'blue' };
  if (/wallet|address|^0x/.test(n)) return { label: 'identifier · wallet', tone: 'amber' };
  if (/name/.test(n)) return { label: 'profile', tone: 'sage' };
  if (/total|amount|value|price|revenue/.test(n)) return { label: 'value', tone: 'sage' };
  if (inferred === 'datetime' || inferred === 'date' || /date|time|_at$/.test(n)) return { label: 'event time', tone: 'mute' };
  return { label: inferred, tone: 'mute' };
}

/**
 * CSV step inside Sources. The file goes through the real imports pipeline
 * (create → upload → analyze); the profiled columns are shown here and the
 * visitor finishes mapping, validation and commit on the Imports review page,
 * which owns the governed approve/commit path. Nothing is matched or written
 * from this panel.
 */
export function CsvImportPanel() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [importId, setImportId] = useState<string | null>(null);
  const [fileName, setFileName] = useState('');
  const [schema, setSchema] = useState<SchemaProfileRecord | null>(null);
  const [rowCount, setRowCount] = useState<number>(0);

  async function handleFile(file: File | undefined) {
    if (input.current) input.current.value = '';
    if (!file) return;
    setPhase('uploading');
    setError(null);
    setFileName(file.name);
    try {
      const session = await createImport();
      setImportId(session.id);
      await uploadImportFile(session.id, file);
      const analysis = await analyzeImport(session.id);
      setSchema(analysis.schemas[0] ?? null);
      setRowCount(analysis.row_count);
      setPhase('ready');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The file could not be imported.');
      setPhase('error');
    }
  }

  async function remove() {
    const id = importId;
    // Clear the native input too, or re-picking the same file fires no change.
    if (input.current) input.current.value = '';
    setPhase('idle');
    setSchema(null);
    setImportId(null);
    setFileName('');
    if (id) {
      try {
        await cancelImport(id);
      } catch {
        // The draft stays visible on the Imports page; nothing else depends on it.
      }
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    void handleFile(e.dataTransfer?.files?.[0]);
  }

  return (
    <div className="flex w-full flex-col items-center gap-3" data-testid="csv-import-panel">
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv,.tsv,.txt"
        className="hidden"
        data-testid="csv-file-input"
        onChange={e => void handleFile(e.target.files?.[0])}
      />

      {(phase === 'idle' || phase === 'error') && (
        <>
          <div
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={onDrop}
            className="ae-focus flex w-full max-w-[640px] cursor-pointer flex-col items-center gap-2 rounded-[22px] border-[1.5px] border-dashed px-5 text-center transition-colors hover:border-[var(--ae-blue)] hover:bg-[var(--ae-blue-tint)]"
            style={{ borderColor: 'var(--ae-faint)', background: 'var(--ae-glass-card)', paddingTop: 'clamp(24px,5vw,40px)', paddingBottom: 'clamp(24px,5vw,40px)' }}
          >
            <span className="ae-mono text-[22px]" style={{ color: 'var(--ae-blue-ink)' }}>↑</span>
            <span className="text-[15px] font-medium">Drop a CSV here, or browse</span>
            <span className="text-[12px] leading-normal" style={{ color: 'var(--ae-mute)' }}>
              Customers, orders, wallets or events. The first row must be a header.
            </span>
          </div>
          {error && <InlineNotice tone="ember">{error}</InlineNotice>}
          <LinkButton onClick={() => void navigate('/imports')}>See previous imports</LinkButton>
        </>
      )}

      {phase === 'uploading' && (
        <Panel className="flex w-full max-w-[640px] flex-col items-center gap-3 p-6 text-center">
          <Spinner />
          <span className="text-[14px] font-medium">Reading and profiling the file</span>
          <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{fileName}</span>
        </Panel>
      )}

      {phase === 'ready' && (
        <Panel className="flex w-full max-w-[640px] flex-col gap-4" style={{ padding: 'clamp(16px,3vw,24px)' }}>
          <div className="flex items-center gap-3">
            <span className="ae-mark-chip ae-mono h-9 w-9 rounded-[10px] text-[11px]" style={{ color: 'var(--ae-mute)' }}>csv</span>
            <span className="flex min-w-0 flex-1 flex-col leading-tight">
              <span className="truncate text-[14px] font-medium">{fileName}</span>
              <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                {rowCount.toLocaleString('en-US')} records · {schema?.columns.length ?? 0} columns
              </span>
            </span>
            <LinkButton tone="mute" onClick={() => void remove()}>Remove</LinkButton>
          </div>

          <div className="flex flex-col gap-0.5">
            <Eyebrow className="pb-1">Detected columns</Eyebrow>
            {(schema?.columns ?? []).slice(0, 8).map(col => {
              const kind = columnKind(col.inferred_type, col.name);
              return (
                <div key={col.name} className="flex items-center gap-2.5 border-t py-[7px] text-[13px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                  <span className="ae-mono min-w-0 flex-1 truncate text-[12px]">{col.name}</span>
                  <span style={{ color: 'var(--ae-faint)' }}>→</span>
                  <span className="min-w-0 flex-1 truncate" style={{ color: 'var(--ae-mute)' }}>{col.sample_values[0] ?? '—'}</span>
                  <TonePill tone={kind.tone}>{kind.label}</TonePill>
                  {col.sensitivity !== 'none' && <TonePill tone="amber">{col.sensitivity}</TonePill>}
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              Read-only matching. Nothing is written to your sources.
            </span>
            <PrimaryButton onClick={() => importId && void navigate(`/imports/${importId}`)} data-testid="csv-review-import">
              Review mapping and import
            </PrimaryButton>
          </div>
        </Panel>
      )}
    </div>
  );
}
