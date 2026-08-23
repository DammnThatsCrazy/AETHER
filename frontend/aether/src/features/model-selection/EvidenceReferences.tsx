/**
 * Evidence references attached to a grounded answer (ADR-008 D6).
 *
 * Read-only list that maps an answer's claims back to the retrieved records
 * they cite — source, reference id, and a bounded excerpt. This surface never
 * renders raw credentials or out-of-tenant data: snippets are sanitized
 * (control characters stripped, credential-like patterns redacted to
 * `[redacted]`) and truncated to a bounded length before display.
 */

/** One citation back to a retrieved record. */
export interface EvidenceRef {
  /** Stable identifier for the cited record. */
  referenceId: string;
  /** Origin of the record (e.g. table, endpoint, or source system). */
  source: string;
  /** Optional excerpt of the record shown to justify the citation. */
  snippet?: string;
}

/** Max rendered snippet length; longer snippets are truncated with an ellipsis. */
export const SNIPPET_MAX_LENGTH = 160;

/**
 * Redacts credential-like patterns from a snippet so the read-only evidence
 * surface can never leak raw secrets: `sk-…` API keys, `AKIA…` AWS access
 * keys, and `Bearer …` authorization tokens are replaced with `[redacted]`.
 * Control characters are stripped to plain spaces first.
 */
export function sanitizeSnippet(raw: string): string {
  return raw
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, ' ')
    .replace(/\bsk-[A-Za-z0-9_-]+/g, '[redacted]')
    .replace(/\bAKIA[A-Z0-9_-]+/g, '[redacted]')
    .replace(/\bBearer\s+[A-Za-z0-9._~+/-=]+/gi, '[redacted]');
}

/** Truncates a snippet to `maxLength` chars, appending "…" when it is longer. */
export function truncateSnippet(
  snippet: string,
  maxLength: number = SNIPPET_MAX_LENGTH,
): string {
  return snippet.length > maxLength ? `${snippet.slice(0, maxLength)}…` : snippet;
}

export function EvidenceReferences({ evidence }: { evidence: EvidenceRef[] }) {
  if (evidence.length === 0) return null;

  return (
    <details className="text-xs text-text-muted">
      <summary className="cursor-pointer font-mono hover:text-text-secondary">
        Evidence references ({evidence.length})
      </summary>
      <ul className="mt-2 space-y-2">
        {evidence.map(ref => {
          const snippet =
            ref.snippet == null ? null : truncateSnippet(sanitizeSnippet(ref.snippet));
          return (
            <li
              key={ref.referenceId}
              className="rounded border border-border-subtle bg-surface-raised/50 px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="font-mono text-text-primary">{ref.referenceId}</span>
                <span className="text-text-muted">{ref.source}</span>
              </div>
              {snippet != null && (
                <p className="mt-1 text-[11px] text-text-muted">{snippet}</p>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
