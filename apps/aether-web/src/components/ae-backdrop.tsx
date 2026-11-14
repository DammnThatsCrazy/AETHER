import { useMemo } from 'react';

/** Deterministic pseudo-random in [0, 1) so the field is stable across renders. */
function fract(n: number): number {
  const v = Math.sin(n) * 43758.5453;
  return v - Math.floor(v);
}

/**
 * The design's "whisper" ASCII grid: `+` every 10 columns / 5 rows, `·` every
 * 5, and a sparse scatter of `:`. Built once; the container clips it.
 */
export function buildAsciiField(cols: number, rows: number): string {
  let out = '';
  for (let y = 0; y < rows; y++) {
    let line = '';
    for (let x = 0; x < cols; x++) {
      if (x % 10 === 0 && y % 5 === 0) line += '+';
      else if (x % 5 === 0 && y % 5 === 0) line += '·';
      else line += fract(x * 1.7 + y * 31.3) > 0.965 ? ':' : ' ';
    }
    out += line + '\n';
  }
  return out;
}

/** Fixed, non-interactive page backdrop: two soft colour blobs + ASCII grid. */
export function AeBackdrop() {
  const ascii = useMemo(() => buildAsciiField(300, 90), []);
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 overflow-hidden">
      <div
        className="absolute rounded-full"
        style={{ left: -120, top: '55%', width: 640, height: 520, background: 'var(--ae-blob-a)', filter: 'blur(70px)' }}
      />
      <div
        className="absolute rounded-full"
        style={{ right: -100, top: -60, width: 600, height: 480, background: 'var(--ae-blob-b)', filter: 'blur(70px)' }}
      />
      <div
        className="ae-mono select-none whitespace-pre"
        style={{ fontSize: 12, lineHeight: '16px', color: 'var(--ae-ascii)' }}
      >
        {ascii}
      </div>
    </div>
  );
}
