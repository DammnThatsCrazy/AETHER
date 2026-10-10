import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCount,
  useTimeContext,
  useToast,
} from '@aether/ui';
import {
  importPrimitives,
  importTransforms,
  primitiveFields,
  isTerminalImportStatus,
} from '@aether/shared';
import type { ImportPrimitive, ImportTransform, FieldMapping } from '@aether/shared';
import {
  useImportDetail,
  useImportCommits,
  useUploadImportFile,
  useAnalyzeImport,
  useSaveImportMapping,
  useValidateImport,
  useApproveImport,
  useCancelImport,
  useCommitImport,
  useReplayImport,
  useRollbackImport,
} from '@aether-app/features/imports';
import type {
  SchemaProfileRecord,
  ValidateResponse,
  ImportCommitRecord,
} from '@aether-app/features/imports';
import { ImportStatusBadge, formatImportDate } from './imports-page';

const SELECT_CLASS =
  'text-xs border border-border-default rounded-md px-2 py-1 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent';

interface RowState {
  readonly primitive: ImportPrimitive;
  readonly target_field: string;
  readonly transform: ImportTransform;
  readonly required: boolean;
}

function defaultRow(): RowState {
  return { primitive: 'entity', target_field: primitiveFields('entity')[0] ?? '', transform: 'none', required: false };
}

function firstSchema(detail: { schemas: SchemaProfileRecord[] } | null): SchemaProfileRecord | null {
  return detail?.schemas?.[0] ?? null;
}

export function ImportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const importId = id ?? null;
  const { toast } = useToast();
  const timeCtx = useTimeContext();

  const { detail, loading, error, refresh } = useImportDetail(importId);
  const { commits } = useImportCommits(importId);

  const { upload, loading: uploading } = useUploadImportFile();
  const { analyze, loading: analyzing } = useAnalyzeImport();
  const { save, loading: savingMapping } = useSaveImportMapping();
  const { validate, loading: validating } = useValidateImport();
  const { approve, loading: approving } = useApproveImport();
  const { cancel, loading: cancelling } = useCancelImport();
  const { commit, loading: committing } = useCommitImport();
  const { replay, loading: replaying } = useReplayImport();
  const { rollback, loading: rollingBack } = useRollbackImport();

  const [rowState, setRowState] = useState<Record<string, RowState>>({});
  const [validateResult, setValidateResult] = useState<ValidateResponse | null>(null);

  // Seed the mapping editor once a schema is available, preferring any existing
  // mapping already stored for the session.
  useEffect(() => {
    const schema = firstSchema(detail);
    const columns = schema?.columns ?? [];
    if (columns.length === 0) return;
    setRowState(prev => {
      if (Object.keys(prev).length > 0) return prev;
      const next: Record<string, RowState> = {};
      for (const col of columns) next[col.name] = defaultRow();
      if (detail?.mapping) {
        for (const f of detail.mapping.fields) {
          next[f.source_column] = {
            primitive: f.primitive,
            target_field: f.target_field,
            transform: f.transform,
            required: f.required,
          };
        }
      }
      return next;
    });
  }, [detail]);

  if (loading && !detail) {
    return (
      <div className="p-8">
        <LoadingState lines={8} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <ErrorState title="Failed to load import" message={error} onRetry={refresh} />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="p-8">
        <EmptyState
          title="Import not found"
          description="This import session does not exist or is not visible to your tenant."
          action={<Link to="/imports" className="text-sm text-accent hover:underline">Back to imports</Link>}
        />
      </div>
    );
  }

  const session = detail.session;
  const terminal = isTerminalImportStatus(session.status);
  const schema = firstSchema(detail);
  const columns = schema?.columns ?? [];
  const hasSchema = columns.length > 0;

  const validation = validateResult?.validation ?? detail.validation ?? null;
  const reviewReasons = validateResult?.review_reasons ?? validation?.governance_reasons ?? [];
  const validated = validation?.ok === true;
  const canApprove = validated && !terminal && session.status !== 'approved';
  const canCommit = session.status === 'approved';

  const updateRow = (column: string, patch: Partial<RowState>) => {
    setRowState(prev => {
      const current = prev[column] ?? defaultRow();
      const merged: RowState = { ...current, ...patch };
      if (patch.primitive && patch.primitive !== current.primitive) {
        return { ...prev, [column]: { ...merged, target_field: primitiveFields(patch.primitive)[0] ?? '' } };
      }
      return { ...prev, [column]: merged };
    });
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || !importId) return;
    const uploaded = await upload(importId, file);
    if (!uploaded) {
      toast.error('File upload failed');
      return;
    }
    const analyzed = await analyze(importId);
    if (analyzed) toast.success('File uploaded and analyzed');
    else toast.error('Schema analysis failed');
  };

  const handleSaveMapping = async () => {
    if (!importId) return;
    const fields: FieldMapping[] = columns.map(col => {
      const rs = rowState[col.name] ?? defaultRow();
      return {
        source_column: col.name,
        primitive: rs.primitive,
        target_field: rs.target_field,
        transform: rs.transform,
        required: rs.required,
      };
    });
    const result = await save(importId, fields);
    if (result) toast.success('Mapping saved');
    else toast.error('Failed to save mapping');
  };

  const handleValidate = async () => {
    if (!importId) return;
    const result = await validate(importId);
    if (result) {
      setValidateResult(result);
      toast.success(result.validation.ok ? 'Validation passed' : 'Validation found issues');
    } else {
      toast.error('Validation failed');
    }
  };

  const handleApprove = async () => {
    if (!importId) return;
    const result = await approve(importId);
    if (result) toast.success('Import approved');
    else toast.error('Failed to approve import');
  };

  const handleCancel = async () => {
    if (!importId) return;
    const result = await cancel(importId);
    if (result) toast.success('Import cancelled');
    else toast.error('Failed to cancel import');
  };

  const handleCommit = async () => {
    if (!importId) return;
    const result = await commit(importId);
    if (result) toast.success('Commit enqueued');
    else toast.error('Failed to enqueue commit');
  };

  const handleReplay = async () => {
    if (!importId) return;
    const result = await replay(importId);
    if (result) toast.success('Replay enqueued');
    else toast.error('Failed to enqueue replay');
  };

  const handleRollback = async (commitRecord: ImportCommitRecord) => {
    if (!importId) return;
    const reason = window.prompt('Reason for rollback') ?? '';
    if (reason.trim() === '') return;
    const input = commitRecord.id ? { commit_id: commitRecord.id, reason } : { reason };
    const result = await rollback(importId, input);
    if (result) toast.success('Rollback requested');
    else toast.error('Failed to roll back');
  };

  return (
    <div className="p-8 space-y-6">
      <div>
        <Link to="/imports" className="text-xs text-text-muted hover:text-text-primary font-mono">
          ← Imports
        </Link>
        <div className="flex items-start justify-between mt-2">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-text-primary font-mono">{session.id}</h1>
              <ImportStatusBadge status={session.status} />
            </div>
            <p className="text-sm text-text-secondary mt-0.5">
              <span className="font-mono">{session.source_kind}</span> · {session.file_count} file(s) ·{' '}
              {session.row_count !== null && session.row_count !== undefined ? `${session.row_count} rows` : 'rows pending'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {!terminal && (
              <Button variant="ghost" size="sm" disabled={cancelling} onClick={() => void handleCancel()}>
                {cancelling ? 'Cancelling…' : 'Cancel'}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Step 1 — Upload + analyze */}
      {!hasSchema && !terminal && (
        <Card>
          <CardHeader>
            <CardTitle>Upload a file</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-text-secondary">
              Upload a CSV, JSON, or JSONL file. Aether stores the bytes and analyzes the schema.
            </p>
            <input
              type="file"
              aria-label="Upload import file"
              onChange={e => void handleFileChange(e)}
              disabled={uploading || analyzing}
              className="text-sm text-text-secondary"
            />
            {(uploading || analyzing) && (
              <div className="text-xs text-text-muted font-mono">
                {uploading ? 'Uploading…' : 'Analyzing schema…'}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 2 — Analyzed schema */}
      {hasSchema && schema && (
        <Card>
          <CardHeader>
            <CardTitle>Analyzed schema</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xs text-text-muted font-mono mb-3">
              {schema.format} · {schema.row_count} rows · {schema.columns.length} columns
            </div>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-default text-text-secondary">
                    <th className="text-left py-2 px-3 font-medium">Column</th>
                    <th className="text-left py-2 px-3 font-medium">Inferred type</th>
                    <th className="text-left py-2 px-3 font-medium">Sensitivity</th>
                    <th className="text-left py-2 px-3 font-medium">Nullable</th>
                    <th className="text-left py-2 px-3 font-medium">Distinct</th>
                  </tr>
                </thead>
                <tbody>
                  {columns.map(col => (
                    <tr key={col.name} className="border-b border-border-subtle">
                      <td className="py-2 px-3 font-mono text-text-primary">{col.name}</td>
                      <td className="py-2 px-3 font-mono text-text-secondary">{col.inferred_type}</td>
                      <td className="py-2 px-3">
                        <Badge size="sm" variant={col.sensitivity === 'none' ? 'default' : 'warning'}>
                          {col.sensitivity}
                        </Badge>
                      </td>
                      <td className="py-2 px-3 font-mono text-text-secondary">{col.nullable ? 'yes' : 'no'}</td>
                      <td className="py-2 px-3 font-mono text-text-secondary">{formatCount(col.distinct_count, timeCtx)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3 — Mapping editor */}
      {hasSchema && !terminal && (
        <Card>
          <CardHeader>
            <CardTitle>Map columns onto primitives</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-default text-text-secondary">
                    <th className="text-left py-2 px-3 font-medium">Source column</th>
                    <th className="text-left py-2 px-3 font-medium">Primitive</th>
                    <th className="text-left py-2 px-3 font-medium">Target field</th>
                    <th className="text-left py-2 px-3 font-medium">Transform</th>
                    <th className="text-left py-2 px-3 font-medium">Required</th>
                  </tr>
                </thead>
                <tbody>
                  {columns.map(col => {
                    const rs = rowState[col.name] ?? defaultRow();
                    return (
                      <tr key={col.name} className="border-b border-border-subtle">
                        <td className="py-2 px-3 font-mono text-text-primary">{col.name}</td>
                        <td className="py-2 px-3">
                          <select
                            aria-label={`Primitive for ${col.name}`}
                            value={rs.primitive}
                            onChange={e => updateRow(col.name, { primitive: e.target.value as ImportPrimitive })}
                            className={SELECT_CLASS}
                          >
                            {importPrimitives.map(p => (
                              <option key={p} value={p}>{p}</option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 px-3">
                          <select
                            aria-label={`Target field for ${col.name}`}
                            value={rs.target_field}
                            onChange={e => updateRow(col.name, { target_field: e.target.value })}
                            className={SELECT_CLASS}
                          >
                            {primitiveFields(rs.primitive).map(f => (
                              <option key={f} value={f}>{f}</option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 px-3">
                          <select
                            aria-label={`Transform for ${col.name}`}
                            value={rs.transform}
                            onChange={e => updateRow(col.name, { transform: e.target.value as ImportTransform })}
                            className={SELECT_CLASS}
                          >
                            {importTransforms.map(t => (
                              <option key={t} value={t}>{t}</option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 px-3">
                          <input
                            type="checkbox"
                            aria-label={`Required for ${col.name}`}
                            checked={rs.required}
                            onChange={e => updateRow(col.name, { required: e.target.checked })}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
          <CardFooter>
            <Button onClick={() => void handleSaveMapping()} disabled={savingMapping}>
              {savingMapping ? 'Saving…' : 'Save mapping'}
            </Button>
          </CardFooter>
        </Card>
      )}

      {/* Step 4 — Validation */}
      {hasSchema && (
        <Card>
          <CardHeader>
            <CardTitle>Validate</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <Button variant="secondary" onClick={() => void handleValidate()} disabled={validating || terminal}>
                {validating ? 'Validating…' : 'Run validation'}
              </Button>
              {validation && (
                <Badge variant={validation.ok ? 'success' : 'danger'}>
                  {validation.ok ? 'valid' : 'invalid'}
                </Badge>
              )}
            </div>

            {validation && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3 text-xs font-mono">
                  <div>
                    <div className="text-text-muted">Rows total</div>
                    <div className="text-text-primary mt-0.5">{formatCount(validation.rows_total, timeCtx)}</div>
                  </div>
                  <div>
                    <div className="text-text-muted">Rows valid</div>
                    <div className="text-success mt-0.5">{formatCount(validation.rows_valid, timeCtx)}</div>
                  </div>
                  <div>
                    <div className="text-text-muted">Rows invalid</div>
                    <div className="text-danger mt-0.5">{formatCount(validation.rows_invalid, timeCtx)}</div>
                  </div>
                </div>

                {validation.governance_review_required && (
                  <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2">
                    <div className="text-xs font-semibold text-warning">Governance review required</div>
                    {reviewReasons.length > 0 && (
                      <ul className="mt-1 list-disc list-inside text-xs text-text-secondary">
                        {reviewReasons.map((reason, i) => (
                          <li key={`${reason}-${i}`}>{reason}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {validation.errors.length > 0 && (
                  <div>
                    <div className="text-xs text-text-muted font-mono mb-1">
                      Errors{validation.errors_truncated ? ' (truncated)' : ''}
                    </div>
                    <ul className="space-y-1">
                      {validation.errors.map((err, i) => (
                        <li key={`${err.code}-${err.row}-${i}`} className="text-xs text-text-secondary font-mono">
                          row {err.row}
                          {err.source_column ? ` · ${err.source_column}` : ''} · {err.code}: {err.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 5 — Approve + commit */}
      {hasSchema && (
        <Card>
          <CardHeader>
            <CardTitle>Approve &amp; commit</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-3">
            <Button onClick={() => void handleApprove()} disabled={!canApprove || approving}>
              {approving ? 'Approving…' : 'Approve'}
            </Button>
            <Button onClick={() => void handleCommit()} disabled={!canCommit || committing}>
              {committing ? 'Committing…' : 'Commit'}
            </Button>
            {!validated && (
              <span className="text-xs text-text-muted">Approve is enabled once validation passes.</span>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 6 — Commit history */}
      <Card>
        <CardHeader>
          <CardTitle>Commit history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Button variant="secondary" size="sm" onClick={() => void handleReplay()} disabled={replaying}>
              {replaying ? 'Replaying…' : 'Replay import'}
            </Button>
          </div>
          {commits.length === 0 ? (
            <EmptyState title="No commits yet" description="Commit history for this import will appear here." />
          ) : (
            <ul className="space-y-3">
              {commits.map(commitRecord => (
                <li
                  key={commitRecord.id}
                  className="flex items-start justify-between gap-3 border-b border-border-subtle last:border-0 pb-3 last:pb-0"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-text-primary text-xs">{commitRecord.id}</span>
                      {commitRecord.status && <Badge size="sm">{commitRecord.status}</Badge>}
                    </div>
                    <div className="text-[10px] text-text-muted font-mono mt-1">
                      {commitRecord.row_count !== null && commitRecord.row_count !== undefined
                        ? `${commitRecord.row_count} rows · `
                        : ''}
                      {formatImportDate(commitRecord.created_at, timeCtx)}
                    </div>
                  </div>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={rollingBack}
                    onClick={() => void handleRollback(commitRecord)}
                  >
                    Rollback
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
