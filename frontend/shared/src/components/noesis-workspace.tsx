import { Component, useState, useRef, type FormEvent, type ReactNode, type ErrorInfo } from 'react';
import { Badge } from './badge';
import { Button } from './button';
import { Card, CardContent, CardHeader, CardTitle } from './card';
import { EmptyState } from './empty-state';
import { LoadingState } from './loading-state';
import { cn } from '../utils/cn';

export interface NoesisAction {
  readonly type: 'navigate' | 'open_inspector' | 'highlight_graph' | 'refine_query';
  readonly label?: string;
  readonly href?: string;
  readonly entity_id?: string;
  readonly entity_type?: string;
  readonly node_ids?: readonly string[];
  readonly edge_ids?: readonly string[];
  readonly prompt?: string;
}

export interface NoesisGraphPayload {
  readonly nodes: readonly Record<string, unknown>[];
  readonly edges: readonly Record<string, unknown>[];
  readonly highlights: readonly string[];
}

export interface NoesisResponsePayload {
  readonly answer: string;
  readonly mode: 'deterministic' | 'llm_text_to_query' | 'fallback';
  readonly intent: string;
  readonly confidence: number;
  readonly entities: readonly Record<string, unknown>[];
  readonly results: readonly Record<string, unknown>[];
  readonly graph: NoesisGraphPayload;
  readonly actions: readonly NoesisAction[];
  readonly query_debug?: Record<string, unknown> | undefined;
  readonly warnings: readonly string[];
  readonly error?: { readonly code: string; readonly message: string } | undefined;
}

export interface NoesisMessageItem {
  readonly id: string;
  readonly role: 'user' | 'assistant';
  readonly content: string;
  readonly response?: NoesisResponsePayload | undefined;
}

interface NoesisWorkspaceProps {
  readonly title: string;
  readonly subtitle: string;
  readonly placeholder: string;
  readonly suggestedPrompts: readonly string[];
  readonly messages: readonly NoesisMessageItem[];
  readonly isLoading: boolean;
  readonly error?: string | null | undefined;
  readonly surfaceTone: 'kyber' | 'aether';
  readonly emptyTitle: string;
  readonly emptyDescription: string;
  readonly onSubmit: (message: string) => Promise<void> | void;
}

function valueLabel(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value == null) return '—';
  return JSON.stringify(value);
}

function ResultCard({ result, index }: { readonly result: Record<string, unknown>; readonly index: number }) {
  const entries = Object.entries(result).filter(([key]) => !['metadata', 'properties'].includes(key)).slice(0, 6);
  return (
    <Card className="bg-surface-raised/70 border-border-subtle">
      <CardHeader className="mb-2">
        <CardTitle className="text-xs font-mono">Result {index + 1}</CardTitle>
        {typeof result.type === 'string' ? <Badge>{result.type}</Badge> : null}
      </CardHeader>
      <CardContent className="space-y-1 text-xs">
        {entries.map(([key, value]) => (
          <div key={key} className="flex gap-2 border-b border-border-subtle/50 pb-1 last:border-0">
            <span className="w-28 shrink-0 text-text-muted font-mono">{key}</span>
            <span className="truncate text-text-secondary">{valueLabel(value)}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ActionBar({ actions }: { readonly actions: readonly NoesisAction[] }) {
  if (!actions.length) return null;
  return (
    <div className="flex flex-wrap gap-2 pt-2">
      {actions.slice(0, 6).map((action, index) => action.href ? (
        <Button key={`${action.type}-${index}`} variant="secondary" size="sm" onClick={() => { window.location.href = action.href ?? '#'; }}>
          {action.label ?? action.type}
        </Button>
      ) : (
        <Badge key={`${action.type}-${index}`} variant={action.type === 'refine_query' ? 'warning' : 'default'}>
          {action.label ?? action.prompt ?? action.type}
        </Badge>
      ))}
    </div>
  );
}

function AssistantResponse({ response }: { readonly response: NoesisResponsePayload }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={response.mode === 'fallback' ? 'warning' : 'accent'}>{response.mode}</Badge>
        <Badge>{response.intent}</Badge>
        <span className="text-xs text-text-muted font-mono">confidence {(response.confidence * 100).toFixed(0)}%</span>
      </div>
      <p className="text-sm leading-6 text-text-primary whitespace-pre-wrap">{response.answer}</p>
      {response.warnings.map(warning => <div key={warning} className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{warning}</div>)}
      {response.error ? <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{response.error.message}</div> : null}
      {response.graph.nodes.length || response.graph.edges.length ? (
        <Card className="bg-surface-sunken/60">
          <CardHeader><CardTitle>Graph context</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2 text-xs text-text-secondary">
            <Badge variant="accent">{response.graph.nodes.length} nodes</Badge>
            <Badge>{response.graph.edges.length} edges</Badge>
            {response.graph.highlights.slice(0, 5).map(id => <Badge key={id}>{id}</Badge>)}
          </CardContent>
        </Card>
      ) : null}
      {response.results.length ? (
        <div className="grid gap-2 md:grid-cols-2">
          {response.results.slice(0, 6).map((result, index) => <ResultCard key={index} result={result} index={index} />)}
        </div>
      ) : null}
      <ActionBar actions={response.actions} />
      {response.query_debug ? (
        <details className="rounded border border-border-subtle bg-surface-sunken/50 px-3 py-2 text-xs text-text-muted">
          <summary className="cursor-pointer font-mono text-text-secondary">Query debug</summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(response.query_debug, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}

interface ResponseErrorBoundaryState {
  readonly hasError: boolean;
}

class ResponseErrorBoundary extends Component<{ readonly children: ReactNode }, ResponseErrorBoundaryState> {
  constructor(props: { readonly children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ResponseErrorBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[NoesisWorkspace] Error rendering response:', error, info);
  }

  override render() {
    if (this.state.hasError) {
      return (
        <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          Unable to render this response. The data may be malformed.
        </div>
      );
    }
    return this.props.children;
  }
}

function SafeAssistantResponse({ response }: { readonly response: NoesisResponsePayload }) {
  return (
    <ResponseErrorBoundary>
      <AssistantResponse response={response} />
    </ResponseErrorBoundary>
  );
}

function MessageBubble({ message }: { readonly message: NoesisMessageItem }) {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn(
        'max-w-[920px] rounded-2xl border px-4 py-3 shadow-sm',
        isUser ? 'border-accent/30 bg-accent/10 text-text-primary' : 'border-border-default bg-surface-raised text-text-primary',
      )}>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-text-muted font-mono">{isUser ? 'You' : 'Noesis'}</div>
        {message.response ? <SafeAssistantResponse response={message.response} /> : <p className="text-sm">{message.content}</p>}
      </div>
    </div>
  );
}

function PromptForm({ placeholder, isLoading, onSubmit }: Pick<NoesisWorkspaceProps, 'placeholder' | 'isLoading' | 'onSubmit'>) {
  const [value, setValue] = useState('');
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = value.trim();
    if (!message || isLoading) return;
    setValue('');
    void onSubmit(message);
  }
  return (
    <form onSubmit={submit} className="rounded-2xl border border-border-default bg-surface-raised/95 p-2 shadow-xl">
      <textarea
        value={value}
        onChange={event => setValue(event.target.value)}
        placeholder={placeholder}
        rows={3}
        className="min-h-20 w-full resize-none bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none"
      />
      <div className="flex items-center justify-between border-t border-border-subtle pt-2">
        <span className="px-3 text-[10px] uppercase tracking-wide text-text-muted font-mono">Read-only graph intelligence</span>
        <Button type="submit" disabled={isLoading} size="sm">{isLoading ? 'Thinking…' : 'Ask Noesis'}</Button>
      </div>
    </form>
  );
}

export function NoesisWorkspace({
  title,
  subtitle,
  placeholder,
  suggestedPrompts,
  messages,
  isLoading,
  error,
  surfaceTone,
  emptyTitle,
  emptyDescription,
  onSubmit,
}: NoesisWorkspaceProps) {
  const hasMessages = messages.length > 0;
  const submittingRef = useRef(false);
  const accent: ReactNode = surfaceTone === 'kyber' ? 'Internal operator graph command' : 'Tenant-safe intelligence copilot';

  function guardedSubmit(message: string) {
    if (submittingRef.current || isLoading) return;
    submittingRef.current = true;
    const result = onSubmit(message);
    if (result && typeof result.then === 'function') {
      void result.then(() => { submittingRef.current = false; }, () => { submittingRef.current = false; });
    } else {
      submittingRef.current = false;
    }
  }
  return (
    <div className="min-h-full rounded-2xl bg-[radial-gradient(circle_at_top,_rgba(86,143,255,0.18),_transparent_34%),linear-gradient(180deg,_rgba(7,10,18,0.96),_rgba(12,16,28,0.98))] p-5 text-text-primary">
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="space-y-2 py-4 text-center">
          <Badge variant="accent">Noesis</Badge>
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          <p className="mx-auto max-w-2xl text-sm text-text-secondary">{subtitle}</p>
          <p className="text-[10px] uppercase tracking-widest text-text-muted font-mono">{accent}</p>
        </header>

        <PromptForm placeholder={placeholder} isLoading={isLoading} onSubmit={onSubmit} />

        {!hasMessages ? (
          <Card className="bg-surface-raised/60">
            <CardContent className="space-y-4 py-6">
              <EmptyState title={emptyTitle} description={emptyDescription} />
              <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
                {suggestedPrompts.map(prompt => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={isLoading}
                    onClick={() => guardedSubmit(prompt)}
                    className="rounded-lg border border-border-subtle bg-surface-sunken/60 px-3 py-3 text-left text-xs text-text-secondary transition hover:border-accent/50 hover:text-text-primary"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4 pb-8">
            {messages.map(message => <MessageBubble key={message.id} message={message} />)}
            {isLoading ? <LoadingState lines={3} /> : null}
          </div>
        )}
        {error ? <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div> : null}
      </div>
    </div>
  );
}
