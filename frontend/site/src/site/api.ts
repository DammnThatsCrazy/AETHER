/**
 * Public API calls from the marketing pages. The base URL comes from
 * VITE_API_BASE_URL (same variable as the older marketing apps); without it
 * the forms say they are not connected instead of pretending to succeed.
 */

export function apiBase(env: { VITE_API_BASE_URL?: string } = import.meta.env): string {
  return (env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');
}

/** Topics accepted by POST /v1/contact/lead as `lead_type`. */
export type ContactTopic = 'pilot' | 'product' | 'developer' | 'security' | 'proof' | 'research';

export interface LeadPayload {
  lead_type: ContactTopic;
  name: string;
  email: string;
  message: string;
  company?: string;
  use_case?: string;
  source: 'olympus-marketing' | 'aether-marketing';
}

export type LeadResult = { status: 'ok'; leadId: string } | { status: 'error' } | { status: 'unconfigured' };

/** Success only on a 2xx response that carries a lead id. */
export async function submitLead(payload: LeadPayload, base = apiBase(), fetchImpl: typeof fetch = fetch): Promise<LeadResult> {
  if (!base) return { status: 'unconfigured' };
  try {
    const res = await fetchImpl(`${base}/v1/contact/lead`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return { status: 'error' };
    const body = (await res.json()) as { data?: { lead_id?: unknown } };
    const leadId = body.data?.lead_id;
    return typeof leadId === 'string' ? { status: 'ok', leadId } : { status: 'error' };
  } catch {
    return { status: 'error' };
  }
}
