import { useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

export function useResolveError() {
  return useMutation({
    mutationFn: (fingerprint: string) => api.diagnostics.resolveError(fingerprint),
  });
}

export function useSuppressError() {
  return useMutation({
    mutationFn: (fingerprint: string) => api.diagnostics.suppressError(fingerprint),
  });
}
