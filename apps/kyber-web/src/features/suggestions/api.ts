import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

export function fetchSuggestions(params?: AnyRecord): Promise<unknown> {
  return api.admin.kyber.suggestionsList(params);
}

export function fetchSuggestionsSummary(tenantId?: string): Promise<unknown> {
  return api.admin.kyber.suggestionsSummary(tenantId);
}

export function fetchReviewQueue(limit?: number): Promise<unknown> {
  return api.admin.kyber.suggestionsReviewQueue(limit);
}

export function fetchQuality(): Promise<unknown> {
  return api.admin.kyber.suggestionsQuality();
}

export function fetchOutcomes(tenantId?: string): Promise<unknown> {
  return api.admin.kyber.suggestionsOutcomes(tenantId);
}

export function approveSuggestion(id: string, notes?: string): Promise<unknown> {
  const body: { notes?: string } = {};
  if (notes !== undefined) body.notes = notes;
  return api.admin.kyber.approveSuggestion(id, body);
}

export function rejectSuggestion(id: string, reason: string, notes?: string): Promise<unknown> {
  const body: { reason: string; notes?: string } = { reason };
  if (notes !== undefined) body.notes = notes;
  return api.admin.kyber.rejectSuggestion(id, body);
}

export function suppressSuggestion(id: string, reason: string, hours?: number): Promise<unknown> {
  const body: { reason: string; suppress_duration_hours?: number } = { reason };
  if (hours !== undefined) body.suppress_duration_hours = hours;
  return api.admin.kyber.suppressSuggestion(id, body);
}
