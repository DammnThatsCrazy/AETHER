// =============================================================================
// AETHER SDK — UTILITY FUNCTIONS
// =============================================================================

import type { DeviceContext, CampaignContext, PageContext } from './WebSDKTypes(CoreTypeDefinitions)';

/** Generate a UUID v4 */
export function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Get current ISO timestamp */
export function now(): string {
  return new Date().toISOString();
}

/** SHA-256 hash (async, uses SubtleCrypto where available) */
export async function sha256(input: string): Promise<string> {
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const buf = new TextEncoder().encode(input);
    const hash = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hash))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }
  // Fallback: simple FNV-1a 64-bit (NOT cryptographic — dev only)
  let h = 0xcbf29ce484222325n;
  for (let i = 0; i < input.length; i++) {
    h ^= BigInt(input.charCodeAt(i));
    h *= 0x100000001b3n;
    h &= 0xffffffffffffffffn;
  }
  return h.toString(16).padStart(16, '0');
}

/** Anonymize an IP address (zero last octet for IPv4, last 80 bits for IPv6) */
export function anonymizeIP(ip: string): string {
  if (ip.includes(':')) {
    // IPv6: zero last 5 groups
    const parts = ip.split(':');
    return parts.slice(0, 3).concat(['0', '0', '0', '0', '0']).join(':');
  }
  // IPv4: zero last octet
  const parts = ip.split('.');
  parts[3] = '0';
  return parts.join('.');
}

/** Detect device context from browser environment */
export function getDeviceContext(): DeviceContext {
  const ua = navigator.userAgent;

  const getDeviceType = (): 'desktop' | 'mobile' | 'tablet' => {
    if (/tablet|ipad|playbook|silk/i.test(ua)) return 'tablet';
    if (/mobile|iphone|ipod|android|blackberry|opera mini|iemobile/i.test(ua)) return 'mobile';
    return 'desktop';
  };

  const getBrowser = (): { name: string; version: string } => {
    const browsers: [RegExp, string][] = [
      [/edg\//i, 'Edge'],
      [/opr\//i, 'Opera'],
      [/chrome\//i, 'Chrome'],
      [/safari\//i, 'Safari'],
      [/firefox\//i, 'Firefox'],
    ];
    for (const [regex, name] of browsers) {
      if (regex.test(ua)) {
        const match = ua.match(new RegExp(`${name === 'Edge' ? 'Edg' : name === 'Opera' ? 'OPR' : name}/([\\d.]+)`, 'i'));
        return { name, version: match?.[1] ?? 'unknown' };
      }
    }
    return { name: 'unknown', version: 'unknown' };
  };

  const getOS = (): { name: string; version: string } => {
    const systems: [RegExp, string, RegExp?][] = [
      [/windows nt/i, 'Windows', /windows nt ([\d.]+)/i],
      [/mac os x/i, 'macOS', /mac os x ([\d_.]+)/i],
      [/android/i, 'Android', /android ([\d.]+)/i],
      [/iphone|ipad/i, 'iOS', /os ([\d_]+)/i],
      [/linux/i, 'Linux'],
    ];
    for (const [test, name, verRegex] of systems) {
      if (test.test(ua)) {
        const ver = verRegex ? ua.match(verRegex)?.[1]?.replace(/_/g, '.') : 'unknown';
        return { name, version: ver ?? 'unknown' };
      }
    }
    return { name: 'unknown', version: 'unknown' };
  };

  const browser = getBrowser();
  const os = getOS();

  return {
    type: getDeviceType(),
    browser: browser.name,
    browserVersion: browser.version,
    os: os.name,
    osVersion: os.version,
    screenWidth: screen.width,
    screenHeight: screen.height,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    pixelRatio: window.devicePixelRatio || 1,
    language: navigator.language,
    cookieEnabled: navigator.cookieEnabled,
    online: navigator.onLine,
  };
}

/** Get current page context */
export function getPageContext(): PageContext {
  return {
    url: window.location.href,
    path: window.location.pathname,
    title: document.title,
    referrer: document.referrer,
    search: window.location.search,
    hash: window.location.hash,
  };
}

/** Extract campaign/UTM parameters from URL */
export function getCampaignContext(): CampaignContext {
  const params = new URLSearchParams(window.location.search);

  const getReferrerType = (): CampaignContext['referrerType'] => {
    if (!document.referrer) return 'direct';
    try {
      const ref = new URL(document.referrer);
      const domain = ref.hostname.toLowerCase();
      const searchEngines = ['google', 'bing', 'yahoo', 'duckduckgo', 'baidu', 'yandex'];
      const socialNetworks = ['facebook', 'twitter', 'linkedin', 'instagram', 'tiktok', 'reddit', 'youtube'];

      if (searchEngines.some((se) => domain.includes(se))) {
        return params.get('gclid') || params.get('msclkid') ? 'paid' : 'organic';
      }
      if (socialNetworks.some((sn) => domain.includes(sn))) return 'social';
      if (params.get('utm_medium')?.toLowerCase() === 'email') return 'email';
      return 'referral';
    } catch {
      return 'unknown';
    }
  };

  const referrerDomain = document.referrer
    ? (() => { try { return new URL(document.referrer).hostname; } catch { return undefined; } })()
    : undefined;

  return {
    source: params.get('utm_source') ?? undefined,
    medium: params.get('utm_medium') ?? undefined,
    campaign: params.get('utm_campaign') ?? undefined,
    content: params.get('utm_content') ?? undefined,
    term: params.get('utm_term') ?? undefined,
    clickId: params.get('gclid') ?? params.get('fbclid') ?? params.get('msclkid') ?? undefined,
    referrerDomain,
    referrerType: getReferrerType(),
  };
}

// =============================================================================
// LOCAL STORAGE HELPERS
// =============================================================================

const STORAGE_PREFIX = '_aether_';

export const storage = {
  get<T>(key: string): T | null {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + key);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  },

  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage full or unavailable
    }
  },

  remove(key: string): void {
    try {
      localStorage.removeItem(STORAGE_PREFIX + key);
    } catch {
      // Ignore
    }
  },

  clear(): void {
    try {
      const keys = Object.keys(localStorage).filter((k) => k.startsWith(STORAGE_PREFIX));
      keys.forEach((k) => localStorage.removeItem(k));
    } catch {
      // Ignore
    }
  },
};

// =============================================================================
// COOKIE HELPERS
// =============================================================================

export const cookies = {
  get(name: string): string | null {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : null;
  },

  set(name: string, value: string, days: number = 365, domain?: string): void {
    const date = new Date();
    date.setTime(date.getTime() + days * 86400000);
    let cookie = `${name}=${encodeURIComponent(value)};expires=${date.toUTCString()};path=/;SameSite=Lax;Secure`;
    if (domain) cookie += `;domain=${domain}`;
    document.cookie = cookie;
  },

  remove(name: string, domain?: string): void {
    this.set(name, '', -1, domain);
  },
};

// =============================================================================
// SENSITIVE DATA MASKING
// =============================================================================

const SENSITIVE_PATTERNS: RegExp[] = [
  /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g, // Credit cards
  /\b\d{3}-\d{2}-\d{4}\b/g,                        // SSN
  /\bpassword\b/gi,
  /\bsecret\b/gi,
  /\bcvv\b/gi,
  /\bssn\b/gi,
];

export function maskSensitiveData(
  value: string,
  additionalPatterns: RegExp[] = []
): string {
  let masked = value;
  const patterns = [...SENSITIVE_PATTERNS, ...additionalPatterns];
  for (const pattern of patterns) {
    masked = masked.replace(pattern, '[REDACTED]');
  }
  return masked;
}

/** Check if a form field is likely sensitive */
export function isSensitiveField(el: HTMLInputElement | HTMLTextAreaElement): boolean {
  const sensitiveTypes = ['password', 'hidden'];
  const sensitiveNames = ['ssn', 'social', 'cvv', 'cvc', 'card', 'credit', 'secret', 'token', 'password', 'pin'];

  if (sensitiveTypes.includes(el.type)) return true;

  const nameAndId = `${el.name} ${el.id} ${el.className}`.toLowerCase();
  return sensitiveNames.some((s) => nameAndId.includes(s));
}

// =============================================================================
// THROTTLE / DEBOUNCE
// =============================================================================

export function throttle<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number
): T {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  return ((...args: unknown[]) => {
    const now = Date.now();
    const remaining = ms - (now - last);
    if (remaining <= 0) {
      if (timer) { clearTimeout(timer); timer = null; }
      last = now;
      fn(...args);
    } else if (!timer) {
      timer = setTimeout(() => {
        last = Date.now();
        timer = null;
        fn(...args);
      }, remaining);
    }
  }) as T;
}

export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number
): T {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return ((...args: unknown[]) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}
