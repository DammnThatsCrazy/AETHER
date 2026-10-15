import { useState, useEffect, useRef } from 'react';
import { z } from 'zod';
import { NoesisWorkspace, type NoesisMessageItem, type NoesisResponsePayload } from '@aether/ui';
import { useNoesisQuery } from '@kyber/features/noesis-command';
import { restClient } from '@kyber/lib/api/rest/client';

const capabilitiesSchema = z.object({
  capabilities: z.array(z.object({
    intent: z.string(),
    example_prompts: z.array(z.string()).default([]),
  })).default([]),
}).passthrough();

const FALLBACK_PROMPTS = [
  'Show tenants with unhealthy SDK telemetry.',
  'Summarize graph health across all tenants.',
  'Find high-risk wallet clusters this week.',
  'Show unresolved intelligence alerts.',
  'Which agents are producing abnormal activity?',
  'Find graph drift or contamination events.',
];

function ScopeBar({ scopeSummary }: { readonly scopeSummary: Record<string, unknown> | undefined }) {
  if (!scopeSummary) return null;
  const surface = String(scopeSummary.surface ?? '');
  const tenant = String(scopeSummary.effective_tenant_id ?? '');
  const crossTenant = Boolean(scopeSummary.cross_tenant);
  return (
    <div className="flex items-center gap-2 rounded border border-border-subtle bg-surface-sunken/50 px-3 py-1.5 text-[10px] font-mono text-text-muted">
      <span className="uppercase tracking-wide">{surface || 'kyber'}</span>
      {tenant ? <><span>·</span><span className="text-text-secondary">{tenant}</span></> : null}
      {crossTenant ? <span className="rounded bg-warning/20 px-1.5 py-0.5 text-warning">cross-tenant</span> : null}
    </div>
  );
}

function ExecutionTrace({ response }: { readonly response: NoesisResponsePayload }) {
  const debug = response.query_debug as Record<string, unknown> | undefined;
  const scope = response.scope_summary as Record<string, unknown> | undefined;
  const evidence = response.evidence;
  const requestId = String(debug?.request_id ?? '');
  if (!debug && !scope && !evidence) return null;
  return (
    <details className="mt-2 rounded border border-border-subtle bg-surface-sunken/50 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-mono text-text-secondary">Execution trace</summary>
      <div className="mt-2 space-y-2 text-text-muted">
        {scope && (
          <div className="flex flex-wrap gap-2">
            <span>Surface: <span className="text-text-secondary">{String(scope.surface ?? '—')}</span></span>
            <span>Tenant: <span className="text-text-secondary">{String(scope.effective_tenant_id ?? '—')}</span></span>
            {scope.cross_tenant ? <span className="text-warning">cross-tenant</span> : null}
          </div>
        )}
        {debug && (
          <div className="flex flex-wrap gap-2">
            <span>Intent: <span className="text-text-secondary">{String(debug.intent ?? response.intent)}</span></span>
            <span>Mode: <span className="text-text-secondary">{String(debug.mode ?? response.mode)}</span></span>
            <span>Provider: <span className="text-text-secondary">{String(debug.provider ?? '—')}</span></span>
            <span>Confidence: <span className="text-text-secondary">{(response.confidence * 100).toFixed(0)}%</span></span>
          </div>
        )}
        {evidence && evidence.sources.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide mb-1">Evidence sources</div>
            {evidence.sources.map((src, i) => (
              <div key={i} className="font-mono text-[11px]">{src.service} / {src.resource_type}</div>
            ))}
          </div>
        )}
        {response.warnings.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-warning mb-1">Warnings</div>
            {response.warnings.map((w, i) => <div key={i} className="text-warning">{w}</div>)}
          </div>
        )}
        {requestId && (
          <a
            href={`/audit?request_id=${requestId}`}
            className="inline-block text-accent underline underline-offset-2 hover:opacity-80"
          >
            View in Audit Ledger →
          </a>
        )}
      </div>
    </details>
  );
}

function KyberMessageBubble({ message }: { readonly message: NoesisMessageItem }) {
  const isUser = message.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[920px] rounded-2xl border px-4 py-3 shadow-sm ${isUser ? 'border-accent/30 bg-accent/10 text-text-primary' : 'border-border-default bg-surface-raised text-text-primary'}`}>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-text-muted font-mono">{isUser ? 'Operator' : 'Noesis'}</div>
        {message.response ? (
          <div>
            <ScopeBar scopeSummary={message.response.scope_summary} />
            <ExecutionTrace response={message.response} />
          </div>
        ) : <p className="text-sm">{message.content}</p>}
      </div>
    </div>
  );
}

export function NoesisPage() {
  const [messages, setMessages] = useState<NoesisMessageItem[]>([]);
  const [suggestedPrompts, setSuggestedPrompts] = useState<readonly string[]>(FALLBACK_PROMPTS);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);
  const query = useNoesisQuery();
  const focusHandled = useRef(false);

  useEffect(() => {
    void restClient.get('/v1/noesis/capabilities', capabilitiesSchema).then(res => {
      const caps = res.capabilities ?? [];
      const prompts: string[] = caps.flatMap(c => (c.example_prompts ?? []).filter((p): p is string => Boolean(p))).slice(0, 6);
      if (prompts.length > 0) setSuggestedPrompts(prompts);
    }).catch((cause: unknown) => {
      setCapabilitiesError(cause instanceof Error ? cause.message : 'Noesis capabilities unavailable');
    });
  }, []);

  async function handleSubmit(message: string) {
    const userMessage: NoesisMessageItem = { id: `user-${Date.now()}`, role: 'user', content: message };
    setMessages(prev => [...prev, userMessage]);
    const response = await query.mutate({ message, context: { current_page: window.location.pathname } });
    if (response) {
      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        response,
      }]);
    }
  }

  useEffect(() => {
    if (focusHandled.current) return;
    const params = new URLSearchParams(window.location.search);
    const focus = params.get('focus');
    if (focus) {
      focusHandled.current = true;
      void handleSubmit(`what is connected to entity ${focus}`);
    }
  }, []);

  return (
    <NoesisWorkspace
      title="Noesis Command"
      subtitle="Ask cross-tenant, permission-gated questions about graph health, SDK telemetry, alerts, agents, tenants, rewards, orchestration, and investigations."
      placeholder="Ask Noesis to inspect graph health, unresolved alerts, failing SDK telemetry, risky clusters, or a specific tenant/entity…"
      suggestedPrompts={suggestedPrompts}
      messages={messages}
      isLoading={query.isLoading}
      error={query.error ?? capabilitiesError}
      surfaceTone="kyber"
      emptyTitle="Noesis is ready for operator intelligence"
      emptyDescription="Use natural language to route into safe read-only graph, health, alert, tenant, agent, reward, and entity lookups."
      onSubmit={handleSubmit}
    />
  );
}
