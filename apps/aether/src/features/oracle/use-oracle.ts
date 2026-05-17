import { useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export function useGenerateProof() {
  return useMutation({
    mutationFn: (params: { user: string; action_type: string; amount_wei: number }) =>
      api.oracle.generateProof(params),
  });
}

export function useVerifyProof() {
  return useMutation({
    mutationFn: (params: { user: string; action_type: string; amount_wei: number; nonce: string; expiry: number; chain_id: number; contract_address: string; signature: string; message_hash: string }) =>
      api.oracle.verifyProof(params),
  });
}
