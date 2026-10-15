import { readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Static motion-budget guard for the Aether public marketing shell.
 *
 * The marketing shells deliberately carry no decorative or ambient motion and
 * no route-level animation: no `@keyframes`, no `will-change`, no `animate-*`
 * utilities, and no inline per-feature transition strings. The ONLY motion
 * budget in `src/styles/index.css` is two plain-CSS utilities bound to the
 * shared brand duration tokens:
 *
 *   - .mkt-motion-color           micro   120ms — hover / press / focus recipes
 *   - .mkt-motion-color-standard  standard 180ms — tab / disclosure / toggle
 *
 * `prefers-reduced-motion` is honored by the blanket override in index.css,
 * which reads its durations from `var(--aether-motion-reduced, 0.01ms)`.
 *
 * This test is deliberately static and hermetic (no DOM): it walks this
 * workspace's own `src` tree and asserts the budget contract holds. It skips
 * any `*.test.*` file so its own assertion strings are never scanned.
 */

/** The workspace `src` directory that owns this test file. */
const SRC_DIR = resolve(process.cwd(), 'src');

const INDEX_CSS_PATH = join(SRC_DIR, 'styles', 'index.css');

/** Recursively collect .tsx/.css sources under `dir`, skipping test files. */
function collectSources(dir: string = SRC_DIR): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      found.push(...collectSources(full));
    } else if (/\.(tsx|css)$/.test(entry) && !/\.test\./.test(basename(full))) {
      found.push(full);
    }
  }
  return found;
}

const SOURCES = collectSources();

/** Readable per-file failure context (relative to the workspace src root). */
function label(file: string): string {
  return relative(SRC_DIR, file);
}

describe('aether-marketing motion budget', () => {
  it('locks the CSS contract: budget utilities on the shared duration tokens plus the reduced-motion override', () => {
    expect(SOURCES.length).toBeGreaterThan(0);
    expect(SOURCES).toContain(INDEX_CSS_PATH);

    const css = readFileSync(INDEX_CSS_PATH, 'utf8');
    expect(css, 'index.css must keep the prefers-reduced-motion blanket override').toContain(
      '@media (prefers-reduced-motion: reduce)',
    );
    expect(
      css,
      'the reduced-motion override must consume var(--aether-motion-reduced)',
    ).toContain('var(--aether-motion-reduced');
    expect(css, 'the micro budget utility .mkt-motion-color is required').toContain(
      '.mkt-motion-color {',
    );
    expect(css, 'the standard budget utility .mkt-motion-color-standard is required').toContain(
      '.mkt-motion-color-standard {',
    );
    expect(
      css,
      'the micro utility must bind its duration to --aether-motion-micro (120ms fallback)',
    ).toMatch(/transition-duration:\s*var\(--aether-motion-micro,\s*120ms\)/);
    expect(
      css,
      'the standard utility must bind its duration to --aether-motion-standard (180ms fallback)',
    ).toMatch(/transition-duration:\s*var\(--aether-motion-standard,\s*180ms\)/);
    expect(css, 'budget utilities must share the --aether-ease-standard token').toContain(
      'var(--aether-ease-standard',
    );
  });

  it('keeps every scanned source free of ambient/decorative animation and unbudgeted motion utilities', () => {
    for (const file of SOURCES) {
      const source = readFileSync(file, 'utf8');
      const where = (what: string) => `${label(file)} must not contain ${what}`;
      expect(source, where('@keyframes')).not.toContain('@keyframes');
      expect(source, where('will-change')).not.toContain('will-change');
      expect(source, where('animate-')).not.toContain('animate-');
      expect(source, where('the raw transition-colors utility')).not.toContain('transition-colors');
      expect(source, where('the tailwind duration-<number> utility')).not.toMatch(/duration-[0-9]/);
      expect(source, where('the tailwind duration-[...] arbitrary utility')).not.toContain('duration-[');
      expect(source, where('the tailwind ease-[...] arbitrary utility')).not.toContain('ease-[');
    }
  });

  it('leaves no literal transition text in component/page sources (all color transitions are tokenized to mkt-motion-color*)', () => {
    const tsxSources = SOURCES.filter((file) => file.endsWith('.tsx'));
    expect(tsxSources.length).toBeGreaterThan(0);
    for (const file of tsxSources) {
      const source = readFileSync(file, 'utf8');
      expect(
        source,
        `${label(file)} must not reference the literal 'transition' — use the mkt-motion-color* budget utilities`,
      ).not.toMatch(/transition/i);
    }
  });

  it('confines transition/animation declarations to the budget utilities and the reduced-motion override', () => {
    for (const file of SOURCES.filter((entry) => entry.endsWith('.css'))) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((raw, index) => {
        if (!/^\s*(transition|animation)-/.test(raw)) return;
        const line = raw.trim();
        const allowed =
          /^transition-property:/.test(line) ||
          /^transition-timing-function:/.test(line) ||
          /^transition-duration:\s*var\(--aether-motion-/.test(line) ||
          /^animation-duration:\s*var\(--aether-motion-reduced/.test(line) ||
          /^animation-iteration-count:\s*1\s*!important;/.test(line);
        expect(
          allowed,
          `${label(file)}:${index + 1} declares motion outside the budget utilities / reduced-motion override: ${line}`,
        ).toBe(true);
      });
    }
  });
});
