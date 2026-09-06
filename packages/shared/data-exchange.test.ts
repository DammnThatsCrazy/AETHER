import { describe, expect, it } from 'vitest';
import {
  classificationBlockedByDefault,
  isDataArtifactStatus,
  isEgressFormat,
  isIngressFormat,
  isTerminalDataArtifactStatus,
} from './data-exchange';

describe('data exchange contract helpers', () => {
  it('recognizes terminal and active artifact states', () => {
    expect(isTerminalDataArtifactStatus('available')).toBe(true);
    expect(isTerminalDataArtifactStatus('committed')).toBe(true);
    expect(isTerminalDataArtifactStatus('rolled_back')).toBe(false);
    expect(isTerminalDataArtifactStatus('generating')).toBe(false);
  });

  it('validates artifact statuses against the canonical vocabulary', () => {
    expect(isDataArtifactStatus('uploading')).toBe(true);
    expect(isDataArtifactStatus('committed')).toBe(true);
    expect(isDataArtifactStatus('draft')).toBe(false);
    expect(isDataArtifactStatus('map')).toBe(false);
  });

  it('separates ingress and egress format vocabularies', () => {
    expect(isIngressFormat('jsonl')).toBe(true);
    expect(isEgressFormat('jsonl')).toBe(false);
    expect(isEgressFormat('ndjson')).toBe(true);
    expect(isIngressFormat('ndjson')).toBe(false);
    expect(isIngressFormat('parquet')).toBe(true);
    expect(isEgressFormat('parquet')).toBe(true);
  });

  it('blocks secrets and credentials by default', () => {
    expect(classificationBlockedByDefault('secret')).toBe(true);
    expect(classificationBlockedByDefault('credential')).toBe(true);
    expect(classificationBlockedByDefault('pii')).toBe(false);
    expect(classificationBlockedByDefault('none')).toBe(false);
  });
});
