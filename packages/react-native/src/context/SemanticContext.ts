// =============================================================================
// AETHER SDK — REACT NATIVE SEMANTIC CONTEXT (Thin Client)
// Tier 1 context only — backend handles enrichment
// =============================================================================

import { Platform, Dimensions } from 'react-native';

export interface SemanticContextEnvelope {
  eventId: string;
  timestamp: string;
  sdk: { name: string; version: string };
  platform: string;
  device: { os: string; osVersion: string; type: string };
  viewport: { width: number; height: number };
  locale: string;
  timezone: string;
  sessionId: string;
  screenPath: string[];
}

let sessionStartedAt = Date.now();
let screenPath: string[] = [];
let sessionId = generateId();

function generateId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export class RNSemanticContextCollector {
  collect(): SemanticContextEnvelope {
    const { width, height } = Dimensions.get('window');
    return {
      eventId: generateId(),
      timestamp: new Date().toISOString(),
      sdk: { name: 'aether-react-native', version: '7.0.0' },
      platform: Platform.OS,
      device: {
        os: Platform.OS,
        osVersion: String(Platform.Version),
        type: width >= 768 ? 'tablet' : 'mobile',
      },
      viewport: { width, height },
      locale: 'en', // RN doesn't expose locale easily without native module
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      sessionId,
      screenPath: [...screenPath],
    };
  }

  recordScreen(screenName: string): void {
    screenPath.push(screenName);
    if (screenPath.length > 50) screenPath = screenPath.slice(-50);
  }

  resetSession(): void {
    sessionId = generateId();
    sessionStartedAt = Date.now();
    screenPath = [];
  }

  destroy(): void {
    screenPath = [];
  }
}

export const semanticContext = new RNSemanticContextCollector();
