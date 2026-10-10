/**
 * Public API calls from the marketing pages. The base URL comes from
 * VITE_API_BASE_URL (same variable as the older marketing apps); without it
 * the forms say they are not connected instead of pretending to succeed.
 */

export function apiBase(env: { VITE_API_BASE_URL?: string } = import.meta.env): string {
  return (env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');
}

/**
 * Where the contact form posts. VITE_LEAD_URL names a standalone lead intake
 * (production's, before its backend exists: infra/aws/lead-intake) that takes
 * the same body and answers like the API; otherwise the API's lead route.
 */
export function leadUrl(env: { VITE_API_BASE_URL?: string; VITE_LEAD_URL?: string } = import.meta.env): string {
  const intake = env.VITE_LEAD_URL?.trim();
  if (intake) return intake;
  const base = apiBase(env);
  return base ? `${base}/v1/contact/lead` : '';
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
export async function submitLead(payload: LeadPayload, url = leadUrl(), fetchImpl: typeof fetch = fetch): Promise<LeadResult> {
  if (!url) return { status: 'unconfigured' };
  try {
    const res = await fetchImpl(url, {
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
