import fs from 'fs';
import path from 'path';

/** Platform version from pyproject.toml (CLAUDE.md, "Canonical version source"). */
export function platformVersion(): string {
  const toml = fs.readFileSync(path.resolve(__dirname, '../../pyproject.toml'), 'utf8');
  return /^version\s*=\s*"([^"]+)"/m.exec(toml)?.[1] ?? 'unknown';
}
