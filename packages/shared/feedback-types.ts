// =============================================================================
// Aether SDK — Shared Feedback/Survey Types
// Canonical type definitions used by Web, iOS, Android, and React Native SDKs
// =============================================================================

export type SurveyType = 'nps' | 'csat' | 'ces' | 'custom';

export interface SurveyQuestion {
  id: string;
  type: 'rating' | 'scale' | 'text' | 'multiple_choice' | 'boolean';
  text: string;
  options?: string[];
  min?: number;
  max?: number;
  required?: boolean;
}

export interface Survey {
  id: string;
  type: SurveyType;
  title: string;
  questions: SurveyQuestion[];
  thankYouMessage?: string;
}

export interface SurveyResponse {
  surveyId: string;
  responses: Record<string, unknown>;
  completedAt: number;
  dismissed: boolean;
}

export interface SurveyTrigger {
  event?: string;
  delay?: number;
  pageUrl?: string;
  screenName?: string;
  sessionCount?: number;
  minSessionDuration?: number;
  sampleRate?: number;
  maxDisplays?: number;
}
