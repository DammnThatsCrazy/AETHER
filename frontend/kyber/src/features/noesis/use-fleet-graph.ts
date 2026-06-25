import { useState, useEffect, useCallback } from 'react';
import { api } from '@kyber/lib/api/endpoints';

export interface TenantEnvelopeData {
  tenant_id: string;
  computed_at: string;
  graph: {
    node_count: number;
    edge_count_sample: number;
    has_data: boolean;
  };
  fraud: {
    fraud_network_count: number;
  };
  sdk: {
    health_score: number | null;
  };
  status: 'healthy' | 'no_data' | string;
}

export interface OperatorSession {
  session_id: string;
  tenant_id: string;
  purpose: string;
  entered_at: string;
  expires_at: string | null;
  message: string;
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

export function useFleetTenantEnvelope(tenantId: string | null) {
  const [envelope, setEnvelope] = useState<TenantEnvelopeData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!tenantId) { setEnvelope(null); return; }
    setIsLoading(true);
    setError(null);
    api.kyberOperator.tenantEnvelope(tenantId)
      .then(raw => {
        const r = asRec(raw);
        setEnvelope(r as unknown as TenantEnvelopeData);
        setIsLoading(false);
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : 'Failed to load envelope');
        setIsLoading(false);
      });
  }, [tenantId]);

  useEffect(() => { refresh(); }, [refresh]);

  return { envelope, isLoading, error, refresh };
}

export type OperatorAccessPurpose =
  | 'incident_response'
  | 'customer_support'
  | 'compliance_audit'
  | 'security_investigation'
  | 'data_request'
  | 'diagnostics'
  | 'break_glass';

export function useKyberOperatorEntry() {
  const [session, setSession] = useState<OperatorSession | null>(null);
  const [isEntering, setIsEntering] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enterTenant = useCallback(async (params: {
    tenant_id: string;
    access_reason: string;
    purpose: OperatorAccessPurpose;
    duration_minutes?: number;
  }) => {
    setIsEntering(true);
    setError(null);
    try {
      const raw = await api.kyberOperator.enterTenant(params);
      const r = asRec(raw);
      setSession(r as unknown as OperatorSession);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to enter tenant');
      throw err;
    } finally {
      setIsEntering(false);
    }
  }, []);

  const exitTenant = useCallback(async () => {
    if (!session) return;
    setIsExiting(true);
    setError(null);
    try {
      await api.kyberOperator.exitTenant(session.session_id);
      setSession(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to exit tenant');
      throw err;
    } finally {
      setIsExiting(false);
    }
  }, [session]);

  return { session, isEntering, isExiting, error, enterTenant, exitTenant };
}
