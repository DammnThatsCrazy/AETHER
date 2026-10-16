import { cn } from '@aether/ui';

/**
 * Third-party brand marks for connectors, SDK platforms and wallets
 * (src/assets/brand, from the AETHER brand asset set and simple-icons).
 * Vite resolves each file to a hashed URL that respects the configured base
 * path, so the marks work both at the app root and under /app/.
 */
const MARK_URLS = import.meta.glob<string>('../assets/brand/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
});

const MARKS: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(MARK_URLS).map(([path, url]) => [
    path.slice(path.lastIndexOf('/') + 1, -'.svg'.length),
    url,
  ]),
);

/**
 * Aliases from provider families, catalog display names and SDK platform
 * tokens onto the mark file names. Lookups are case-insensitive and also
 * match on a family prefix (`google_ads_v2` → `googleads`).
 */
const ALIASES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^(google[\s_-]?ads|adwords)/, 'googleads'],
  [/^(google[\s_-]?analytics|ga4)/, 'googleanalytics'],
  [/^(meta|facebook)/, 'meta'],
  [/^(app[\s_-]?store|apple[\s_-]?app)/, 'appstore'],
  [/^(gmail|google[\s_-]?mail)/, 'mail-gmail'],
  [/^(outlook|microsoft[\s_-]?365|office365|imap)/, 'mail-work'],
  [/^(coinbase)/, 'coinbase'],
  [/^(react[\s_-]?native|react)/, 'react'],
  [/^(ios|swift|apple)/, 'apple'],
  [/^(android|kotlin)/, 'android'],
  [/^(server|node)/, 'nodedotjs'],
  [/^(web|javascript|browser)/, 'javascript'],
  [/^(agent|atlas)/, 'atlas'],
  [/^(csv|import|webhook|aether|generic)/, 'aether'],
];

export function resolveBrandMark(token: string | null | undefined): string | null {
  if (!token) return null;
  const key = token.trim().toLowerCase();
  const exact = MARKS[key];
  if (exact) return exact;
  for (const [pattern, mark] of ALIASES) {
    const hit = MARKS[mark];
    if (pattern.test(key) && hit) return hit;
  }
  const compact = key.replace(/[^a-z0-9]/g, '');
  for (const name of Object.keys(MARKS)) {
    if (compact.startsWith(name.replace(/[^a-z0-9]/g, ''))) return MARKS[name] ?? null;
  }
  return null;
}

interface BrandMarkProps {
  /** Provider family, display name or platform token. */
  readonly token: string;
  /** Fallback lettermark text when no mark is known (defaults to the token). */
  readonly label?: string;
  /** Outer chip size in px. */
  readonly size?: number;
  /** Mark size inside the chip in px. */
  readonly markSize?: number;
  readonly shape?: 'round' | 'rounded' | 'square';
  readonly className?: string;
}

/** A brand mark on a white chip; falls back to a neutral lettermark. */
export function BrandMark({ token, label, size = 30, markSize, shape = 'rounded', className }: BrandMarkProps) {
  const url = resolveBrandMark(token) ?? resolveBrandMark(label);
  const inner = markSize ?? Math.round(size * 0.58);
  const radius = shape === 'round' ? '50%' : shape === 'square' ? 4 : Math.round(size * 0.3);
  return (
    <span
      className={cn('ae-mark-chip', className)}
      style={{ width: size, height: size, borderRadius: radius }}
      data-brand-mark={url ? token : undefined}
    >
      {url ? (
        <img src={url} alt="" aria-hidden="true" style={{ width: inner, height: inner, objectFit: 'contain' }} />
      ) : (
        <span className="ae-mono" style={{ fontSize: Math.max(9, Math.round(size * 0.36)), color: '#6b6a65' }}>
          {(label ?? token).trim().charAt(0).toUpperCase()}
        </span>
      )}
    </span>
  );
}
