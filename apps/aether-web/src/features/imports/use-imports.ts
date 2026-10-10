import { useCallback } from 'react';
import { useQuery, useMutation, queryCache } from '@aether/ui';
import type { FieldMapping } from '@aether/shared';
import {
  fetchImports,
  createImport,
  fetchImportDetail,
  uploadImportFile,
  analyzeImport,
  putImportMapping,
  validateImport,
  approveImport,
  cancelImport,
  suggestImportTemplates,
  applyImportTemplate,
  fetchImportTemplates,
  graphPreviewImport,
  commitImport,
  replayImport,
  rollbackImport,
  fetchImportCommits,
} from './api';
import type {
  ImportListParams,
  ImportListResult,
  ImportSessionRecord,
  ImportDetail,
  ImportFileMetaRecord,
  ImportMappingRecord,
  AnalyzeResult,
  ValidateResponse,
  TemplateSuggestResult,
  TemplateListResult,
  GraphPreviewResult,
  JobResponse,
  RollbackInput,
  RollbackResult,
  CommitsListResult,
} from './api';

const KEY_PREFIX = 'imports';
const STALE = 15_000;

// ── Queries ───────────────────────────────────────────────────────────────────

export function useImports(params?: ImportListParams): {
  readonly imports: ImportSessionRecord[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const key = `${KEY_PREFIX}:list:${params?.limit ?? 'all'}:${params?.offset ?? 0}`;
  const { data, isLoading, error, refetch } = useQuery<ImportListResult>({
    key,
    fetcher: () => fetchImports(params),
    staleTime: STALE,
  });

  return {
    imports: data?.imports ?? [],
    count: data?.count ?? 0,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useImportDetail(id: string | null): {
  readonly detail: ImportDetail | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ImportDetail>({
    key: `${KEY_PREFIX}:detail:${id ?? 'none'}`,
    fetcher: () => fetchImportDetail(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { detail: data, loading: isLoading, error, refresh: refetch };
}

export function useImportCommits(id: string | null): {
  readonly commits: CommitsListResult['commits'];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<CommitsListResult>({
    key: `${KEY_PREFIX}:commits:${id ?? 'none'}`,
    fetcher: () => fetchImportCommits(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { commits: data?.commits ?? [], count: data?.count ?? 0, loading: isLoading, error };
}

export function useImportTemplates(): {
  readonly templates: TemplateListResult['templates'];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<TemplateListResult>({
    key: `${KEY_PREFIX}:templates`,
    fetcher: fetchImportTemplates,
    staleTime: STALE,
  });

  return { templates: data?.templates ?? [], count: data?.count ?? 0, loading: isLoading, error };
}

// ── Mutations ─────────────────────────────────────────────────────────────────

const invalidate = () => queryCache.invalidatePrefix(KEY_PREFIX);

export function useCreateImport(): {
  readonly create: () => Promise<ImportSessionRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<void, ImportSessionRecord>({
    mutationFn: () => createImport(),
    onSuccess: invalidate,
  });
  const create = useCallback(() => mutate(undefined), [mutate]);
  return { create, loading: isLoading, error };
}

export function useUploadImportFile(): {
  readonly upload: (id: string, file: File) => Promise<ImportFileMetaRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<{ id: string; file: File }, ImportFileMetaRecord>({
    mutationFn: ({ id, file }) => uploadImportFile(id, file),
    onSuccess: invalidate,
  });
  const upload = useCallback((id: string, file: File) => mutate({ id, file }), [mutate]);
  return { upload, loading: isLoading, error };
}

export function useAnalyzeImport(): {
  readonly analyze: (id: string) => Promise<AnalyzeResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, AnalyzeResult>({
    mutationFn: id => analyzeImport(id),
    onSuccess: invalidate,
  });
  return { analyze: mutate, loading: isLoading, error };
}

export function useSaveImportMapping(): {
  readonly save: (id: string, fields: FieldMapping[]) => Promise<ImportMappingRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<{ id: string; fields: FieldMapping[] }, ImportMappingRecord>({
    mutationFn: ({ id, fields }) => putImportMapping(id, fields),
    onSuccess: invalidate,
  });
  const save = useCallback((id: string, fields: FieldMapping[]) => mutate({ id, fields }), [mutate]);
  return { save, loading: isLoading, error };
}

export function useValidateImport(): {
  readonly validate: (id: string) => Promise<ValidateResponse | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, ValidateResponse>({
    mutationFn: id => validateImport(id),
    onSuccess: invalidate,
  });
  return { validate: mutate, loading: isLoading, error };
}

export function useApproveImport(): {
  readonly approve: (id: string) => Promise<ImportSessionRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, ImportSessionRecord>({
    mutationFn: id => approveImport(id),
    onSuccess: invalidate,
  });
  return { approve: mutate, loading: isLoading, error };
}

export function useCancelImport(): {
  readonly cancel: (id: string) => Promise<ImportSessionRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, ImportSessionRecord>({
    mutationFn: id => cancelImport(id),
    onSuccess: invalidate,
  });
  return { cancel: mutate, loading: isLoading, error };
}

export function useSuggestImportTemplates(): {
  readonly suggest: (id: string) => Promise<TemplateSuggestResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, TemplateSuggestResult>({
    mutationFn: id => suggestImportTemplates(id),
    onSuccess: invalidate,
  });
  return { suggest: mutate, loading: isLoading, error };
}

export function useApplyImportTemplate(): {
  readonly apply: (id: string, templateId: string) => Promise<ImportMappingRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<{ id: string; templateId: string }, ImportMappingRecord>({
    mutationFn: ({ id, templateId }) => applyImportTemplate(id, templateId),
    onSuccess: invalidate,
  });
  const apply = useCallback((id: string, templateId: string) => mutate({ id, templateId }), [mutate]);
  return { apply, loading: isLoading, error };
}

export function useGraphPreviewImport(): {
  readonly preview: (id: string) => Promise<GraphPreviewResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, GraphPreviewResult>({
    mutationFn: id => graphPreviewImport(id),
    onSuccess: invalidate,
  });
  return { preview: mutate, loading: isLoading, error };
}

export function useCommitImport(): {
  readonly commit: (id: string) => Promise<JobResponse | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, JobResponse>({
    mutationFn: id => commitImport(id),
    onSuccess: invalidate,
  });
  return { commit: mutate, loading: isLoading, error };
}

export function useReplayImport(): {
  readonly replay: (id: string) => Promise<JobResponse | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, JobResponse>({
    mutationFn: id => replayImport(id),
    onSuccess: invalidate,
  });
  return { replay: mutate, loading: isLoading, error };
}

export function useRollbackImport(): {
  readonly rollback: (id: string, input: RollbackInput) => Promise<RollbackResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<{ id: string; input: RollbackInput }, RollbackResult>({
    mutationFn: ({ id, input }) => rollbackImport(id, input),
    onSuccess: invalidate,
  });
  const rollback = useCallback((id: string, input: RollbackInput) => mutate({ id, input }), [mutate]);
  return { rollback, loading: isLoading, error };
}
