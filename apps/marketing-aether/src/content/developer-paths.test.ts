import { describe, expect, it } from 'vitest';
import { DEFAULT_PATH_ID, DEVELOPER_PATHS, findDeveloperPath } from './developer-paths';

const KEBAB_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

describe('developer-paths content', () => {
  it('exposes four developer paths', () => {
    expect(DEVELOPER_PATHS).toHaveLength(4);
  });

  it('gives every path a unique kebab-case id', () => {
    const ids = DEVELOPER_PATHS.map((path) => path.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(KEBAB_ID);
    }
  });

  it('defaults to the first real path', () => {
    expect(DEFAULT_PATH_ID).toBe(DEVELOPER_PATHS[0].id);
    expect(findDeveloperPath(DEFAULT_PATH_ID)?.id).toBe(DEFAULT_PATH_ID);
  });

  it('fills every field on every path', () => {
    for (const path of DEVELOPER_PATHS) {
      expect(path.label.trim()).not.toBe('');
      expect(path.eyebrow.trim()).not.toBe('');
      expect(path.description.trim()).not.toBe('');
      expect(path.state.trim()).not.toBe('');
      expect(path.id).toBe(findDeveloperPath(path.id)?.id);
    }
  });

  it('gives each path at least three steps with non-empty heading and text', () => {
    for (const path of DEVELOPER_PATHS) {
      expect(path.steps.length).toBeGreaterThanOrEqual(3);
      for (const step of path.steps) {
        expect(step.heading.trim()).not.toBe('');
        expect(step.text.trim()).not.toBe('');
      }
    }
  });

  it('resolves each path id and rejects an unknown id', () => {
    for (const path of DEVELOPER_PATHS) {
      expect(findDeveloperPath(path.id)?.id).toBe(path.id);
    }
    expect(findDeveloperPath('nope')).toBeUndefined();
  });
});
