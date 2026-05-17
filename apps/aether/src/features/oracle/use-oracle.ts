import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useOracleProofStatus(proofId: string) {
  return useQuery({
    key: `oracle:proof:${proofId}`,
    fetcher: () => api.oracle.getStatus(proofId),
    staleTime: STALE,
    enabled: !!proofId,
  });
}

export function useGenerateProof() {
  return useMutation({
    mutationFn: (params: { entity_id: string; data_type: string; chain: string }) =>
      api.oracle.generateProof(params),
  });
}

export function useVerifyProof() {
  return useMutation({
    mutationFn: ({ proofId, proof }: { proofId: string; proof: string }) =>
      api.oracle.verifyProof(proofId, proof),
  });
}
